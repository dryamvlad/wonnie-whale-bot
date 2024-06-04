import sys
from pydantic_settings import BaseSettings
from dotenv import find_dotenv, load_dotenv

# Check if we're in debug mode
env_file = ".env.debug" if "dev_environment" in sys.argv else ".env"

load_dotenv(find_dotenv(env_file))


class Settings(BaseSettings):
    DB_HOST: str
    DB_PORT: int
    DB_USER: str
    DB_PASS: str
    DB_NAME: str

    WON_ADDR: str
    WON_LP_ADDR: str
    CHAT_ID: int
    CHANNEL_ID: int
    ADMIN_CHAT_ID: int
    THRESHOLD_BALANCE: int
    OG_THRESHOLD_BALANCE: int

    BOT_TOKEN: str
    REDIS_DSN: str
    TON_API_KEY: str

    REFRESH_TIMEOUT: int

    MANIFEST_URL: str

    class Config:
        env_file = env_file
        env_prefix = "DEBUG_" if "dev_environment" in sys.argv else ""

    @property
    def DATABASE_URL_asyncpg(self):
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASS}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def DATABASE_URL_psycopg(self):
        return f"postgresql+psycopg://{self.DB_USER}:{self.DB_PASS}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"


settings = Settings()
