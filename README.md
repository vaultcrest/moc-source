# MOC Source

LEGO acquisition planning tool. Overlays PAB (Pick a Brick) and BAP (Bricks and Pieces) prices from LEGO direct onto BrickLink pages so you can compare store prices vs. buying direct.

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

Manifest V3 Chrome/Brave extension. Injects PAB price badges on:

| Page | Badge location |
|------|----------------|
| BrickLink wanted list (`/v2/wanted/search.page`) | Inside Max Price cell |
| BrickLink buy page modal (`/v2/wanted/buy.page`) | Inside store price cell |
| BrickLink store listing (`store.bricklink.com/#/shop`) | Between price and Add to Cart |
| BrickLink store cart (`store.bricklink.com/#/cart`) | Inside price cell |

Features:
- Green **PAB** badge = Pick a Brick (fast shipping)
- Amber **STD** badge = Bricks and Pieces (30+ day shipping)
- Grey **PAB: N/A** = not available on LEGO direct
- **Set PAB** button on wanted lists fills max price inputs from PAB prices
- Auto-sets page size to 10,000 on wanted lists
- Buy page: auto-checks "Lots over max price", sets store location filter
- Popup settings: store location (215 countries + 8 regions), PAB region (18 locales), filter toggles, timezone auto-detect

**Loading for development:**
- Extension folder shared via Samba: `\\dev.home.arpa\moc-extension`
- Load in Brave: `brave://extensions` → Load unpacked → browse to share
- Edits on dev server are live; just reload the extension card

### API (`mocsource/`)

FastAPI app at `https://api.moc-source.com`. Deployed to `/opt/mocsource/app/` on `app.home.arpa`.

Key endpoint: `GET /api/v1/parts/pab/price/{part_no}/{color_id}?locale=en-us`

Full deploy: `ansible-playbook site.yml` from `moc-source-infra/` (repos must be siblings on disk).

Quick deploy (app code only):
```bash
rsync -av --exclude=__pycache__ --exclude='*.pyc' --exclude=.env \
  mocsource/ excalibrax@app.home.arpa:/tmp/mocsource_deploy/
ssh app.home.arpa "sudo cp -r /tmp/mocsource_deploy/. /opt/mocsource/app/mocsource/ && sudo systemctl restart mocsource"
```

### Static pages (`static/`)

Served at `/page-name` via FastAPI `FileResponse`. Pattern for new pages:
1. Add `static/page-name.html` (include favicon link tags from existing pages)
2. Add `@app.get("/page-name")` route in `mocsource/main.py`
3. Deploy

Current pages: `/privacy`

### Database

PostgreSQL 18 on `app.home.arpa`.

- `lego_elements` — element metadata + en-us price (backwards compat)
- `lego_element_prices` — multi-region prices, PK (element_id, locale), 18 locales × ~17k entries
- `bricklink_mappings` — element_id → part_no + color_id
- `bricklink_alternates`, `studio_resolutions`, `multipacks`, `failed_studio_mappings`

### PAB Scraper (`scripts/scrape_pab.py`)

Loops 18 confirmed LEGO locales, upserts into `lego_element_prices` directly. Runs hourly via `mocsource-scrape-pab.timer` on app server.

Required headers (LEGO blocks without these): `Origin: https://www.lego.com`, `x-locale: {locale}`  
Required query fix: no `$sku` variable, use `quantityInSet(sku: null)` hardcoded.

**Confirmed working locales:** `en-us`, `en-gb`, `en-au`, `de-de`, `fr-fr`, `nl-nl`, `en-ca`, `ko-kr`, `pl-pl`, `sv-se`, `en-nz`, `cs-cz`, `da-dk`, `fi-fi`, `nb-no`, `es-es`, `it-it`, `pt-pt`  
Not available: `ja-jp` (no results), `zh-cn` (invalid response)  
Note: `ko-kr` returns only ~1,299 entries vs ~17k for other locales — may need investigation.

## Infrastructure

| Host | IP | Role |
|------|----|------|
| `dev.home.arpa` | 10.242.42.10 | Dev/jumpbox (Fedora 44) |
| `app.home.arpa` | 10.242.42.20 | App server (Rocky Linux 10.2) |
| Technitium DNS | 10.242.42.47 | Internal DNS, home.arpa zone |

Full Ansible provisioning in [`moc-source-infra`](https://github.com/vaultcrest/moc-source-infra).

## What's Working

- [x] Extension badges on all 4 BrickLink page types
- [x] Set PAB button on wanted lists
- [x] Buy page auto-filter (store location, Lots over max price, Lots below Wanted qty)
- [x] Popup: full 215-country + 8-region list, 18 PAB locale options, timezone auto-detect
- [x] Multi-region pricing — 18 locales in DB, API `?locale=` param, extension reads pabRegion setting
- [x] Hourly scraper running on app server
- [x] Privacy page at https://api.moc-source.com/privacy
- [x] Favicon on all web pages
- [x] Repo fully backed up, AGPL-3.0 licensed, brand assets protected in NOTICE
- [x] Ansible infra covers full server rebuild from scratch
- [x] Cloudflare tunnel — `api.moc-source.com` publicly accessible via Cloudflare edge

## What's Next

1. **Chrome Web Store** — paid, draft ready, privacy page live. Package: zip `extension/` folder, upload as unlisted.
2. **ko-kr** — investigate why only 1,299 entries vs ~17k for other locales
3. **Regional Studio palettes** — `generate_palettes.py` reading from DB per locale
4. **Icon** — diamond shape in toolbar, deferred

## Related Projects

- [`brick_palettes_generator`](https://github.com/vaultcrest/brick_palettes_generator) — standalone offline LEGO Studio palette generator; also upstream source for canonical LEGO↔BrickLink mappings
- [`moc-source-infra`](https://github.com/vaultcrest/moc-source-infra) — Ansible playbooks for full server provisioning
