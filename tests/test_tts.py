import base64
from unittest.mock import MagicMock, patch

from bot import tts


def test_synthesize_japanese_calls_client() -> None:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.audio_content = b"fake-mp3-data"
    mock_client.synthesize_speech.return_value = mock_response

    with patch.object(tts, "_tts_client", mock_client):
        result = tts.synthesize_japanese("テスト音声")

    assert result == b"fake-mp3-data"
    mock_client.synthesize_speech.assert_called_once()


def test_synthesize_to_base64_returns_encoded() -> None:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.audio_content = b"fake-mp3-data"
    mock_client.synthesize_speech.return_value = mock_response

    with patch.object(tts, "_tts_client", mock_client):
        result = tts.synthesize_to_base64("テスト")

    decoded = base64.b64decode(result)
    assert decoded == b"fake-mp3-data"


def test_is_available_false_when_not_initialized() -> None:
    with patch.object(tts, "_tts_client", None):
        assert tts.is_available() is False
