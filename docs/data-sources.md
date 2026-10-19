# Historical data sources

The sidebar offers four separate sources: Sample market, Upload CSV, Alpha Vantage,
and Yahoo Finance. All feed the same existing validation, training-only optimization,
holdout backtest, risk charts, agents and consented Groq/OpenAI explanation pipeline.
Provider results are stored separately in session state, so switching sources cannot
relabel another provider's loaded data. Neither provider supplies real-time tick quotes.

## Yahoo Finance via yfinance

No API key or paid Alpha Vantage subscription is needed. Install the normal pinned
project dependencies, select **Yahoo Finance**, enter 2–5 unique exchange tickers
(default SPY, QQQ, GLD), choose dates and press **Load market history**. Downloads
occur only on submission. The selected end date is inclusive; the adapter translates
it to yfinance's exclusive end by adding a day. Use compatible asset currencies and
trading calendars; QuantMesh does not perform FX conversion or calendar imputation.

`yfinance==1.7.0` is pinned. Its current defaults adjust prices automatically and
may omit Adj Close. QuantMesh explicitly sets auto_adjust=False and back_adjust=False,
requests daily data with missing rows retained, disables repair/progress/threads,
and extracts **Adj Close only**. Flat single-ticker and both Price/Ticker MultiIndex
orders are handled. A Close-only response is rejected, never assumed adjusted.

Trading dates retain exchange session dates, are normalized and sorted. Invalid
dates and identical duplicate dates are removed with counts in provenance.
Conflicting duplicate prices are rejected. Missing tickers, NaN/nonfinite/nonpositive
prices and fewer than 61 observations fail validation. Missing observations are not
filled or silently dropped. Returned rows outside the requested range are excluded
and counted. Single-ticker extraction is tested, but portfolio input still requires
at least two assets. No optimization or metric implementation is duplicated.

Provenance includes source, requested/actual dates, ticker symbols, adjustment policy,
retrieval timestamp, provider/cache status and date-cleaning counts. Shared Yahoo
cache is separate from Alpha Vantage's table, keyed by symbols/date range/adjustment
policy, bounded to 64 datasets and refreshed after six hours. Expired Yahoo results
are not silently served stale. If a download fails, the optional checkbox permits
**whole-portfolio synthetic sample fallback**, clearly labeled in the UI and report;
the fallback does not impersonate the requested tickers or dates.

A persistent budget allows at most five logical downloads/minute and 25/day across
the instance. Each logical download may perform multiple Yahoo HTTP requests for
prices, cookies and crumbs; this is not a promise about Yahoo's IP-level quota.
There is no automatic retry loop or rate-limit bypass. Swallowed yfinance rate-limit
errors are recognized in its per-call diagnostics; raw diagnostics are suppressed
for that thread to avoid displaying cookies, request URLs or sensitive library errors.
Other threads' logging filters are preserved. The library's request timeout is 20s;
unlike the direct Alpha/LLM transport, its cookie negotiation/retries are managed by
yfinance and may make a whole logical download take longer. Public history and
library-generated cookie/timezone caches stay in the configured local cache directory.

## Limitations and terms

Yahoo access through yfinance is unofficial, may break or be throttled, and has no
availability or completeness guarantee. yfinance's software license does not grant
rights to redistribute Yahoo data. Review Yahoo's terms and your intended personal,
commercial, educational or redistribution use before hosting/sharing results.
For completed-session research, select an end date before today: Yahoo may return
an in-progress current daily candle. Adjusted history can be revised for corporate actions; it is not a point-in-time
licensed research feed and can carry survivorship or revision bias. Local methodology
citations are not market news. AI receives only consented question/summary evidence;
this integration does not add raw-price or ticker transmission to the LLM.

References: [yfinance API](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html),
[yfinance project](https://github.com/ranaroussi/yfinance),
[Yahoo terms](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html).

## Network and live verification

Outbound HTTPS is needed to query1.finance.yahoo.com, query2.finance.yahoo.com,
fc.yahoo.com and, when cookie-consent negotiation requires it, guce.yahoo.com and
consent.yahoo.com. Permit only required hosts under your organization policy. Do not
disable TLS verification or change proxy settings to bypass access restrictions.

During implementation a genuine three-symbol fetch returned no history. Independent
checks to Yahoo query/cookie hosts returned proxy HTTP 403. **Live Yahoo retrieval is
unverified in this cloud environment.** Automated tests use controlled DataFrames
and exceptions, require no internet, and do not establish live provider availability.
Verify a real load from your permitted environment, check provenance and inspect
prices before relying on results.
