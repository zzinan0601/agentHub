# 에이전트 계약 명세 v1.0

이 문서가 정본이다. 개발자 10명이 만드는 모든 에이전트는 여기 적힌 대로 동작해야 하며,
코디네이터(코어)는 그 이상을 가정하지 않는다. 계약만 지키면 내부는 무엇을 쓰든 자유다.

계약의 파이썬 구현은 [`core/contract.py`](../core/contract.py) 한 파일이고,
`agent_template/contract.py` 는 그 복사본이다. **직접 만들지 말고 복사본을 그대로 쓴다.**

---

## 1. 에이전트는 무엇인가

- 독립적으로 도는 **FastAPI 프로세스** 하나다. 개발자 각자의 노트북에서 뜬다.
- 아래 4개의 HTTP 엔드포인트를 노출한다. 그 외에는 코어가 부르지 않는다.
- 상태를 서버에 저장하지 않는다. 필요한 맥락은 매 요청의 `context` / `upstream` 으로 온다.

| 메서드 | 경로 | 용도 |
| --- | --- | --- |
| GET | `/manifest` | 자기소개. 라우팅 판단의 근거 |
| GET | `/health` | 생존 확인. 코어가 30초마다 부른다 |
| POST | `/invoke` | 실행 |
| GET | `/files/{파일명}` | 첨부파일 내려주기 |

---

## 2. GET /manifest

```json
{
  "contract_version": "1.0",
  "id": "sales-report",
  "name": "매출 리포트",
  "description": "영업 오라클 DB 의 일별 매출 테이블을 조회해 기간별/지점별 매출 합계와 전월 대비 증감을 Markdown 표로 정리한다. 최대 조회 기간은 12개월이다.",
  "owner": "홍길동",
  "tags": ["매출", "오라클"],
  "examples": ["지난달 지점별 매출 알려줘", "3월 매출 상위 10개 지점은?"]
}
```

- `id` 는 `registry.yaml` 의 `id` 와 **정확히 같아야 한다.** 다르면 코어가 경고를 띄운다.
- `description` 과 `examples` 는 **라우터 LLM 이 읽는 유일한 근거**다. 여기가 부실하면
  사용자가 에이전트를 직접 고르지 않는 한 호출되지 않는다. "무엇을, 어떤 단위로,
  어떤 형태로 주는지" 를 구체적으로 쓴다.
- 이 값들은 `manifest.yaml` 에 쓰면 템플릿이 알아서 읽어 응답한다.

## 3. GET /health

```json
{ "status": "ok", "agent_id": "sales-report", "contract_version": "1.0" }
```

템플릿이 자동으로 처리하므로 손댈 것이 없다.

---

## 4. POST /invoke

### 요청

```json
{
  "request_id": "8f3c…",
  "room_id": 12,
  "query": "지난달 지점별 매출 알려줘",
  "context": [{ "role": "user", "content": "…" }],
  "upstream": [{ "agent_id": "db-health", "markdown": "…" }],
  "model": "gemma4-12b",
  "options": {},
  "stream": true
}
```

| 필드 | 의미 |
| --- | --- |
| `request_id` | 추적용 UUID. 로그에 그대로 남긴다 |
| `room_id` | 채팅방 id |
| `query` | 사용자가 입력한 원문 |
| `context` | 최근 대화 N턴 (N은 코어의 `CONTEXT_TURNS`) |
| `upstream` | **순차 호출**일 때 앞 단계 에이전트의 결과. 단독/병렬이면 빈 배열 |
| `model` | 방에서 선택한 모델. **기본은 이 값을 그대로 쓴다.** 다만 `.env` 의 `AGENT_MODEL` 로 고정할 수 있다 (6-1) |
| `options` | temperature 등 부가 옵션 |
| `stream` | `false` 면 종료 이벤트 하나를 일반 JSON 으로 반환 (스케줄 실행이 이 모드를 쓴다) |

### 응답 - streamable HTTP (SSE 아님)

`Content-Type: application/x-ndjson` 으로 **한 줄에 JSON 하나씩** 흘려보낸다.
SSE(`text/event-stream`)를 쓰지 않는다.

```
{"type":"status","message":"업무 DB 조회 중"}
{"type":"delta","text":"매출 "}
{"type":"delta","text":"현황입니다"}
{"type":"result","markdown":"## 결과\n…","attachments":[],"meta":{"elapsed_ms":8210}}
```

| type | 언제 | 개수 |
| --- | --- | --- |
| `status` | 진행 상황 알림. 화면에 칩으로 표시된다 | 0개 이상 |
| `delta` | LLM 토큰 조각. 화면에 이어붙는다 | 0개 이상 |
| `result` | 성공 종료 | 종료 이벤트 |
| `error` | 실패 종료 | 종료 이벤트 |

### 지켜야 할 규칙 3가지

1. **마지막 줄은 반드시 `result` 또는 `error` 하나다.** 종료 이벤트가 없으면 코어는
   응답을 완결시킬 수 없다. (템플릿이 `NO_RESULT` 오류로 잡아준다)
2. **`result.markdown` 은 Markdown 이어야 한다.** 화면이 md 로 렌더하고 사용자가
   그 원문을 복사한다. JSON 덩어리나 파이썬 repr 을 넣지 않는다.
   조회 시각·소요 시간·모델명 같은 **부가 정보는 본문에 넣지 말고 `meta` 로 넘긴다.**
   화면이 답변 구석에 작게 따로 표시하므로 본문에 쓰면 중복이고 복사할 때도 거슬린다.

   ```python
   yield result(markdown, queried_at=f"{now:%Y-%m-%d %H:%M:%S}")   # meta 로
   ```
3. **예외를 밖으로 던지지 않는다.** 템플릿의 `main.py` 가 예외를 `error` 이벤트로
   바꿔주므로 `agent.py` 안에서는 그냥 던져도 되지만, 응답 본문이 500 HTML 이 되면
   병렬 호출에서 다른 에이전트의 결과까지 흔들린다.

---

## 5. 첨부파일 (이미지 / 엑셀 / PDF)

**파일 실물은 에이전트 노트북에 남는다.** 코어는 URL 만 받아 브라우저에 중계한다.

```python
from files import save_bytes

att = save_bytes(png_bytes, "매출차트.png")
yield result(f"## 매출 추이\n\n![차트](attachment:{att.file})", attachments=[att])
```

- `save_bytes()` / `save_text()` 가 파일을 `AGENT_FILES_DIR` 에 저장하고 `Attachment` 를 돌려준다.
- markdown 안에서 `attachment:<file>` 로 참조하면 코어가 실제 URL(`/api/files/<agent_id>/<file>`)
  로 바꿔준다. **에이전트가 URL 을 직접 만들지 않는다.**
- 참조하지 않은 첨부는 화면 아래에 다운로드 링크로 자동 표시된다.
- 브라우저는 항상 코어를 거치므로 에이전트마다 CORS 를 열 필요가 없다.
- 캐시하지 않는다. **에이전트 노트북이 꺼져 있으면 과거 대화의 파일도 열리지 않는다.**
- 파일은 `AGENT_FILE_TTL_HOURS`(기본 72시간) 이 지나면 기동 시 자동 삭제된다.

```json
{
  "name": "매출차트.png",
  "file": "9f1c…c4.png",
  "mime": "image/png",
  "size": 20481
}
```

`file` 에 경로 구분자(`/` `\`)나 `..` 가 들어가면 코어와 에이전트 양쪽에서 거부한다.

### 한글이 깨지지 않게 하려면

**엑셀은 내려받은 `.csv` 를 열 때 HTTP 의 `charset` 을 보지 않고 파일 바이트만 본다.**
UTF-8 BOM 이 없으면 한국어 윈도우에서 시스템 코드페이지(CP949)로 가정해 한글이 전부 깨진다.

`save_text()` 가 `.csv` / `.tsv` 에는 BOM 을 자동으로 붙이므로 **그 함수만 쓰면 신경 쓸 것이 없다.**

```python
from files import save_text

att = save_text(csv, "매출.csv", mime="text/csv; charset=utf-8")   # BOM 자동
att = save_text(log, "실행.log")                                    # BOM 없음 (기본)
att = save_text(csv, "원본.csv", bom=False)                         # 필요하면 끌 수 있다
```

직접 `save_bytes(text.encode("utf-8"), "매출.csv")` 로 저장하면 BOM 이 붙지 않아 깨진다.
엑셀에서 열릴 파일은 `save_text()` 를 쓴다.

라이브러리로 엑셀 파일(`.xlsx`)을 만드는 경우에는 해당하지 않는다. xlsx 는 내부가 UTF-8 로
고정되어 있어 인코딩 문제가 없다.

---

## 6. num_ctx 규칙

LLM 을 부를 때 `num_ctx` 를 고정값으로 박지 않는다. 프롬프트 길이 + 응답 길이로
매번 계산한다. `llm.prepare()` 가 이미 그렇게 동작하므로 그것만 쓰면 된다.

```python
call = llm.prepare(prompt, model=req.model, system=SYSTEM_PROMPT)
async for token in call.stream():
    yield delta(token)
yield result(call.text, **call.meta())   # meta 에 실제 num_ctx 가 실린다
```

계산식과 상·하한은 `.env` 의 `CHARS_PER_TOKEN`, `NUM_CTX_MARGIN`, `NUM_CTX_MIN/MAX` 로 조정한다.

---

## 6-1. 모델은 누가 정하나

기본은 **화면에서 고른 모델**이다. 코어가 `model` 로 내려주고 에이전트는 그대로 쓴다.
사용자가 모델을 바꿔가며 비교할 수 있어야 하기 때문이다. (요구사항 18)

다만 **에이전트는 각자 자기 노트북의 Ollama 를 부른다.** 화면의 모델 목록은 코어의
Ollama 에서 오므로, 거기 있는 모델이 내 노트북에는 없을 수 있다. 그러면 그 에이전트만
`MODEL_NOT_FOUND` 로 빠진다.

그래서 `.env` 에 빠져나갈 구멍을 두었다.

```
# 비워두면 화면에서 고른 모델을 쓴다 (기본)
AGENT_MODEL=

# 값을 적으면 화면에서 무엇을 고르든 이 모델로 돈다
AGENT_MODEL=gemma4:e4b
```

`main.py` 가 `run()` 을 부르기 전에 `req.model` 을 갈아 끼우므로 **`agent.py` 는 손댈 것이
없다.** 고정해 두면 `/manifest` 의 `model` 에 실려 화면 목록에 `gemma4:e4b 고정` 으로
표시되고, 그 에이전트가 실제로 쓴 모델이 호출 기록에도 남는다.

`ollama list` 에 나온 이름을 **그대로** 적는다.

---

## 7. 버전 정책

- `CONTRACT_VERSION` 은 `core/contract.py` 에 있다. 현재 `1.0`.
- 에이전트의 manifest 버전이 코어와 다르면 화면의 에이전트 목록에 **"계약 버전이 다릅니다"**
  경고가 뜬다. 호출은 계속 되지만 동작을 보장하지 않는다.
- 계약이 바뀌면 코어 담당자가 `scripts/sync_contract.py` 로 템플릿을 갱신하고 공지한다.
  각 개발자는 자기 에이전트 폴더의 `contract.py` / `llm.py` 를 새 것으로 덮어쓴다.

---

## 8. 제출 전 자가검사

에이전트를 띄운 상태에서:

```bash
python scripts/check_contract.py http://localhost:9001
```

manifest 필수 항목, 계약 버전, Content-Type, 종료 이벤트 개수와 위치, markdown 유무,
첨부파일 다운로드까지 확인한다. 전 항목 통과해야 제출한다.
