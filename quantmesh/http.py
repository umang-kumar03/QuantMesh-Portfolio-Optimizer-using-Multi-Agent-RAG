"""Bounded HTTPS transport; only allowlisted error metadata crosses the provider boundary."""
import json

import requests

# Provider bodies can contain keys, prompt text and failed generations. Never echo them.
SAFE_ERROR_CODES = frozenset({
    "json_validate_failed", "json_generation_failed", "model_not_found", "model_decommissioned",
    "context_length_exceeded", "invalid_api_key", "invalid_request_error", "unsupported_parameter",
    "rate_limit_exceeded", "insufficient_quota", "permission_denied", "model_permission_denied",
    "billing_hard_limit_reached", "content_policy_violation",
})


class ServiceError(ValueError):
    """Safe error plus bounded machine-readable metadata; never retain a response/request."""

    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def error_code(response) -> str | None:
    """Read at most 64 KiB of an error body and retain only a known constant code."""
    try:
        chunks, size = [], 0
        for chunk in response.iter_content(16384):
            size += len(chunk)
            if size > 65536:
                return None
            chunks.append(chunk)
        payload = json.loads(b"".join(chunks))
        error = payload.get("error") if isinstance(payload, dict) else None
        if not isinstance(error, dict):
            return None
        for field in ("code", "type"):
            value = error.get(field)
            if isinstance(value, str) and value in SAFE_ERROR_CODES:
                return value
    except (requests.RequestException, ValueError, UnicodeError):
        pass
    return None


def http_error(response) -> ServiceError:
    status, code = response.status_code, error_code(response)
    if status == 400 and code in {"json_validate_failed", "json_generation_failed"}:
        detail = "Model could not generate the requested JSON. Try a shorter research question."
    elif code in {"model_not_found", "model_decommissioned"} or status == 404:
        detail = ("Chat model or endpoint is unavailable. Check QUANTMESH_LLM_MODEL and "
                  "that this account can use it; models-list access does not prove chat access.")
    elif code == "context_length_exceeded":
        detail = "Model context limit exceeded. Shorten the question or select a larger-context model."
    elif status == 400:
        detail = "Request rejected. Check the model's chat parameters and JSON-output support."
    elif status == 401:
        detail = "Authentication rejected for this request. Check the selected provider's credential."
    elif status == 403:
        detail = "Chat access forbidden. Check account, organization, model and network permissions."
    elif status == 429:
        detail = "Provider rate limit or quota reached. Wait and check the provider's account limits."
    elif 500 <= status <= 599:
        detail = "Provider service failed. Retry later; your API key is not assumed invalid."
    elif 300 <= status <= 399:
        detail = "Provider redirect refused to protect credentials. Check the configured endpoint."
    else:
        detail = "Provider request was rejected. Check provider availability and configuration."
    suffix = f" ({code})" if code else ""
    return ServiceError(f"Provider HTTP {status}{suffix}: {detail}", status_code=status, code=code)


def request_json(method: str, url: str, *, session=None, timeout=(5, 20), **kwargs) -> dict:
    client = session or requests
    try:
        with client.request(method, url, timeout=timeout, allow_redirects=False,
                            stream=True, **kwargs) as response:
            if not 200 <= response.status_code < 300:
                raise http_error(response) from None
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 5 * 1024 * 1024:
                    raise ServiceError("Provider response exceeded the 5 MB safety limit.")
                chunks.append(chunk)
            data = json.loads(b"".join(chunks))
            if not isinstance(data, dict):
                raise ServiceError("Provider returned an unexpected response format.")
            return data
    except requests.Timeout:
        raise ServiceError("Provider request timed out. Retry later or shorten the research question.",
                           code="request_timeout") from None
    except (requests.RequestException, ValueError, UnicodeError) as exc:
        if isinstance(exc, ServiceError):
            raise
        raise ServiceError("Provider is unavailable or returned invalid JSON. "
                           "Check network connectivity and retry later.") from None
