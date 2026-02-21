import os
import tempfile

from fastapi.testclient import TestClient

from config import settings
from main import app


def _set_admin_test_settings(tmp_dir: str) -> None:
    settings.api_key = None
    settings.persona_profile_path = os.path.join(tmp_dir, "profile.md")
    settings.knowledge_dir = os.path.join(tmp_dir, "docs")
    os.makedirs(os.path.join(tmp_dir, "docs"), exist_ok=True)


# --- Status ---


def test_admin_status_returns_info() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _set_admin_test_settings(tmp)
        client = TestClient(app)
        resp = client.get("/admin/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "tts_available" in data
        assert "knowledge_docs" in data
        assert "active_sessions" in data


# --- Auth ---


def test_admin_auth_required_when_enabled() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _set_admin_test_settings(tmp)
        settings.api_key = "test-secret-key"
        client = TestClient(app)
        resp = client.get("/admin/status")
        assert resp.status_code == 401


def test_admin_auth_passes_with_key() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _set_admin_test_settings(tmp)
        settings.api_key = "test-secret-key"
        client = TestClient(app)
        resp = client.get("/admin/status", headers={"X-API-Key": "test-secret-key"})
        assert resp.status_code == 200


# --- Profile ---


def test_get_profile_empty() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _set_admin_test_settings(tmp)
        client = TestClient(app)
        resp = client.get("/admin/profile")
        assert resp.status_code == 200
        assert resp.json()["content"] == ""


def test_put_and_get_profile() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _set_admin_test_settings(tmp)
        client = TestClient(app)

        resp = client.put("/admin/profile", json={"content": "# Test Profile\n- Name: TestBot"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "saved"

        resp = client.get("/admin/profile")
        assert resp.status_code == 200
        assert "TestBot" in resp.json()["content"]


def test_put_profile_missing_content() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _set_admin_test_settings(tmp)
        client = TestClient(app)
        resp = client.put("/admin/profile", json={})
        assert resp.status_code == 400


# --- Settings ---


def test_get_settings() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _set_admin_test_settings(tmp)
        client = TestClient(app)
        resp = client.get("/admin/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "tts_voice_name" in data
        assert "tts_speaking_rate" in data


def test_put_settings() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _set_admin_test_settings(tmp)
        client = TestClient(app)
        resp = client.put(
            "/admin/settings",
            json={
                "bot_display_name": "NewName",
                "tts_speaking_rate": 1.2,
            },
        )
        assert resp.status_code == 200
        assert "bot_display_name" in resp.json()["fields"]
        assert "tts_speaking_rate" in resp.json()["fields"]


def test_put_settings_invalid_type() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _set_admin_test_settings(tmp)
        client = TestClient(app)
        resp = client.put("/admin/settings", json={"silence_timeout_seconds": "not-a-number"})
        assert resp.status_code == 400


# --- TTS Preview ---


def test_tts_preview_empty_text() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _set_admin_test_settings(tmp)
        client = TestClient(app)
        resp = client.post("/admin/tts/preview", json={"text": ""})
        assert resp.status_code == 400


def test_tts_preview_unavailable() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _set_admin_test_settings(tmp)
        client = TestClient(app)
        resp = client.post("/admin/tts/preview", json={"text": "hello"})
        assert resp.status_code == 503


# --- Knowledge ---


def test_list_knowledge_empty() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _set_admin_test_settings(tmp)
        client = TestClient(app)
        resp = client.get("/admin/knowledge")
        assert resp.status_code == 200
        assert resp.json()["documents"] == []


def test_knowledge_crud() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _set_admin_test_settings(tmp)
        client = TestClient(app)

        # Create
        resp = client.put("/admin/knowledge/test-doc.md", json={"content": "# Test\nHello"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "saved"

        # List
        resp = client.get("/admin/knowledge")
        docs = resp.json()["documents"]
        assert len(docs) == 1
        assert docs[0]["filename"] == "test-doc.md"

        # Read
        resp = client.get("/admin/knowledge/test-doc.md")
        assert resp.status_code == 200
        assert "Hello" in resp.json()["content"]

        # Update
        resp = client.put("/admin/knowledge/test-doc.md", json={"content": "# Updated"})
        assert resp.status_code == 200

        resp = client.get("/admin/knowledge/test-doc.md")
        assert "Updated" in resp.json()["content"]

        # Delete
        resp = client.delete("/admin/knowledge/test-doc.md")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        resp = client.get("/admin/knowledge")
        assert resp.json()["documents"] == []


def test_knowledge_get_not_found() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _set_admin_test_settings(tmp)
        client = TestClient(app)
        resp = client.get("/admin/knowledge/nonexistent.md")
        assert resp.status_code == 404


def test_knowledge_delete_not_found() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _set_admin_test_settings(tmp)
        client = TestClient(app)
        resp = client.delete("/admin/knowledge/nonexistent.md")
        assert resp.status_code == 404


# --- Filename Traversal Prevention ---


def test_filename_traversal_dotdot() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _set_admin_test_settings(tmp)
        client = TestClient(app)
        # Encoded slashes are decoded by Starlette as path segments → 404
        resp = client.get("/admin/knowledge/..%2F..%2Fetc%2Fpasswd")
        assert resp.status_code in (400, 404, 422)


def test_filename_traversal_dotdot_direct() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _set_admin_test_settings(tmp)
        client = TestClient(app)
        resp = client.get("/admin/knowledge/..secret.md")
        assert resp.status_code == 400


def test_filename_traversal_invalid_extension() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _set_admin_test_settings(tmp)
        client = TestClient(app)
        resp = client.get("/admin/knowledge/evil.py")
        assert resp.status_code in (400, 422)


def test_filename_traversal_slash() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _set_admin_test_settings(tmp)
        client = TestClient(app)
        # Encoded slashes are decoded by Starlette as path segments → 404
        resp = client.put("/admin/knowledge/sub%2Fpath.md", json={"content": "x"})
        assert resp.status_code in (400, 404, 422)
