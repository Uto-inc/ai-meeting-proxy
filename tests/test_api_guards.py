from fastapi.testclient import TestClient

from config import settings
from main import app


def _set_default_test_settings() -> None:
    settings.api_key = None
    settings.max_audio_size_bytes = 1024 * 1024
    settings.max_input_chars = 200


def test_api_key_required_when_enabled() -> None:
    _set_default_test_settings()
    settings.api_key = "test-secret"
    client = TestClient(app)

    response = client.post("/chat", data={"message": "hello"})
    assert response.status_code == 401


def test_audio_size_limit() -> None:
    _set_default_test_settings()
    settings.max_audio_size_bytes = 16
    client = TestClient(app)

    response = client.post(
        "/transcribe",
        files={"audio_file": ("sample.wav", b"RIFF1234WAVE" + b"x" * 64, "audio/wav")},
    )
    assert response.status_code == 413


def test_audio_signature_validation() -> None:
    _set_default_test_settings()
    client = TestClient(app)

    response = client.post(
        "/transcribe",
        files={"audio_file": ("sample.wav", b"not-a-real-wave", "audio/wav")},
    )
    assert response.status_code == 400
    assert "signature" in response.json()["detail"]


def test_chat_input_size_limit() -> None:
    _set_default_test_settings()
    settings.max_input_chars = 10
    client = TestClient(app)

    response = client.post("/chat", data={"message": "0123456789012345"})
    assert response.status_code == 413
