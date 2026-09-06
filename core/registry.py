"""에이전트 레지스트리 - registry.yaml 을 읽고 각 에이전트의 생존/manifest 를 확인한다.

registry.yaml 이 '호출 가능한 에이전트'의 유일한 목록이다. (요구사항 17)
파일이 바뀌면 30초 안에 자동 반영되므로 에이전트를 추가할 때 코어를 재기동할 필요가 없다.

'지금 누가 쓰는 중인지'(busy)도 여기서 함께 들고 있다. 폐쇄망의 로컬 모델은 한 응답에
몇 분이 걸리므로, 그 사이 다른 사람이 같은 에이전트를 또 부르면 Ollama 를 나눠 쓰며
둘 다 느려진다. 그래서 호출 중인 에이전트는 화면에서 고를 수 없게 막는다.

주의: 이것은 코어 한 프로세스의 메모리다. 폐쇄망은 코어가 1대이므로 전체 그림이 맞지만,
코어를 2대 띄우면 서로의 busy 를 보지 못한다. 에이전트 자신은 아무것도 강제하지 않는다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

from core.config import settings
from core.contract import CONTRACT_VERSION, Manifest

log = logging.getLogger("registry")


@dataclass
class AgentInfo:
    """레지스트리에 등록된 에이전트 하나의 현재 상태."""

    id: str
    url: str
    manifest: Manifest | None = None
    online: bool = False
    error: str | None = None
    # 계약 버전이 코어와 다르면 화면에 경고를 띄운다.
    contract_mismatch: bool = False
    # 지금 이 에이전트를 쓰고 있는 사람. None 이면 비어 있다.
    busy_by: str | None = None
    busy_since: float | None = None

    def to_dict(self) -> dict[str, Any]:
        m = self.manifest
        return {
            "id": self.id,
            "url": self.url,
            "online": self.online,
            "error": self.error,
            "contract_mismatch": self.contract_mismatch,
            "busy": self.busy_by is not None,
            "busy_by": self.busy_by,
            # 얼마나 오래 잡고 있는지. 기다릴지 말지 판단하는 데 쓴다.
            "busy_seconds": int(time.monotonic() - self.busy_since) if self.busy_since else 0,
            "name": m.name if m else self.id,
            "description": m.description if m else "",
            "owner": m.owner if m else "",
            "tags": m.tags if m else [],
            "examples": m.examples if m else [],
            # 이 에이전트가 자기 .env 로 고정해 둔 모델. None 이면 화면 선택을 따른다.
            "model": m.model if m else None,
        }


class Registry:
    """메모리에 들고 있는 에이전트 목록. 백그라운드에서 주기적으로 갱신한다."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentInfo] = {}
        self._mtime: float = 0.0
        self._task: asyncio.Task | None = None

    # --- 조회 ---------------------------------------------------------------

    def all(self) -> list[AgentInfo]:
        return list(self._agents.values())

    def online(self) -> list[AgentInfo]:
        return [a for a in self._agents.values() if a.online]

    def get(self, agent_id: str) -> AgentInfo | None:
        return self._agents.get(agent_id)

    def callable(self) -> list[AgentInfo]:
        """지금 부를 수 있는 에이전트. 온라인이면서 비어 있는 것."""
        return [a for a in self._agents.values() if a.online and a.busy_by is None]

    # --- 사용 중 표시 -------------------------------------------------------
    #
    # 단일 스레드 이벤트 루프에서 await 없이 확인-후-설정을 하므로 잠금이 필요 없다.
    # 중간에 다른 코루틴이 끼어들 수 없다.

    def acquire(self, agent_id: str, who: str) -> bool:
        """에이전트를 잡는다. 이미 누가 쓰고 있으면 False."""
        agent = self._agents.get(agent_id)
        if agent is None or agent.busy_by is not None:
            return False
        agent.busy_by = who
        agent.busy_since = time.monotonic()
        return True

    def release(self, agent_id: str) -> None:
        agent = self._agents.get(agent_id)
        if agent:
            agent.busy_by = None
            agent.busy_since = None

    # --- 갱신 ---------------------------------------------------------------

    def _load_file(self) -> None:
        """registry.yaml 이 바뀌었으면 다시 읽는다."""
        path = Path(settings.registry_path)
        if not path.is_file():
            log.warning("registry 파일이 없습니다: %s", path)
            return
        mtime = path.stat().st_mtime
        if mtime == self._mtime:
            return
        self._mtime = mtime

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entries: dict[str, str] = {}
        for entry in data.get("agents", []) or []:
            # 한 줄이 잘못 적혀 있어도 나머지 에이전트는 살려둔다.
            if not isinstance(entry, dict) or not entry.get("id") or not entry.get("url"):
                log.warning("registry 항목을 건너뜁니다 (id/url 누락): %s", entry)
                continue
            entries[str(entry["id"])] = str(entry["url"]).rstrip("/")

        # 사라진 항목은 제거하고, 새 항목은 오프라인 상태로 추가한다.
        for gone in set(self._agents) - set(entries):
            del self._agents[gone]
        for agent_id, url in entries.items():
            if agent_id in self._agents:
                self._agents[agent_id].url = url
            else:
                self._agents[agent_id] = AgentInfo(id=agent_id, url=url)
        log.info("registry 로드: %d개 - %s", len(entries), ", ".join(entries))

    async def _probe(self, client: httpx.AsyncClient, agent: AgentInfo) -> None:
        """에이전트 하나의 manifest 를 읽어 상태를 갱신한다."""
        try:
            res = await client.get(f"{agent.url}/manifest", timeout=5.0)
            res.raise_for_status()
            manifest = Manifest(**res.json())
            agent.manifest = manifest
            agent.online = True
            agent.error = None
            agent.contract_mismatch = manifest.contract_version != CONTRACT_VERSION
            if manifest.id != agent.id:
                agent.error = f"manifest 의 id({manifest.id})가 registry.yaml 과 다릅니다"
        except Exception as exc:  # noqa: BLE001 - 죽은 에이전트는 오프라인 표시만 하면 된다
            agent.online = False
            agent.error = f"{type(exc).__name__}: {exc}"

    async def refresh(self) -> None:
        """파일을 다시 읽고 전체 에이전트를 동시에 확인한다."""
        self._load_file()
        if not self._agents:
            return
        async with httpx.AsyncClient() as client:
            await asyncio.gather(*(self._probe(client, a) for a in self._agents.values()))

    async def _loop(self) -> None:
        while True:
            try:
                await self.refresh()
            except Exception:  # noqa: BLE001 - 폴링이 죽으면 목록이 굳어버린다
                log.exception("registry 갱신 실패")
            await asyncio.sleep(settings.health_poll_s)

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()


registry = Registry()
