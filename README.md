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

Manifest V3 Chrome/Brave extension. Clicking the toolbar icon opens `index.html` — a full SPA with sidebar navigation (Lists, Settings, Info).

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

- **Lists view** — three sections (Wanted Lists, BrickLink Carts, LEGO Carts); click a name to open detail view
- **Detail view (Wanted List)** — tabs: All / Bestseller / Standard / Not on PAB; toolbar: Remove Selected, → BrickLink / → PAB channel buttons (on All tab shows both), Copy to ▾ / Move to ▾ dropdowns, sort control; columns: Part #, Image, Name, Color, Want / Have (inline editable), Need, Max $, PAB Price, Channel; element ID under part number
- **Detail view (BL Cart)** — same tabs; toolbar: Remove Selected, → BrickLink / → PAB, ☑ BL cheaper / ☑ PAB ≤ store auto-select buttons, Copy to ▾ / Move to ▾; Qty read-only; "↻ Open cart" link; flag/unflag rows for "To Remove" tab
- **Detail view (LEGO Cart)** — tabs: All / Bestseller / Standard / BrickLink / To Remove; toolbar: Remove Selected, → BrickLink / → PAB, Copy to ▾ / Move to ▾; Qty read-only
- All detail views: context-aware sort (column-order options per list type; color sorts alphabetically by BrickLink color name); sort resets on list navigation
- **Settings** — mirrors popup: PAB region (18 locales), store location filter, buy page filter toggles
- **Info** — donation links, disclaimer, license

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

**Rebrickable enrichment** (`rebrickable_client.py`, `enrichment.py`): When a BL part+color combo is not in the DB, the endpoint returns what it knows (name, color) and schedules a background task. The task cross-references Rebrickable — trying the primary part number then any known alternates from `bricklink_alternates` — to find LEGO element IDs, then upserts them into `lego_elements` + `bricklink_mappings`. The next request for the same part returns the full element ID. BL→RB color mapping is fetched once per process and cached in memory. Sends an enrichment email report if SMTP is configured.

Full deploy: `ansible-playbook site.yml` from `moc-source-infra/` (repos must be siblings on disk).

**Quick deploy caveat:** the rsync-based quick deploy only copies `mocsource/` Python files — it does not update `/opt/mocsource/app/.env`. Changes to `smtp_*` / `report_email` / `SECRET_KEY` etc. require either a full Ansible run or a direct `sed` edit of `.env` on the server followed by `sudo systemctl restart mocsource`.

**Email config** (`mocsource/config.py`): enrichment reports are sent via SMTP. `smtp_from` defaults to `noreply@vaultcrest.com`; `report_email` defaults to `sean.m.sulliv@gmail.com`. The scraper (`scripts/scrape_pab.py`) also sends via the same SMTP settings, reading them from the process environment directly. Note: if `smtp_user` and the routing destination for `report_email` resolve to the same Gmail account, Gmail silently deduplicates the message — use a different destination address.

### Static pages (`static/`)

Served at `/page-name` via FastAPI `FileResponse`. Pattern for new pages:
1. Add `static/page-name.html` (include favicon link tags from existing pages)
2. Add `@app.get("/page-name")` route in `mocsource/main.py`
3. Deploy

Current pages: `/privacy`

### Database

PostgreSQL 18 on `app.home.arpa`.

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
- [x] Chrome Web Store — extension v0.4.1 submitted (ID: `hoglacgnlglnbpeffbdndnhaokiojigh`); v0.4.0 approved
- [x] BrickLink catalog badge — injected into "Item Consists Of" column; shows color-specific PAB price or max price across all colors (no-color case)
- [x] PAB badges are clickable — clicking any PAB/STD badge opens that element on lego.com Pick a Brick in the user's region (`?query={element_id}`); N/A badges are not linked
- [x] Privacy page at https://api.moc-source.com/privacy
- [x] Extension icon — Vaultcrest brick shield
- [x] AGPL-3.0 licensed, brand assets protected in NOTICE
- [x] Ansible infra covers full server rebuild from scratch
- [x] Rebrickable enrichment — on-demand background task fills missing element IDs; tries alternates from `bricklink_alternates`; upserts `lego_elements` + `bricklink_mappings`; email report on enrichment
- [x] BrickLink API key setting — encrypted storage of BL OAuth consumer key/secret/token/token secret in `chrome.storage.local` (AES-GCM via SubtleCrypto; key derived from the extension ID via PBKDF2, never transmitted)
- [x] BrickLink market price API — `GET_BL_MARKET_PRICE` handler in background.js; OAuth 1.0a signing (HMAC-SHA1) for BL store API; session-scoped price cache; foundation for BL price column UI
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

## What's Next

1. **Import wanted list or cart from XML** — import BrickLink wanted list or cart from exported XML file
2. **BrickLink price column** — backend OAuth done (`GET_BL_MARKET_PRICE`); UI display in detail view remaining
3. **Rakuten affiliate** — wrap PAB links in affiliate deeplinks once Projects routes users to lego.com (LEGO merchant ID: 50641, DSA approval required for extensions)
4. **Cloudflare cache** — cache PAB price responses at the Cloudflare edge to reduce origin load; cache-bust on scraper run
5. **Regional Studio palettes** — `generate_palettes.py` reading from DB per locale
6. **Social sharing** — Canvas-generated PNG in-extension ("I saved $X vs PAB!"); Facebook/Instagram primary targets; $5+ savings threshold; polished Vaultcrest-branded card

## Related Projects

- [`brick_palettes_generator`](https://github.com/vaultcrest/brick_palettes_generator) — standalone offline LEGO Studio palette generator; upstream source for canonical LEGO↔BrickLink mappings and color database
- [`moc-source-infra`](https://github.com/vaultcrest/moc-source-infra) — Ansible playbooks for full server provisioning
