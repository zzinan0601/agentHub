-- 에이전트 허브 - 설치 확인
--
--   psql -U postgres -d agenthub -f sql/03_check.sql
--
-- 반입 직후, 코어를 띄우기 전에 한 번 돌려 본다.
-- 코어를 띄운 뒤에 돌리면 "코어가 만든 것"과 "내가 만든 것"이 섞여 판단이 어려워진다.

\echo '== 1. 테이블 7개가 있는가 =='
SELECT tablename
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename IN ('users', 'rooms', 'sessions', 'room_agents',
                    'messages', 'schedules', 'agent_runs')
ORDER BY tablename;
-- 7행이 나와야 한다.

\echo '== 2. 외래키가 제대로 걸렸는가 (특히 rooms 는 SET NULL 이어야 한다) =='
SELECT c.conname,
       c.confdeltype AS on_delete   -- a=NO ACTION, c=CASCADE, n=SET NULL
FROM pg_constraint c
WHERE c.contype = 'f'
  AND c.conrelid::regclass::text IN ('rooms', 'sessions', 'room_agents',
                                     'messages', 'schedules')
ORDER BY c.conname;
-- rooms_user_id_fkey 가 n(SET NULL) 이어야 한다. 사용자를 지워도 대화가 남는 근거다.
-- 나머지는 c(CASCADE).

\echo '== 3. agent_runs 에 외래키가 없어야 한다 (방을 지워도 지표는 남긴다) =='
SELECT count(*) AS fk_count
FROM pg_constraint
WHERE contype = 'f' AND conrelid = 'agent_runs'::regclass;
-- 0 이어야 한다.

\echo '== 4. 인덱스 =='
SELECT tablename, indexname
FROM pg_indexes
WHERE schemaname = 'public' AND indexname LIKE 'ix_%'
ORDER BY tablename, indexname;
-- 8개 (users 1, rooms 1, sessions 1, messages 2, agent_runs 3)

\echo '== 5. meta 컬럼이 JSONB 인가 (JSON 이면 Dashboard 집계가 느려진다) =='
SELECT data_type
FROM information_schema.columns
WHERE table_name = 'messages' AND column_name = 'meta';
-- jsonb 여야 한다.

\echo '== 6. 관리자 계정 =='
SELECT id, username, display_name, is_admin FROM users WHERE is_admin ORDER BY id;
-- 02_seed.sql 을 돌렸다면 1행. 안 돌렸으면 0행이고,
-- 이 경우 가장 먼저 로그인하는 사람이 관리자가 된다.
