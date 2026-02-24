from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="AI Meeting Proxy PoC", alias="APP_NAME")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    env: str = Field(default="dev", alias="APP_ENV")
    enable_docs: bool = Field(default=True, alias="ENABLE_DOCS")

    gcp_project_id: str = Field(default="local-dev-project", alias="GCP_PROJECT_ID")
    gcp_location: str = Field(default="us-central1", alias="GCP_LOCATION")

    stt_language_code: str = Field(default="ja-JP", alias="STT_LANGUAGE_CODE")
    stt_model: str = Field(default="latest_long", alias="STT_MODEL")

    gemini_model: str = Field(default="gemini-1.5-pro", alias="GEMINI_MODEL")
    api_key: str | None = Field(default=None, alias="API_KEY")
    max_audio_size_bytes: int = Field(default=10 * 1024 * 1024, alias="MAX_AUDIO_SIZE_BYTES")
    max_input_chars: int = Field(default=20_000, alias="MAX_INPUT_CHARS")

    recall_api_key: str | None = Field(default=None, alias="RECALL_API_KEY")
    recall_base_url: str = Field(default="https://us-west-2.recall.ai/api/v1", alias="RECALL_BASE_URL")
    webhook_base_url: str | None = Field(default=None, alias="WEBHOOK_BASE_URL")

    # Avatar bot settings
    persona_profile_path: str = Field(default="knowledge/profile.md", alias="PERSONA_PROFILE_PATH")
    knowledge_dir: str = Field(default="knowledge/docs", alias="KNOWLEDGE_DIR")
    tts_voice_name: str = Field(default="ja-JP-Neural2-B", alias="TTS_VOICE_NAME")
    tts_speaking_rate: float = Field(default=1.0, alias="TTS_SPEAKING_RATE")
    bot_display_name: str = Field(default="AI Avatar", alias="BOT_DISPLAY_NAME")
    bot_image_filename: str = Field(default="bot_avatar.jpg", alias="BOT_IMAGE_FILENAME")
    response_triggers: str = Field(default="", alias="RESPONSE_TRIGGERS")
    silence_timeout_seconds: int = Field(default=3, alias="SILENCE_TIMEOUT_SECONDS")
    max_conversation_history: int = Field(default=20, alias="MAX_CONVERSATION_HISTORY")

    # Google OAuth2 settings
    google_client_id: str = Field(default="", alias="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(default="", alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = Field(default="http://localhost:8000/auth/google/callback", alias="GOOGLE_REDIRECT_URI")

    # Database
    db_path: str = Field(default="data/meetings.db", alias="DB_PATH")

    # Materials
    materials_upload_dir: str = Field(default="data/materials", alias="MATERIALS_UPLOAD_DIR")

    # Gemini Live API
    gemini_live_enabled: bool = Field(default=False, alias="GEMINI_LIVE_ENABLED")
    gemini_live_model: str = Field(default="gemini-live-2.5-flash-native-audio", alias="GEMINI_LIVE_MODEL")
    gemini_live_session_timeout_seconds: int = Field(default=840, alias="GEMINI_LIVE_SESSION_TIMEOUT")
    gemini_live_output_sample_rate: int = Field(default=24000, alias="GEMINI_LIVE_OUTPUT_SAMPLE_RATE")
    gemini_live_voice_name: str = Field(default="Kore", alias="GEMINI_LIVE_VOICE_NAME")
    gemini_live_language_code: str = Field(default="ja-JP", alias="GEMINI_LIVE_LANGUAGE_CODE")
    gemini_live_temperature: float = Field(default=0.7, alias="GEMINI_LIVE_TEMPERATURE")
    gemini_live_enable_affective_dialog: bool = Field(default=True, alias="GEMINI_LIVE_ENABLE_AFFECTIVE_DIALOG")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
