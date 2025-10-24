import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv


load_dotenv()


class Settings(BaseSettings):
    """
    Global Backend App settings
    """

    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")
    OPENAI_API_MODEL: str = os.getenv("OPENAI_API_MODEL", "gpt-5")
    IS_DEV: bool = True if os.getenv("STACK", "DEV") == "DEV" else False
    fake_db_host: str = os.getenv("POSTGRES_HOST", "localhost")
    fake_db_port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    fake_db_user: str = os.getenv("POSTGRES_USER", "asquare")
    fake_db_password: str = os.getenv("POSTGRES_PASSWORD", "bro_secret")
    fake_db_database: str = os.getenv("POSTGRES_DB", "chat_with_data_db")
    USER_DATABASE_URL: str = os.getenv(
        "USER_DATABASE_URL",
        "postgresql+asyncpg://asquare:bro_secret@localhost:5431/chat_with_data_db",
    )

    class Config:
        """Load secret file"""

        env_file = ".env"
        env_file_encoding = "utf-8"


# Create a global settings instance
settings = Settings()
