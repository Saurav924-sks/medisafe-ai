import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings
from sqlalchemy.engine import make_url

# Local layout is <repo>/frontend/backend/app/core/config.py. Docker receives
# the same values through Compose environment variables, so the file is optional.
ROOT_ENV_FILE = Path(__file__).resolve().parents[4] / ".env"
load_dotenv(ROOT_ENV_FILE)


class Settings(BaseSettings):
    APP_NAME: str = "MediSafe AI"
    VERSION: str = "2.0.0-prototype"
    DESCRIPTION: str = "Production-oriented clinical decision support prototype"
    APP_ENV: str = "development"

    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "medisafe_user")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "")
    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT: str = os.getenv("POSTGRES_PORT", "5432")
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "medisafe_db")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    API_KEY: str = os.getenv("API_KEY", "")
    CORS_ORIGINS: str = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://localhost:3000",
    )
    FHIR_BASE_URL: str | None = None
    FHIR_CLIENT_ID: str | None = None
    FHIR_CLIENT_SECRET: str | None = None
    FHIR_SCOPES: str = "launch/patient openid fhirUser offline_access patient/*.read user/Practitioner.read"
    FHIR_REDIRECT_URI: str | None = None
    FHIR_CONTEXT_MAX_AGE_HOURS: int = 24
    database_url_override: str | None = Field(default=None, validation_alias="DATABASE_URL")

    @property
    def is_hosted(self) -> bool:
        app_environment = os.getenv("APP_ENV", self.APP_ENV).strip().lower()
        render_hosted = os.getenv("RENDER", "").strip().lower() == "true"
        return render_hosted or app_environment in {"staging", "production"}

    @property
    def DATABASE_URL(self) -> str:
        # Always check the environment directly because test and host settings
        # may be set after this Settings instance is created.
        explicit_url = os.getenv("DATABASE_URL") or self.database_url_override
        if self.is_hosted and not explicit_url:
            raise ValueError("DATABASE_URL must be explicitly configured in hosted environments.")

        if explicit_url:
            url = explicit_url.strip()
        else:
            user = quote_plus(self.POSTGRES_USER)
            password = quote_plus(self.POSTGRES_PASSWORD)
            url = (
                f"postgresql+psycopg2://{user}:{password}@"
                f"{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )

        if url.startswith("postgres://"):
            url = "postgresql+psycopg2://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg2://" + url[len("postgresql://"):]

        if self.is_hosted:
            try:
                parsed_url = make_url(url)
            except Exception as exc:
                raise ValueError("DATABASE_URL is invalid for the hosted environment.") from exc
            if (
                parsed_url.get_backend_name() != "postgresql"
                or parsed_url.drivername not in {"postgresql", "postgresql+psycopg2"}
            ):
                raise ValueError("Hosted environments require a PostgreSQL DATABASE_URL.")

        return url


settings = Settings()
