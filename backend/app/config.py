from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://chopper:chopper@localhost:25432/postgres"
    db_schema: str = "agent_meeting_dev"
    redis_url: str = "redis://localhost:6379/0"
    debug: bool = True
    cors_origins: list[str] = ["http://localhost:3000"]

    # LLM / OpenRouter
    llm_model: str = "openrouter/google/gemini-2.5-flash"
    openrouter_api_key: str = ""

    # Auth
    secret_key: str = "change-me-in-production-use-a-256-bit-random-key"
    access_token_expire_minutes: int = 1440  # 24 hours

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
