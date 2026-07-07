# Changelog

All notable changes to MOC Source are documented here.

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
