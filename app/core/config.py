from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    database_url: str = "postgresql+asyncpg://supportflow:supportflow@127.0.0.1:5433/supportflow"
    checkpoint_database_url: str = "postgresql://supportflow:supportflow@127.0.0.1:5433/supportflow"
    chroma_path: str = ".local/chroma"
    embedding_model: str = "all-MiniLM-L6-v2"
    reviewer_api_keys: dict[str, str] = {}
    api_key: str = ""
    auth_mode: Literal["demo", "oidc", "local"] = "demo"
    local_auth_secret: str = ""
    oidc_issuer: str = ""
    oidc_audience: str = "supportflow-api"
    oidc_jwks_url: str = ""
    oidc_allow_http: bool = False
    email_enabled: bool = False
    email_worker_in_api: bool = True
    email_delivery_mode: Literal["local", "smtp"] = "local"
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 1025
    smtp_starttls: bool = True
    smtp_username: str = ""
    smtp_password: str = ""
    email_from: str = "supportflow@localhost"
    voice_enabled: bool = False
    voice_asr_model: str = "small"
    voice_device: str = "cpu"
    voice_compute_type: str = "int8"
    voice_offline: bool = True
    voice_tts_backend: Literal["piper", "indic_parler"] = "piper"
    voice_piper_models: dict[str, str] = {}
    voice_indic_model: str = "ai4bharat/indic-parler-tts"
    voice_max_connections: int = 2
    voice_allowed_origins: list[str] = ["http://localhost:8000", "http://127.0.0.1:8000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
