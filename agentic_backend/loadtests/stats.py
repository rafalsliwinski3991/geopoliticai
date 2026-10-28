"""Turn a run's samples into per-request-kind numbers and pass/fail checks."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from loadtests.scenarios import LoadResult, Sample

TOP_ERRORS = 3


@dataclass(frozen=True)
class KindSummary:
    """One request kind's count, failures, and latency percentiles in seconds.

    The percentiles cover every sample, failed ones included: a request that
    timed out still kept its user waiting.
    """

    kind: str
    count: int
    errors: int
    p50: float
    p95: float
    p99: float
    max: float
    first_token_p95: float | None
    top_errors: tuple[tuple[str, int], ...]

    @property
    def error_rate(self) -> float:
        """Failed requests as a share of all requests of this kind."""
        return self.errors / self.count


def compute_percentile(values: Sequence[float], q: float) -> float:
    """Return the nearest-rank `q`th percentile (0 < q <= 100) of non-empty values."""
    if not values:
        raise ValueError("percentile of no values")
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


def summarize(samples: Sequence[Sample]) -> list[KindSummary]:
    """Group samples by kind, in the order each kind first appears."""
    by_kind: dict[str, list[Sample]] = {}
    for sample in samples:
        by_kind.setdefault(sample.kind, []).append(sample)
    summaries = []
    for kind, group in by_kind.items():
        latencies = [sample.latency for sample in group]
        first_tokens = [s.first_token for s in group if s.first_token is not None]
        failures = Counter(sample.error for sample in group if not sample.ok)
        summaries.append(
            KindSummary(
                kind=kind,
                count=len(group),
                errors=sum(failures.values()),
                p50=compute_percentile(latencies, 50),
                p95=compute_percentile(latencies, 95),
                p99=compute_percentile(latencies, 99),
                max=max(latencies),
                first_token_p95=compute_percentile(first_tokens, 95)
                if first_tokens
                else None,
                top_errors=tuple(failures.most_common(TOP_ERRORS)),
            )
        )
    return summaries


def find_breaches(
    summaries: Sequence[KindSummary],
    *,
    max_error_rate: float,
    max_p95: float | None,
) -> list[str]:
    """Name every kind over the error-rate or p95 limit; empty when the run passes."""
    breaches = []
    for summary in summaries:
        if summary.error_rate > max_error_rate:
            breaches.append(
                f"{summary.kind}: error rate {summary.error_rate:.1%} "
                f"over {max_error_rate:.1%}"
            )
        if max_p95 is not None and summary.p95 > max_p95:
            breaches.append(
                f"{summary.kind}: p95 {summary.p95:.3f}s over {max_p95:.3f}s"
            )
    return breaches


def format_report(result: LoadResult, summaries: Sequence[KindSummary]) -> str:
    """Return the run as a plain-text table, then each kind's top failure reasons."""
    total = len(result.samples)
    lines = [
        f"{total} requests in {result.wall_seconds:.1f}s "
        f"({total / result.wall_seconds:.1f} req/s)",
        "",
        f"{'kind':<10}{'count':>7}{'errors':>8}{'p50':>9}{'p95':>9}"
        f"{'p99':>9}{'max':>9}{'ttft p95':>10}",
    ]
    for s in summaries:
        ttft = f"{s.first_token_p95:.3f}" if s.first_token_p95 is not None else "-"
        lines.append(
            f"{s.kind:<10}{s.count:>7}{s.errors:>8}{s.p50:>9.3f}{s.p95:>9.3f}"
            f"{s.p99:>9.3f}{s.max:>9.3f}{ttft:>10}"
        )
    for s in summaries:
        for error, count in s.top_errors:
            lines.append(f"  {s.kind}: {count} x {error}")
    return "\n".join(lines)
