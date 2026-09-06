-- 에이전트 허브 - 테이블 생성 (PostgreSQL)
--
-- 코어는 기동할 때 테이블을 스스로 만든다. 이 파일은 그것과 **같은 결과**를 내는
-- 스크립트다. 폐쇄망처럼 DBA 가 미리 검토하고 직접 만들어야 하는 곳에서 쓴다.
-- 모델(core/models.py)에서 뽑아낸 것이라 손으로 옮겨 적어 어긋날 일이 없다.
--
-- 실행
--   psql -U postgres -c "CREATE DATABASE agenthub;"
--   psql -U postgres -d agenthub -f sql/01_schema.sql
--
-- 여러 번 실행해도 안전하다 (IF NOT EXISTS). 이미 쓰던 DB 에 그대로 돌려도 된다.
--
-- 주의: 아래 컬럼들은 DB 기본값이 없다. 애플리케이션이 항상 값을 채워 넣기 때문이다.
-- 직접 INSERT 할 때는 값을 명시해야 한다.
--   users.is_admin / users.is_active / rooms.title / rooms.mode
--   messages.meta / agent_runs.elapsed_ms / schedules.enabled

-- ---------------------------------------------------------------------------
-- 사용자 (비밀번호 컬럼이 없다. 이름만으로 들어오는 신원 표시다)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id           SERIAL                   NOT NULL,
    username     VARCHAR(50)              NOT NULL,  -- 소문자로 정규화해 저장한다
    display_name VARCHAR(100)             NOT NULL,
    is_admin     BOOLEAN                  NOT NULL,  -- 첫 계정만 true
    is_active    BOOLEAN                  NOT NULL,
    created_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username);

-- ---------------------------------------------------------------------------
-- 채팅방 (요구사항 13). user_id 로 주인을 구분해 자기 방만 목록에 보인다.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rooms (
    id         SERIAL                   NOT NULL,
    -- SET NULL 이다. 사용자를 지웠다고 대화까지 사라지면 안 된다.
    user_id    INTEGER                  NULL,
    title      VARCHAR(200)             NOT NULL,
    model      VARCHAR(100)             NOT NULL,  -- 방마다 모델 선택 (요구사항 18)
    mode       VARCHAR(20)              NOT NULL,  -- parallel | sequential
    workflow   VARCHAR(100)             NULL,      -- 고정 파이프라인 key
    unread     INTEGER                  NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_rooms_user_id ON rooms (user_id);

-- ---------------------------------------------------------------------------
-- 로그인 세션. DB 에 두므로 코어를 재기동해도 로그인이 유지된다.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sessions (
    token        VARCHAR(64)              NOT NULL,
    user_id      INTEGER                  NOT NULL,
    created_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    PRIMARY KEY (token),
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_sessions_user_id ON sessions (user_id);

-- ---------------------------------------------------------------------------
-- 방에서 사용자가 직접 고른 에이전트. 비어 있으면 라우터 LLM 이 고른다.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS room_agents (
    room_id  INTEGER      NOT NULL,
    agent_id VARCHAR(100) NOT NULL,
    -- 화면에서 고른 순서. 순차 실행에서는 이것이 곧 실행 순서다.
    position INTEGER      NOT NULL DEFAULT 0,
    PRIMARY KEY (room_id, agent_id),
    FOREIGN KEY (room_id) REFERENCES rooms (id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- 대화 한 줄. 응답은 Markdown 원문 그대로 저장한다. (요구사항 19)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS messages (
    id         SERIAL                   NOT NULL,
    room_id    INTEGER                  NOT NULL,
    user_id    INTEGER                  NULL,  -- 질문한 사람. FK 를 걸지 않는다
    role       VARCHAR(20)              NOT NULL,  -- user | assistant | schedule | system
    content_md TEXT                     NOT NULL,
    -- 첨부파일 목록, 호출된 에이전트, plan, num_ctx 등 부가 정보
    meta       JSONB                    NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY (room_id) REFERENCES rooms (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_messages_room_id ON messages (room_id);
CREATE INDEX IF NOT EXISTS ix_messages_user_id ON messages (user_id);

-- ---------------------------------------------------------------------------
-- 방별 스케줄. room_id 가 기본키라 '방당 1개'를 DB 가 보장한다. (요구사항 16)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schedules (
    room_id     INTEGER                  NOT NULL,
    cron        VARCHAR(100)             NOT NULL,  -- 예: '0 9 * * 1-5' (분 시 일 월 요일)
    prompt      TEXT                     NOT NULL,
    enabled     BOOLEAN                  NOT NULL,
    last_run_at TIMESTAMP WITH TIME ZONE NULL,
    PRIMARY KEY (room_id),
    FOREIGN KEY (room_id) REFERENCES rooms (id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- 에이전트 호출 1건의 기록. 누가 느린지 / 실패하는지 추적한다.
-- room_id 에 외래키를 걸지 않는다. 방을 지워도 운영 지표는 남아야 하기 때문이다.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_runs (
    id         SERIAL                   NOT NULL,
    room_id    INTEGER                  NOT NULL,
    user_id    INTEGER                  NULL,
    agent_id   VARCHAR(100)             NOT NULL,
    status     VARCHAR(20)              NOT NULL,  -- ok | error
    elapsed_ms INTEGER                  NOT NULL,
    -- 에이전트가 실제로 쓴 num_ctx. .env 의 CHARS_PER_TOKEN 추정치를 보정하는 근거다.
    num_ctx    INTEGER                  NULL,
    error      TEXT                     NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_agent_runs_room_id  ON agent_runs (room_id);
CREATE INDEX IF NOT EXISTS ix_agent_runs_user_id  ON agent_runs (user_id);
CREATE INDEX IF NOT EXISTS ix_agent_runs_agent_id ON agent_runs (agent_id);
