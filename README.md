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
| `colors` | BrickLink color ID → BL name, LEGO ID, LEGO name (174 colors) |
| `bl_part_catalog` | Cache for BL catalog API lookups (part_no PK, name, item_type, looked_up_at) |
| `bricklink_alternates` | Alternate part numbers (e.g. x224 ↔ 41751 ↔ 40995); used by Rebrickable enrichment fallback |
| `studio_resolutions` | Studio → BrickLink part resolution |
| `multipacks` | Multipack definitions |
| `failed_studio_mappings` | Parts that couldn't be resolved |

### Scripts (`scripts/`)

| Script | Purpose | Frequency |
|--------|---------|-----------|
| `scrape_pab.py` | Scrapes 18 LEGO locales → `lego_element_prices` | Hourly via systemd timer |
| `seed.py` | Seeds `lego_elements`, `bricklink_mappings` etc. from `canonical_mapping.json` | On data refresh |
| `seed_colors.py` | Seeds `colors` table from `color_database.json` | Once or twice a year |
| `build_color_database.py` | Builds `color_database.json` from Studio's `CustomColorDefinition.txt` | Once or twice a year |

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

## What's Next

1. **Import wanted list or cart from XML** — import BrickLink wanted list or cart from exported XML file
2. **Rakuten affiliate** — wrap PAB links in affiliate deeplinks once Projects routes users to lego.com (LEGO merchant ID: 50641, DSA approval required for extensions)
3. **BrickLink average/median price** — new `bl_price_guide` table (`part_no`, `color_id`, `avg_price_cents`, `min_price_cents` — median too if BL's Price Guide API supports it), populated on a slow, paced schedule (same pattern as the Rebrickable scrape-time enrichment — never a live BL call inside the request handler, that's what got the server temporarily IP-banned by Rebrickable once already). Joined into the existing `/pab/price/{part_no}/{color_id}` response as new `bl_avg_price_cents` / `bl_avg_price_formatted` fields — no new endpoint, no extra client-side network call. Once that's in, compute the % difference between that average/median and the current store's price (already DOM-scraped client-side) and surface it as a comparison alongside the existing PAB badge.
   - Scope: the ~105K `(part_no, color_id)` pairs already in `bricklink_mappings`, not BL's full ~96K-part catalog — BL pricing only matters here in comparison to a PAB price, and that set is already known
   - Priority: parts with an active PAB/BAP price first (the comparison use case); parts with no current PAB price after that — still useful as standalone reference pricing even with nothing to compare against
   - Refresh cadence (proposed): track lookup frequency per part+color, refresh the most-requested pairs weekly, work through the long tail on a slow monthly sweep. BrickLink's actual rate limit isn't verified yet — confirm it before scheduling, given what happened with Rebrickable's
4. **Discontinued part / newer mold detection** — many parts (jumper plates especially) get re-tooled over the years into a new mold under the same base part number with a different letter suffix (e.g. `3684a` "hollow studs" 1978 vs `3684c` "solid studs" 2009). Idea: detect when a part in a user's list is an old, likely-discontinued mold and suggest the newer one, which may currently be on PAB.
   - **Signal — "last used" year**: BL's `GET /items/PART/{no}/supersets` returns every set containing that part (grouped by color), but not the sets' years. Resolve each set's year via the local `lego_sets` table (populated from `sets.csv`, see above) instead of an extra BL call per set — `max(year)` across all supersets = that part's last-used year. This is the same insight that motivated importing `sets.csv` in the first place.
   - **Mold family**: BL's catalog endpoint already returns `alternate_no` (comma-separated sibling part numbers) — currently fetched but discarded in `bl_client.fetch_bl_part()`. The existing `bricklink_alternates` table is stale/sparse (1,880 rows, left over from the original seed import) and needs to be refreshed from live BL data, not trusted as-is.
   - **Exclude `u`-suffixed parts** (e.g. `3684u` "Undetermined Type") from suggestions — BL uses that suffix as a placeholder for "some set contains this base part but the exact mold variant hasn't been identified yet," not a real distinct mold.
   - **Suggested replacement**: for a part flagged likely-discontinued, pick the sibling in its mold family (excluding itself and any `u`-suffixed placeholders) with the newest last-used year that also has a current price — PAB first, BL average (#3 above) as fallback.
   - **Surfacing**: add an optional field to the existing `/pab/price/{part_no}/{color_id}` response, e.g. `mold_succession: {is_likely_discontinued, last_used_year, suggested_part_no, suggested_price_cents, suggested_price_source}` — no new endpoint. Also feeds the #3 cost comparison (old mold's BL average vs new mold's PAB/BL price).
   - **UX**: never auto-swap — surface a suggestion banner ("This mold may be discontinued — newer mold `3684c` available for $X. Update wanted list?") with an explicit confirm step before touching the user's BL wanted list.
   - Needs its own scrape step (per unique `part_no` in `bricklink_mappings`, not per part/color) — shares the same rate-limit pacing concerns as #3 and can likely run as part of the same job.
5. **Cloudflare cache** — cache PAB price responses at the Cloudflare edge to reduce origin load; cache-bust on scraper run
6. **Regional Studio palettes** — `generate_palettes.py` reading from DB per locale
7. **Social sharing** — Canvas-generated PNG in-extension ("I saved $X vs PAB!"); Facebook/Instagram primary targets; $5+ savings threshold; polished Vaultcrest-branded card

## Related Projects

- [`brick_palettes_generator`](https://github.com/vaultcrest/brick_palettes_generator) — standalone offline LEGO Studio palette generator; upstream source for canonical LEGO↔BrickLink mappings and color database
- [`moc-source-infra`](https://github.com/vaultcrest/moc-source-infra) — Ansible playbooks for full server provisioning
