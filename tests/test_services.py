import json
from datetime import date

import pytest
import requests

from quantmesh.analytics import research
from quantmesh.data import sample_prices
from quantmesh.http import ServiceError, request_json
from quantmesh.llm import LLMConfig, explain
from quantmesh.market import MarketClient, database, reserve_request


class Response:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def iter_content(self, _):
        yield json.dumps(self.data).encode()


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def history(symbol):
    p = sample_prices(periods=100)
    return {"Meta Data": {"2. Symbol": symbol}, "Time Series (Daily)": {
        str(day.date()): {"5. adjusted close": str(price)}
        for day, price in p.iloc[:, 0].items()}}


def test_market_fetch_then_durable_cache_without_credentials(tmp_path):
    path = str(tmp_path / "cache.db")
    session = Session([Response(history("SPY")), Response(history("QQQ"))])
    client = MarketClient(path, "test-key", session=session, clock=lambda: 1000)
    first = client.load(["SPY", "QQQ"], date(2021, 1, 1), date(2022, 1, 1))
    assert len(first.prices) == 100
    assert not first.provenance["synthetic"]
    second = MarketClient(path, clock=lambda: 1100).load(
        ["SPY", "QQQ"], date(2021, 1, 1), date(2022, 1, 1))
    assert all(d["status"] == "cache" for d in second.provenance["symbols"].values())
    assert len(session.calls) == 2
    assert session.calls[0][2]["allow_redirects"] is False


def test_stale_cache_used_on_provider_timeout_then_expires(tmp_path):
    path = str(tmp_path / "cache.db")
    seed = Session([Response(history("SPY"))])
    MarketClient(path, "key", session=seed, clock=lambda: 1000).history("SPY")
    failed = Session([requests.Timeout("secret must never leak")])
    _, _, status = MarketClient(path, "key", session=failed, clock=lambda: 30000).history("SPY")
    assert status == "stale cache"
    with pytest.raises(ServiceError, match="not configured"):
        MarketClient(path, clock=lambda: 800000).history("SPY")


def test_missing_key_returns_labeled_sample_or_error(tmp_path):
    client = MarketClient(str(tmp_path / "cache.db"))
    result = client.load(["SPY", "QQQ"], date(2021, 1, 1), date(2022, 1, 1))
    assert result.provenance["synthetic"]
    assert "SYNTHETIC" in result.warning
    assert "SPY" not in result.prices.columns
    with pytest.raises(ServiceError, match="ALPHAVANTAGE_API_KEY"):
        client.load(["SPY", "QQQ"], date(2021, 1, 1), date(2022, 1, 1), fallback=False)


@pytest.mark.parametrize("symbols", [["SPY"], ["SPY", "SPY"], ["SPY", "https://evil"]])
def test_invalid_symbols_do_not_fall_back(tmp_path, symbols):
    with pytest.raises(ValueError):
        MarketClient(str(tmp_path / "cache.db")).load(symbols, date(2021, 1, 1), date(2022, 1, 1))


def test_budget_is_persistent_and_window_resets(tmp_path):
    path = str(tmp_path / "cache.db")
    reserve_request(path, "test", 1, 2, 100)
    with pytest.raises(ServiceError, match="budget"):
        reserve_request(path, "test", 1, 2, 110)
    reserve_request(path, "test", 1, 2, 161)
    with pytest.raises(ServiceError):
        reserve_request(path, "test", 1, 2, 222)
    reserve_request(path, "test", 1, 2, 90000)


def test_corrupt_cache_and_invalid_payload_are_not_trusted(tmp_path):
    path = str(tmp_path / "cache.db")
    with database(path) as conn:
        conn.execute("INSERT INTO market_cache VALUES (?,?,?)", ("SPY", 1000, "not json"))
    client = MarketClient(path, "key", session=Session([Response({"Note": "quota"})]),
                          clock=lambda: 1100)
    with pytest.raises(ServiceError, match="adjusted history"):
        client.history("SPY")


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
def test_transport_failure_redacts_keys_and_provider_body(status):
    session = Session([Response({"error": "credential-value"}, status)])
    with pytest.raises(ServiceError) as error:
        request_json("GET", "https://example.com", session=session, params={"apikey": "private"})
    assert "private" not in str(error.value)
    assert "credential-value" not in str(error.value)


def test_transport_timeout_is_sanitized():
    with pytest.raises(ServiceError) as error:
        request_json("GET", "https://example.com", session=Session([
            requests.Timeout("https://example.com?apikey=secret-value")]))
    assert "secret-value" not in str(error.value)


def test_grounded_model_quotes_validated_and_private_data_not_sent(tmp_path):
    p = sample_prices()
    r = research(p)
    claim = {"source_id": "M5", "quote": "Volatility measures return dispersion.",
             "explanation": "Volatility describes how much observed returns vary."}
    session = Session([Response({"choices": [{"message": {"content": json.dumps({"claims": [claim]})}}]})])
    output = explain(r, "risk volatility", LLMConfig(api_key="test-key"),
                     str(tmp_path / "budget.db"), session=session)
    assert output["status"] == "generated"
    sent = json.dumps(session.calls[0][2]["json"])
    assert "US Equity" not in sent
    assert "api_key" not in sent
    assert output["sources"]["M5"]["text"].find(claim["quote"]) >= 0


@pytest.mark.parametrize("change", ["source", "quote", "url", "schema"])
def test_model_fabricated_citations_and_bad_output_rejected(tmp_path, change):
    claim = {"source_id": "M5", "quote": "Volatility measures return dispersion.",
             "explanation": "A methodology explanation."}
    if change == "source":
        claim["source_id"] = "NEWS999"
    elif change == "quote":
        claim["quote"] = "Invented financial source claim."
    elif change == "url":
        claim["explanation"] = "Read https://invented.example/news"
    content = "not json" if change == "schema" else json.dumps({"claims": [claim]})
    session = Session([Response({"choices": [{"message": {"content": content}}]})])
    with pytest.raises(ServiceError, match="discarded"):
        explain(research(sample_prices()), "risk volatility", LLMConfig(api_key="key"),
                str(tmp_path / "budget.db"), session=session)


def test_no_evidence_abstains_without_model_request(tmp_path):
    output = explain(research(sample_prices()), "xyzunknown", LLMConfig(),
                     str(tmp_path / "budget.db"), session=Session([]))
    assert output["status"] == "abstained"


def test_llm_configuration_cannot_redirect_secrets():
    with pytest.raises(ServiceError):
        LLMConfig(provider="https://attacker.example", api_key="key").endpoint()


def test_transport_rejects_oversized_and_malformed_responses():
    class Oversized(Response):
        def iter_content(self, _):
            for _ in range(6):
                yield b"x" * (1024 * 1024)
    with pytest.raises(ServiceError, match="5 MB"):
        request_json("GET", "https://example.com", session=Session([Oversized({})]))
    with pytest.raises(ServiceError, match="unexpected"):
        request_json("GET", "https://example.com", session=Session([Response([])]))


def test_bad_alignment_falls_back_without_mixing_assets(tmp_path):
    session = Session([Response(history("SPY")), Response(history("QQQ"))])
    result = MarketClient(str(tmp_path / "cache.db"), "key", session=session).load(
        ["SPY", "QQQ"], date(2021, 1, 1), date(2021, 1, 10))
    assert result.provenance["synthetic"]
    assert list(result.prices.columns) == list(sample_prices().columns)


def test_budget_concurrent_reservations_are_atomic(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    path = str(tmp_path / "cache.db")
    # Initialize schema before the concurrent quota reservations.
    with database(path):
        pass
    def reserve(_):
        try:
            reserve_request(path, "concurrent", 1, 10, 100)
            return True
        except ServiceError:
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(reserve, range(4))) == 1
