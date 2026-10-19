# Comparative research and attribution

## Method and evidence

Inspected public repository source, READMEs, license files, test directories,
manifests and CI configuration through read-only shallow Git clones. GitHub API
requests were denied (proxy HTTP 403), including the connected repository's issues;
no claim is made to have reviewed issues. Git transport worked. No upstream source
code was copied or vendored and none of these projects is a runtime dependency.
Licenses below reflect the inspected commits, not assumptions about older releases.

| Project / source | Inspected commit | License | Architecture, pipeline and interface | Tests / deployment | Ideas used |
|---|---|---|---|---|---|
| [PyPortfolioOpt](https://github.com/robertmartin8/PyPortfolioOpt) | `a6638d2e06dae6f444fd022cfd4b3c528902a85b` | MIT | Modular Python expected return, risk model and optimizer components; notebook/cookbook examples and price-to-weight flow | `tests/`, GitHub main/release workflows, pip distribution | Separate covariance estimation and portfolio decisions; explicit constraints and conditioning |
| [bt](https://github.com/pmorissette/bt) | `4b76bad2dbf3a49e99feb49db3eee1dde2ef8e12` | MIT | Composable strategy algorithms, portfolio tree, historical prices, weighting and rebalancing; Python/ffn charts | `tests/`, regression/build/docs workflows, pip | Explicit execution and cost assumptions; compare a benchmark using the same data |
| [Backtesting.py](https://github.com/kernc/backtesting.py) | `ca2e2611621e472542ba90f7243a1fa06a7d7108` | AGPL-3.0 | Strategy lifecycle, historical bar input, broker simulation, interactive plots and summary statistics | `backtesting/test`, CI and documentation deployment, pip | Keep simulation separate from visualization; inspect commissions and trade timing. No AGPL implementation copied or linked |
| [pyfolio](https://github.com/quantopian/pyfolio) | `4b901f6d73aa02ceb6d04b7d83502e5c6f2e81aa` | Apache-2.0 | Return/position/transaction analytics with notebook-oriented risk and performance tear sheets | `pyfolio/tests`, setup.py distribution and historical Travis configuration | Present drawdown alongside returns, explain statistical limitations |
| [OpenBB](https://github.com/OpenBB-finance/OpenBB) | `78020ee4b864ab50b8c1f56373877c2b4e7fb623` | Apache-2.0 at this commit | Provider/core/extension separation; standardized data access; Python, CLI, REST/FastAPI integration; proprietary Workspace is a distinct product | Core/provider tests, per-provider CI/publishing, Python packages and API service | Keep data validation behind a clear boundary; provider adapters should be isolated when added |

## Technology decision

QuantMesh needs a coherent runnable research product, not a clone of a trading
framework. A Streamlit application and independent Python engine are sufficient
for its private single-instance scope. Plotly supplies interactive charts. SciPy
supports small constrained allocation problems without the weight of a full
external investment platform. SQLite is appropriate for local research summaries.
There is no reason to add microservices or user accounts beyond the provisioned accounts and owner-scoped records needed for private sharing. Numerical correctness and reproducible holdout
comparisons take precedence over the number of features.

## Technical documentation

These are relevant authoritative documentation entry points; the source inspection
above is the evidence actually obtained in this environment. External documentation
web pages were not separately verified here.

- [SciPy SLSQP](https://docs.scipy.org/doc/scipy/reference/optimize.minimize-slsqp.html)
- [Streamlit testing](https://docs.streamlit.io/develop/api-reference/app-testing)
- [pandas percent change](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.pct_change.html)
- [SQLite parameter binding](https://docs.python.org/3/library/sqlite3.html)
- [PyPortfolioOpt methodology](https://pyportfolioopt.readthedocs.io/)

## License handling

Architectural ideas were independently implemented. Preserve notices if source is
introduced later; review AGPL obligations before integrating Backtesting.py.
OpenBB's inspected root license is Apache-2.0; verify any selected package or
subcomponent independently before adoption. QuantMesh does not choose a new
license on behalf of its owner. Runtime dependencies have their own distribution
licenses; pinning them does not remove attribution obligations for redistributed
artifacts. This comparison is engineering research, not legal advice.
