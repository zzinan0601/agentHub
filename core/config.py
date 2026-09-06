"""코어 설정 - 모든 설정값은 .env 에서 온다. 코드에 값을 박지 않는다. (요구사항 9)"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- 코어 서버 ---
    core_host: str = "0.0.0.0"
    core_port: int = 8000
    log_level: str = "INFO"

    # --- 저장소 (대화/스케줄) ---
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/agenthub"

    # --- Ollama (각자 노트북 주소로 바꿀 수 있다) ---
    ollama_base_url: str = "http://localhost:11434"
    default_model: str = "gemma4:31b-cloud"

    # --- 에이전트 레지스트리 ---
    registry_path: str = "./registry.yaml"
    health_poll_s: int = 30  # 온/오프라인 확인 주기
    agent_timeout_s: int = 300  # 에이전트 한 개의 최대 응답 시간

    # --- 라우팅 ---
    # Ollama 에게 "JSON 만 내라" 고 강제한다. 작은 로컬 모델은 이걸 켜지 않으면
    # 설명 문장이나 코드펜스를 섞어 내보내 파싱이 실패한다.
    # 아주 오래된 Ollama 라 format 을 모르면 false 로 끈다.
    router_json_format: bool = True
    router_retries: int = 2  # JSON 파싱 실패 시 다시 물어보는 횟수
    # 라우터가 무엇을 받았는지 남길 파일. 비우면 기록하지 않는다.
    # 폐쇄망에서 파싱이 계속 실패할 때 응답 원문을 봐야 원인을 알 수 있다.
    router_log_path: str = "./logs/router.log"

    # 병렬로 2개 이상 성공했을 때 결과를 어떻게 낼지
    #   off : 에이전트 이름을 제목으로 순서대로 붙인다 (LLM 호출 없음, 빠르다)
    #   llm : 코디네이터 LLM 이 하나의 답변으로 정리한다 (읽기 좋지만 수십 초 더 걸린다)
    reduce_mode: str = "off"

    # --- 대화 ---
    context_turns: int = 6  # 에이전트에게 넘길 최근 대화 턴 수
    timezone: str = "Asia/Seoul"  # 스케줄 기준 시간대

    # --- 로그인 (비밀번호 없음, 사내망 전용) ---
    session_ttl_days: int = 30  # 로그인 유지 기간
    # 개발 중 Vue 개발 서버(5173)에서 쿠키를 주고받으려면 출처를 명시해야 한다.
    # 쿠키를 쓰면 "*" 를 브라우저가 거부하기 때문이다.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- 활용 현황 ---
    insight_fail_rate_warn: float = 0.2  # 이 실패율을 넘으면 '점검 대상' 에 올린다
    # 자주 묻는 질문을 묶는 기준. 0.8 이면 여덟 글자 중 여섯 자 이상 닮으면 같은 질문으로 본다.
    insight_similarity: float = 0.8
    # 묶기에 쓸 최근 질문 수. 비교가 제곱으로 늘어나므로 상한을 둔다.
    insight_sample: int = 2000

    # --- 프롬프트/스킬/워크플로우 (소프트 하네스) ---
    prompts_dir: str = "./core/prompts"
    skills_dir: str = "./core/skills"
    workflows_dir: str = "./core/workflows"
    # 화면에서 워크플로우를 등록/수정/삭제할 수 있는지. 폐쇄망 반입본을 읽기 전용으로
    # 잠그고 싶을 때만 false 로 둔다.
    workflow_edit_enabled: bool = True

    # --- UI 정적 파일 (npm run build 결과) ---
    ui_dist_dir: str = "./ui/dist"


settings = Settings()
