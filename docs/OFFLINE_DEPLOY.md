# 폐쇄망 반입 절차

인터넷이 되는 곳에서 **미리 다 받아 두고**, 반입 후에는 설치만 한다.
반입 후 `pip install` 이나 `npm install` 이 네트워크를 타면 그 자리에서 막힌다.

---

## 1. 반입 전 (인터넷 되는 PC)

### 1-1. 파이썬 패키지 내려받기

**`requirements.txt` 가 아니라 `requirements.lock.txt` 를 기준으로 받는다.**
`requirements.txt` 는 직접 의존성만 고정하므로, 반입 시점에 전이 의존성이 다르게 풀려
여기서 검증한 것과 다른 조합이 설치될 수 있다.

```bash
pip download -d vendor/py --only-binary=:all: -r requirements.lock.txt
```

```bash
pip download -d vendor/py --only-binary=:all: -r agent_template/requirements.lock.txt
```

```bash
pip download -d vendor/py --only-binary=:all: pip
```

- `--only-binary=:all:` 을 반드시 붙인다. 소스 배포판(sdist)이 섞이면 컴파일러가 없는
  폐쇄망에서 빌드하다 실패한다.
- 각 개발자가 업무 DB 드라이버(`oracledb`, `psycopg` 등)를 추가했다면 같은 방식으로
  받아 이 폴더에 합친다.

같은 패키지가 두 벌 받아지지 않았는지 확인한다. 하나라도 나오면 잠금본이 어긋난 것이다.

```bash
ls vendor/py/*.whl | cut -d- -f1 | sort | uniq -d
```

### 1-1-1. 받은 것이 실제로 설치되는지 확인

**받아만 두고 넘기면 안 된다.** 반입한 뒤에 알면 되돌릴 수 없다.
인터넷을 끊은 것과 같은 조건(`--no-index`)으로 빈 가상환경에 설치해 본다.

```bash
python -m venv /tmp/offcheck && /tmp/offcheck/Scripts/pip install --no-index --find-links vendor/py -r requirements.lock.txt
```

```bash
python -m venv /tmp/offcheck2 && /tmp/offcheck2/Scripts/pip install --no-index --find-links vendor/py -r agent_template/requirements.lock.txt
```

둘 다 오류 없이 끝나야 한다.

### 1-2. UI 빌드

```bash
cd ui
npm ci
npm run build
```

`ui/dist/` 가 만들어진다. **`node_modules` 는 반입하지 않는다.** 폐쇄망에서는
빌드하지 않고 `dist` 를 그대로 쓴다.

### 1-3. 외부 참조 0건 확인

빌드 결과가 CDN 에서 무언가를 **받아오려 하면** 폐쇄망에서 화면이 깨진다.
단순히 `http` 문자열을 세면 안 된다. 번들에는 XML 네임스페이스(`http://www.w3.org/2000/svg`)나
라이브러리 오류 안내 링크가 문자열로 남아 있는데, 이것들은 네트워크 요청이 아니다.

실제로 요청을 만드는 것만 확인한다. 아래 명령들이 모두 결과 없음이어야 한다.

```bash
grep -nE '<script[^>]+src="https?://|<link[^>]+href="https?://' ui/dist/index.html
```

```bash
grep -roE '@font-face|fonts\.googleapis|cdn\.|unpkg|jsdelivr' ui/dist/
```

파이썬 쪽은 localhost 와 사내 주소 외의 접속처가 없어야 한다.

```bash
grep -rnoE 'https?://[a-zA-Z0-9._/-]+' core/ agent_template/ --include=*.py | grep -v localhost
```

가장 확실한 확인은 **네트워크를 끊고 화면을 열어 보는 것**이다.
브라우저 개발자도구 Network 탭에 실패한 요청이 하나도 없어야 한다.

### 1-4. Ollama 모델

폐쇄망 Ollama 에 `gemma4-12b` 가 올라가 있어야 한다. 모델 반입은 인프라 담당이 처리한다.
반입 후 반드시 실제 태그를 확인한다.

```bash
ollama list
```

여기 출력된 이름을 **그대로** `.env` 의 `DEFAULT_MODEL` 에 넣는다.

### 1-5. 반입 대상

| 넣는다 | 뺀다 |
| --- | --- |
| `core/` `agent_template/` `scripts/` `docs/` `sql/` | `.venv/` `agents/*/.venv/` |
| `ui/dist/` `registry.yaml` | `ui/node_modules/` |
| `requirements*.txt` `.env.example` | `.env` (환경마다 다름) |
| **`vendor/`** (미리 받아 둔 휠) | `agents/*/files/` (첨부 캐시) |
| `sql/` | `logs/` (반입지에서 새로 쌓인다) |
| | `__pycache__/` |

---

## 2. 반입 후 - 코어 서버 1대

```bash
python -m venv .venv
.venv\Scripts\activate
pip install --no-index --find-links vendor/py -r requirements.lock.txt
```

`--no-index` 를 반드시 붙인다. 빠뜨리면 외부 인덱스를 찾다가 멈춘다.

### 2-1. PostgreSQL 준비

```bash
psql -U postgres -c "CREATE DATABASE agenthub;"
```

테이블을 만드는 길은 두 가지다. **결과는 같으므로 편한 쪽 하나만 고른다.**

**(가) 코어가 만들게 둔다** — 아무것도 안 해도 된다. 코어가 처음 뜰 때 만들고,
이미 쓰던 DB 를 옮겨온 경우에는 `core/migrate.py` 가 나중에 추가된 컬럼을 덧붙인다.
여러 번 떠도 안전하다. 단, 앱이 쓰는 DB 계정에 `CREATE TABLE` 권한이 있어야 한다.

**(나) SQL 로 미리 만든다** — DBA 가 DDL 을 검토해야 하거나, 앱 계정에 DDL 권한을
주지 않는 곳에서 쓴다.

```bash
psql -U postgres -d agenthub -f sql/01_schema.sql
```

```bash
psql -U postgres -d agenthub -f sql/02_seed.sql
```

```bash
psql -U postgres -d agenthub -f sql/03_check.sql
```

`02_seed.sql` 은 **관리자 계정을 미리 만든다.** 앱은 가장 먼저 로그인한 사람을
자동으로 관리자로 만들기 때문에, 그냥 열어두면 아무나 먼저 들어온 사람이 관리자가 된다.
파일 안의 이름을 실제 관리자로 바꿔 놓고 **서비스를 열기 전에** 돌린다.

기준정보 테이블은 없다. 에이전트 목록은 `registry.yaml`, 워크플로우와 프롬프트는
파일이고 DB 에는 사람이 만든 것만 쌓인다. 자세한 것은 [../sql/README.md](../sql/README.md).

### 2-2. .env 작성

```bash
copy .env.example .env
```

폐쇄망에서 바꿔야 하는 항목:

```
DATABASE_URL=postgresql+asyncpg://<계정>:<암호>@<DB주소>:5432/agenthub
OLLAMA_BASE_URL=http://<Ollama주소>:11434
DEFAULT_MODEL=gemma4-12b          # ollama list 출력값 그대로
UI_DIST_DIR=./ui/dist
```

### 2-3. 기동

```bash
python -m core.main
```

`ui/dist` 가 있으면 코어가 화면까지 직접 서빙한다. 브라우저에서 `http://<코어주소>:8000` 으로 접속한다.

```bash
curl http://localhost:8000/api/health
```

`{"status":"ok", ...}` 가 나오면 정상이다.

### 2-4. 첫 사용자

화면에서 이름을 넣으면 그 자리에서 계정이 만들어진다. **맨 처음 들어온 사람이
관리자**가 되고, 로그인 도입 전에 쌓여 있던 주인 없는 대화를 넘겨받는다.
그러니 운영 담당자가 먼저 들어가는 편이 낫다.

> 비밀번호를 받지 않는다. **사내망 밖에서 접근되지 않도록** 방화벽을 확인한다.

---

## 3. 반입 후 - 개발자 노트북 10대

각자 자기 에이전트 폴더에서:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install --no-index --find-links ..\..\vendor\py -r ..\..\agent_template\requirements.lock.txt
copy .env.example .env
```

`.env` 에서 확인할 것:

```
AGENT_PORT=9010                   # 전원 같은 값. 노트북이 다르므로 나눌 필요가 없다
AGENT_HOST=0.0.0.0                # 코어가 접속해야 하므로 0.0.0.0 이어야 한다
OLLAMA_BASE_URL=http://<Ollama주소>:11434
```

띄운다.

```bash
run.bat
```

방화벽에서 해당 포트의 인바운드를 허용해야 코어가 접속할 수 있다.

```powershell
New-NetFirewallRule -DisplayName "AgentHub 9001" -Direction Inbound -LocalPort 9001 -Protocol TCP -Action Allow
```

---

## 4. registry.yaml

코어 서버의 `registry.yaml` 에 10명의 에이전트를 등록한다. **노트북 IP** 를 쓴다.

```yaml
agents:
  - id: sales-report
    url: http://192.168.0.31:9001
  - id: batch-status
    url: http://192.168.0.42:9002
```

코어가 30초마다 다시 읽으므로 재기동이 필요 없다. 화면 오른쪽에서 초록 점을 확인한다.

---

## 5. 반입 후 점검

```bash
python scripts/check_contract.py
```

registry 의 모든 에이전트를 한 번에 검사한다.

```bash
python scripts/e2e_test.py
```

방 생성부터 단일·병렬·순차 호출, 첨부파일, 스케줄까지 전체 흐름을 확인한다.
(예제 에이전트 `echo`, `summary` 가 떠 있어야 한다)

---

## 6. 자주 막히는 곳

| 증상 | 확인할 것 |
| --- | --- |
| `pip install` 이 멈춤 | `--no-index` 를 빠뜨렸다 |
| 화면은 뜨는데 스타일이 없음 | `ui/dist` 가 아니라 소스를 올렸다. 빌드 결과를 넣는다 |
| 모델을 못 찾음 | `.env` 의 `DEFAULT_MODEL` 이 `ollama list` 출력과 다르다 |
| 에이전트가 전부 회색 | 노트북 방화벽. 코어에서 `curl <노트북IP>:<포트>/health` 로 확인 |
| 에이전트가 `127.0.0.1` 로만 열림 | `AGENT_HOST` 가 `0.0.0.0` 이 아니다 |
| 응답이 뚝뚝 끊겨 한 번에 옴 | 중간에 버퍼링하는 프록시가 있다. NDJSON 스트림은 버퍼링하면 안 된다 |
