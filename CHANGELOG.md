# Changelog

All notable changes to MOC Source are documented here.

## [Backend] — 2026-07-15

### BrickLink Price Guide — first pass (`bl_price_guide_monthly`, `bl_price_guide_scan_log`, `scripts/scrape_bl_price_guide.py`)
- New tables (Alembic `e7f8a9b0`): `bl_price_guide_monthly` (part_no, color_id, region, new_or_used, month → avg/min/max/median price cents + sample_count/raw_sample_count, PK includes month) and `bl_price_guide_scan_log` (thin resumability tracker, PK part_no/color_id/region) — additive only
- New `BLClient.fetch_price_guide()` in `scripts/_bricklink_lookup.py` — `GET /items/PART/{no}/price?guide_type=sold&region=north_america`, North America only for now (region is a PK column, not hardcoded, so other regions can be added later without a schema change)
- New `scripts/_outlier_filter.py` — three-tier outlier rejection (MAD-based modified z-score on log(price) for n≥8, ratio bound against PAB price for smaller samples with a PAB anchor, drop-the-implausible-max otherwise), formalized against BL parts 6020/27448 evidence. Unit-verified: a simulated $3,072 laundering sale among ~900 real-range ($0.02–0.45) sales is correctly rejected, average drops from would-be-distorted to $0.24/max $0.45
- New `scripts/scrape_bl_price_guide.py` — priority-ordered first pass over the ~81K known `(part_no, color_id)` pairs in `bricklink_mappings`: PAB/BAP-priced pairs first, then everything else by `bl_part_catalog.last_used_year` descending (current year backward), then no-year-data pairs last. Each call returns up to ~6 months of real sold-listing history (`price_detail[]`), bucketed by month and outlier-filtered before being written — a single pass backfills several months of history per pair, not just a current snapshot. Raw `price_detail` rows are never persisted, only the derived monthly summary. **No retention limit** — supersedes the earlier-drafted 12-month rolling design; history accumulates indefinitely for multi-year price-trend charts
- `scrape_bl_mold_data.py` throttled from 5,000 to 500 calls/night (`moc-source-infra`) to free up BrickLink's shared ~5,000 calls/day budget for the new scraper (~4,500 calls/night, 2,250 pairs), since mold-backfill's output only feeds the not-yet-built discontinued-mold feature — nothing live consumes it yet, unlike price-guide data. New `mocsource-scrape-bl-price-guide.service/.timer` (daily 03:00)

## [Backend] — 2026-07-14

### Colors Table (`colors`, `scripts/backfill_rebrickable_colors.py`, `scripts/backfill_bricklink_colors.py`)
- Added `rebrickable_id` column (Alembic `b4c5d6e7`) — additive only, no existing `bl_id`/`bl_name`/`lego_id`/`lego_name`/`hex` values touched
- New `scripts/backfill_rebrickable_colors.py` cross-references Rebrickable's `/lego/colors/` API against `colors.bl_id` via `external_ids.BrickLink.ext_ids`, matching the ID-based approach already proven in `mocsource/rebrickable_client.py`. 170/174 colors matched; the 4 unmatched are BrickLink placeholder entries with negative IDs (Magnet, Electric Contact Alloy/Copper, and an unnamed `-1`), not real colors
- Added `color_type`, `rebrickable_year_from`, `rebrickable_year_to` columns (Alembic `c5d6e7f8`) — additive only
- New `scripts/backfill_bricklink_colors.py` pulls BrickLink's own `GET /colors` catalog (214 live colors): backfills `color_type` for existing rows and inserts the 44 BrickLink colors previously missing from the table entirely (mostly the "Mx" Modulex sub-brand) — `ON CONFLICT (bl_id) DO NOTHING` on insert, so it can never overwrite an existing row
- `scripts/backfill_rebrickable_colors.py` extended to also backfill `rebrickable_year_from`/`_to` from Rebrickable's bulk `colors.csv` download (`cdn.rebrickable.com/media/downloads/colors.csv.gz`) — confirmed the live REST API has no year field at all, this data only exists in that bulk product. Fetched fresh each run (small file, ~275 rows), not cached locally. After both scripts: 218 total colors (174 original + 44 newly inserted), 214/218 have `color_type`, 213/218 matched to a `rebrickable_id` with year data

### Manual overrides + Rebrickable part_no retry tiering (`scripts/apply_manual_overrides.py`, `scripts/fix_rebrickable_part_nos.py`)
- Applied a 77-row hand-reviewed batch of `cache/manual_overrides.yaml` entries against `bricklink_mappings`: 3 corrections (real BrickLink part numbers identified by hand) + 74 confirmed N/A (one-off promotional/exclusive prints — SDCC exclusives, LEGO Store grand-opening tiles, licensed-IP crossover variants — that BrickLink genuinely doesn't catalog as distinct entries). 0 skipped.
- Added `year_from`/`year_to` columns to `rebrickable_part_no_fixes` (Alembic `d6e7f8a9`) — additive only
- `fix_rebrickable_part_nos.py` now backfills a year signal for unresolved rows (reusing `resolve_part_years_bulk()`, already built for `backfill_last_used_year.py`) and gained a `--year-tier {recent,old}` flag splitting retries into two scheduled cadences: weekly for current-year-and-prior parts (likely to resolve soon as BrickLink catalogs new releases), monthly for confirmed-older ones. Self-bootstrapping — rows with no year data yet default into the "recent" tier so nothing is stranded. Two new systemd timers in `moc-source-infra` (`mocsource-fix-rebrickable-weekly`/`-monthly`). Confirmed live: all 137 currently-unresolved rows are 2026-released parts BrickLink hasn't cataloged yet, not errors — the untiered default (full-backlog) behavior is unchanged for manual/ad hoc runs

## [0.4.10] — 2026-07-07

### Extension
- Added a "Links" card (Website, Guide, Patreon, PayPal) to the Info page, with a note encouraging support if MOC Source has saved you money
- Same Links card, plus Disclaimer and License, now also shown at the bottom of the Parts Lists page — factored into a shared `footerCardsHtml()` helper so both pages stay in sync

## [0.4.9] — 2026-07-07

### Extension
- Renamed "LEGO Cart(s)" to "Pick-A-Brick Cart(s)" across the Lists view and Project detail page for clarity
- Removed the unused BrickLink API Credentials settings card and its encrypt/decrypt wiring — it was never used and only added confusion

## [Backend] — 2026-07-05

### PAB Scraper (`scripts/scrape_pab.py`)
- Replaced `curl_cffi` with system `curl` subprocess — correct OpenSSL TLS fingerprint avoids Cloudflare Bot Management blocks
- Reduced page size 400 → 150 and sibling batch size 900 → 300 to stay within LEGO API per-request timeouts
- Increased inter-page delay to 2 s and inter-locale delay to 30 s for rate-limit recovery
- Added 504 retry logic with 30 s / 60 s / 90 s backoff
- Added `scan_complete` flag: stale OOS marking is skipped when a scrape completes only partially, preventing false out-of-stock writes
- Added `--one-locale` flag for round-robin hourly price refresh (one locale per invocation, state tracked in `.pab_locale_idx`)
- Changed OOS representative locale from `pl-pl` to `de-de`

### Element Enrichment (`mocsource/enrichment.py`, `mocsource/rebrickable_client.py`)
- Added `lookup_element_mapping(element_id)` — queries Rebrickable by LEGO element ID to resolve BrickLink part number, color ID, and part name
- Added `enrich_element_bg(element_id)` background task — triggered automatically by `GET /api/v1/parts/element/{id}/price` when no BrickLink mapping exists; fills `bricklink_mappings` so subsequent lookups resolve correctly

### API (`mocsource/routers/parts.py`)
- `pab_price_by_element`: Cache-Control header is now set per code path — `no-store` when element has no mapping (forces re-fetch after background enrichment), `s-maxage=3600` only when data is present
- Unknown elements now trigger `enrich_element_bg` as a FastAPI `BackgroundTask` (zero latency impact on the HTTP response)

### Privacy Policy (`static/privacy.html`)
- Updated wording for clarity; added "What that means" section header

## [0.4.8] — 2026-07-05

### Multi-Cart Project Support
- Projects can now link multiple LEGO carts with roles: Main, Overflow, Bestseller Only, Standard Only, Bestseller Overflow, Standard Overflow
- Project detail view shows all linked carts with role labels below the primary cart name
- Save to Cart modal routes overflow lots to the configured overflow cart instead of always creating a new one
- "Add Overflow Cart to Project" prompt is suppressed when an overflow cart is already configured
- Overflow cart contents are merged (quantities added for duplicate element IDs) on repeated saves

### Save to Cart Modal
- Fixed multiple save modals spawning on repeated project navigation (open-guard via `.lego-diff-modal` class)
- Save + Create Overflow Cart splits PAB and Standard lots at the 200-lot limit and caps individual qty at 999
- Replace Cart and Save to Overflow use the same split logic

### Parts Lists — Sort Controls
- All three list sections (Wanted Lists, BrickLink Carts, LEGO Carts) now have sort dropdowns
- Sort options: Name (default), Most Parts, Last Saved, Last Created
- Sort preference is remembered within the session

### LEGO Transfer
- Bestseller and Standard transfers are now sequential full-batch operations (no chunking)
- HTTP 429 rate-limit errors are retried with exponential backoff (3 s → 6 s → 12 s)
- Removed stray `query: ""` variable from `ElementCartQuery` that caused HTTP 400 Validation errors on the Standard cart read
- Removed artificial inter-channel delay

### CSP Fix
- Replaced all inline `onerror=` image-fallback handlers with `data-fb1` / `data-fb2` attributes and a single delegated `error` listener — resolves Content Security Policy violations in the extension page

## [0.4.7] — prior

### Multi-Cart Schema (Step 1)
- Projects store `legoCartIds: [{cartId, role}]` array; legacy `legoCartId` scalar auto-migrated on first access
- Project setup UI: add/remove/reorder LEGO carts, assign roles, single-Main enforcement
- Overflow detection warns when PAB > 200 lots, Standard > 200 lots, or any item qty > 999
- Split Cart button on standalone LEGO cart detail pages

### Main Page
- Cart sort control for LEGO Carts section (Last Created / Most Parts / Last Saved)

## [0.4.2] — prior

- LEGO cart transfer reliability improvements
- Inter-batch delay tuning for rate-limit avoidance

## [0.4.1] — prior

- LEGO PAB/STD transfer via Pick a Brick page
- Save Cart button injected into LEGO.com cart tab bar
- Overflow lot-limit warning in transfer UI

## [0.4.0] — prior

- BrickLink wanted list and cart import
- Project system with allocation tracking
- PAB price comparison and channel badges
- Auto Allocate and Fill Wanted Qtys
