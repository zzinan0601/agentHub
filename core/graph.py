"""코디네이터 오케스트레이션 - LangGraph 3단계: plan -> dispatch -> reduce. (요구사항 4/15)

이벤트(status/delta/result)는 큐를 통해 밖으로 흘려보내고, 라우터의 요청 처리기가
그 큐를 읽어 NDJSON 으로 브라우저에 중계한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from typing import Any, AsyncIterator, TypedDict

from langgraph.graph import END, StateGraph

from core import dispatcher, harness, llm, router_log
from core.config import settings
from core.contract import InvokeRequest, Turn
from core.registry import registry

log = logging.getLogger("graph")

# 큐의 끝을 알리는 신호
_END_OF_STREAM = object()


class ChatState(TypedDict, total=False):
    """그래프가 들고 다니는 상태."""

    room_id: int
    query: str
    model: str
    context: list[dict[str, str]]  # [{"role": ..., "content": ...}]
    selected: list[str]  # 사용자가 화면에서 고른 에이전트 (없으면 LLM 이 고른다)
    mode: str  # parallel | sequential
    workflow: str | None
    who: str  # 지금 부르는 사람의 표시 이름. '사용 중' 표시에 그대로 쓴다
    # 단계별 소요 시간(ms). 어디가 느린지 알려면 재는 것부터 있어야 한다.
    timings: dict[str, int]
    plan: dict[str, Any]
    results: list[dict[str, Any]]  # 에이전트별 결과
    final_markdown: str
    final_attachments: list[dict[str, Any]]
    queue: Any  # asyncio.Queue - 이벤트 중계용


# ---------------------------------------------------------------------------
# 보조 함수
# ---------------------------------------------------------------------------


async def _emit(state: ChatState, event: dict[str, Any]) -> None:
    await state["queue"].put(event)


def _mark(state: ChatState, key: str, started: float) -> None:
    """단계 하나가 쓴 시간을 기록한다.

    지금까지는 에이전트 시간만 남아 있어, 느릴 때 코어가 느린 건지 에이전트가 느린 건지
    가릴 수가 없었다. 튜닝을 하려면 이것부터 있어야 한다.

    timings 는 run_chat 이 미리 만들어 둔 **하나의 dict** 다. 노드마다 상태 사본을 받으므로
    여기서 새로 만들면 다른 노드에는 보이지 않는다. 같은 객체를 고쳐야 한다.
    """
    state["timings"][key] = int((time.monotonic() - started) * 1000)


def _agent_name(agent_id: str) -> str:
    """화면에 보이는 이름. 등록이 안 돼 있으면 id 를 그대로 쓴다."""
    info = registry.get(agent_id)
    return info.manifest.name if info and info.manifest else agent_id


def _agent_catalog() -> str:
    """라우터 LLM 에게 보여줄 에이전트 목록.

    켜져 있고 **지금 비어 있는** 것만 후보가 된다. 남이 쓰는 중인 에이전트를 후보로 주면
    LLM 이 그걸 고르고, 부르는 순간 AGENT_BUSY 로 튕긴다. 애초에 보여주지 않는다.
    """
    lines = []
    for agent in registry.callable():
        m = agent.manifest
        if not m:
            continue
        examples = " / ".join(m.examples[:3])
        lines.append(f"- id: {m.id}\n  설명: {m.description.strip()}\n  질문 예시: {examples}")
    return "\n".join(lines) if lines else "(현재 켜져 있는 에이전트가 없습니다)"


# 생각을 먼저 적고 답하는 모델이 있다. 그 안에도 중괄호가 들어 있어 먼저 걷어낸다.
_THINK = re.compile(r"<(?:think|thinking|reasoning)>.*?</(?:think|thinking|reasoning)>", re.DOTALL | re.IGNORECASE)


def _json_candidates(text: str) -> list[str]:
    r"""중괄호 짝을 세어 최상위 {...} 덩어리를 전부 뽑는다.

    예전에는 `\{.*\}` 하나로 잡았는데, 그건 **첫 { 부터 마지막 } 까지**를 통째로
    집어온다. 모델이 설명을 곁들이거나 JSON 을 두 번 내면 두 덩어리가 하나로 붙어
    반드시 파싱이 깨진다. 작은 로컬 모델에서 이런 출력이 흔하다.
    """
    out: list[str] = []
    depth = 0
    start = -1
    in_str = False
    escape = False
    for i, ch in enumerate(text):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth:
                depth -= 1
                if depth == 0 and start >= 0:
                    out.append(text[start : i + 1])
    return out


def _extract_json(text: str) -> dict[str, Any] | None:
    """LLM 응답에서 계획 JSON 을 뽑아낸다. 코드펜스·설명·생각 블록이 섞여도 견딘다."""
    cleaned = _THINK.sub(" ", text or "")
    fallback: dict[str, Any] | None = None
    for chunk in _json_candidates(cleaned):
        try:
            data = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        # 여러 덩어리가 나오면 agents 를 가진 것이 진짜 계획이다.
        if isinstance(data.get("agents"), list):
            return data
        fallback = fallback or data
    return fallback


# ---------------------------------------------------------------------------
# 노드 1. plan - 누구를 어떤 순서로 부를지 정한다
# ---------------------------------------------------------------------------


async def plan_node(state: ChatState) -> dict[str, Any]:
    # (1) 워크플로우가 지정되어 있으면 라우팅 자체를 하지 않는다. (요구사항 11)
    if state.get("workflow"):
        wf = harness.get_workflow(state["workflow"])
        if wf:
            plan = {
                "agents": [s["agent"] for s in wf.get("steps", [])],
                "mode": wf.get("mode", "sequential"),
                "source": "workflow",  # 집계가 reason 문장을 추측하지 않도록 명시한다
                "reason": f"워크플로우 '{wf.get('name', state['workflow'])}'",
            }
            await _emit(state, {"type": "plan", **plan})
            return {"plan": plan}

    # (2) 사용자가 화면에서 직접 골랐으면 그대로 따른다. (요구사항 15/17)
    if state.get("selected"):
        plan = {
            "agents": state["selected"],
            "mode": state.get("mode", "parallel"),
            "source": "manual",
            "reason": "사용자가 직접 선택",
        }
        await _emit(state, {"type": "plan", **plan})
        return {"plan": plan}

    # (3) 아무것도 안 골랐으면 코디네이터 LLM 이 고른다.
    await _emit(state, {"type": "status", "message": "어떤 에이전트를 부를지 판단 중"})
    prompt = harness.prompt("router", agents=_agent_catalog(), query=state["query"])
    plan: dict[str, Any] = {
        "agents": [],
        "mode": "parallel",
        "source": "auto",
        "reason": "",
    }

    # Ollama 에게 "JSON 만 내라" 고 강제한다. 프롬프트로 부탁하는 것과 달리 디코딩
    # 단계에서 막으므로, 작은 로컬 모델도 설명 문장이나 코드펜스를 섞을 수 없다.
    # 라우팅은 매번 같은 답이 나오는 편이 좋아 temperature 도 0 으로 둔다.
    options: dict[str, Any] = {"temperature": 0}
    if settings.router_json_format:
        options["format"] = "json"

    last_text = ""
    started = time.monotonic()
    retries = max(1, settings.router_retries)
    for attempt in range(retries):
        one = time.monotonic()
        call = llm.prepare(prompt, model=state["model"], max_tokens=300, **options)
        last_text = await call.invoke()
        took = int((time.monotonic() - one) * 1000)
        parsed = _extract_json(last_text)
        if parsed and isinstance(parsed.get("agents"), list):
            plan = {
                "agents": [str(a) for a in parsed["agents"]],
                "mode": parsed.get("mode", "parallel"),
                "source": "auto",
                "reason": parsed.get("reason", ""),
            }
            router_log.success(
                state["model"], state["query"], plan["agents"], took, attempt + 1
            )
            break

        # 콘솔에는 짧게, 파일에는 응답 원문을 통째로. 300자로 잘린 로그로는
        # 폐쇄망에서 원인을 찾을 수 없다.
        reason = router_log.diagnose(last_text)
        log.warning(
            "라우터 JSON 파싱 실패 (%d/%d회차) model=%s: %s",
            attempt + 1, retries, state["model"], reason,
        )
        router_log.prompt_once(prompt)
        router_log.failure(
            model=state["model"],
            query=state["query"],
            prompt=prompt,
            response=last_text,
            attempt=attempt + 1,
            retries=retries,
            num_ctx=call.num_ctx,
            max_tokens=call.max_tokens,
            json_format=settings.router_json_format,
            ms=took,
        )
        prompt += '\n\n반드시 JSON 객체 하나만 출력하세요. 다른 글자는 쓰지 마세요.'
    else:
        # 다 실패했다. 조용히 '직접 답변' 으로 넘어가면 원인을 영영 못 찾는다.
        log.error(
            "라우터가 끝내 JSON 을 못 냈습니다. 에이전트 없이 직접 답변합니다. "
            "model=%s ROUTER_JSON_FORMAT=%s / 자세한 것은 %s",
            state["model"], settings.router_json_format, settings.router_log_path,
        )
        router_log.give_up(state["model"], state["query"], last_text)
        plan["reason"] = "라우팅 판단 실패 (에이전트를 고르지 못했습니다)"

    _mark(state, "route_ms", started)
    await _emit(state, {"type": "plan", **plan})
    return {"plan": plan}


# ---------------------------------------------------------------------------
# 노드 2. dispatch - 계획대로 에이전트를 부른다
# ---------------------------------------------------------------------------


async def dispatch_node(state: ChatState) -> dict[str, Any]:
    started = time.monotonic()
    plan = state["plan"]
    agents, missing = dispatcher.resolve(plan["agents"])

    results: list[dict[str, Any]] = []
    for agent_id in missing:
        message = f"'{agent_id}' 를 부를 수 없습니다 (등록되지 않았거나 꺼져 있음)"
        await _emit(state, {"type": "error", "agent_id": agent_id, "message": message})
        results.append({"agent_id": agent_id, "ok": False, "error": message})

    if not agents:
        return {"results": results}

    def make_req(agent) -> InvokeRequest:
        return InvokeRequest(
            request_id=str(uuid.uuid4()),
            room_id=state["room_id"],
            query=state["query"],
            context=[Turn(**t) for t in state.get("context", [])],
            model=state["model"],
            stream=True,
        )

    runner = (
        dispatcher.run_sequential if plan.get("mode") == "sequential" else dispatcher.run_parallel
    )
    async for event in runner(agents, make_req, state.get("who", "")):
        await _emit(state, event)  # 진행 상황을 그대로 브라우저에 중계
        if event.get("type") == "result":
            results.append(
                {
                    "agent_id": event.get("agent_id"),
                    "ok": True,
                    "markdown": event.get("markdown", ""),
                    "attachments": event.get("attachments") or [],
                    "meta": event.get("meta") or {},
                }
            )
        elif event.get("type") == "error":
            results.append(
                {
                    "agent_id": event.get("agent_id"),
                    "ok": False,
                    "error": event.get("message", ""),
                }
            )

    _mark(state, "agents_ms", started)
    return {"results": results}


# ---------------------------------------------------------------------------
# 노드 3. reduce - 결과를 하나의 Markdown 으로 정리한다
# ---------------------------------------------------------------------------


async def reduce_node(state: ChatState) -> dict[str, Any]:
    results = state.get("results", [])
    ok = [r for r in results if r.get("ok")]
    failed = [r for r in results if not r.get("ok")]
    attachments = [a for r in ok for a in r.get("attachments", [])]

    # (1) 부를 에이전트가 없었다 -> 코디네이터가 직접 답한다
    if not results:
        history = "\n".join(f"- {t['role']}: {t['content']}" for t in state.get("context", []))
        prompt = harness.prompt(
            "direct",
            format_rules=harness.skill("md-format"),
            context=history or "(없음)",
            query=state["query"],
        )
        started = time.monotonic()
        call = llm.prepare(prompt, model=state["model"])
        async for token in call.stream():
            await _emit(state, {"type": "delta", "text": token})
        _mark(state, "direct_ms", started)
        return {"final_markdown": call.text, "final_attachments": []}

    # (2) 성공한 결과가 하나뿐이면 그대로 쓴다. 굳이 LLM 을 한 번 더 돌리지 않는다.
    if len(ok) == 1:
        markdown = ok[0]["markdown"]
        if failed:
            markdown += "\n\n> 확인 필요: " + ", ".join(
                f"{f['agent_id']} ({f.get('error', '')})" for f in failed
            )
        return {"final_markdown": markdown, "final_attachments": attachments}

    # (3) 전부 실패했다면 LLM 을 부르지 않고 실패 사유만 정리해서 보여준다.
    if not ok:
        markdown = "## 결과 없음\n\n호출한 에이전트가 모두 실패했습니다.\n\n" + "\n".join(
            f"- **{f['agent_id']}**: {f.get('error', '')}" for f in failed
        )
        return {"final_markdown": markdown, "final_attachments": []}

    # (4) 여러 결과를 어떻게 낼지는 .env 의 REDUCE_MODE 가 정한다.
    #     순차든 병렬이든 똑같이 다룬다.
    #
    #     한때 순차는 "마지막 결과가 곧 답" 으로 특별 취급했는데, 그러면 앞 단계가
    #     만든 것이 통째로 사라진다. "매출 알려주고 요약해줘" 는 표와 요약을 **둘 다**
    #     원한 것이지 요약만 원한 것이 아니다. 뒤 단계가 앞 단계를 대신한다고
    #     단정할 근거가 없다.

    # 합치면 읽기는 좋지만 로컬 모델로 LLM 한 번이 더 붙어 수십 초가 늘어난다.
    # 폐쇄망에서는 그 값이 크므로 기본은 붙이기만 한다.
    if settings.reduce_mode != "llm":
        parts = [f"## {_agent_name(r['agent_id'])}\n\n{r['markdown'].strip()}" for r in ok]
        markdown = "\n\n".join(parts)
        if failed:
            markdown += "\n\n> 확인 필요: " + ", ".join(
                f"{f['agent_id']} ({f.get('error', '')})" for f in failed
            )
        return {"final_markdown": markdown, "final_attachments": attachments}

    await _emit(state, {"type": "status", "message": "결과를 하나로 정리하는 중"})
    blocks = [f"### {r['agent_id']}\n{r['markdown']}" for r in ok]
    blocks += [f"### {r['agent_id']} (실패)\n{r.get('error', '')}" for r in failed]
    # 순차인지 알려주지 않으면 "겹치면 한 번만" 규칙에 걸려 뒤 단계를 통째로 지운다.
    sequential = state.get("plan", {}).get("mode") == "sequential"
    prompt = harness.prompt(
        "reduce",
        format_rules=harness.skill("md-format"),
        mode_note=(
            "순차 — 뒤 에이전트가 앞 결과를 받아 다듬었습니다. "
            "원본(표 등)과 다듬은 결과를 둘 다 남기세요."
            if sequential
            else "병렬 — 각자 다른 정보를 따로 가져왔습니다."
        ),
        query=state["query"],
        results="\n\n".join(blocks),
    )
    started = time.monotonic()
    call = llm.prepare(prompt, model=state["model"])
    async for token in call.stream():
        await _emit(state, {"type": "delta", "text": token})
    _mark(state, "reduce_ms", started)
    return {"final_markdown": call.text, "final_attachments": attachments}


# ---------------------------------------------------------------------------
# 그래프 조립
# ---------------------------------------------------------------------------


def _build():
    graph = StateGraph(ChatState)
    graph.add_node("plan", plan_node)
    graph.add_node("dispatch", dispatch_node)
    graph.add_node("reduce", reduce_node)
    graph.set_entry_point("plan")
    graph.add_edge("plan", "dispatch")
    graph.add_edge("dispatch", "reduce")
    graph.add_edge("reduce", END)
    return graph.compile()


CHAT_GRAPH = _build()


async def run_chat(state: ChatState) -> AsyncIterator[dict[str, Any]]:
    """그래프를 돌리면서 발생하는 이벤트를 하나씩 내보낸다.

    마지막에는 항상 result(또는 error) 이벤트가 한 번 나온다.
    """
    queue: asyncio.Queue = asyncio.Queue()
    state["queue"] = queue
    # 노드마다 상태 사본을 받으므로, 계측 칸은 여기서 하나 만들어 공유한다.
    state["timings"] = {}
    started = time.monotonic()

    async def _run() -> None:
        try:
            final = await CHAT_GRAPH.ainvoke(state)
            await queue.put(
                {
                    "type": "result",
                    "markdown": final.get("final_markdown", ""),
                    "attachments": final.get("final_attachments", []),
                    "meta": {
                        "plan": final.get("plan", {}),
                        "model": state["model"],
                        # 어디서 시간을 썼는지. 코어가 느린지 에이전트가 느린지 가른다.
                        "timings": {
                            **state["timings"],
                            "total_ms": int((time.monotonic() - started) * 1000),
                        },
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001 - 무슨 일이 있어도 종료 이벤트는 보낸다
            log.exception("대화 처리 실패")
            await queue.put(
                {"type": "error", "message": f"{type(exc).__name__}: {exc}", "code": "CORE_ERROR"}
            )
        finally:
            await queue.put(_END_OF_STREAM)

    task = asyncio.create_task(_run())
    try:
        while True:
            event = await queue.get()
            if event is _END_OF_STREAM:
                break
            yield event
    finally:
        if not task.done():
            task.cancel()
