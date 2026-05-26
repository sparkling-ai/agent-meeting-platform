from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://chopper:chopper@localhost:25432/postgres"
    db_schema: str = "agent_meeting"
    redis_url: str = "redis://localhost:6379/0"
    debug: bool = True
    cors_origins: list[str] = ["http://localhost:3000"]

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
