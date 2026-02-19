from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="AI Meeting Proxy PoC", alias="APP_NAME")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    env: str = Field(default="dev", alias="APP_ENV")
    enable_docs: bool = Field(default=True, alias="ENABLE_DOCS")

    gcp_project_id: str = Field(default="local-dev-project", alias="GCP_PROJECT_ID")
    gcp_location: str = Field(default="us-central1", alias="GCP_LOCATION")

    stt_language_code: str = Field(default="en-US", alias="STT_LANGUAGE_CODE")
    stt_model: str = Field(default="latest_long", alias="STT_MODEL")

    gemini_model: str = Field(default="gemini-1.5-pro", alias="GEMINI_MODEL")
    api_key: str | None = Field(default=None, alias="API_KEY")
    max_audio_size_bytes: int = Field(default=10 * 1024 * 1024, alias="MAX_AUDIO_SIZE_BYTES")
    max_input_chars: int = Field(default=20_000, alias="MAX_INPUT_CHARS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
