import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    PROJECT_NAME: str = "MOYZA API"

    DB_HOST: str = os.getenv("DB_HOST")
    DB_PORT: str = os.getenv("DB_PORT")
    DB_USER: str = os.getenv("DB_USER")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD")
    DB_NAME: str = os.getenv("DB_NAME")

    EVOLUTION_URL_SENDMEDIA: str = os.getenv("EVOLUTION_URL_SENDMEDIA")
    EVOLUTION_URL_SENDPRESENCE: str = os.getenv("EVOLUTION_URL_SENDPRESENCE")
    WHATSAPP_API_KEY: str = os.getenv("WHATSAPP_API_KEY")
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "https://moyza.duckdns.org")

    @property
    def DATABASE_URL(self):
        return (
            f"postgresql+psycopg2://"
            f"{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    def public_url(self, path: str) -> str:
        return f"{self.PUBLIC_BASE_URL.rstrip('/')}/{path.lstrip('/')}"

settings = Settings()
