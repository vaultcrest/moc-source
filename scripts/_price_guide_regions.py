"""Buckets BrickLink Price Guide sold-listing rows by seller region.

Used by scripts/scrape_bl_price_guide.py. BrickLink's price_detail[] rows
carry seller_country_code (ISO-3166 alpha-2, except the UK which BrickLink
reports as "UK" rather than "GB" -- confirmed live 2026-07-15). Four groups
are written per (pair, month) from the same worldwide fetch (see
BLClient.fetch_price_guide) -- NOT four independent partitions of equal
standing. Only three are a real partition; "global" is the superset they're
carved out of, not a peer bucket:

  global         -- EVERY row, unfiltered by region. This is the whole set;
                    north_america + eu_gb + other are mutually exclusive
                    subsets of it, so their sample counts always sum to
                    global's. Matches BrickLink's own default no-region
                    Price Guide view.
  north_america  -- subset: US, CA, MX
  eu_gb          -- subset: the 27 EU member states + UK
  other          -- subset: everything else (open-ended, not enumerated)
"""

NORTH_AMERICA = {"US", "CA", "MX"}

EU_GB = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE", "UK",
}

REGIONS = ("global", "north_america", "eu_gb", "other")


def bucket_region(seller_country_code: str) -> str:
    if seller_country_code in NORTH_AMERICA:
        return "north_america"
    if seller_country_code in EU_GB:
        return "eu_gb"
    return "other"


def rows_by_region(rows: list[dict]) -> dict[str, list[dict]]:
    """Returns {'global': all rows, 'north_america': subset, 'eu_gb': subset, 'other': subset}.

    'global' is the full input, not a 4th partition -- the other three are
    mutually exclusive subsets of it (len(north_america) + len(eu_gb) +
    len(other) == len(global) always holds).
    """
    grouped: dict[str, list[dict]] = {"global": rows, "north_america": [], "eu_gb": [], "other": []}
    for row in rows:
        grouped[bucket_region(row["seller_country_code"])].append(row)
    return grouped
