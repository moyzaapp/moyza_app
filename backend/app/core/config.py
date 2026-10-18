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

    AI_ENABLED: bool = os.getenv("AI_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "openai")

    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")
    OPENAI_MAX_TOKENS: int = int(os.getenv("OPENAI_MAX_TOKENS", "2000"))
    OPENAI_TEMPERATURE: float = float(os.getenv("OPENAI_TEMPERATURE", "0.3"))

    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

    # Gmail OAuth — recordatorio de compradores
    GMAIL_CREDENTIALS_PATH: str = os.getenv(
        "GMAIL_CREDENTIALS_PATH",
        "app/credentials/gmail_credentials.json"
    )
    GMAIL_TOKEN_PATH: str = os.getenv(
        "GMAIL_TOKEN_PATH",
        "app/credentials/gmail_token.json"
    )

    # Avisos de compradores en horas hábiles (PLAN_ALERTAS_DIAS_HABILES.md).
    # Las horas se cuentan solo en días hábiles de Jaén (24 h por día hábil,
    # app/core/business_calendar.py): 48 = dos días hábiles completos.
    # R1 "sin gestión": horas hábiles desde la última gestión real o la asignación
    BUYER_REMINDER_HOURS: int = int(os.getenv("BUYER_REMINDER_HOURS", "48"))
    # R2 "sin avance": horas hábiles sin pasar de Primera llamada
    BUYER_STAGE_STALL_HOURS: int = int(os.getenv("BUYER_STAGE_STALL_HOURS", "48"))
    # Aviso in-app: al cruzar el umbral y de nuevo cada N días hábiles mientras siga igual
    BUYER_REMINDER_REPEAT_BUSINESS_DAYS: int = int(os.getenv("BUYER_REMINDER_REPEAT_BUSINESS_DAYS", "2"))

    # Hora del día (Europe/Madrid) del email diario y los avisos in-app; solo
    # en días hábiles. Antes era 6 en UTC: revisar el .env al desplegar.
    BUYER_REMINDER_HOUR: int = int(os.getenv("BUYER_REMINDER_HOUR", "8"))

    # Habilitar/deshabilitar el recordatorio sin necesidad de eliminar el job
    BUYER_REMINDER_ENABLED: bool = os.getenv("BUYER_REMINDER_ENABLED", "true").lower() in {"1", "true", "yes", "on"}

    # Correo de bienvenida con credenciales al crear un usuario
    WELCOME_EMAIL_ENABLED: bool = os.getenv("WELCOME_EMAIL_ENABLED", "true").lower() in {"1", "true", "yes", "on"}

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
