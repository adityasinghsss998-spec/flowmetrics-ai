from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PORT: int = 3006
    ENVIRONMENT: str = "development"

    # Database
    DATABASE_URL: str | None = None
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASS: str = ""
    DB_NAME: str = "defaultdb"
    DB_SSL: bool = False

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # RabbitMQ
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"

    # Analytics Service
    ANALYTICS_SERVICE_URL: str = "http://localhost:3003"

    # Security
    JWT_ACCESS_SECRET: str = ""
    ALERT_EMAIL: str = ""
    
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.8-flash"
    GEMINI_FALLBACK_MODEL: str = ""
    
    PINECONE_API_KEY: str = ""
    PINECONE_INDEX_NAME: str = "flowmetrics-prs"
    INTERNAL_API_KEY: str = ""
    ALLOWED_ORIGINS: str = ""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def async_database_url(self) -> str:
        if self.DATABASE_URL:
            url = self.DATABASE_URL
            if url.startswith("mysql://"):
                url = url.replace("mysql://", "mysql+aiomysql://", 1)
            return url
        return (
            f"mysql+aiomysql://{self.DB_USER}:{self.DB_PASS}@"
            f"{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
