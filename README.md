# 에이전트 허브

개발자 10명이 각자 하나씩 만든 업무 에이전트를, 코디네이터가 **똑같은 방식으로** 불러
쓰는 사내 채팅 플랫폼. 개발은 인터넷 환경에서 하고 결과물은 폐쇄망으로 반입한다.

이 저장소가 내놓는 것은 세 가지다.

1. **코어** — 채팅 UI + 코디네이터. 에이전트를 단일·병렬·순차로 부르고 결과를 합친다.
2. **에이전트 템플릿** — 계약을 이미 지키고 있는 껍데기. 개발자는 `agent.py` 한 파일만 채운다.
3. **문서** — 계약 명세와 따라하기 가이드.

---

## 5분 만에 띄우기

### 1) 코어

```bash
python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt
```

```bash
copy .env.example .env
```

`.env` 에서 최소 두 줄을 확인한다.

```
DATABASE_URL=postgresql+asyncpg://postgres:암호@localhost:5432/agenthub
DEFAULT_MODEL=gemma4:31b-cloud
```

PostgreSQL 에 빈 데이터베이스를 하나 만든 뒤(`CREATE DATABASE agenthub;`) 띄운다.
테이블은 자동으로 생성된다. DDL 을 미리 검토하거나 직접 만들어야 한다면
[sql/](sql/) 의 스크립트를 쓴다.

```bash
python -m core.main
```

### 2) 예제 에이전트 (계약 확인용)

```bash
cd agents/echo && ..\..\.venv\Scripts\python main.py
```

```bash
cd agents/summary && ..\..\.venv\Scripts\python main.py
```

### 3) 화면

```bash
cd ui && npm install && npm run dev
```

`http://localhost:5173` 으로 접속한다.
(`npm run build` 를 해두면 코어가 `http://localhost:8000` 에서 화면까지 직접 서빙한다)

### 4) 처음 들어가기

이름을 넣으면 바로 들어간다. **비밀번호를 받지 않는다.** 처음 들어온 사람이 계정과
함께 만들어지고, **맨 처음 계정이 관리자**가 된다.

들어가면 **Dashboard** 가 먼저 열린다. 자리를 비운 사이 스케줄이 남긴 결과가 어느 방에
쌓였는지 여기서 확인하고 대화로 넘어가면 된다.

> 비밀번호가 없으므로 이것은 인증이 아니라 신원 표시다. 남의 이름을 넣으면 그 사람으로
> 들어올 수 있다. **반드시 사내망 안에서만 띄운다.** 인터넷에 노출하지 않는다.

---

## 구조

```
core/            코디네이터 + 채팅 API (FastAPI, LangGraph)
  contract.py      ★ 계약 스키마 - 모든 에이전트가 공유하는 원본
  auth.py          로그인 (이름만, 비밀번호 없음) + 세션
  migrate.py       기존 테이블에 컬럼 덧붙이기 (멱등)
  llm.py           ★ Ollama 호출 + num_ctx 동적 계산
  graph.py         plan -> dispatch -> reduce
  dispatcher.py    단일 / 병렬 / 순차 호출
  registry.py      registry.yaml 로드 + 생존 확인
  scheduler.py     방당 1개 스케줄
  prompts/         소프트 하네스 - 라우팅·통합 규칙 (md)
  skills/          공통 출력 규칙 (md)
  workflows/       고정 파이프라인 (yaml)
agent_template/  ★ 개발자에게 배포하는 템플릿
  agent.py         개발자가 고치는 유일한 파일
agents/          각자 만든 에이전트 (new_agent.py 가 생성)
ui/              Vue3 화면
scripts/         계약 동기화 / 스캐폴딩 / 자가검사 / E2E
sql/             테이블 생성 스크립트 (DBA 가 직접 만들어야 할 때)
vendor/          폐쇄망 반입용 사전 다운로드 (파이썬 휠)
docs/            계약 명세, 개발 가이드, 반입 절차
registry.yaml    호출 가능한 에이전트 목록
```

---

## 핵심 규칙

### 에이전트 계약

모든 에이전트는 독립 FastAPI 프로세스이며 `/manifest`, `/health`, `/invoke`, `/files/{name}`
네 개만 노출한다. `/invoke` 는 **NDJSON(streamable HTTP)** 으로 응답하고 마지막 줄은 반드시
`result` 또는 `error` 다. → [docs/AGENT_CONTRACT.md](docs/AGENT_CONTRACT.md)

### 소프트 하네스

라우팅 규칙, 출력 형식, 결과 통합 방식은 코드가 아니라 `core/prompts/*.md` 와
`core/skills/*.md` 파일이다. 파이썬 코드에 프롬프트 문자열을 넣지 않는다.
파일을 고치면 다음 호출부터 바로 반영된다. 판단을 고정하고 싶으면
`core/workflows/*.yaml` 로 순서를 못 박는다. **워크플로우는 화면에서 원문을 보고 그대로
등록·수정·삭제할 수 있다.** → [docs/WORKFLOWS.md](docs/WORKFLOWS.md)

### 설정

모든 설정은 `.env` 에서 온다. 모델명, 주소, 포트, 임계값을 코드에 박지 않는다.
`requirements.txt` 는 전 항목 버전을 `==` 로 고정한다.

### num_ctx

`llm.prepare()` 가 프롬프트 길이 + 응답 길이로 매 호출 계산한다. 고정값을 쓰지 않는다.

### 라우팅

화면에서 에이전트를 고르면 그대로 실행하고, 아무것도 고르지 않으면 코디네이터 LLM 이
manifest 설명을 읽고 누구를 어떤 순서로 부를지 정한다.

### 코어 LLM 이 끼는 곳

| 언제 | |
|---|---|
| 라우팅 | 에이전트를 **안 골랐을 때만**. 직접 고르거나 워크플로우면 건너뛴다 |
| 직접 답변 | 부를 에이전트가 없을 때. 그 자체가 답이다 |
| 합치기 | 병렬로 2개 이상 성공했고 `REDUCE_MODE=llm` 일 때만 |

기본값 `REDUCE_MODE=off` 는 합치지 않고 **에이전트 이름을 제목으로 붙인다.** 로컬 모델은
한 번 부를 때마다 수십 초라 그 값이 크기 때문이다. 읽기 좋게 합치고 싶으면 `llm` 으로 바꾼다.
**순차도 똑같이 다룬다** — 뒤 단계가 앞 단계를 대신한다고 단정하지 않는다.
"매출 알려주고 요약해줘" 는 표와 요약을 둘 다 원한 것이지 요약만 원한 것이 아니다.

즉 **에이전트를 직접 고르면 코어 LLM 이 한 번도 불리지 않는다.**

어디서 시간을 썼는지는 답변의 실행 트레이스에 `코디네이터 1.8s (라우팅 1.8s)` 로 보이고,
Dashboard 의 `코디네이터` 타일에 평균이 뜬다.

### 순차 실행 순서

| 고르는 방법 | 순서 |
|---|---|
| 직접 선택 | **고른 순서.** 오른쪽 패널 `실행 방식 > 호출 순서` 에서 ↑↓ 로 바꾼다 |
| 자동 라우팅 | 라우터 LLM 이 낸 순서 |
| 워크플로우 | yaml 의 `steps` 순서 |

### 모델

방에서 고른 모델이 코어와 에이전트 전부에 쓰인다. (요구사항 18) 다만 **에이전트는 각자
자기 노트북의 Ollama 를 부르므로** 화면 목록에 있는 모델이 그 노트북에는 없을 수 있다.
그럴 때는 에이전트 `.env` 의 `AGENT_MODEL` 에 적어 고정한다. 고정한 에이전트는 화면
목록에 `gemma4:e4b 고정` 으로 표시된다. → [docs/AGENT_CONTRACT.md](docs/AGENT_CONTRACT.md)

### 동시 호출

폐쇄망의 로컬 모델은 한 응답에 몇 분이 걸린다. 그 사이 **다른 사람이 같은 에이전트를 또
부르면 Ollama 를 나눠 쓰며 둘 다 느려진다.** 그래서 호출 중인 에이전트는 목록에 **주황**으로
표시되고 고를 수 없다. 누가 몇 초째 쓰는지도 함께 보인다.

브라우저가 끊겨도(탭 닫기·새로고침·방 이동) **서버는 끝까지 돌고 결과를 저장한다.**
다시 열면 답이 있다. 몇 분 걸린 응답을 실수 하나로 잃지 않기 위해서다.
잘못 보낸 질문은 `보내기` 자리에 나타나는 `중단` 으로 멈출 수 있고, 중단해도 그때까지
받은 부분 결과는 남는다.

### 사용자 구분

이름만으로 들어간다. 비밀번호가 없으므로 **보안 경계는 사내망이 맡고** 앱은 누가 무엇을
썼는지만 구분한다. 채팅방은 **개인 전용**이라 내가 만든 방은 내 목록에만 보인다.
Dashboard(활용 현황)는 전원 공개다. → [docs/INSIGHTS.md](docs/INSIGHTS.md)

---

## 점검 명령

```bash
python scripts/check_contract.py
```

registry 의 모든 에이전트가 계약을 지키는지 검사한다. 개발자는 제출 전에 돌린다.

```bash
python scripts/e2e_test.py
```

방 생성부터 단일·병렬·순차 호출, 첨부파일 프록시, 스케줄까지 전체 흐름을 확인한다.

```bash
python scripts/test_attachment_encoding.py
```

첨부파일 인코딩을 검사한다. 엑셀에서 CSV 한글이 깨지지 않는지 확인한다.

```bash
python scripts/test_similar.py
```

비슷한 질문을 묶는 기준이 맞는지 검사한다. `INSIGHT_SIMILARITY` 를 바꿨다면 돌려본다.

```bash
python scripts/test_workflow_api.py
```

화면에서 워크플로우를 만들고 고치고 지우는 길이 안전한지 검사한다.
코어가 파일을 쓰게 되었으므로 경로가 새지 않는지도 함께 본다.

```bash
python scripts/test_concurrency.py
```

```bash
python scripts/test_router_parse.py
```

```bash
python scripts/test_pipeline.py
```

```bash
python scripts/router_log.py
```

**자동 선택이 자꾸 실패할 때 가장 먼저 본다.** 라우터가 실제로 무엇을 받았는지
`logs/router.log` 에 남으므로, 성공/실패 비율과 실패 원인, 응답 원문을 그대로 보여준다.

합치기 설정·순차 실행 순서·단계별 계측이 맞는지 검사한다.
`REDUCE_MODE` 나 순서 관련을 손봤다면 돌려본다.

라우터가 낸 응답에서 계획 JSON 을 뽑아내는지 검사한다. 코드펜스·설명·생각 블록이
섞인 출력을 넣어 본다. 코어를 띄우지 않아도 되고 1초면 끝난다.

동시 호출을 검사한다. 느린 에이전트를 잠깐 띄워 사용 중 표시·거부·중단과,
**브라우저가 끊겨도 결과가 저장되는지**를 확인한다. 1분쯤 걸린다.

```bash
python scripts/users.py list
```

사용자 목록을 본다. `rename` / `disable` / `enable` / `admin` 도 있다.
사람을 지우는 명령은 없다. 지우는 대신 `disable` 을 쓴다.

```bash
python scripts/new_agent.py <id> <포트> "<담당자>"
```

내 에이전트 폴더를 만든다.

```bash
python scripts/sync_contract.py
```

계약 고정부(`main.py` `contract.py` `llm.py` `files.py`)를 core → 템플릿 → `agents/*` 순으로
맞춘다. `--check` 를 붙이면 고치지 않고 다른 것만 알려준다.

---

## 문서

- [**시작하기**](docs/START_HERE.md) — 에이전트를 맡은 개발자가 **가장 먼저** 읽는다
- [에이전트 계약 명세](docs/AGENT_CONTRACT.md) — 정본. 요청/응답 스키마와 규칙
- [내 에이전트 만들기](docs/DEVELOPER_GUIDE.md) — 개발자 10명이 따라 하는 순서
- [워크플로우](docs/WORKFLOWS.md) — 호출 순서를 고정하고 스케줄과 묶어 쓰기
- [스케줄](docs/SCHEDULE.md) — cron 식과 자주 쓰는 주기 모음
- [Dashboard](docs/INSIGHTS.md) — 지표를 읽고 무엇을 고칠지 판단하기
- [폐쇄망 반입 절차](docs/OFFLINE_DEPLOY.md) — 사전 준비부터 반입 후 점검까지
