"""Groq contracts use synthetic responses only; never require provider credentials."""
from pathlib import Path
import json

import pytest
import requests

from quantmesh.analytics import research
from quantmesh.data import sample_prices
from quantmesh.http import ServiceError, request_json
from quantmesh.llm import LLMConfig, explain
from quantmesh.market import database
from test_services import Response, Session


@pytest.fixture
def result():
    return research(sample_prices())


def completion(*, quote="Volatility measures return dispersion.", finish_reason="stop"):
    return Response({"choices": [{"finish_reason": finish_reason, "message": {
        "content": json.dumps({"claims": [{"source_id": "M5", "quote": quote,
                    "explanation": "Volatility describes observed return dispersion."}]})}}]})


def failure(status, code=None):
    return Response({"error": {"code": code, "message": "private-key and sensitive prompt",
                               "failed_generation": "secret financial content"}}, status)


def test_groq_payload_endpoint_timeout_and_parsing(tmp_path, result):
    session = Session([completion()])
    output = explain(result, "risk volatility", LLMConfig(" GROQ ", " llama-3.3-70b-versatile ",
                     "test-only-key"), str(tmp_path / "budget.db"), session=session)
    method, url, options = session.calls[0]
    assert method == "POST" and url == "https://api.groq.com/openai/v1/chat/completions"
    assert options["timeout"] == (5, 60)
    assert options["allow_redirects"] is False
    body = options["json"]
    assert body["model"] == "llama-3.3-70b-versatile"
    assert body["max_completion_tokens"] == 2048 and "max_tokens" not in body
    assert body["response_format"] == {"type": "json_object"}
    assert output["status"] == "generated" and not output["json_mode_recovery"]


def test_known_groq_json_rejection_recovers_once_with_validation(tmp_path, result):
    path = str(tmp_path / "budget.db")
    session = Session([failure(400, "json_validate_failed"), completion()])
    output = explain(result, "risk volatility", LLMConfig("groq", api_key="test-key"),
                     path, session=session)
    assert output["json_mode_recovery"]
    assert len(session.calls) == 2
    first, second = [call[2]["json"] for call in session.calls]
    assert "response_format" in first and "response_format" not in second
    assert first["messages"] == second["messages"]
    with database(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM request_budget WHERE service='llm'").fetchone()[0] == 2


def test_recovered_generation_cannot_bypass_grounding(tmp_path, result):
    session = Session([failure(400, "json_validate_failed"), completion(quote="Invented evidence here.")])
    with pytest.raises(ServiceError, match="discarded"):
        explain(result, "risk volatility", LLMConfig("groq", api_key="key"),
                str(tmp_path / "budget.db"), session=session)
    assert len(session.calls) == 2


def test_recovery_is_bounded_and_does_not_change_models(tmp_path, result):
    session = Session([failure(400, "json_validate_failed"), failure(400, "json_validate_failed")])
    with pytest.raises(ServiceError, match="HTTP 400.*json_validate_failed"):
        explain(result, "risk volatility", LLMConfig("groq", api_key="key"),
                str(tmp_path / "budget.db"), session=session)
    assert len(session.calls) == 2
    assert all(c[2]["json"]["model"] == "llama-3.3-70b-versatile" for c in session.calls)


@pytest.mark.parametrize(("status", "fragment"), [
    (400, "Request rejected"), (401, "Authentication rejected"), (403, "access forbidden"),
    (404, "unavailable"), (429, "rate limit"), (500, "service failed"), (503, "service failed"),
])
def test_groq_errors_are_actionable_redacted_and_not_retried(tmp_path, result, status, fragment):
    session = Session([failure(status)])
    with pytest.raises(ServiceError) as caught:
        explain(result, "risk volatility", LLMConfig("groq", api_key="private-key"),
                str(tmp_path / "budget.db"), session=session)
    error = caught.value
    assert error.status_code == status
    assert f"HTTP {status}" in str(error) and fragment in str(error)
    assert "private-key" not in str(error) and "sensitive prompt" not in str(error)
    assert "secret financial content" not in str(error)
    assert len(session.calls) == 1


def test_unknown_provider_code_is_not_displayed():
    with pytest.raises(ServiceError) as caught:
        request_json("POST", "https://api.groq.com/openai/v1/chat/completions",
                     session=Session([failure(400, "secret-key-as-error-code")]))
    assert caught.value.code is None
    assert "secret-key" not in str(caught.value)


@pytest.mark.parametrize("body", [None, [], {"error": "sensitive content"},
                                   {"error": {"code": ["invalid"]}}])
def test_malformed_error_body_preserves_status_without_leaking(body):
    with pytest.raises(ServiceError, match="HTTP 400") as caught:
        request_json("POST", "https://api.groq.com/openai/v1/chat/completions",
                     session=Session([Response(body, 400)]))
    assert "sensitive content" not in str(caught.value)


def test_model_not_found_reports_model_permission_not_invalid_key(tmp_path, result):
    session = Session([failure(404, "model_not_found")])
    with pytest.raises(ServiceError, match="QUANTMESH_LLM_MODEL") as caught:
        explain(result, "risk volatility", LLMConfig("groq", api_key="key"),
                str(tmp_path / "budget.db"), session=session)
    assert caught.value.code == "model_not_found"


def test_truncated_response_is_not_parsed_as_a_schema_failure(tmp_path, result):
    with pytest.raises(ServiceError, match="truncated") as caught:
        explain(result, "risk volatility", LLMConfig("groq", api_key="key"),
                str(tmp_path / "budget.db"),
                session=Session([completion(finish_reason="length")]))
    assert caught.value.code == "completion_truncated"


def test_timeout_does_not_retry_or_leak_request_data(tmp_path, result):
    session = Session([requests.Timeout("Authorization Bearer private-key")])
    with pytest.raises(ServiceError, match="timed out") as caught:
        explain(result, "risk volatility", LLMConfig("groq", api_key="key"),
                str(tmp_path / "budget.db"), session=session)
    assert caught.value.code == "request_timeout"
    assert "private-key" not in str(caught.value)
    assert len(session.calls) == 1


def test_openai_json_error_does_not_trigger_groq_recovery(tmp_path, result):
    session = Session([failure(400, "json_validate_failed")])
    with pytest.raises(ServiceError):
        explain(result, "risk volatility", LLMConfig("openai", api_key="key"),
                str(tmp_path / "budget.db"), session=session)
    assert len(session.calls) == 1
    assert session.calls[0][2]["json"]["max_tokens"] == 1000


def test_streamlit_shows_sanitized_groq_failure_and_preserves_dashboard(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("QUANTMESH_LLM_PROVIDER", "groq")
    monkeypatch.setenv("QUANTMESH_LLM_API_KEY", "test-only-private-key")
    monkeypatch.setenv("QUANTMESH_LLM_MODEL", "llama-3.3-70b-versatile")
    monkeypatch.setenv("QUANTMESH_DB", str(tmp_path / "journal.db"))
    monkeypatch.setenv("QUANTMESH_CACHE_DB", str(tmp_path / "budget.db"))
    session = Session([failure(400, "context_length_exceeded")])
    monkeypatch.setattr(requests, "request", session.request)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    next(c for c in app.checkbox if c.label.startswith("I agree")).check().run()
    next(b for b in app.button if b.label == "Generate AI explanation").click().run()
    assert not app.exception and len(app.metric) == 4
    text = " ".join(e.value for e in app.error)
    assert "HTTP 400" in text and "context_length_exceeded" in text
    assert "private-key" not in text and "sensitive prompt" not in text


def test_streamlit_groq_recovery_is_disclosed(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("QUANTMESH_LLM_PROVIDER", "groq")
    monkeypatch.setenv("QUANTMESH_LLM_API_KEY", "test-only-key")
    monkeypatch.setenv("QUANTMESH_DB", str(tmp_path / "journal.db"))
    monkeypatch.setenv("QUANTMESH_CACHE_DB", str(tmp_path / "budget.db"))
    session = Session([failure(400, "json_validate_failed"), completion()])
    monkeypatch.setattr(requests, "request", session.request)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    next(t for t in app.text_input if t.label == "Find methodology evidence").set_value("risk volatility")
    next(c for c in app.checkbox if c.label.startswith("I agree")).check().run()
    next(b for b in app.button if b.label == "Generate AI explanation").click().run()
    assert not app.exception and not app.error and len(app.metric) == 4
    assert any("single recovery" in message.value for message in app.info)
