import requests
import pytest

from backend.services.llm_fallback import LLMFallback


def test_falls_back_after_timeout_invalid_json_and_invalid_schema():
    attempted = []

    def provider(name, result):
        def call(key, prompt, system):
            attempted.append(name)
            if isinstance(result, Exception):
                raise result
            return result
        return (name, "test-key", call)

    llm = LLMFallback()
    llm.providers = (
        provider("timeout", requests.Timeout()),
        provider("invalid JSON", "not JSON"),
        provider("invalid schema", '{"ok":false}'),
        provider("valid", '```json\n{"ok":true}\n```'),
    )

    def validate(data):
        if data.get("ok") is not True:
            raise ValueError("invalid schema")

    assert llm.generate_json("prompt", "system", validate) == {"ok": True}
    assert attempted == ["timeout", "invalid JSON", "invalid schema", "valid"]


def test_http_200_provider_error_triggers_fallback(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"error": {"code": 503, "message": "provider overloaded"}}

    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: Response())

    with pytest.raises(ValueError, match="Provider returned an error"):
        LLMFallback._post("https://example.test", {}, {})
