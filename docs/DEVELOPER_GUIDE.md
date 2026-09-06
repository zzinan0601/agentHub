# 내 에이전트 만들기

처음부터 끝까지 따라 하면 30분 안에 자기 업무 에이전트를 코어에 붙일 수 있다.
계약의 상세 규칙은 [AGENT_CONTRACT.md](AGENT_CONTRACT.md) 를 본다.

---

## 0. 준비물

- Python 3.12
- 내 노트북에서 도는 Ollama (`ollama list` 로 모델 확인)
- 이 저장소를 clone 한 폴더. 아래 명령은 전부 그 폴더 안에서 실행한다

---

## 1. 내 에이전트 폴더 만들기

```bash
python scripts/new_agent.py sales-report "홍길동"
```

- 첫 번째 인자: 에이전트 id (영문 소문자/하이픈). 이후 계속 쓰는 이름이다.
- 두 번째 인자: 담당자 이름.
- 포트는 **전원이 9010** 이라 적지 않는다. 에이전트마다 노트북이 다르므로 IP 가 이미
  서로를 구분하고, 방화벽도 한 포트만 열면 된다. 한 노트북에서 두 개를 띄울 때만
  세 번째 인자로 다른 포트를 준다.

`agents/sales-report/` 가 만들어지고 `manifest.yaml` 과 `.env` 가 채워진다.

```bash
cd agents/sales-report
setup.bat
```

가상환경을 만들고 의존성을 설치한다. (최초 1회)

---

## 2. manifest.yaml 채우기 - 여기가 가장 중요하다

```yaml
id: sales-report
name: 매출 리포트
owner: 홍길동

description: |
  영업 오라클 DB 의 일별 매출 테이블을 조회해 기간별/지점별 매출 합계와
  전월 대비 증감을 Markdown 표로 정리한다. 최대 조회 기간은 12개월이다.

tags: [매출, 오라클]

examples:
  - 지난달 지점별 매출 알려줘
  - 3월 매출 상위 10개 지점은?
```

사용자가 화면에서 에이전트를 직접 고르지 않으면 **코디네이터 LLM 이 `description` 과
`examples` 만 읽고** 누구를 부를지 정한다. "매출을 조회한다" 처럼 뭉뚱그리면 비슷한
에이전트와 구분되지 않아 엉뚱하게 호출되거나 아예 호출되지 않는다.

좋은 설명은 세 가지를 담는다: **어떤 데이터를 / 어떤 기간·단위로 / 어떤 형태로 준다.**

---

## 3. agent.py 채우기 - 내가 고치는 유일한 파일

`main.py`, `contract.py`, `llm.py`, `files.py` 는 계약 고정부다. **건드리지 않는다.**

```python
async def fetch_business_data(query: str) -> str:
    """여기에 내 업무 조회를 구현한다."""
    # 오라클이든 PostgreSQL 이든 사내 API 든 자유다.
    # LLM 이 읽을 수 있도록 문자열(가급적 Markdown 표)로 돌려주면 뒤가 편하다.
    ...
```

`run()` 의 기본 뼈대는 이미 들어 있다. 보통은 `fetch_business_data()` 만 채우면 끝난다.

```python
async def run(req: InvokeRequest) -> AsyncIterator[Event]:
    yield status("업무 데이터 조회 중")
    data = await fetch_business_data(req.query)

    yield status("응답 작성 중")
    call = llm.prepare(build_prompt(req, data), model=req.model, system=SYSTEM_PROMPT)
    async for token in call.stream():
        yield delta(token)

    yield result(call.text, **call.meta())
```

### 업무 DB 붙이기

템플릿은 DB 접근을 강제하지 않는다. 각자 편한 라이브러리를 `requirements.txt` 에
**버전을 명시해서** 추가한다.

```
oracledb==2.5.1          # 오라클
psycopg[binary]==3.2.3   # PostgreSQL
```

접속 정보는 **코드에 쓰지 않고 `.env` 에 넣는다.**

```
# .env
BIZ_DB_DSN=oracle+oracledb://scott:tiger@dbhost:1521/?service_name=ORCL
```

```python
import os
DSN = os.getenv("BIZ_DB_DSN")   # 하드코딩 금지
```

### LLM 이 만든 SQL 을 그대로 실행하지 않기

질문을 SQL 로 바꾸는 방식을 쓴다면, 조회 대상 테이블과 조건을 코드에서 고정하고
LLM 에게는 값만 뽑게 하는 편이 안전하다. 최소한 SELECT 만 허용하고 바인드 파라미터를 쓴다.

### 프롬프트는 prompt.md 에

시스템 프롬프트는 `prompt.md` 파일에 있다. 코드를 고치지 않고 문구만 다듬을 수 있고,
서버를 다시 띄우면 반영된다.

---

## 4. 이미지나 파일을 함께 주고 싶다면

```python
from files import save_bytes

att = save_bytes(png_bytes, "매출차트.png")
yield result(f"## 매출 추이\n\n![차트](attachment:{att.file})", attachments=[att])
```

- 이미지는 본문에 그대로 그려지고, 엑셀·PDF 는 화면 아래 다운로드 링크로 뜬다.
- **CSV 는 `save_text()` 를 쓴다.** `.csv` / `.tsv` 에 UTF-8 BOM 을 자동으로 붙여준다.
  BOM 이 없으면 엑셀이 CP949 로 읽어 한글이 전부 깨진다.
- 파일은 **내 노트북**에 남는다. 노트북을 끄면 과거 대화의 파일도 열리지 않는다.
- 기본 72시간 뒤 자동 삭제된다 (`AGENT_FILE_TTL_HOURS`).

---

## 5. 띄우고 확인하기

```bash
run.bat
```

다른 창에서 자가검사를 돌린다.

```bash
python scripts/check_contract.py http://localhost:9010
```

전 항목이 `OK` 여야 한다. 눈으로 직접 보고 싶으면:

```bash
curl -s http://localhost:9010/manifest
```

```bash
curl -N -X POST http://localhost:9010/invoke -H "Content-Type: application/json" -d "{\"request_id\":\"t1\",\"room_id\":1,\"query\":\"test\",\"model\":\"gemma4:31b-cloud\",\"stream\":true}"
```

NDJSON 이 한 줄씩 흘러나오고 **마지막 줄이 `result`** 면 정상이다.

---

## 6. registry.yaml 에 등록하기

```yaml
agents:
  - id: sales-report
    url: http://192.168.0.31:9010 # 내 노트북 IP. 개발 중엔 localhost
```

코어는 이 파일을 30초마다 다시 읽으므로 **코어를 재기동할 필요가 없다.**
화면 오른쪽 에이전트 목록에 초록 점과 함께 나타나면 성공이다.

---

## 7. 자주 하는 실수

| 증상 | 원인 |
| --- | --- |
| 목록에 안 보임 | `registry.yaml` 에 없거나 `id` 가 manifest 와 다름 |
| 회색 점(꺼짐)으로 표시 | 프로세스가 죽었거나 방화벽이 포트를 막음. 다른 PC 에서 `curl <내IP>:9010/health` 로 확인 |
| "계약 버전이 다릅니다" | `contract.py` 가 옛날 복사본. `scripts/sync_contract.py` 결과로 덮어쓴다 |
| `NO_RESULT` 오류 | `run()` 이 `result` 를 yield 하지 않고 끝남 |
| 응답이 깨져 보임 | `markdown` 이 아니라 평문/JSON 을 넣음 |
| 화면이 한참 멈춤 | `status` 를 하나도 안 보냄. 오래 걸리는 단계마다 `yield status(...)` 를 넣는다 |
| 내가 부르지 않았는데 호출됨 / 안 됨 | `description` 이 모호함. 구체적으로 다시 쓴다 |
| 첨부가 안 열림 | 내 노트북이 꺼져 있음 (캐시하지 않는 구조) |
| 엑셀에서 CSV 한글이 깨짐 | `save_bytes` 로 직접 저장했다. `save_text()` 를 쓰면 BOM 이 자동으로 붙는다 |

---

## 8. 체크리스트

- [ ] `manifest.yaml` 의 `description` 이 구체적이고 `examples` 가 2개 이상
- [ ] `main.py` / `contract.py` / `llm.py` / `files.py` 를 고치지 않음
- [ ] 접속 정보·경로·모델명을 코드에 하드코딩하지 않고 `.env` 로 뺌
- [ ] `requirements.txt` 의 모든 패키지에 `==` 버전이 명시됨
- [ ] `python scripts/check_contract.py <내주소>` 전 항목 통과
- [ ] `registry.yaml` 에 등록하고 화면에서 초록 점 확인
