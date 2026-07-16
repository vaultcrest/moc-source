# MOC Source

LEGO acquisition planning tool. Overlays PAB (Pick a Brick) and BAP (Bricks and Pieces) prices from LEGO direct onto BrickLink pages so you can compare store prices vs. buying direct. Also imports BrickLink wanted lists and carts into a built-in list manager with part-level detail, Want/Have tracking, and LEGO direct price comparison.

MOC Source is a free, open source community tool built by AFOLs for AFOLs. The goal is recognition and community contribution — not profit. If it saves you time sourcing parts, consider supporting the server costs:

[![Patreon](https://img.shields.io/badge/Patreon-Support-orange)](https://www.patreon.com/c/MocSource)
[![PayPal](https://img.shields.io/badge/PayPal-Tip-blue)](https://www.paypal.com/ncp/payment/SAACTUBPTPBSS)

## Architecture

```
LEGO PAB API (GraphQL)
      ↓  (scraped hourly, 18 locales)
PostgreSQL 18 (app.home.arpa)
      ↓
FastAPI (api.moc-source.com)
      ↓
MOC Source Browser Extension (Chrome/Brave, Manifest V3)
```

## Components

### Browser Extension (`extension/`)

Manifest V3 Chrome/Brave extension. Clicking the toolbar icon opens `index.html` — a full SPA with sidebar navigation (Lists, Projects, Settings, Info).

**Price badges** injected on BrickLink pages:

| Page | Badge location |
|------|----------------|
| BrickLink wanted list (`/v2/wanted/search.page`) | Inside Max Price cell |
| BrickLink buy page modal (`/v2/wanted/buy.page`) | Inside store price cell |
| BrickLink store listing (`store.bricklink.com/#/shop`) | Between price and Add to Cart |
| BrickLink store cart (`store.bricklink.com/#/cart`) | Inside price cell |
| BrickLink catalog item (`/v2/catalog/catalogitem.page`) | Inside "Item Consists Of" column |

Badge types:
- Green **PAB** = Pick a Brick (fast shipping)
- Amber **STD** = Bricks and Pieces (30+ day shipping)
- Grey **PAB: N/A** = not available on LEGO direct

Catalog badge behaviour: shows the price for the selected color tab; if no color is selected (`C=0` or no `C` param in the URL hash) shows the highest available PAB price across all colors with a "max price" label and "N/A" for the color line. Listens to `hashchange` so it updates as the user switches color tabs.

**"Save to MOC Source" button** injected on:
- Wanted list pages — next to the list name (`h2.tight`); deduplicates by name on re-import
- Store cart pages — above the cart items; deduplicates by store name on re-import

**SPA (`index.html` / `index.js`):**

- **Lists view** — three sections (Wanted Lists, BrickLink Carts, Pick-A-Brick Carts); click a name to open detail view; Links/Disclaimer/License cards at the bottom (same cards as Info)
- **Detail view (Wanted List)** — tabs: All / Bestseller / Standard / Not on PAB; toolbar: Remove Selected, → BrickLink / → PAB channel buttons (on All tab shows both), Copy to ▾ / Move to ▾ dropdowns, sort control; columns: Part #, Image, Name, Color, Want / Have (inline editable), Need, Max $, PAB Price, Channel; element ID under part number
- **Detail view (BL Cart)** — same tabs; toolbar: Remove Selected, → BrickLink / → PAB, ☑ BL cheaper / ☑ PAB ≤ store auto-select buttons, Copy to ▾ / Move to ▾; Qty read-only; "↻ Open cart" link; flag/unflag rows for "To Remove" tab
- **Detail view (Pick-A-Brick Cart)** — tabs: All / Bestseller / Standard / BrickLink / To Remove; toolbar: Remove Selected, → BrickLink / → PAB, Copy to ▾ / Move to ▾; Qty read-only
- All detail views: context-aware sort (column-order options per list type; color sorts alphabetically by BrickLink color name); sort resets on list navigation
- **Projects (Cart Jigsaw)** — 4th SPA section; workspace for splitting a wanted-list pool across Pick-A-Brick and BrickLink store carts. See "Projects (Cart Jigsaw)" under What's Working for detail
- **Settings** — PAB region (18 locales), store location filter, buy page filter toggles, wanted list page size, Fill Wanted Qtys condition preference, Project LEGO fee estimate toggle
- **Info** — What's New, Links (Website / Guide / Patreon / PayPal, with a note to support if MOC Source saved you money), Disclaimer, License

**Other features:**
- **Set PAB** button on wanted lists fills max price inputs from PAB prices
- Auto page size 10,000 on wanted list pages
- Buy page: auto-checks "Lots over max price", sets store location filter
- MutationObserver + hashchange for SPA navigation on store.bricklink.com

**Loading for development:**
- Extension folder shared via Samba: `\\dev.home.arpa\moc-extension`
- Load in Brave: `brave://extensions` → Load unpacked → browse to share
- Edits on dev server are live; just reload the extension card

### API (`mocsource/`)

FastAPI app at `https://api.moc-source.com`. Deployed to `/opt/mocsource/app/` on `app.home.arpa`.

Key endpoint: `GET /api/v1/parts/pab/price/{part_no}/{color_id}?locale=en-us`

Response includes:
- `element_id` — LEGO element ID (e.g. 4211063)
- `bl_part_name` — BrickLink part name (e.g. "Plate 1 x 2")
- `bl_color_id` / `bl_color_name` — BrickLink color (e.g. 85 / "Dark Bluish Gray")
- `lego_color_id` / `lego_color_name` — LEGO color (e.g. 199 / "Dark stone grey")
- `price_formatted`, `channel`, `in_stock`, `locale`, `currency_code`

**Element enrichment** — resolves LEGO element_id ↔ BrickLink part_no/color_id for parts the canonical mapping missed. **Runs only at scrape time, for genuinely new elements** (`scripts/scrape_pab.py`): the daily en-us full run diffs incoming element_ids against existing `lego_elements` rows before upserting, then resolves mapping only for the new ones (paced 1s apart), upserting into `bricklink_mappings`. Sends a dedicated enrichment email (resolved vs. unresolved, broken down by source) when new elements were seen, separate from the regular scraper run-report email.

Resolution order per element (mirrors `brick_palettes_generator`'s proven `resolve_mapping()`):
1. **BrickLink's own `item_mapping` endpoint first** (`fetch_bl_item_mapping()`) — `GET /item_mapping/{element_id}` on `api.bricklink.com/api/store/v1`, same OAuth as `bl_client.py`. Authoritative source, tried before anything else.
2. **Rebrickable as fallback only**, when BL's own mapping has nothing for that element.

An earlier version fired a Rebrickable call on every unmapped BL part+color a user's browser happened to render (`mocsource/enrichment.py`, `mocsource/rebrickable_client.py`, triggered from `routers/parts.py`) — that generated far more traffic than Rebrickable's rate limit allows and got the app server's IP temporarily banned. Those per-request trigger points were removed; the modules themselves are still in the repo, unreferenced, in case a limited version of that path comes back later. An even earlier gap — MOC Source skipping BL's own `item_mapping` step entirely and only ever calling Rebrickable — was fixed 2026-07-08, verified live against real elements (one resolved identically to its existing canonical row; another, not yet in `bricklink_mappings`, resolved via BL's own mapping while Rebrickable had nothing for it).

Full deploy: `ansible-playbook site.yml` from `moc-source-infra/` (repos must be siblings on disk).

**Quick deploy caveat:** the rsync-based quick deploy only copies `mocsource/` Python files — it does not update `/opt/mocsource/app/.env`. Changes to `smtp_*` / `report_email` / `SECRET_KEY` etc. require either a full Ansible run or a direct `sed` edit of `.env` on the server followed by `sudo systemctl restart mocsource`.

**Email config** (`mocsource/config.py`): enrichment reports are sent via SMTP. `smtp_from` defaults to `noreply@vaultcrest.com`; `report_email` defaults to `sean.m.sulliv@gmail.com`. The scraper (`scripts/scrape_pab.py`) also sends via the same SMTP settings, reading them from the process environment directly. Note: if `smtp_user` and the routing destination for `report_email` resolve to the same Gmail account, Gmail silently deduplicates the message — use a different destination address.

### Static pages (`static/`)

Served at `/page-name` via FastAPI `FileResponse`. Pattern for new pages:
1. Add `static/page-name.html` (include favicon link tags from existing pages)
2. Add `@app.get("/page-name")` route in `mocsource/main.py`
3. Deploy

Current pages: `/privacy`, `/guide` (branded user guide, matches `index.html`'s theme — installation through Projects/Jigsaw, screenshots, FAQ)

### Database

PostgreSQL 18 on `app.home.arpa`. See [`docs/database-schema.png`](docs/database-schema.png) for the full entity-relationship diagram (11 domain tables, 517K+ rows, solid lines = enforced foreign keys, dashed = app-level joins with no DB constraint) — generated from a live schema query, 2026-07-08.

| Table | Purpose |
|-------|---------|
| `lego_elements` | Element metadata + en-us price (backwards compat) |
| `lego_element_prices` | Multi-region prices, PK (element_id, locale), 18 locales × ~17k entries |
| `bricklink_mappings` | element_id → part_no + color_id + part_name; `source` = "bricklink" or "rebrickable" |
| `colors` | BrickLink color ID → BL name, LEGO ID, LEGO name, hex, Rebrickable ID, `color_type` (BrickLink's own category: Solid/Transparent/Modulex/Pearl/Chrome/Satin/Glitter/Metallic/Milky/Speckle), Rebrickable year range (218 colors — full live BrickLink catalog, not just the original Studio-derived seed) |
| `bl_part_catalog` | Cache for BL catalog data (part_no PK, name, item_type, `category_id`, looked_up_at, `last_used_year`, `year_released`). **`name`/`item_type`/`category_id` now bulk-populated by `scripts/ingest_brickstore_catalog.py` (2026-07-16)**, not live BL API calls — `mold_backfilled_at` is vestigial (no longer gates anything, left in place rather than dropped) |
| `bl_categories` | BrickLink's Parts-catalog category list (`category_id` PK, `category_name`, `parent_id`) — 243 rows, seeded 2026-07-15 via `scripts/seed_bl_categories.py`. Not sourced from `GET /categories` directly — that endpoint returns one flat 561-row list shared across every item type (sets, minifigs, books, etc., not just parts) with no server-side item-type filter (confirmed live, all filter param variants tried return the identical 561). Seeded instead from BrickLink's own Parts-catalog browse page's category dropdown (a web page, not an API endpoint), cross-verified live against `GET /categories` — all 243 (id, name) pairs matched exactly, confirming these IDs share the same `category_id` namespace, just pre-filtered to parts. No FK constraint from `bl_part_catalog.category_id` — a part's category isn't guaranteed to land in this 243-row set (e.g. a category added since this seed) |
| `bricklink_alternates` | Alternate part numbers (e.g. x224 ↔ 41751 ↔ 40995). `source` column (2026-07-16) distinguishes 3 writers, each scoping its own delete+reinsert so none clobber each other: `brickstore_alternate_ids` (each part's own `ALTITEMIDS` field, bulk), `brickstore_mold_group` (derived from BrickLink's "similar molds" relationship pages, bulk), and legacy `NULL`-source rows from the retired live-API mold scraper |
| `brickstore_part_catalog` | Full real BrickLink Parts catalog (part_no PK, category_id, name, raw `alternate_item_ids`, `imported_at`, `inventory_imported_at`) — 95,310 rows, sourced from BrickStore's public GitHub Release (see Scripts below), refreshed weekly. Distinct from `bricklink_mappings` (our own curated, naturally partial subset with LEGO element_id/PAB pricing attached) — this table exists specifically to find gaps in that subset |
| `brickstore_minifig_catalog` | Full real BrickLink Minifigure catalog (minifig_no PK, category_id, name, `imported_at`, `inventory_imported_at`) — 19,039 rows. Minifigs have no LEGO element_id (never sold individually via PAB), so this is a parallel table, not folded into `bricklink_mappings`/`lego_elements` |
| `brickstore_minifig_inventory_items` / `brickstore_part_assembly_inventory_items` | Component part_no/color_id/qty breakdown per minifig / per assembled part (e.g. a bicycle part = frame + 2 tires) — 83,430 / 34,449 rows. References `brickstore_part_catalog`, not `bricklink_mappings` (PAB and BL Price Guide pricing resolve via two independent paths — the latter needs no `bricklink_mappings` coverage at all). Foundation for a future minifig/assembly build-cost calculator (not built yet) |
| `brickstore_part_colors` | Per-part color availability — (part_no, color_id) pairs, sourced from `part_color_codes.xml` (a file missed in the original catalogue of the release, added 2026-07-16). 85,366 rows across 44,851 distinct parts. Full truncate+reload each run (single writer, no `source` tagging needed). Cross-checked against `bricklink_mappings`' LEGO element-id crosswalk in the same source file: ~93% already agree, only 18 rows would add a net-new mapping, so that crosswalk wasn't kept as a separate table — not worth the complexity for the yield |
| `brickstore_mold_relationship_groups` / `_members` | Mold-family cliques (e.g. `4085`/`4085a`/`4085b`/`4085c`/`4085d` all one group) parsed from BrickLink's own "Item Relationships" pages — 1,292 groups (1,066 `similar_mold`, 226 `different_mold`). Kept as real groups, not flattened immediately, so a future UI can show "this part's whole mold family." Only `similar_mold` groups feed `bricklink_alternates` |
| `bl_price_guide_monthly` | BrickLink Price Guide history, sold — PK (part_no, color_id, region, new_or_used, month); avg/min/max/median in cents plus `sample_count` (post-outlier-filter) and `raw_sample_count`. `region` is one of `global` (every seller worldwide, unfiltered — the superset), `north_america` (US/CA/MX), `eu_gb` (27 EU states + UK), or `other` (everything else) — `north_america`+`eu_gb`+`other` mutually exclusively partition `global`, they don't add calls (`scripts/_price_guide_regions.py`, 2026-07-15). One row per (month, region) bucket found in a scrape's `price_detail[]` (outlier-filtered per bucket — MAD/PAB-ratio/max-drop three-tier strategy, `scripts/_outlier_filter.py`). No retention limit — rows accumulate indefinitely for multi-year price-trend history (see What's Next #3) |
| `bl_price_guide_scan_log` | Thin resumability tracker for the price-guide first pass — PK (part_no, color_id), `scanned_at`. One worldwide scrape covers all 4 `bl_price_guide_monthly` regions at once, so no `region` column here. Decoupled from `bl_price_guide_monthly` so a pair with zero BL sales still gets marked done instead of retried forever |
| `bl_price_guide_velocity` | "Quick movers" + price-stability signal (2026-07-16) — one rolled-up row per (part_no, color_id, region, new_or_used), not a monthly time series: `avg_monthly_qty` (summed from outlier-filtered `price_detail[]` quantities) and `price_cv` (population stdev / mean of the pooled, outlier-filtered per-sale prices a single call returns, up to ~6 months at once — a real dispersion measure, not stddev of the monthly averages already in `bl_price_guide_monthly`, which would only show month-to-month drift). Both computed by `scrape_bl_price_guide.py` in-memory from data it already fetches, no new BL calls, refreshed each run rather than tracked as their own trend. Together, meant to drive future re-scrape prioritization: low volume = nothing new to learn regardless of frequency; volatility = how stale a stale price actually is |
| `studio_resolutions` | Studio → BrickLink part resolution |
| `multipacks` | Multipack definitions |
| `failed_studio_mappings` | Parts that couldn't be resolved |

### Scripts (`scripts/`)

| Script | Purpose | Frequency |
|--------|---------|-----------|
| `scrape_pab.py` | Scrapes 18 LEGO locales → `lego_element_prices` | Hourly via systemd timer |
| `seed.py` | Seeds `lego_elements`, `bricklink_mappings` etc. from `canonical_mapping.json` | On data refresh |
| `seed_colors.py` | Seeds `colors` table from `color_database.json` | Once or twice a year |
| `seed_bl_categories.py` | Seeds `bl_categories` table from `cache/bl_part_categories.json` (static, hand-curated — see `bl_categories` above) | Once, or after re-generating the JSON if BrickLink adds new part categories |
| `build_color_database.py` | Builds `color_database.json` from Studio's `CustomColorDefinition.txt` | Once or twice a year |
| `import_rebrickable.py` | Bulk-imports `lego_elements`/`bricklink_mappings` from Rebrickable's `elements.csv`/`parts.csv`, translating part numbers via `_rebrickable_lookup.py` (never writes Rebrickable's own numbering) | Manual, as needed |
| `fix_rebrickable_part_nos.py` | Correction pass for `bricklink_mappings.part_no` rows written with Rebrickable's own numbering instead of a real BrickLink part number (root-caused 2026-07-14) — two-tier resolution (bulk lookup + per-`element_id` fallback), tracked via `rebrickable_part_no_fixes`. Unresolved rows are retry-eligible forever (Rebrickable's own data changes over time), tiered by a `year_from`/`year_to` signal (same bulk endpoint, via `resolve_part_years_bulk()`) into `--year-tier recent` (current year + prior, weekly) and `--year-tier old` (confirmed older, monthly) — see systemd timers below. 137 rows unresolved as of 2026-07-14, all confirmed via the year backfill to be 2026-released parts BrickLink hasn't cataloged yet, not errors | Weekly (recent tier) + monthly (old tier) via systemd timer, plus manual/ad hoc (`--year-tier` omitted processes the full backlog) |
| `apply_manual_overrides.py` | Applies hand-verified corrections/dead-ends from `cache/manual_overrides.yaml` for rows `fix_rebrickable_part_nos.py` couldn't resolve automatically. Ran 2026-07-14 against a 77-row reviewed batch: 3 corrections + 74 confirmed N/A (promotional/exclusive prints BrickLink doesn't catalog separately) | Manual, as needed |
| `backfill_last_used_year.py` | Backfills `bl_part_catalog.last_used_year`/`year_released` from Rebrickable's bulk parts API (`year_from`/`year_to`), joining `bricklink_mappings.element_id` to Rebrickable part numbers via a local `elements.csv` copy — no BrickLink calls, no `lego_sets` dependency, full pass every run (~25 min live) | Monthly via systemd timer |
| `backfill_bricklink_colors.py` | Backfills `colors.color_type` from BrickLink's own `GET /colors` catalog (214 live colors) and inserts any BrickLink colors missing from the table entirely (44 as of 2026-07-14, mostly the "Mx" Modulex sub-brand). Additive only — existing rows only ever get `color_type` written, never `bl_name`/`hex`/`lego_id`/`lego_name`/`rebrickable_id`; inserts use `ON CONFLICT (bl_id) DO NOTHING`. `--dry-run` flag available | Manual, as needed |
| `backfill_rebrickable_colors.py` | Backfills `colors.rebrickable_id` by cross-referencing Rebrickable's `/lego/colors/` API (`external_ids.BrickLink.ext_ids`) against `colors.bl_id`, plus `colors.rebrickable_year_from`/`_to` from Rebrickable's bulk `colors.csv` download (year data isn't exposed by the live REST API at all — confirmed 2026-07-14). Additive only — never writes `bl_id`/`bl_name`/`lego_id`/`lego_name`/`hex`/`color_type`. 213/218 matched as of 2026-07-14 (run after `backfill_bricklink_colors.py` so it also covers the newly-inserted rows); the 5 unmatched are the 4 BrickLink placeholder entries with negative IDs (Magnet, Electric Contact Alloy/Copper, unnamed `-1`) plus `Pearl Sand Purple` (bl_id 243, no Rebrickable BrickLink mapping found). `--dry-run` flag available | Manual, as needed |
| `_brickstore_release.py` | Shared helper (not standalone) — downloads/caches BrickStore's public BrickLink catalog release (`github.com/rgriebl/brickstore-database`, always "latest"), checked via the GitHub API's release metadata (not an HTTP ETag — the download URL redirects through a signed, time-limited Azure blob URL that changes every request). Extracts to `/opt/mocsource/data/brickstore/`. Exposes iterators over the catalog CSV/XML, minifig/assembly inventory XML files, and relationship HTML pages | n/a |
| `ingest_brickstore_catalog.py` | **Replaces the retired `scrape_bl_mold_data.py` entirely** (2026-07-16) — `items/P.xml` → `brickstore_part_catalog` and `bl_part_catalog` (`name`/`item_type`/`category_id`), `items/M.csv` → `brickstore_minifig_catalog`, `part_color_codes.xml` → `brickstore_part_colors` (per-part color availability), each part's own `ALTITEMIDS` field → `bricklink_alternates` (`source='brickstore_alternate_ids'`). All present in BrickStore's bulk download for the entire ~95K-part catalog at once — zero BrickLink API calls, versus the old script's ~42,000 individual paced calls. Known gap: `year_released` isn't in this bulk download (was only a secondary tie-break signal, not the primary `last_used_year` signal, which comes from Rebrickable) — not populated, existing values left untouched | Weekly via systemd timer |
| `analyze_bl_catalog_gaps.py` | Read-only report: `brickstore_part_catalog` parts with no `bricklink_mappings` entry at all — a real, rigorous catalog-gap list (real BL part numbers, not Rebrickable's numbering scheme). Excludes sticker-sheet categories, determined dynamically by category name (not hardcoded) after confirming by hand that a same-named-sounding category, "Stickered Assembly" (710 real decorated parts), must NOT be excluded. Console + `cache/bl_catalog_gaps.csv` + email report (confirmed live 2026-07-16: 95,310 real parts, 4,950 sticker-excluded, 52,528 with no mapping) | Manual, as needed |
| `ingest_brickstore_mold_relationships.py` | Parses BrickLink's "Item Relationships" mold-family pages (`similar_parts_with_similar_molds_*.html`, `similar_parts_with_different_molds_*.html`) into `brickstore_mold_relationship_groups`/`_members` — full truncate+reload each run, self-check (parsed group/member counts vs. the page's own banner and raw link counts) hard-fails before any write on mismatch. Derives pairwise `bricklink_alternates` rows from `similar_mold` groups only (`source='brickstore_mold_group'`) — `different_mold` groups mean "visually similar but NOT interchangeable," deliberately never written there. Confirmed live 2026-07-16: 1,066 similar_mold + 226 different_mold groups, 4,040 derived alternate pairs | Weekly via systemd timer |
| `ingest_brickstore_minifig_inventories.py` | Ingests per-minifig part/color/qty breakdowns (`M/<minifig_no>.xml`) into `brickstore_minifig_inventory_items` — foundation for a future minifig build-cost calculator (not built yet). Resumable via `brickstore_minifig_catalog.inventory_imported_at` (dedicated gate, never reusing `imported_at`). Confirmed live 2026-07-16: 17,106 minifigs have inventory data (of 19,039 cataloged), 83,430 component rows | Weekly via systemd timer |
| `ingest_brickstore_assembly_inventories.py` | Same as above for parts that are themselves assemblies of other parts (`P/<part_no>.xml`, e.g. a bicycle part = frame + 2 tires) — foundation for a future "cheaper as a whole item or as separate parts" comparison (the motivating real case: a store selling a whole bicycle assembly but not its individual tire parts). Resumable via `brickstore_part_catalog.inventory_imported_at`; parts confirmed to have no assembly file are marked done too, so they're never rescanned. Confirmed live 2026-07-16: 10,788 of 95,310 parts are assemblies, 34,449 component rows | Weekly via systemd timer |
| `scrape_bl_price_guide.py` | First pass: BrickLink Price Guide (worldwide, sold, New+Used — no `region` param; confirmed live 2026-07-15 that omitting it returns the same single call's data unfiltered rather than costing extra calls) into `bl_price_guide_monthly`, priority-ordered — PAB/BAP-priced pairs first, then by `bl_part_catalog.last_used_year` descending, then no-year-data pairs last. `price_detail[]` isn't a clean rolling window — the recent `RETENTION_MONTHS` (6) are dense/comprehensive (hundreds of sales/month for common parts), but older than that BrickLink returns sporadic single leftover listings, not real history (confirmed live: part 2357/Black had up to 962 sales in one recent month vs. 1-3/month scattered back to 2018, with whole months missing entirely) — so any month older than 6 full calendar months back (`_outlier_filter.month_floor_minus()`, month-aligned, not a naive day-count window that would truncate the oldest kept month in half) is dropped before bucketing. Within the retained window, rows are bucketed by month, then by seller region into `global`/`north_america`/`eu_gb`/`other` (`scripts/_price_guide_regions.py`), each outlier-filtered independently (`scripts/_outlier_filter.py`) before being written — 4 rows per (pair, month). Resumable via `bl_price_guide_scan_log`. Still 2 BL calls/pair (region bucketing is free — same worldwide data, split client-side). `filter_bucket()` drops non-positive prices before any tier logic (BL's `price_detail[]` includes some genuine $0.0000 line items — fixed 2026-07-15 after two crashes on real data); any other per-bucket failure is caught, skips just that bucket, and is named (`part_no/color_id/new_or_used/region/month`) in the email report instead of killing the run. **Also computes `bl_price_guide_velocity`** (2026-07-16) — `avg_monthly_qty` (summed from the outlier-filtered `price_detail[]` quantities) and `price_cv` (coefficient of variation of the pooled outlier-filtered per-sale prices), per (pair, region, condition), no new calls | Nightly via systemd timer, 03:00 (2,500 pairs = ~5,000 calls/night — the full BrickLink budget, freed up after `scrape_bl_mold_data.py`'s retirement) |

**Color refresh workflow** (after a BrickLink Studio update):
```bash
python scripts/build_color_database.py   # reads ~/.local/share/BrickLink/Studio/CustomColorDefinition.txt
DATABASE_URL=... python scripts/seed_colors.py
```

### PAB Scraper

Loops 18 confirmed LEGO locales, upserts into `lego_element_prices` directly. Two systemd timers on app server:

| Timer | Schedule | What it runs |
|-------|----------|-------------|
| `mocsource-scrape-pab.timer` | Daily at 02:00 | Full 18-locale price + stock update (~18 min) |
| `mocsource-scrape-pab-oos.timer` | Hourly at :30 | OOS-only stock check (3 locales, ~2 min) |

In the 2 AM hour both timers fire, producing two scraper emails ~14 minutes apart — this is expected.

The scraper reads `REPORT_EMAIL` directly from the process environment (not from `Settings`). The quick-deploy rsync only copies Python files; to change `REPORT_EMAIL` or any other `.env` value on the server without a full Ansible run, update `/opt/mocsource/app/.env` directly and restart the service.

Required headers: `Origin: https://www.lego.com`, `x-locale: {locale}`  
Required query fix: no `$sku` variable, use `quantityInSet(sku: null)` hardcoded.

**Confirmed working locales:** `en-us`, `en-gb`, `en-au`, `de-de`, `fr-fr`, `nl-nl`, `en-ca`, `ko-kr`, `pl-pl`, `sv-se`, `en-nz`, `cs-cz`, `da-dk`, `fi-fi`, `nb-no`, `es-es`, `it-it`, `pt-pt`  
Not available: `ja-jp` (no results), `zh-cn` (invalid response)  
Note: `ko-kr` returns only ~1,299 entries vs ~17k for other locales — needs investigation.

## Infrastructure

| Host | IP | Role |
|------|----|------|
| `dev.home.arpa` | 10.242.42.10 | Dev/jumpbox (Fedora 44) |
| `app.home.arpa` | 10.242.42.20 | App server (Rocky Linux 10.2) |
| Technitium DNS | 10.242.42.47 | Internal DNS, home.arpa zone |

Full Ansible provisioning in [`moc-source-infra`](https://github.com/vaultcrest/moc-source-infra).

## What's Working

- [x] Extension badges on all 4 BrickLink page types
- [x] "Save to MOC Source" button on wanted lists and store carts
- [x] SPA extension page — Lists, Settings, Info with sidebar nav
- [x] Wanted list detail view — Want/Have inline editing, Need column, Max $ column, PAB price + channel
- [x] Cart detail view — read-only qty, flag/unflag for removal, "To Remove" tab, "↻ Open cart" link
- [x] Wanted list + cart deduplication by name on re-import
- [x] Color names in detail view — BL name (prominent) + LEGO name in brackets
- [x] Element ID shown under part number; BrickLink part name as display name
- [x] API returns element_id, bl_part_name, bl_color_name, lego_color_name per price lookup
- [x] Colors table (174 BrickLink colors) seeded from Studio's CustomColorDefinition.txt
- [x] Set PAB button on wanted lists
- [x] Buy page auto-filter (store location, Lots over max price, Lots below Wanted qty)
- [x] Multi-region pricing — 18 locales in DB, API `?locale=` param, extension reads pabRegion setting
- [x] Hourly scraper running on app server
- [x] Cloudflare tunnel — `api.moc-source.com` publicly accessible
- [x] Chrome Web Store — v0.4.10 submitted for review; v0.4.8 is the live version until approved (ID: `hoglacgnlglnbpeffbdndnhaokiojigh`)
- [x] BrickLink catalog badge — injected into "Item Consists Of" column; shows color-specific PAB price or max price across all colors (no-color case)
- [x] PAB badges are clickable — clicking any PAB/STD badge opens that element on lego.com Pick a Brick in the user's region (`?query={element_id}`); N/A badges are not linked
- [x] Privacy page at https://api.moc-source.com/privacy
- [x] Extension icon — Vaultcrest brick shield
- [x] AGPL-3.0 licensed, brand assets protected in NOTICE
- [x] Ansible infra covers full server rebuild from scratch
- [x] Rebrickable enrichment — scrape-time only, for genuinely new PAB elements (see Rebrickable enrichment section above); tries alternates from `bricklink_alternates`; upserts `lego_elements` + `bricklink_mappings`; dedicated email report
- [x] BrickLink market price API — `GET_BL_MARKET_PRICE` handler in background.js; OAuth 1.0a signing (HMAC-SHA1) for BL store API; session-scoped price cache (the BL API Credentials settings UI that fed this was removed in v0.4.9 — never used, only added confusion). **Superseded as the plan for BL average pricing**: BL's API only ever returns your own store's data or public Price Guide averages, regardless of whose key — see "BrickLink price column" under What's Next for the actual design
- [x] **Projects (Cart Jigsaw)** — 4th SPA section; Phases 1–5 fully complete:
  - Phase 1: Project CRUD + `chrome.storage.local` schema (`projects`, allocations, estimatedShipping, scratchWantedListId)
  - Phase 2: Setup view — configure wanted lists, BL store carts, LEGO cart, scratch list per project
  - Phase 3: Detail view — wanted list pool (PAB/STD/BL/All tabs), LEGO cart section, per-cart BL sections, scratch space; over-allocation highlighting; part IDs link to BrickLink catalog
  - Phase 4: Allocation moves — checkbox multi-select; move pool→LEGO/BL/scratch, section→section; BL-only parts blocked from LEGO cart; per-cart sort (7 options); unallocate single rows
  - Phase 5: Save actions — LEGO cart diff+replace modal; scratch space save to linked list (or create new); pool save to single wanted list (diff modal) or combined new list (multi-source); pool part exclude/restore; BL store cart writeback: "Save Cart ↓" diffs allocations vs stored cart and stages `pendingBlCartWriteback` in local storage; "Update cart from MOC Source" button on BL cart page shows a single combined modal (QTY CHANGED + REMOVED sections) with one "Apply all changes" button — applies qty changes sequentially via native focus/blur (React 17+ compatible, 600ms between saves to avoid AJAX race), then removals sequentially with auto-confirm via MAIN-world content script; clicks BL's "Update Cart" to commit; updates stored cart snapshot so re-running "Save Cart ↓" produces no diff; live DOM qty read at modal-open time (shows actual cart state, not stale snapshot; skips lots already at target qty; handles inventory changes); `↻ Refresh` button per BL cart section triggers bidirectional allocation sync: caps over-allocated entries to actual cart qty, and fills scratch-space qty back into carts when qty is restored
  - Grand total bar across all carts with per-cart BL subtotals, estimated shipping inputs for TBD stores, and vs-PAB net savings per BL cart and grand total (green/red/grey neutral for $0); savings figures include LEGO shipping tier + $7 service fee (if order < $14) vs store shipping — both per-store and grand total
  - LEGO cart cost summary shows Bestseller (BS) and Standard (STD) subtotals alongside Parts/Shipping/Total
  - Sort controls (6 sort keys × asc/desc) on LEGO cart section and Scratch space (matching BL cart sort)
  - Pool header shows total lots/pieces + allocated vs remaining breakdown; allocated parts hidden from pool by default — "Show N allocated" reveals them dimmed
  - Scroll position preserved when checking boxes
  - Auto-allocation seeds LEGO cart from saved cart parts on first open and reset
  - Phase 6: **⚡ Auto Allocate** — prominent green bar between grand total and pool; reads all BL store cart prices + PAB prices and allocates every pool part to its cheapest source in one click; "Domestic PAB only (skip STD)" checkbox appears automatically if any pool part has a STD/BAP channel entry; LEGO section shows allocations even without a linked LEGO cart (Save/Open buttons hidden until configured)
  - Scratch space definition: strictly zero-allocation parts only (legoQty = 0 AND all storeQty = 0); partially-allocated parts belong to the section they're allocated to, not scratch
- [x] **Fill Wanted Qtys button** (BL store shop page, `store.bricklink.com/#/shop?bOnWantedList=1`): fills qty inputs for cheapest matching lot per part; condition preference New/Used (default Used); cross-condition cheapest-lot: if opposite condition is strictly cheaper, picks it regardless of preference; skips rows already in cart (avoids BL cart error); skips lots priced ≥ PAB (PAB channel only); status line shows filled / already-in-cart / skipped / PAB≤store counts
- [x] **Wanted list qty edit overhaul** — inline Want/Have edit no longer closes immediately; root causes fixed: `mousedown` `preventDefault` stops browser stealing focus before click handler runs; blur-based save replaces stale document click listeners; `pendingQtyEditIdx` carries re-open intent through re-render so clicking a different cell switches to it in one click
- [x] **Color swatches** — BrickLink color ID → hex map; color dot shown on all part listings in detail view
- [x] **v0.4.2 Projects fixes & polish:**
  - Fix: "Return to Pool" now works correctly — removed `pruneStaleAllocations` Pass 2 (auto-fill) which was immediately re-allocating returned parts; `onSectionMove`/`onUnallocate` do direct targeted re-renders instead of calling `refresh()` to avoid re-triggering auto-allocation
  - Feature: "→ LEGO Cart" move button added to each BL store section and scratch space; shows non-PAB warning listing skipped parts if any; LEGO Cart is an allocation bucket (button always shown regardless of whether a LEGO cart list is linked)
  - Fix: vs-PAB savings no longer overstates when BL-only parts are in the same store — `blPabTotal` tracks PAB-comparable store cost separately so comparison is apples-to-apples
  - UI: Channel badges unified to **PAB** (green `#16a34a`) / **STD** (amber `#ca8a04`) across all surfaces — detail view badge, BL store ☑ buttons, LEGO section tabs, pool/project tabs, summary rows, catalog page badge
  - UI: Savings label simplified to **PAB Savings $X.XX** (was verbose "BL $X vs PAB $Y · save $Z")
- [x] **Project LEGO Cart transfer buttons** — "Transfer: PAB / STD / ALL" buttons in the LEGO Cart section header on the project page; STD button only shown when BAP-channel items exist; uses `legoCart.parts` as primary source (same as LEGO Cart list view), falls back to pool allocations when no saved cart is linked
- [x] **LEGO cart transfer reliability fixes** — transfer batches capped at 50 items (was 300); 400ms pause between batches prevents Cloudflare 1015 rate limiting; `MAX_LINE_ITEMS_REACHED` response bails the loop early; CSV download and Transfer All now read correct qty from `p.qty` instead of `(want - have)` formula (which always returned 1 for LEGO cart parts)
- [x] **v0.4.8 — Multi-cart projects** — a project can link multiple Pick-A-Brick carts with roles (Main, Overflow, Bestseller Only, Standard Only, Bestseller Overflow, Standard Overflow); overflow lots route automatically past the 200-lot / 999-qty limits; sort controls (Name, Most Parts, Last Saved, Last Created) on all three Lists sections
- [x] **v0.4.9 — "LEGO Cart(s)" renamed to "Pick-A-Brick Cart(s)"** across the Lists view and Project detail page; unused BrickLink API Credentials settings card removed (was never wired to anything, only added confusion)
- [x] **v0.4.10 — Links card** — Website / Guide / Patreon / PayPal, with a note to support the project if it's saved you money; shown on the Info page and at the bottom of the Parts Lists page (shared via one `footerCardsHtml()` helper)
- [x] **User guide page** — `/guide` on the website; full walkthrough with screenshots, matches the marketing site's branded theme, linked from the extension's Info page and Lists page footer
- [x] **`lego_sets` table** — imported from Rebrickable's `sets.csv` (set_num, name, year, theme_id, num_parts, img_url; 27,318 rows); refreshed via `scripts/import_sets_csv.py`, deployed by the infra playbook to `/opt/mocsource/data/sets.csv` (outside the app sync path) with a monthly systemd timer re-import. Not surfaced anywhere yet — foundation for the "last used" year lookups in the discontinued-part detection idea below
- [x] **v0.4.11/12 — Row-level deal indicator**: on BL price rows, a green (beats channel price, and BL average too once that exists) or amber (beats channel price only) left-stripe + background wash, plus a caption line with the real compared numbers (e.g. "▼ below PAB $0.100"). Channel badge (PAB/STD) is untouched by design — the wash lives on the row so it doesn't overload the badge's existing green=PAB/amber=STD meaning. `bl_avg_price_cents` doesn't exist server-side yet (see #3 below), so only the green "full" state can trigger today. Verified working on the store shop page (`article.component` — needed an extra fix: BrickLink's own `div.buy` panel has an opaque background that was painting over the row wash, now overridden), the store cart page, and the wanted list page. **Known issue**: not yet verified on the buy-page store-selection popup (`div.cart-item-row`) — reported to look broken; likely needs the same kind of panel-background override as the shop-page fix (see What's Next #9)

## What's Next

1. **Import wanted list or cart from XML** — import BrickLink wanted list or cart from exported XML file
2. **Rakuten affiliate** — wrap PAB links in affiliate deeplinks once Projects routes users to lego.com (LEGO merchant ID: 50641, DSA approval required for extensions)
3. **BrickLink average/median price** — **first-pass scrape built and running as of 2026-07-15.** `bl_price_guide_monthly` (sold, New+Used, monthly-bucketed — the real ~6 full calendar months of dense history BrickLink actually has per pair, floored via `month_floor_minus()` to drop sporadic older single-listing noise) is populated by `scripts/scrape_bl_price_guide.py` on a nightly systemd timer (03:00, 2,250 pairs/night), same never-a-live-call-in-the-request-handler pattern as the Rebrickable scrape-time enrichment. Outlier rejection (three-tier MAD/PAB-ratio/max-drop, `scripts/_outlier_filter.py`) is applied per (month, region) bucket before avg/min/max/median are written. No retention limit on rows once written — they're kept indefinitely to build multi-year price-trend history over time as new scrapes add new months; each individual scrape's *input* window is what's floored to ~6 months, not the table's accumulated output.
   - **Future refresh design (not built yet)**: once the first pass has built up a real 6-month baseline, ongoing re-scans should only re-fetch/recompute a rolling ~60-day window and leave older "at rest" months alone, rather than re-processing the full 6-month window (most of which won't have changed) on every run.
   - **Region (redesigned 2026-07-15)**: the scrape fetches worldwide (no `region` param — confirmed live that BrickLink returns the exact same single call's data either way, just unfiltered) and buckets client-side into 4 `bl_price_guide_monthly` rows per (pair, month): `global` (every seller worldwide — the superset, not a peer bucket), and three mutually-exclusive subsets of it: `north_america` (US/CA/MX), `eu_gb` (27 EU states + UK), `other` (everywhere else). Still 2 BL calls/pair — this is free regional granularity, not an extra scrape. A 100-pair live sample found NA is only ~33% of worldwide sold-listing volume for popular parts, so the earlier NA-only design was discarding roughly two-thirds of the real data BrickLink was already handing back in the same call.
   - Scope: the ~81K `(part_no, color_id)` pairs already in `bricklink_mappings`, not BL's full ~125K-combo catalog
   - Priority (this first pass): parts with an active PAB/BAP price first, then everything else by `bl_part_catalog.last_used_year` descending (current year backward), then no-year-data pairs last
   - **Still to do**: join `bl_price_guide_monthly` (latest month) into the existing `/pab/price/{part_no}/{color_id}` response as `bl_avg_price_cents`/`bl_avg_price_formatted` — the extension's client side has been ready for this field since v0.4.11/12; which `region` to surface (`global` is the obvious default) is undecided. An ongoing refresh cadence for already-scraped pairs (re-checking the current still-open month, periodically re-verifying older ones) is also undecided — this first pass only sweeps each pair once. Buckets may get pruned later once it's clear which regions are actually useful to show.
4. **Discontinued part / newer mold detection** — many parts (jumper plates especially) get re-tooled over the years into a new mold under the same base part number with a different letter suffix (e.g. `3684a` "hollow studs" 1978 vs `3684c` "solid studs" 2009). Idea: detect when a part in a user's list is an old, likely-discontinued mold and suggest the newer one, which may currently be on PAB.
   - **Data collection is built and running.** `scripts/ingest_brickstore_catalog.py` (weekly systemd timer, replaced the old live-API `scrape_bl_mold_data.py` entirely on 2026-07-16 — see Scripts above) backfills `name`/`item_type`/`category_id`/`alternate_no` for the **entire** ~95K-part catalog at once from BrickStore's public bulk release, zero BrickLink API calls. `scripts/ingest_brickstore_mold_relationships.py` additionally parses BrickLink's own "similar molds" relationship pages into real mold-family groups (1,066 groups confirmed live 2026-07-16), a materially richer signal than per-part `alternate_no` alone (which is asymmetric — not every sibling cross-references every other one). `scripts/backfill_last_used_year.py` (monthly, full pass, ~25 min live) separately backfills `last_used_year`/`year_released` from Rebrickable's bulk parts API (2026-07-14 — faster and no longer dependent on `lego_sets` coverage, which previously left a gap for series like Collectible Minifigures). First run resolved 41,404/41,473. 67 part_nos (76 elements) still lack `last_used_year` — confirmed all 67 got zero year data from Rebrickable (not a resolution bug); of those, 43 already have a correct BL id (just obscure Rebrickable print variants Rebrickable itself has thin metadata for), 23 were never touched by the pr/pb bug, and exactly 1 (`100588pat0001pr0002`) overlaps with the 221-row unresolved-BL-id list above. **What's still undone is everything below this line** — the actual detection/suggestion logic and its surfacing in the API/UI.
   - **Signal — "last used" year**: sourced from Rebrickable's bulk `/lego/parts/` API (`year_from`/`year_to`), not BL's `/supersets` endpoint — see `backfill_last_used_year.py` above. Faster (bulk vs. one paced BL call per part) and doesn't depend on `lego_sets` coverage.
   - **Mold family**: `bricklink_alternates` (previously stale/sparse — 1,880 rows, left over from the original seed import) is now populated from two independent BrickStore-sourced signals (see Database section above): each part's own `alternate_no`/`ALTITEMIDS` field, and the richer group-based `similar_mold` relationship data in `brickstore_mold_relationship_groups`/`_members` (which also preserves whole-family clique structure, not just pairwise, for a future "show this part's whole mold family" UI).
   - **Exclude `u`-suffixed parts** (e.g. `3684u` "Undetermined Type") from suggestions — BL uses that suffix as a placeholder for "some set contains this base part but the exact mold variant hasn't been identified yet," not a real distinct mold.
   - **Suggested replacement**: for a part flagged likely-discontinued, pick the sibling in its mold family (excluding itself and any `u`-suffixed placeholders) with the newest last-used year that also has a current price — PAB first, BL average (#3 above) as fallback.
   - **Surfacing**: add an optional field to the existing `/pab/price/{part_no}/{color_id}` response, e.g. `mold_succession: {is_likely_discontinued, last_used_year, suggested_part_no, suggested_price_cents, suggested_price_source}` — no new endpoint. Also feeds the #3 cost comparison (old mold's BL average vs new mold's PAB/BL price).
   - **UX**: never auto-swap — surface a suggestion banner ("This mold may be discontinued — newer mold `3684c` available for $X. Update wanted list?") with an explicit confirm step before touching the user's BL wanted list.
   - Needs its own scrape step (per unique `part_no` in `bricklink_mappings`, not per part/color) — shares the same rate-limit pacing concerns as #3 and can likely run as part of the same job.
5. **Cloudflare cache** — cache PAB price responses at the Cloudflare edge to reduce origin load; cache-bust on scraper run
6. **Regional Studio palettes** — `generate_palettes.py` reading from DB per locale
7. **Social sharing** — Canvas-generated PNG in-extension ("I saved $X vs PAB!"); Facebook/Instagram primary targets; $5+ savings threshold; polished Vaultcrest-branded card
8. **Firefox support** — ✅ shipped and live-tested 2026-07-13 in both Brave and Firefox. `extension/master/` holds the real files (all shared `.js`/`.html`/icons, plus `manifest.chrome.json` and `manifest.firefox.json`); `extension/chrome/` and `extension/firefox/` are independent load-unpacked folders, each a **plain-copy snapshot** of the relevant `master/` files — Chrome loads `extension/chrome/`, Firefox loads `extension/firefox/manifest.json` via `about:debugging` → Load Temporary Add-on (or `web-ext run`/`web-ext build` for a real package). Run `extension/sync.sh` after editing anything in `master/` to refresh both copies before reloading either browser.
   - **Two mechanisms were tried and rejected before landing on plain copies, both confirmed live, not theoretical:** (1) **symlinks** — Chrome and Firefox both refused to load `content_scripts` files that were symlinks resolving outside the loaded extension folder (Chromium bug 27185; matching Firefox bugzilla 1420286 describes this as an intentional security measure) — broke badge injection on BrickLink store/wanted-list pages specifically, since those are the pages driven by `content.js`/`content_main.js` as content scripts. (2) **hard links** — survived the browser-side check (no symlink, same inode) but broke on the very next edit: Claude Code's own `Edit` tool writes via temp-file-then-rename, not in-place, which silently detaches the hard link — `master/` got the new content, `chrome/`/`firefox/` silently kept the stale pre-edit version with no error anywhere. Confirmed by direct test in `/tmp` before it could bite a real edit.
   - Firefox manifest differs from Chrome's only in: `background.scripts` (not `service_worker`), and `browser_specific_settings.gecko.id = "moc-source@moc-source.com"` / `strict_min_version: "128.0"` (the version Firefox added support for the `"world": "MAIN"` content-script key used by `content_main.js`).
   - Remaining: AMO (addons.mozilla.org) submission — not done yet, self-distribution signing is fast/automated if not doing a public listing.
   - Aside noticed during the original audit, unrelated to Firefox: `content-lego-spy.js` isn't referenced in `manifest.json`'s `content_scripts` nor injected anywhere found in `content-lego.js` — looks like dead code, worth checking separately.
9. **Fix row-level deal indicator on the buy-page popup** — the green/amber stripe+wash (see v0.4.11/12 above) works on the shop, cart, and wanted-list pages but reportedly looks broken on the buy-page store-selection popup (`div.cart-item-row`, inside `injectBadge()` in `extension/content.js`). The shop page needed a fix for the same class of bug — BrickLink's `div.buy` panel had its own opaque background painting over the row wash — so the popup likely has an analogous panel that needs the same background override. Not yet diagnosed against the live popup DOM.
10. **Minifig/assembly build-cost calculator** — the recurring real case that motivates this: a store selling a whole assembly (e.g. a bicycle) but not its individual components, or vice versa, where splitting/combining could be cheaper. Data foundation shipped 2026-07-16 (`brickstore_minifig_inventory_items`, `brickstore_part_assembly_inventory_items` — see Database section above) but the actual comparison logic and its surfacing in the API/UI are **not built yet**. Would sum PAB (`bricklink_mappings` → `element_id` → `lego_element_prices`, naturally partial) and/or BL Price Guide (`bl_price_guide_monthly`, direct `part_no`/`color_id` join, no `bricklink_mappings` dependency) cost across a minifig's or assembly's components, compared against the whole item's own price.
11. **Minifig BL Price Guide history** — tracking minifig cost over time (not just component cost), the same monthly-bucketed pattern `scrape_bl_price_guide.py` already does for parts, but for minifigs as sellable items themselves (`item_type=M` on BrickLink's Price Guide API). Explicitly deferred (2026-07-16) from the BrickStore ingestion work — this is a live-API/budget change (competes for the shared ~5,000 calls/day budget, freed up somewhat by retiring `scrape_bl_mold_data.py`), not just static-file ingestion, and needs its own sizing discussion before building.

## Related Projects

- [`brick_palettes_generator`](https://github.com/vaultcrest/brick_palettes_generator) — standalone offline LEGO Studio palette generator; upstream source for canonical LEGO↔BrickLink mappings and color database
- [`moc-source-infra`](https://github.com/vaultcrest/moc-source-infra) — Ansible playbooks for full server provisioning
