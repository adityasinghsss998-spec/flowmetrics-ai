from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PORT: int = 3006
    ENVIRONMENT: str = "development"

    # Database (flowmetrics_github)
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASS: str = ""
    DB_NAME: str = "flowmetrics_github"
    DB_SSL: bool = False

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # RabbitMQ
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"

    # Analytics Service
    ANALYTICS_SERVICE_URL: str = "http://localhost:3003"

    # Security
    JWT_ACCESS_SECRET: str = ""

    GEMINI_API_KEY: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def async_database_url(self) -> str:
        return (
            f"mysql+aiomysql://{self.DB_USER}:{self.DB_PASS}@"
            f"{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
