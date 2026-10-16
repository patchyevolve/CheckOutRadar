"""
Settings and Provider Configuration Service for Checkout Radar.
Manages LLM and TinyFish credentials and endpoints securely on the backend.
Guarantees:
- Secrets are stored exclusively on the backend (SQLite DB / environment variables).
- API keys are NEVER exposed to browser JavaScript, local storage, reports, or logs.
- Dynamic runtime configuration with support for OpenAI-compatible endpoints (Groq, OpenAI, Gemini, Ollama, Custom).
- Deterministic offline mock mode by default.
- Strict secret redaction across all test connection responses, errors, and log messages.
"""

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from ..db.connection import get_connection

logger = logging.getLogger(__name__)

# Patterns for sensitive credentials that must never appear in error outputs or logs
SECRET_SCRUB_PATTERNS = [
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{10,}"),
    re.compile(r"gsk_[A-Za-z0-9_-]{10,}"),
    re.compile(r"AIza[0-9A-Za-z-_]{15,}"),
    re.compile(r"(?:tinyfish|tf_)[A-Za-z0-9_-]{10,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.]{10,}"),
]


def mask_secret(secret: Optional[str]) -> str:
    """Mask a secret key showing only prefix and suffix, never the sensitive center."""
    if not secret:
        return ""
    s = secret.strip()
    if len(s) <= 8:
        return "••••••••"
    return f"{s[:3]}...{s[-4:]}"


def redact_secrets(text: str, custom_secrets: Optional[List[str]] = None) -> str:
    """Scrub known secret patterns and active key literals from any string."""
    if not text:
        return text
    result = text
    if custom_secrets:
        for secret in custom_secrets:
            if secret and len(secret) >= 4:
                result = result.replace(secret, "[REDACTED]")
    for pat in SECRET_SCRUB_PATTERNS:
        result = pat.sub("[REDACTED]", result)
    return result


class SettingsManager:
    """Thread-safe, durable settings store backed by SQLite system_settings and env fallbacks."""

    DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
    DEFAULT_LLM_MODEL = "gpt-4o-mini"
    DEFAULT_LLM_PROVIDER = "openai_compatible"
    DEFAULT_PACING_SECONDS = 2.0

    def __init__(self):
        self._memory_overrides: Dict[str, Any] = {}

    def get_setting(self, key: str, default: Any = None, env_var: Optional[str] = None) -> Any:
        """Resolve a setting by checking in-memory overrides, database persistence, then environment variable."""
        if key in self._memory_overrides:
            return self._memory_overrides[key]

        try:
            conn = get_connection()
            try:
                row = conn.execute("SELECT value FROM system_settings WHERE key = ?", (key,)).fetchone()
                if row:
                    val = row["value"]
                    # Handle boolean conversions
                    if val.lower() in ("true", "1", "yes"):
                        return True
                    elif val.lower() in ("false", "0", "no"):
                        return False
                    return val
            finally:
                conn.close()
        except Exception:
            # Database might not be initialized yet; fallback gracefully
            pass

        if env_var:
            env_val = os.getenv(env_var)
            if env_val is not None:
                if env_val.lower() in ("true", "1", "yes"):
                    return True
                elif env_val.lower() in ("false", "0", "no"):
                    return False
                return env_val

        return default

    def set_setting(self, key: str, value: Any, is_secret: bool = False):
        """Save a setting to the database and update memory cache."""
        val_str = str(value) if value is not None else ""
        self._memory_overrides[key] = value

        try:
            conn = get_connection()
            try:
                conn.execute(
                    "INSERT INTO system_settings (key, value, is_secret, updated_at) "
                    "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value, is_secret = excluded.is_secret, updated_at = CURRENT_TIMESTAMP",
                    (key, val_str, 1 if is_secret else 0),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Could not persist setting {key} to database: {redact_secrets(str(e))}")

    def delete_setting(self, key: str):
        """Remove a setting override from database and memory, reverting to environment default."""
        self._memory_overrides.pop(key, None)
        try:
            conn = get_connection()
            try:
                conn.execute("DELETE FROM system_settings WHERE key = ?", (key,))
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass

    def get_public_settings(self) -> Dict[str, Any]:
        """Return public settings dictionary with ALL credentials safely masked."""
        llm_key = self.get_setting("llm_api_key", "", "LLM_API_KEY")
        tinyfish_key = self.get_setting("tinyfish_api_key", "", "TINYFISH_API_KEY")
        base_url = self.get_setting("llm_base_url", self.DEFAULT_LLM_BASE_URL, "LLM_BASE_URL")
        model = self.get_setting("llm_model", self.DEFAULT_LLM_MODEL, "LLM_MODEL")
        provider = self.get_setting("llm_provider", self.DEFAULT_LLM_PROVIDER, "LLM_PROVIDER")
        mock_mode = self.get_setting("mock_tinyfish", True, "MOCK_TINYFISH")
        pacing = float(self.get_setting("llm_pacing_seconds", self.DEFAULT_PACING_SECONDS, "LLM_PACING_SECONDS"))

        return {
            "llm_provider": provider,
            "llm_base_url": base_url,
            "llm_model": model,
            "has_llm_key": bool(llm_key),
            "llm_key_masked": mask_secret(llm_key),
            "has_tinyfish_key": bool(tinyfish_key),
            "tinyfish_key_masked": mask_secret(tinyfish_key),
            "mock_tinyfish": bool(mock_mode),
            "llm_pacing_seconds": pacing,
        }

    def get_active_credentials(self) -> Dict[str, Any]:
        """Return active unmasked credentials for internal backend use only."""
        return {
            "llm_base_url": self.get_setting("llm_base_url", self.DEFAULT_LLM_BASE_URL, "LLM_BASE_URL"),
            "llm_model": self.get_setting("llm_model", self.DEFAULT_LLM_MODEL, "LLM_MODEL"),
            "llm_api_key": self.get_setting("llm_api_key", "", "LLM_API_KEY"),
            "llm_provider": self.get_setting("llm_provider", self.DEFAULT_LLM_PROVIDER, "LLM_PROVIDER"),
            "tinyfish_api_key": self.get_setting("tinyfish_api_key", "", "TINYFISH_API_KEY"),
            "mock_tinyfish": bool(self.get_setting("mock_tinyfish", True, "MOCK_TINYFISH")),
            "llm_pacing_seconds": float(self.get_setting("llm_pacing_seconds", self.DEFAULT_PACING_SECONDS, "LLM_PACING_SECONDS")),
        }

    def update_settings(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Apply updates to backend settings and return updated public settings."""
        if "llm_base_url" in updates and updates["llm_base_url"]:
            url = updates["llm_base_url"].strip().rstrip("/")
            if not (url.startswith("http://") or url.startswith("https://")):
                raise ValueError("Base URL must begin with http:// or https://")
            self.set_setting("llm_base_url", url)

        if "llm_model" in updates and updates["llm_model"]:
            self.set_setting("llm_model", updates["llm_model"].strip())

        if "llm_provider" in updates and updates["llm_provider"]:
            self.set_setting("llm_provider", updates["llm_provider"].strip())

        if "mock_tinyfish" in updates:
            self.set_setting("mock_tinyfish", bool(updates["mock_tinyfish"]))

        if "llm_pacing_seconds" in updates:
            try:
                p = max(0.0, float(updates["llm_pacing_seconds"]))
                self.set_setting("llm_pacing_seconds", p)
            except (ValueError, TypeError):
                pass

        # Handle LLM key: explicit update, explicit clear, or preserve
        if updates.get("clear_llm_key"):
            self.set_setting("llm_api_key", "", is_secret=True)
        elif updates.get("llm_api_key"):
            key = updates["llm_api_key"].strip()
            if key:
                self.set_setting("llm_api_key", key, is_secret=True)

        # Handle TinyFish key: explicit update, explicit clear, or preserve
        if updates.get("clear_tinyfish_key"):
            self.set_setting("tinyfish_api_key", "", is_secret=True)
        elif updates.get("tinyfish_api_key"):
            key = updates["tinyfish_api_key"].strip()
            if key:
                self.set_setting("tinyfish_api_key", key, is_secret=True)

        return self.get_public_settings()

    def test_llm_connection(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout_sec: float = 6.0,
    ) -> Dict[str, Any]:
        """
        Execute an isolated, timed test request to the OpenAI-compatible endpoint.
        Guarantees that credentials are never leaked in error messages, tracebacks, or output.
        """
        active = self.get_active_credentials()
        test_base = (base_url or active["llm_base_url"]).strip().rstrip("/")
        test_model = (model or active["llm_model"]).strip()
        test_key = api_key.strip() if api_key is not None and api_key.strip() else active["llm_api_key"]

        # Validate presence of API key
        if not test_key:
            return {
                "success": False,
                "status_code": None,
                "latency_ms": None,
                "message": "No API key provided or configured. Enter an API key to test the connection.",
                "error": "missing_api_key",
                "model": test_model,
            }

        # Validate URL syntax
        if not (test_base.startswith("http://") or test_base.startswith("https://")):
            return {
                "success": False,
                "status_code": None,
                "latency_ms": None,
                "message": "Invalid endpoint URL: URL must begin with http:// or https://",
                "error": "invalid_url",
                "model": test_model,
            }

        url = f"{test_base}/chat/completions"
        req_data = {
            "model": test_model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 5,
            "temperature": 0.0,
        }
        body_bytes = json.dumps(req_data).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=body_bytes,
            headers={
                "Authorization": f"Bearer {test_key}",
                "Content-Type": "application/json",
                "User-Agent": "CheckoutRadar-SettingsVerifier/1.0",
            },
            method="POST",
        )

        t_start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                elapsed_ms = round((time.perf_counter() - t_start) * 1000, 1)
                status = resp.status
                return {
                    "success": True,
                    "status_code": status,
                    "latency_ms": elapsed_ms,
                    "message": f"Successfully connected! Model '{test_model}' responded with HTTP {status} in {elapsed_ms}ms.",
                    "model": test_model,
                    "error": None,
                }
        except urllib.error.HTTPError as e:
            elapsed_ms = round((time.perf_counter() - t_start) * 1000, 1)
            status_code = e.code
            if status_code == 401:
                msg = "Authentication failed (HTTP 401 Unauthorized): Invalid API key or expired token."
            elif status_code == 403:
                msg = "Access forbidden (HTTP 403 Forbidden): Check account permissions or API restrictions."
            elif status_code == 404:
                msg = f"Endpoint or model not found (HTTP 404): Verify model name '{test_model}' and base URL path."
            elif status_code == 429:
                msg = "Rate limit or quota exceeded (HTTP 429): Upstream provider rejected request due to throttling."
            elif 500 <= status_code < 600:
                msg = f"Upstream provider error (HTTP {status_code}): Service may be temporarily experiencing outages."
            else:
                msg = f"Upstream provider returned HTTP {status_code}."

            return {
                "success": False,
                "status_code": status_code,
                "latency_ms": elapsed_ms,
                "message": redact_secrets(msg, [test_key]),
                "error": f"http_{status_code}",
                "model": test_model,
            }
        except urllib.error.URLError as e:
            reason_str = str(e.reason)
            sanitized_reason = redact_secrets(reason_str, [test_key])
            return {
                "success": False,
                "status_code": None,
                "latency_ms": None,
                "message": f"Connection failed: {sanitized_reason}",
                "error": "connection_failed",
                "model": test_model,
            }
        except TimeoutError:
            return {
                "success": False,
                "status_code": None,
                "latency_ms": None,
                "message": f"Connection timed out after {timeout_sec}s. Check endpoint address and firewall settings.",
                "error": "timeout",
                "model": test_model,
            }
        except Exception as e:
            err_msg = redact_secrets(str(e), [test_key])
            return {
                "success": False,
                "status_code": None,
                "latency_ms": None,
                "message": f"Provider connection check error: {err_msg}",
                "error": "provider_error",
                "model": test_model,
            }


# Singleton instance
_manager_instance: Optional[SettingsManager] = None


def get_settings_manager() -> SettingsManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = SettingsManager()
    return _manager_instance
