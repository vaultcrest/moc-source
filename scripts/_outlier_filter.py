"""Three-tier outlier rejection for BrickLink Price Guide sold-listing data.

Formalized 2026-07-14 from two real-world laundering examples (BL parts 6020
and 27448 -- a single wildly-inflated sale surviving even BL's own
quantity-weighted average by 6-9x). Applied per month-bucket of a
price_detail[] response, before computing avg/min/max/median:

  Tier 1 (n >= MIN_SAMPLE_FOR_MAD): MAD-based modified z-score on log(price).
    MAD is statistically stable at this sample size; z = 0.6745 * (x -
    median) / MAD, reject |z| > MODIFIED_Z_THRESHOLD (Iglewicz & Hoaglin).
    Chosen over plain z-score (mean/stddev are themselves corrupted by the
    outliers) and over IQR/Tukey's fences (less robust for this failure mode
    per Leys et al. 2013).

  Tier 2 (n < MIN_SAMPLE_FOR_MAD, a PAB/BAP price is known): MAD is unstable
    on a handful of points, so fall back to a ratio bound against LEGO's own
    direct PAB price -- an independent, un-gameable anchor. Reject sales more
    than PAB_RATIO_BOUND away from it in either direction.

  Tier 3 (n < MIN_SAMPLE_FOR_MAD, no PAB price known): no external anchor and
    too few points for real statistics. Coarse guard only: drop the single
    max value if it's more than MAX_DROP_RATIO times the next-highest sale.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from statistics import median

MIN_SAMPLE_FOR_MAD = 8
MODIFIED_Z_THRESHOLD = 3.5
PAB_RATIO_BOUND = 10.0
MAX_DROP_RATIO = 10.0


def _to_cents(unit_price: str) -> int:
    return round(float(unit_price) * 100)


def bucket_by_month(price_detail: list[dict]) -> dict[date, list[dict]]:
    """Groups price_detail rows by the first-of-month of date_ordered."""
    buckets: dict[date, list[dict]] = defaultdict(list)
    for row in price_detail:
        raw_date = row.get("date_ordered")
        if not raw_date:
            continue
        dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        buckets[date(dt.year, dt.month, 1)].append(row)
    return buckets


def filter_bucket(rows: list[dict], pab_price_cents: int | None) -> list[dict]:
    """Returns the subset of rows surviving outlier rejection. Each row must
    have a unit_price field (BL's raw string price)."""
    if not rows:
        return []

    priced = [(row, _to_cents(row["unit_price"])) for row in rows]

    if len(priced) >= MIN_SAMPLE_FOR_MAD:
        return _filter_tier1_mad(priced)
    if pab_price_cents:
        return _filter_tier2_pab_ratio(priced, pab_price_cents)
    return _filter_tier3_max_drop(priced)


def _filter_tier1_mad(priced: list[tuple[dict, int]]) -> list[dict]:
    import math

    logs = [math.log(cents) for _, cents in priced]
    med = median(logs)
    mad = median(abs(x - med) for x in logs)
    if mad == 0:
        # No spread at all -- everything is identical or near-identical, keep all.
        return [row for row, _ in priced]

    kept = []
    for (row, _cents), log_price in zip(priced, logs):
        z = 0.6745 * (log_price - med) / mad
        if abs(z) <= MODIFIED_Z_THRESHOLD:
            kept.append(row)
    return kept or [row for row, _ in priced]  # never return empty if everything got flagged


def _filter_tier2_pab_ratio(priced: list[tuple[dict, int]], pab_price_cents: int) -> list[dict]:
    lo = pab_price_cents / PAB_RATIO_BOUND
    hi = pab_price_cents * PAB_RATIO_BOUND
    kept = [row for row, cents in priced if lo <= cents <= hi]
    return kept or [row for row, _ in priced]


def _filter_tier3_max_drop(priced: list[tuple[dict, int]]) -> list[dict]:
    if len(priced) < 2:
        return [row for row, _ in priced]
    ordered = sorted(priced, key=lambda pair: pair[1])
    (_, second_highest), (top_row, top_cents) = ordered[-2], ordered[-1]
    if second_highest > 0 and top_cents > second_highest * MAX_DROP_RATIO:
        return [row for row, _ in ordered[:-1]]
    return [row for row, _ in priced]


def compute_stats(filtered_rows: list[dict]) -> dict:
    """Unweighted avg/min/max/median + sample_count from filtered rows."""
    if not filtered_rows:
        return {
            "avg_price_cents": None,
            "min_price_cents": None,
            "max_price_cents": None,
            "median_price_cents": None,
            "sample_count": 0,
        }
    prices = sorted(_to_cents(row["unit_price"]) for row in filtered_rows)
    return {
        "avg_price_cents": round(sum(prices) / len(prices)),
        "min_price_cents": prices[0],
        "max_price_cents": prices[-1],
        "median_price_cents": round(median(prices)),
        "sample_count": len(prices),
    }
