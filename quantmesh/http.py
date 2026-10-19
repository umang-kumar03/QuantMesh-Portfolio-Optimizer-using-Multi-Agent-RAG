"""Bounded HTTPS transport; never surface credential-bearing URLs or response bodies."""
import json

import requests


class ServiceError(ValueError):
    """Safe provider failure suitable for display to the user."""


def request_json(method: str, url: str, *, session=None, **kwargs) -> dict:
    client = session or requests
    try:
        with client.request(method, url, timeout=(5, 20), allow_redirects=False,
                            stream=True, **kwargs) as response:
            if response.status_code == 429:
                raise ServiceError("Provider rate limit reached. Retry later or use cached/sample data.")
            if response.status_code in (401, 403):
                raise ServiceError("Provider denied access. Check the configured key and plan permissions.")
            if not 200 <= response.status_code < 300:
                raise ServiceError("Provider request failed. Retry later; no credentials were logged.")
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
    except (requests.RequestException, ValueError, UnicodeError) as exc:
        if isinstance(exc, ServiceError):
            raise
        raise ServiceError("Provider is unavailable or returned invalid JSON. Use cached/sample data.") from None
