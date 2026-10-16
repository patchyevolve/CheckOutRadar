"""
Unit and integration tests for Provider Configuration, Secure Settings Management, and Secret Redaction.
Verifies:
1. Public settings mask credentials and never expose raw API keys.
2. Settings updates preserve existing keys when omitted, and clear keys when explicitly instructed.
3. Connection tester safely handles missing credentials, invalid URLs, HTTP 401, 404, 429, timeouts, and network errors.
4. Secret redaction reliably scrubs credentials from errors and messages.
5. Dynamic settings take effect in LLMClassifier and JobRunner without requiring container restart.
"""

import os
import urllib.error
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.settings_service import (
    get_settings_manager,
    mask_secret,
    redact_secrets,
)
from app.analysis.classifier import LLMClassifier
from app.worker.job_runner import get_adapter
from app.tinyfish.mock_client import MockTinyFishClient


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch):
    """Ensure each test starts with pristine environment and reset settings."""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
    monkeypatch.setenv("MOCK_TINYFISH", "true")
    mgr = get_settings_manager()
    mgr.delete_setting("llm_api_key")
    mgr.delete_setting("tinyfish_api_key")
    mgr.delete_setting("llm_base_url")
    mgr.delete_setting("llm_model")
    mgr.delete_setting("mock_tinyfish")
    mgr.delete_setting("llm_pacing_seconds")
    yield mgr
    mgr.delete_setting("llm_api_key")
    mgr.delete_setting("tinyfish_api_key")


def test_mask_secret_helper():
    """Verify mask_secret only exposes prefix and suffix, never the central key."""
    assert mask_secret("") == ""
    assert mask_secret(None) == ""
    assert mask_secret("short") == "••••••••"
    assert mask_secret("12345678") == "••••••••"
    masked = mask_secret("sk-test-mocksecret9876")
    assert masked.startswith("sk-")
    assert masked.endswith("9876")
    assert "mocksecret" not in masked


def test_redact_secrets_utility():
    """Verify redact_secrets strips sensitive tokens and custom keys."""
    raw = "Error authenticating with sk-test-mocksecret12345 at https://api.openai.com"
    redacted = redact_secrets(raw, ["sk-test-mocksecret12345"])
    assert "sk-test-mocksecret12345" not in redacted
    assert "[REDACTED]" in redacted

    bearer_str = "Authorization: Bearer mock_secret_token_123456789012345"
    assert "[REDACTED]" in redact_secrets(bearer_str)
    assert "mock_secret_token" not in redact_secrets(bearer_str)


def test_settings_endpoint_masks_credentials(client, clean_settings):
    """Verify GET /settings returns public metadata and NEVER leaks raw secrets."""
    clean_settings.set_setting("llm_api_key", "sk-test-mocksecret12345", is_secret=True)
    clean_settings.set_setting("tinyfish_api_key", "tf_mock_secret67890", is_secret=True)

    resp = client.get("/settings")
    assert resp.status_code == 200
    data = resp.json()

    assert data["has_llm_key"] is True
    assert data["has_tinyfish_key"] is True
    assert "sk-test-mocksecret12345" not in resp.text
    assert "tf_mock_secret67890" not in resp.text
    assert data["llm_key_masked"].startswith("sk-")
    assert data["tinyfish_key_masked"].startswith("tf_")


def test_settings_update_preserves_existing_key(client, clean_settings):
    """Updating model or URL without passing llm_api_key preserves the existing backend key."""
    clean_settings.set_setting("llm_api_key", "sk-test-mocksecret12345", is_secret=True)

    update_payload = {
        "llm_model": "llama-3.3-70b-versatile",
        "llm_base_url": "https://api.groq.com/openai/v1",
    }
    resp = client.post("/settings", json=update_payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["llm_model"] == "llama-3.3-70b-versatile"
    assert data["llm_base_url"] == "https://api.groq.com/openai/v1"
    assert data["has_llm_key"] is True
    # Verify backend still retains original key internally
    creds = clean_settings.get_active_credentials()
    assert creds["llm_api_key"] == "sk-test-mocksecret12345"


def test_settings_update_clears_keys_on_instruction(client, clean_settings):
    """Setting clear_llm_key=True removes the stored key."""
    clean_settings.set_setting("llm_api_key", "sk-test-mocksecret12345", is_secret=True)

    resp = client.post("/settings", json={"clear_llm_key": True})
    assert resp.status_code == 200
    data = resp.json()

    assert data["has_llm_key"] is False
    assert data["llm_key_masked"] == ""
    assert clean_settings.get_active_credentials()["llm_api_key"] == ""


def test_test_connection_missing_credentials(client, clean_settings):
    """POST /settings/test-llm fails informatively when no key is provided or stored."""
    clean_settings.delete_setting("llm_api_key")

    resp = client.post("/settings/test-llm", json={})
    assert resp.status_code == 200
    data = resp.json()

    assert data["success"] is False
    assert data["error"] == "missing_api_key"
    assert "No API key provided" in data["message"]


def test_test_connection_invalid_url(client):
    """POST /settings/test-llm rejects invalid URL schemes."""
    resp = client.post(
        "/settings/test-llm",
        json={"base_url": "ftp://invalid-server", "api_key": "sk-test-mocksecret12345"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["success"] is False
    assert data["error"] == "invalid_url"
    assert "begin with http://" in data["message"]


def test_test_connection_http_401_unauthorized(client, monkeypatch):
    """POST /settings/test-llm sanitizes 401 Unauthorized errors and scrubs credentials."""
    import urllib.request
    from io import BytesIO

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            url="https://api.openai.com/v1/chat/completions",
            code=401,
            msg="Unauthorized with sk-test-mocksecret12345",
            hdrs={},
            fp=BytesIO(b'{"error": {"message": "Incorrect API key provided: sk-test-mocksecret12345"}}'),
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    resp = client.post(
        "/settings/test-llm",
        json={"api_key": "sk-test-mocksecret12345", "model": "gpt-4o-mini"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["success"] is False
    assert data["status_code"] == 401
    assert data["error"] == "http_401"
    assert "sk-test-mocksecret12345" not in resp.text
    assert "HTTP 401 Unauthorized" in data["message"]


def test_test_connection_http_404_not_found(client, monkeypatch):
    """POST /settings/test-llm reports model or endpoint not found."""
    import urllib.request
    from io import BytesIO

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            url="https://api.openai.com/v1/chat/completions",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=BytesIO(b'{"error": {"message": "Model not found"}}'),
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    resp = client.post(
        "/settings/test-llm",
        json={"api_key": "sk-test-mocksecret12345", "model": "non-existent-model"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["success"] is False
    assert data["status_code"] == 404
    assert "HTTP 404" in data["message"]
    assert "non-existent-model" in data["message"]


def test_test_connection_http_429_rate_limited(client, monkeypatch):
    """POST /settings/test-llm reports rate limit or quota exceeded."""
    import urllib.request
    from io import BytesIO

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            url="https://api.openai.com/v1/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=BytesIO(b'{"error": {"message": "Rate limit reached"}}'),
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    resp = client.post(
        "/settings/test-llm",
        json={"api_key": "sk-test-mocksecret12345"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["success"] is False
    assert data["status_code"] == 429
    assert "HTTP 429" in data["message"]


def test_test_connection_timeout(client, monkeypatch):
    """POST /settings/test-llm handles socket and HTTP timeouts gracefully."""
    import urllib.request

    def fake_urlopen(req, timeout=None):
        raise TimeoutError("Connection timed out")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    resp = client.post(
        "/settings/test-llm",
        json={"api_key": "sk-test-mocksecret12345"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["success"] is False
    assert data["error"] == "timeout"
    assert "timed out" in data["message"]


def test_test_connection_success(client, monkeypatch):
    """POST /settings/test-llm reports successful round-trip with latency."""
    import urllib.request
    from io import BytesIO

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = b'{"id": "chatcmpl-123", "choices": [{"message": {"content": "pong"}}]}'
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: mock_resp)

    resp = client.post(
        "/settings/test-llm",
        json={"api_key": "sk-test-mocksecret12345", "model": "gpt-4o-mini"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["success"] is True
    assert data["status_code"] == 200
    assert data["latency_ms"] is not None
    assert "Successfully connected" in data["message"]


def test_classifier_uses_active_settings(clean_settings):
    """Verify LLMClassifier picks up dynamic backend configuration."""
    clean_settings.set_setting("llm_model", "gemini-1.5-flash")
    clean_settings.set_setting("llm_base_url", "https://generativelanguage.googleapis.com/v1beta/openai")
    clean_settings.set_setting("llm_api_key", "sk-test-mocksecret12345", is_secret=True)

    classifier = LLMClassifier()
    assert classifier.model == "gemini-1.5-flash"
    assert classifier.base_url == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert classifier.api_key == "sk-test-mocksecret12345"


def test_job_runner_uses_active_mock_setting(clean_settings):
    """Verify get_adapter honors dynamic mock_tinyfish settings."""
    clean_settings.set_setting("mock_tinyfish", True)
    adapter = get_adapter()
    assert isinstance(adapter, MockTinyFishClient)
