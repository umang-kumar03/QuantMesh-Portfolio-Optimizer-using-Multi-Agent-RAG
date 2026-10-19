"""Deterministic specialist agents with lexical retrieval and explicit citations.

No LLM calls, generated market claims, or investment recommendations.
"""
import re
from collections import Counter
from dataclasses import dataclass
from math import log

from quantmesh.analytics import ResearchResult


@dataclass(frozen=True)
class Evidence:
    id: str
    title: str
    text: str


CORPUS = [
    Evidence("M1", "Diversification", "Correlated assets can lose value together. Diversification "
             "reduces concentration but does not eliminate market risk."),
    Evidence("M2", "Estimation risk", "Mean variance optimization depends on estimated returns "
             "and covariance. Shrinkage improves conditioning. Historical estimates are uncertain."),
    Evidence("M3", "Holdout evaluation", "A chronological holdout fits weights on training data "
             "and evaluates future observations. Repeated parameter selection on a holdout leaks "
             "information and invalidates an unbiased out of sample claim."),
    Evidence("M4", "Execution assumptions", "Buy and hold weights drift with prices. Transaction "
             "costs reduce returns. This model charges initial allocation costs but excludes "
             "taxes, spreads beyond the chosen cost, liquidity and market impact."),
    Evidence("M5", "Risk metrics", "Volatility measures return dispersion. Maximum drawdown "
             "measures peak to trough loss. Historical value at risk is a percentile, not a "
             "guaranteed bound on future losses. Sharpe uses arithmetic annualized excess return."),
]


def retrieve(query: str, limit: int = 3) -> list[Evidence]:
    def tokens(s):
        return Counter(re.findall(r"[a-z]+", s.lower()))
    documents = [tokens(d.title + " " + d.text) for d in CORPUS]
    q = tokens(query)
    scores = []
    for doc, terms in zip(CORPUS, documents):
        score = sum(min(terms[t], q[t]) * (log((1 + len(CORPUS)) /
                    (1 + sum(t in d for d in documents))) + 1) for t in q)
        if score > 0:
            scores.append((score, doc))
    return [d for _, d in sorted(scores, key=lambda pair: (-pair[0], pair[1].id))[:limit]]


def analyze(result: ResearchResult, query: str) -> dict:
    w = result.weights
    metrics = result.metrics["Optimized"]
    evidence = retrieve(query)
    synthesis = (" ".join(f"{item.text} [{item.id}]" for item in evidence)
                 if evidence else "Insufficient evidence in the local corpus to answer this query.")
    return {
        "Allocation agent": f"Largest allocation: {w.idxmax()} ({w.max():.1%}). "
                            f"Effective number of assets: {1 / (w ** 2).sum():.2f}. [M1, M2]",
        "Risk agent": f"Holdout volatility: {metrics['Volatility']:.1%}; maximum drawdown: "
                      f"{metrics['Max drawdown']:.1%}. Historical risk is not a forecast. [M5]",
        "Validation agent": f"Training ends {result.training_end}; holdout begins "
                            f"{result.test_start}. Weights are fixed at the split. [M3, M4]",
        "Evidence synthesis agent": synthesis,
        "Retrieved evidence": evidence,
    }
