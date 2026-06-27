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

Badge types:
- Green **PAB** = Pick a Brick (fast shipping)
- Amber **STD** = Bricks and Pieces (30+ day shipping)
- Grey **PAB: N/A** = not available on LEGO direct

**"Save to MOC Source" button** injected on:
- Wanted list pages — next to the list name (`h2.tight`); deduplicates by name on re-import
- Store cart pages — above the cart items; deduplicates by store name on re-import

**SPA (`index.html` / `index.js`):**

- **Lists view** — two sections (Wanted Lists, Carts); click a name to open detail view
- **Detail view (Wanted List)** — tabs: All / PAB / Standard / Not on PAB; columns: Part #, Image, Name (BrickLink name), Color (BL name + LEGO name), Want / Have (inline editable), Need, Max $, PAB Price, Channel; element ID shown under part number
- **Detail view (Cart)** — same tabs + "To Remove" tab; Qty is read-only (cart is source of truth); flag/unflag rows for removal; "↻ Open cart" link to reload from BrickLink
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

Quick deploy (app code only):
```bash
rsync -av mocsource/ excalibrax@app.home.arpa:/tmp/mocsource_deploy/
ssh app.home.arpa "sudo cp -r /tmp/mocsource_deploy/. /opt/mocsource/app/mocsource/ && sudo systemctl restart mocsource"
```

Full deploy: `ansible-playbook site.yml` from `moc-source-infra/` (repos must be siblings on disk).

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
| `bricklink_mappings` | element_id → part_no + color_id + part_name |
| `colors` | BrickLink color ID → BL name, LEGO ID, LEGO name (174 colors) |
| `bricklink_alternates` | Alternate part numbers |
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

Loops 18 confirmed LEGO locales, upserts into `lego_element_prices` directly. Runs hourly via `mocsource-scrape-pab.timer` on app server.

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
- [x] Chrome Web Store — extension published (ID: `hoglacgnlglnbpeffbdndnhaokiojigh`)
- [x] Privacy page at https://api.moc-source.com/privacy
- [x] AGPL-3.0 licensed, brand assets protected in NOTICE
- [x] Ansible infra covers full server rebuild from scratch

## What's Next

1. **Cart split** — split wanted list into PAB vs BrickLink buy recommendations (killer feature)
2. **Rakuten affiliate** — wrap PAB links in affiliate deeplinks once cart split routes users to lego.com (LEGO merchant ID: 50641, DSA approval required for extensions)
3. **BrickLink price column** — needs BrickLink API integration
4. **Color swatches** — BrickLink color ID → hex map for color dot in detail view
5. **ko-kr** — investigate why only 1,299 entries vs ~17k for other locales
6. **Regional Studio palettes** — `generate_palettes.py` reading from DB per locale
7. **Extension icon** — deferred

## Related Projects

- [`brick_palettes_generator`](https://github.com/vaultcrest/brick_palettes_generator) — standalone offline LEGO Studio palette generator; upstream source for canonical LEGO↔BrickLink mappings and color database
- [`moc-source-infra`](https://github.com/vaultcrest/moc-source-infra) — Ansible playbooks for full server provisioning
