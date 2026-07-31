import httpx
import pytest

from gemma.client import OllamaClient, OllamaError


def test_client_connection_error(monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectError("no")
    monkeypatch.setattr(httpx, "post", fail)
    with pytest.raises(OllamaError, match="not reachable"):
        OllamaClient("http://localhost:11434", "gemma4:e2b").chat("s", "u")


def test_health_reports_unreachable(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("no")))
    assert not OllamaClient("x", "m").health_check()["reachable"]


def test_plain_text_chat_omits_json_format(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": "answer"}}

    def post(*args, **kwargs):
        captured.update(kwargs["json"])
        return Response()

    monkeypatch.setattr(httpx, "post", post)
    result = OllamaClient("http://localhost:11434", "model").chat(
        "system", "question", json_output=False
    )

    assert result == "answer"
    assert "format" not in captured
