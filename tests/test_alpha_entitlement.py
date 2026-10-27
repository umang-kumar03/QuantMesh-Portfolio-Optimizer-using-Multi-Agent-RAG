"""Safe Alpha Vantage free-key response handling and no unadjusted substitution."""
import pytest

from quantmesh.http import ServiceError
from quantmesh.market import parse_history


def test_premium_notice_suggests_yahoo_without_reflecting_raw_response():
    payload = {"Information": "This is a premium endpoint. Subscribe with token SECRET-DO-NOT-ECHO"}
    with pytest.raises(ServiceError, match="premium API access") as error:
        parse_history(payload, "SPY")
    assert "Yahoo Finance" in str(error.value)
    assert "SECRET-DO-NOT-ECHO" not in str(error.value)


def test_alpha_rate_limit_notice_is_distinct():
    payload = {"Note": "You have reached the API call frequency limit."}
    with pytest.raises(ServiceError, match="request limit reached"):
        parse_history(payload, "QQQ")


def test_no_unadjusted_close_fallback():
    payload = {"Meta Data": {"2. Symbol": "SPY"},
               "Time Series (Daily)": {"2026-01-01": {"4. close": "100"}}}
    with pytest.raises(ServiceError):
        parse_history(payload, "SPY")
