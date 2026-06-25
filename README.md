# MOC Source

LEGO acquisition planning tool. Overlays PAB (Pick a Brick) and BAP (Bricks and Pieces) prices from LEGO direct onto BrickLink pages so you can compare store prices vs. buying direct.

MOC Source is a free, open source community tool built by AFOLs for AFOLs. The goal is recognition and community contribution — not profit. If it saves you time sourcing parts, consider supporting the server costs:

[![Patreon](https://img.shields.io/badge/Patreon-Support-orange)](https://www.patreon.com/c/MocSource)
[![PayPal](https://img.shields.io/badge/PayPal-Tip-blue)](https://www.paypal.com/ncp/payment/SAACTUBPTPBSS)

## Architecture

```
LEGO PAB API (GraphQL)
      ↓
brick_palettes_generator  ←→  PostgreSQL 18 (app.home.arpa)
                                    ↓
                           FastAPI (api.moc-source.com)
                                    ↓
                      MOC Source Browser Extension
                      (Brave/Chrome, Manifest V3)
```

## Components

### Browser Extension (`extension/`)

Manifest V3 Chrome/Brave extension. Injects PAB price badges on:

| Page | Badge location |
|------|---------------|
| BrickLink wanted list (`/v2/wanted/search.page`) | Inside Max Price cell |
| BrickLink buy page modal (`/v2/wanted/buy.page`) | Inside store price cell |
| BrickLink store listing (`store.bricklink.com/#/shop`) | Between price and Add to Cart |
| BrickLink store cart (`store.bricklink.com/#/cart`) | Inside Each price cell |

Features:
- Green **PAB** badge = Pick a Brick (fast shipping)
- Amber **STD** badge = Bricks and Pieces (30+ day shipping)
- Grey **PAB: N/A** = not available on LEGO direct
- **Set PAB** button on wanted lists fills max price inputs from PAB prices
- Auto-sets page size to 10,000 on wanted lists
- Buy page: auto-checks "Lots over max price", sets store location filter
- Popup settings: store location (215 countries + 8 regions), PAB region, filter toggles

**Loading for development:**
- Extension folder shared via Samba: `\\dev.home.arpa\moc-extension`
- Load in Brave: `brave://extensions` → Load unpacked → browse to share
- Edits on dev server are live; just reload the extension card

### API (`mocsource/`)

FastAPI app deployed to `/opt/mocsource/app/` on `app.home.arpa`.

Key endpoint: `GET /api/v1/parts/pab/price/{part_no}/{color_id}`  
Returns PAB/BAP price entries for a BrickLink part number + color ID.

Deploy: `rsync -av mocsource/ excalibrax@app.home.arpa:/tmp/mocsource_deploy/ && ssh app.home.arpa "sudo cp -r /tmp/mocsource_deploy/. /opt/mocsource/app/mocsource/"`

### Database

PostgreSQL 18 on `app.home.arpa` / `10.242.42.20`.

Tables:
- `lego_elements` — element_id, design_id, lego_name, channel, price_cents, price_formatted, last_seen, first_seen _(en-us values, kept for API backwards compat)_
- `lego_element_prices` — element_id + locale PK, channel, price_cents, price_formatted, currency_code, in_stock, updated_at _(multi-region pricing)_
- `bricklink_mappings` — element_id → part_no + color_id
- `bricklink_alternates`, `studio_resolutions`, `multipacks`, `multipack_components`, `failed_studio_mappings`

**Availability vs price by region:**
- US and EU stock differ independently — channel (PAB/BAP/OOS) tracked per locale
- US only: PAB (Bestseller) = 5 day shipping; BAP (Standard) = 30–40 days
- All other locales: ~18 days regardless of channel — no meaningful tier distinction
- Prices vary by locale/currency across all regions

**PAB Scraper (`scripts/scrape_pab.py`):**
- Loops 18 confirmed locales, upserts into `lego_element_prices`
- Also updates `lego_elements` from en-us to keep existing API current
- Requires `curl_cffi` for Chrome impersonation (in requirements.txt)
- Deployed as `mocsource-scrape-pab.timer` systemd service on app server
- Uses fixed headers: `Origin: https://www.lego.com`, `x-locale: {locale}`
- Uses fixed query: no `$sku` variable, `quantityInSet(sku: null)` hardcoded

**Confirmed working locales (tested 2026-06-24):**
`en-us`, `en-gb`, `en-au`, `de-de`, `fr-fr`, `nl-nl`, `en-ca`, `ko-kr`, `pl-pl`, `sv-se`, `en-nz`, `cs-cz`, `da-dk`, `fi-fi`, `nb-no`, `es-es`, `it-it`, `pt-pt`

Not available: `ja-jp` (no results), `zh-cn` (invalid response)

**Future schema cleanup:** drop channel/price_cents/price_formatted from `lego_elements` once API is updated to join `lego_element_prices` for en-us by default with `?locale=` param support.

## Infrastructure

| Host | Role |
|------|------|
| `dev.home.arpa` | Dev/jumpbox — this machine |
| `app.home.arpa` / `10.242.42.20` | App server — FastAPI + PostgreSQL |
| `api.moc-source.com` | DNS alias for app server (Technitium internal DNS) |

## What's Working

- [x] Extension badges on all 4 BrickLink page types
- [x] Set PAB button on wanted lists
- [x] Buy page auto-filter (store location, Lots over max price)
- [x] Popup settings with full country/region list, timezone auto-detect
- [x] Samba share for live dev workflow
- [x] PAB API returning price_cents + price_formatted

## What's Next

### Multi-region PAB pricing

`lego_element_prices` table and `scripts/scrape_pab.py` are deployed and running.

**Required headers for LEGO GraphQL API** (discovered 2026-06-24 — already applied in scraper):
- `Origin: https://www.lego.com` — required, was missing from original generator
- `x-locale: {locale}` — required, was missing from original generator

**Required query fix** (already applied in scraper):
- Remove `$sku: String` from the operation declaration — now causes a validation error
- Use `quantityInSet(sku: null)` hardcoded instead of `quantityInSet(sku: $sku)`

**Distinct price regions:** US, GB, CA, AU, NZ, EU (de/fr/nl/es/it/pt), SE, NO, DK, PL, CZ, KR

**Remaining:**
1. Update API price endpoint to accept `?locale=` param
2. Wire extension `pabRegion` setting to API call in background.js
3. Future: tiered scrape cadence — US+EU more frequently, other locales daily

### Chrome Web Store

Publish extension as unlisted for beta testing.
- $5 one-time developer fee covers all future listings
- Package: zip the `extension/` folder, upload to Chrome Web Store developer console

### Deferred

- Icon: `Vaultcrest brick shield.png` — diamond shape in toolbar, may want to round/square it
- MutationObserver already handles SPA navigation — no known issues

## Related Projects

- [`brick_palettes_generator`](../brick_palettes_generator/) — scraper that builds the PAB inventory and canonical LEGO↔BrickLink mappings
