# Changelog

All notable changes to MOC Source are documented here.

## [Unreleased]

### Extension
- Fixed (actual root cause): every Wanted List / Cart detail page has been permanently unable to load PAB prices since v0.4.17. That release's Project-detail listener-stacking fix accidentally also touched `attachDetailListeners` (a completely unrelated function used by all list/cart detail pages), converting a working `content.addEventListener("click", ...)` call into `addClick(...)` — but `addClick` is only defined as a local helper inside `renderProjectDetail`, not here. Calling it threw `ReferenceError: addClick is not defined` on every single page visit, which aborted `renderDetailView()` — and since that call happens *before* `renderListDetail`'s PAB-price fetch loop, the fetch loop never ran at all, leaving every row frozen at its initial "…" placeholder. (Confirmed via `git log -p` showing the accidental find-replace, and by reproducing the exact call chain in Node to verify the fetch never fires once the throw happens.) Gave `attachDetailListeners` its own cleanup-tracked `addListener`/`addClick` helpers (same pattern as `renderProjectDetail`'s, since this function has the identical repeated-call-on-persistent-container structure) and converted its other two direct `content.addEventListener` calls to use them too, so they stop stacking across re-renders as well.
- Hardened (real but secondary): `renderListDetail` and the Project pool section each fetch every part's PAB price in parallel via `Promise.all`, which fails the whole batch if even one `chrome.runtime.sendMessage` rejects (e.g. a transient MV3 message-channel hiccup). Switched to `Promise.allSettled` so one bad fetch can't block the rest of a page's prices from rendering. This wasn't the cause of the "stuck at …" reports above (the `addClick` crash was), but it's a legitimate robustness gap worth closing regardless.
- Changed: standardized price rounding across the extension. User-facing prices now always show exactly 2 decimals — the BrickLink-page "below PAB"/"BL avg" caption dropped from 3 decimals, and the Cart Jigsaw SPA's Store Price columns (which previously showed BrickLink's raw scraped text verbatim, e.g. `$0.0812US`) now parse and format to `$X.XX`. Cart cost calculations still sum true, unrounded per-item prices as before (no change there — they already did this correctly) but the final "what you'll pay" totals (LEGO cart total, BrickLink cart total incl. shipping, Project Grand Total) now round *up* to the next cent instead of to the nearest cent, via a new `ceilToCents()` helper, so a total is never shown lower than what the real sum comes to. Per-channel subtotals and savings/delta figures (PAB Savings, "switch to save ~$X", Store Savings Scanner) are unaffected — still plain nearest-cent display, since they're informational breakdowns/estimates, not a standalone amount owed. Also widened `content.js`'s `scrapeRowPrice()` regex, which previously truncated BrickLink's own displayed price to exactly 2 decimals before using it in the "beats PAB" comparison — bulk lots with sub-cent per-unit pricing were being compared against a pre-truncated number; now compares against BrickLink's actual full precision.
- Fixed: an unrelated crash found while touching this code — transferring a part from a LEGO cart to a Wanted List stored its PAB price as a string into the new part's `maxPrice` field, but the Wanted List page later calls `.toFixed(2)` on `maxPrice` assuming a Number, throwing a `TypeError`. That PAB price was never a meaningful "max price" for a Wanted List entry in the first place, so the field is now omitted entirely on this transfer path instead of being reformatted.
- Fixed (data-integrity bug, not just display): `content.js`'s `collectCartParts()` scrapes the full text of BrickLink's own price cell into `storePrice` for each cart lot, but only stripped our own `.moc-source-badge` element first — not the `.moc-source-verdict-caption` element (the "▼ below PAB $X and BL avg $X" text) that `injectBadge()` also appends into that same cell. Any row that already had our comparison caption showing on the page when a cart was saved/imported got that caption's text scraped straight into `storePrice`, corrupting it. This reached more than display: `parseStorePrice()` (which strips non-digit characters then parses a float) fed the corrupted string into Auto Allocate's BL-vs-PAB cutover decision, the "select cheaper" buttons and Savings Scanner's bulk move/remove actions, and — most seriously — the live BrickLink cart write-back (`showBlCartSave`/`applyBlCartWriteback`), which re-finds a cart row by **exact string equality** against the stored value; a mismatch there silently no-ops a quantity change or removal while the UI still reports success. Added the missing strip to all three affected sites (`collectCartParts`, `applyBlCartWriteback`'s `findArticle`, and `scrapeRowPrice`, which has the same gap via a different helper feeding "Fill Wanted Qtys"). This fix is forward-only — data already saved before this fix stays corrupted until you click "↻ Refresh" on that cart; Auto Allocate only runs once per project, so re-run it manually afterward if you suspect a past allocation used bad data.
- Added: a real "X% below/above PAB" indicator on the Cart Jigsaw Store Price columns (`buildAllocRows`, `buildCartRow`), computed fresh at render time from the already-known store/PAB prices via a new `pctVsPab()` helper — a deliberate, always-correct replacement for the percentage that used to appear only as an accidental side effect of the leak bug above (that was BrickLink's own bulk-discount indicator, incidentally scraped into the same cell, not something we computed).
- Hardened (BL cart write-back): two more issues found by inspecting real saved data. First, BrickLink's own price cell can independently corrupt `storePrice` on discounted lots even after the caption-leak fix above — its markup wraps the current price, the struck-through "was" price, and the discount % all in the same `div.price-col`. `collectCartParts()` and `findArticle()` (in `applyBlCartWriteback`) now read the `.native-price` element directly instead of the whole cell's text, so only the real live price is ever captured (confirmed against real BrickLink cart-row markup; falls back to the old strip-and-read approach if `.native-price` isn't present). Second, `findArticle()` — the function that re-locates a cart row on the live BrickLink page to apply a saved quantity change or removal — required an *exact string match* on price to succeed at all, which is why any price drift silently no-opped a change while the UI still reported success. It now matches primarily on `partNo`+`colorId` (usually unambiguous on its own), falls back to lot condition (New/Used, already captured but never previously used for this), and only uses price as a last-resort tiebreaker when still ambiguous — never a hard requirement. `showBlCartSave` now threads `condition` through the write-back payload to support this.

## [0.4.17] — 2026-07-16

### Extension
- Fixed: clicks/saves on the Project detail page (Cart Jigsaw) required closing a dialog 3x, and saving Scratch Space popped up 3 list pickers — `renderProjectDetail(id, content)` attaches 4 event listeners (3 `click`, 1 `change`) directly to the persistent `content` container, but the function gets called repeatedly on that same node across a session (after saves, back-button navigation, etc. — at least 4 call sites). `addEventListener` doesn't dedupe fresh closures, so each re-render stacked another full set of listeners on top of every prior render's, and a single click fired once per render the view had gone through. Added a cleanup-then-reattach pattern (`content._projectDetailCleanup()` runs at the top of every call, tearing down the previous render's listeners before attaching new ones) so exactly one set is ever active. `renderProjectSetup` was checked too and doesn't have this bug — its listeners are all on child elements replaced fresh via `innerHTML` each render, not on the persistent container.

## [0.4.16] — 2026-07-16

### Extension
- Fixed: Project pool aggregation (`index.js`, the Cart Jigsaw feature) counted a wanted list's full "Want" quantity toward the pool, ignoring "Have" entirely — a part with Want 4 / Have 2 showed as needing 4, not 2, so parts a user already partially owned inflated the pool total and Auto Allocate would try to source more than was actually needed. Every other quantity consumer in this codebase already used `Math.max(0, want - have)` (Copy to BL cart, Copy to PAB, sort-by-need, etc.) — the pool was the one place that didn't. Now uses the same formula in both pool aggregation and the "newly-added BL cart" allocation-capping path (`renderProjectSetup`'s save handler). Parts that are 100% already owned (need = 0) no longer show up in the pool at all — nothing left to source for them.

## [0.4.15] — 2026-07-16

### Extension
- Fixed: newly-added Pick-A-Brick cart rows in Project Config defaulted to "Overflow" role, not "Main" — the "Add Cart" button hardcoded `role: "overflow"` for every blank row it appended (`buildLgRow()`'s own default param of `"overflow"` was actually dead code, since both call sites already passed a role explicitly). Now defaults new rows to "Main," except when a Main row already exists in the editor (then falls back to "Overflow"), since only one cart can hold the Main role — the existing demote-on-change logic elsewhere only fires from a real user interaction, not from a pre-set default value, so an unconditional "Main" default would have let two rows show "Main" at once until the user touched one.

## [0.4.14] — 2026-07-16

### Extension
- Disabled the buy-page "Store location" auto-select (`setupBuyPage()` in `content.js`) — it was clicking the location radio buttons and dispatching change events on the region/country `<select>` while BrickLink's own React app was still rendering, and on large "Buy All" pages (many lots) that render window is long enough for the two to visibly fight each other. The "Lots over max price"/"Lots below Wanted qty" auto-check filters are untouched and still work — only the store-location portion of the function is disabled (`storeLocation` value is read but intentionally unused).
- Hid the now-inert "Store location" dropdown in both settings surfaces (`popup.html` and the SPA settings page in `index.js`, `display:none`) rather than removing it — the underlying setting/markup stays intact for a quick re-enable once the render-timing issue is sorted out.

## [Backend] — 2026-07-16

### BrickStore public catalog ingestion — mold gaps, mold relationships, minifig + assembly tracking; retires the live mold scraper
- BrickLink's own bulk catalog-download feature requires an authenticated, partner-registered session we don't have. Found that BrickStore (a GPL-3.0 open-source BrickLink inventory tool) already solves this: its maintainer publishes the raw downloaded bulk files as a public, unauthenticated GitHub Release (`github.com/rgriebl/brickstore-database`), refreshed regularly
- New tables (Alembic `b0c1d2e3`, `c1d2e3f4`): `brickstore_part_catalog` (95,310 rows — the full real BrickLink Parts catalog), `brickstore_minifig_catalog` (19,039 rows — full Minifigure catalog; minifigs get their own PK/table since they have no LEGO element_id, never sold individually via PAB), `brickstore_minifig_inventory_items`/`brickstore_part_assembly_inventory_items` (83,430 / 34,449 component rows — part_no/color_id/qty breakdowns, referencing `brickstore_part_catalog` rather than `bricklink_mappings` since PAB and BL Price Guide pricing resolve via two independent paths with different coverage), `brickstore_mold_relationship_groups`/`_members` (1,292 real mold-family cliques parsed from BrickLink's own "Item Relationships" pages, e.g. `4085`/`4085a`/`4085b`/`4085c`/`4085d`). `bricklink_alternates` gains `source`/`updated_at` so its now-3 writers (legacy live-API rows, `ALTITEMIDS`-derived, mold-relationship-group-derived) scope their own delete+reinsert without clobbering each other
- New `scripts/_brickstore_release.py` (shared download/cache helper, GitHub API-based change detection since the download URL redirects through a signed time-limited blob URL), `ingest_brickstore_catalog.py`, `ingest_brickstore_mold_relationships.py` (BeautifulSoup HTML parser with a hard self-check — parsed group/member counts must match the page's own banner and raw link counts before any DB write), `ingest_brickstore_minifig_inventories.py`, `ingest_brickstore_assembly_inventories.py` — all confirmed against real downloaded data, see counts above
- New `scripts/analyze_bl_catalog_gaps.py` — rigorous BL catalog gap analysis (real BL part numbers, not Rebrickable's numbering scheme like an earlier crude comparison this session used): 52,528 parts confirmed live with no `bricklink_mappings` entry at all, after excluding sticker-sheet categories (dynamically determined by name, not hardcoded — confirmed by hand that "Stickered Assembly," a real decorated-part category, must not be excluded despite the name)
- **Retires `scripts/scrape_bl_mold_data.py` entirely** — `name`/`item_type`/`category_id`/`alternate_no` are all present in the bulk download for the whole catalog at once, replacing ~42,000 individual paced live BrickLink API calls with zero. Known accepted tradeoff: `year_released` isn't in the bulk download (was only ever a secondary mold-succession tie-break signal) and is no longer populated
- New `bl_price_guide_velocity` table (Alembic `d2e3f4a5`) — "quick movers" signal, one rolled-up average-monthly-units-sold figure per (part_no, color_id, region, new_or_used), computed by `scrape_bl_price_guide.py` in-memory from the same outlier-filtered `price_detail[]` quantities it already fetches (no new BL calls)
- `moc-source-infra`: removed the old `mocsource-scrape-bl-mold.service`/`.timer`; new `mocsource-ingest-brickstore.service`/`.timer` (weekly, Sunday 04:30, always "latest" release — no BrickLink API calls at all, so no rate-limit pacing concerns)
- Explicitly deferred: minifig BL Price Guide history (live-API/budget change, needs its own sizing discussion) and the actual minifig/assembly build-cost calculator feature (this pass only ingests the data it would need)
- New dependency: `beautifulsoup4`
- **Addendum, same day**: the original release inventory missed `part_color_codes.xml` — added `brickstore_part_colors` (Alembic `e3f4a5b6`, part_no/color_id pairs, 85,366 rows across 44,851 parts, full truncate+reload) to `ingest_brickstore_catalog.py`, confirmed correct against real data (part `3001`, the 2x4 brick, lands 75 known colors). The same file also carries a LEGO element-id crosswalk per part+color, cross-checked against `bricklink_mappings`: ~93% already agree and only 18 rows would add a net-new mapping, so that crosswalk wasn't kept as its own table
- **Addendum, same day**: bumped `scrape_bl_price_guide.py`'s nightly batch size from 2,250 to 2,500 pairs (4,500 → 5,000 calls/night), using the headroom freed by `scrape_bl_mold_data.py`'s retirement — the full ~5,000/day BrickLink budget (an unwritten limit, treated as a ceiling)
- **Addendum, same day**: added `price_cv` to `bl_price_guide_velocity` (Alembic `f4a5b6c7`) — coefficient of variation of the pooled, outlier-filtered per-sale prices a single `scrape_bl_price_guide.py` call returns (up to ~6 months at once), not stddev of the monthly averages already in `bl_price_guide_monthly` (that would only capture month-to-month drift, not real intra-month price spread). Meant to pair with `avg_monthly_qty` for future re-scrape prioritization: volume gates whether there's anything new to learn at all, volatility indicates how urgently a stale price actually needs rechecking. Confirmed live on part 3001/Black: CV 0.22–0.35 across regions, Used consistently more volatile than New

### PAB scraper — targeted Cloudflare cache purge, replacing blanket purge_everything
- `scripts/scrape_pab.py`'s `purge_cf_cache()` previously fired `purge_everything: true` unconditionally after every run (full-price and hourly OOS both) — found while investigating the dormant Cloudflare-edge-caching roadmap item that this had been quietly running successfully in production the whole time (confirmed via journal: succeeding every ~25-30 min), but as a blanket purge it would undercut the point of edge caching once actually enabled, since it wipes the whole zone regardless of whether any specific part changed
- `write_prices()` now diffs each incoming row's `price_cents`/`in_stock` against what's already in `lego_element_prices` before upserting and returns the set of `element_id`s that actually changed; OOS mode's sibling-locale propagation UPDATE gets the same pre-check (UPDATE behavior itself unchanged — still refreshes `updated_at` on every sibling row)
- New `pab_purge_urls()` resolves changed `element_id`s to real `part_no`/`color_id` via `bricklink_mappings` and builds the exact set of cached URLs to invalidate (`/pab/price/{part_no}/{color_id}`, `/pab/prices/{part_no}`, `/element/{element_id}/price`); `purge_cf_cache()` now purges only those, batched 30/request (Cloudflare's per-request limit), falling back to one `purge_everything` call above `CF_PURGE_EVERYTHING_THRESHOLD` (150 changed elements) where per-URL purging would cost more round-trips than it saves
- Verified: `write_prices()`/`pab_purge_urls()` unit-tested against real production data via a controlled before/after comparison (simulated price change, stock flip, and no-op row all classified correctly; purge URLs correctly resolved real part_no/color_id). Full live OOS run completed clean with the new code path (35,996 rows, 4m53s, matches prior baseline, exit 0)
- **Found and fixed same day**: live testing of `/pab/price/{part_no}/{color_id}` found `cf-cache-status: MISS` and a `, no-store` appended to the `Cache-Control` header the client receives — confirmed the raw origin response (uvicorn direct, bypassing the Cloudflare Tunnel) is clean with no `no-store`, so Cloudflare's edge was adding it, because the zone had no Cache Rule marking these dynamic API paths "Eligible for Cache" (not cached by default regardless of origin `Cache-Control`). Fixed via a new Ansible task (`moc-source-infra/roles/cloudflare_tunnel/tasks/main.yml`, `delegate_to: localhost`, `ansible.builtin.uri` PUT to Cloudflare's Ruleset API `http_request_cache_settings` phase entrypoint) that marks `/api/v1/parts/pab*` and `/api/v1/parts/element*` on `api.moc-source.com` cache-eligible, applied idempotently on every deploy. Required bumping the existing `cloudflare_api_token`'s scope to add `Cache Rules:Edit` (alongside its existing `DNS:Edit`/`Cache Purge:Purge`). Verified live post-deploy: first request `MISS`, immediate second request `HIT`, `age: 0`, `no-store` gone entirely

## [Backend] — 2026-07-15

### BrickLink Price Guide — first pass (`bl_price_guide_monthly`, `bl_price_guide_scan_log`, `scripts/scrape_bl_price_guide.py`)
- New tables (Alembic `e7f8a9b0`): `bl_price_guide_monthly` (part_no, color_id, region, new_or_used, month → avg/min/max/median price cents + sample_count/raw_sample_count, PK includes month) and `bl_price_guide_scan_log` (thin resumability tracker, PK part_no/color_id/region) — additive only
- New `BLClient.fetch_price_guide()` in `scripts/_bricklink_lookup.py` — `GET /items/PART/{no}/price?guide_type=sold&region=north_america`, North America only for now (region is a PK column, not hardcoded, so other regions can be added later without a schema change) — **superseded same day, see the worldwide + 4-region bucketing entry below**
- New `scripts/_outlier_filter.py` — three-tier outlier rejection (MAD-based modified z-score on log(price) for n≥8, ratio bound against PAB price for smaller samples with a PAB anchor, drop-the-implausible-max otherwise), formalized against BL parts 6020/27448 evidence. Unit-verified: a simulated $3,072 laundering sale among ~900 real-range ($0.02–0.45) sales is correctly rejected, average drops from would-be-distorted to $0.24/max $0.45
- New `scripts/scrape_bl_price_guide.py` — priority-ordered first pass over the ~81K known `(part_no, color_id)` pairs in `bricklink_mappings`: PAB/BAP-priced pairs first, then everything else by `bl_part_catalog.last_used_year` descending (current year backward), then no-year-data pairs last. Each call returns up to ~6 months of real sold-listing history (`price_detail[]`), bucketed by month and outlier-filtered before being written — a single pass backfills several months of history per pair, not just a current snapshot. Raw `price_detail` rows are never persisted, only the derived monthly summary. **No retention limit** — supersedes the earlier-drafted 12-month rolling design; history accumulates indefinitely for multi-year price-trend charts
- `scrape_bl_mold_data.py` throttled from 5,000 to 500 calls/night (`moc-source-infra`) to free up BrickLink's shared ~5,000 calls/day budget for the new scraper (~4,500 calls/night, 2,250 pairs), since mold-backfill's output only feeds the not-yet-built discontinued-mold feature — nothing live consumes it yet, unlike price-guide data. New `mocsource-scrape-bl-price-guide.service/.timer` (daily 03:00)

### BL Price Guide — zero-price crash fix + per-bucket crash reporting
- Both runs since initial deploy (a manual test + the first real 03:00 timer run) crashed with `ValueError: math domain error` — BrickLink's `price_detail[]` includes some genuine $0.0000 line items (confirmed real example: part `22885`, Light Bluish Gray, Used, a 129-qty sale recorded at exactly $0.0000/unit on 2026-06-09 — corroborated by BrickLink's own `min_price` aggregate field for that combo, not a rounding artifact; BL reports `unit_price` to 4 decimal places, e.g. `0.0806`, so a true sub-cent price would show as `0.0050`, not `0.0000`) and the MAD tier's `math.log(cents)` has no domain for 0
- `_outlier_filter.py`'s `filter_bucket()` now drops non-positive prices before any tier logic runs
- `scrape_bl_price_guide.py`'s `process_pair()` now catches any per-month-bucket exception (not just this one), skips just that bucket instead of aborting the whole batch, and surfaces `part_no/color_id/new_or_used/month` + error in the email report's new "Errors this run" section
- Verified against real production data (clean 20-pair batch, zero errors) and deployed same day

### Disk usage monitor (`moc-source-infra`, `roles/disk_monitor/`)
- New role: checks `/` on app.home.arpa 4x/day (00:00/06:00/12:00/18:00), emails an alert via the app's existing SMTP settings once usage hits 75% — no new secret needed (reuses `SMTP_HOST`/`SMTP_USER`/`SMTP_PASSWORD`/`SMTP_FROM`/`REPORT_EMAIL` from `/opt/mocsource/app/.env`)
- Added specifically because `bl_price_guide_monthly` has no retention limit by design — this is the early-warning trip wire in case that decision needs revisiting later

### BL Price Guide — worldwide + 4-region bucketing, 6-month retention floor (Alembic `f8a9b0c1`)
- `fetch_price_guide()` no longer sends `region=north_america` — a live test confirmed BrickLink returns the identical single call's data either way, just unfiltered, so the NA-only design was silently discarding real data BrickLink had already handed back for free. A 100-pair live sample found NA-only volume was only ~33% of the true worldwide sold-listing volume for popular parts
- New `scripts/_price_guide_regions.py` buckets each row by `seller_country_code` into 4 groups per (pair, month): `global` (every row, unfiltered — the superset, not a peer bucket), and three mutually-exclusive subsets of it — `north_america` (US/CA/MX), `eu_gb` (27 EU member states + UK), `other` (everything else). 4 `bl_price_guide_monthly` rows per (pair, kept month) now instead of 1, still 2 BL calls/pair
- New `month_floor_minus()` in `_outlier_filter.py` floors each scrape's input to the most recent `RETENTION_MONTHS` (6) full calendar months — BrickLink's `price_detail[]` is dense/reliable for ~6-7 recent months but sporadic single leftover listings older than that (confirmed live: part 2357/Black had up to 962 sales in one recent month vs. 1-3/month scattered back to 2018, whole months like Dec 2025 missing entirely). Month-aligned, not a naive day-count window, so the oldest kept month isn't truncated in half. This floors the scrape's *input* only — `bl_price_guide_monthly` itself still has no retention limit and accumulates indefinitely
- `bl_price_guide_scan_log`'s PK drops `region` (one worldwide scrape now covers all 4 buckets at once, so region is no longer part of its identity) — migration truncates `bl_price_guide_monthly` and resets `scan_log` since only ~1,250/80,894 pairs had been scraped under the old NA-only scheme, simpler than backfilling `eu_gb`/`other` for that small slice in place

### `bl_categories` + `bl_part_catalog.category_id` (Alembic `a9b0c1d2`)
- BrickLink's `GET /categories` returns one flat 561-row list shared across every item type with no server-side item-type filter (confirmed live — `type=P`/`item_type=PART`/`category_type=P` all return the identical 561 rows). New `bl_categories` table seeded instead from BrickLink's own Parts-catalog browse page's category dropdown (`cache/bl_part_categories.json`, 243 rows, hand-curated — not an API response) via new `scripts/seed_bl_categories.py`; cross-verified live against `GET /categories` — all 243 (id, name) pairs matched exactly, confirming it's a clean parts-only subset of the same `category_id` namespace
- `category_id` was already present in `fetch_item()`'s response (parsed for every part by `scrape_bl_mold_data.py`) but discarded — now captured into `bl_part_catalog.category_id` at no extra API cost. Not FK-constrained to `bl_categories` since a part's category isn't guaranteed to land in that 243-row seed. Not consumed by anything live yet — foundation for future category-scoped filtering

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
