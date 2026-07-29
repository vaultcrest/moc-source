// ─── Country list (shared with popup.js) ─────────────────────────────────────

const BL_COUNTRIES = ["Afghanistan","Albania","Algeria","Andorra","Angola","Anguilla","Antigua and Barbuda","Argentina","Armenia","Aruba","Australia","Austria","Azerbaijan","Bahamas","Bahrain","Bangladesh","Barbados","Belgium","Belize","Benin","Bermuda","Bhutan","Bolivia","Bosnia and Herzegovina","Botswana","Brazil","British Indian Ocean Territory","Brunei","Bulgaria","Burkina Faso","Burundi","Cambodia","Cameroon","Canada","Cape Verde","Caribbean Netherlands","Cayman Islands","Central African Republic","Chad","Chile","Colombia","Comoros","Congo","Congo (DRC)","Cook Islands","Costa Rica","Cote D'Ivoire","Croatia","Curacao","Cyprus","Czech Republic","Denmark","Djibouti","Dominica","Dominican Republic","East Timor","Ecuador","Egypt","El Salvador","Equatorial Guinea","Eritrea","Estonia","Ethiopia","Falkland Islands (Islas Malvinas)","Faroe Islands","Fiji","Finland","France","French Polynesia","Gabon","Gambia","Georgia","Germany","Ghana","Gibraltar","Greece","Greenland","Grenada","Guatemala","Guinea","Guinea-Bissau","Guyana","Haiti","Honduras","Hong Kong SAR China","Hungary","Iceland","India","Indonesia","Iraq","Ireland","Israel","Italy","Jamaica","Japan","Jordan","Kazakhstan","Kenya","Kiribati","Kuwait","Kyrgyzstan","Laos","Latvia","Lebanon","Lesotho","Liberia","Libya","Liechtenstein","Lithuania","Luxembourg","Macau","Macedonia","Madagascar","Malawi","Malaysia","Maldives","Mali","Malta","Marshall Islands","Mauritania","Mauritius","Mayotte","Mexico","Micronesia","Moldova","Monaco","Mongolia","Montenegro","Montserrat","Morocco","Mozambique","Myanmar","Namibia","Nauru","Nepal","Netherlands","New Caledonia","New Zealand","Nicaragua","Niger","Niue","Norfolk Island","Norway","Oman","Pakistan","Palau","Panama","Papua new Guinea","Paraguay","Peru","Philippines","Pitcairn Islands","Poland","Portugal","Qatar","Romania","Rwanda","Samoa","San Marino","Sao Tome and Principe","Saudi Arabia","Senegal","Serbia","Seychelles","Sierra Leone","Singapore","Sint Maarten","Slovakia","Slovenia","Solomon Islands","Somalia","South Africa","South Georgia","South Korea","Spain","Sri Lanka","St. Helena","St. Kitts and Nevis","St. Lucia","St. Pierre and Miquelon","St. Vincent and the Grenadines","Sudan","Suriname","Svalbard and Jan Mayen","Swaziland","Sweden","Switzerland","Taiwan Region","Tajikistan","Tanzania","Thailand","Togo","Tonga","Trinidad and Tobago","Tunisia","Turkey","Turkmenistan","Turks and Caicos Islands","Tuvalu","Uganda","Ukraine","United Arab Emirates","United Kingdom","Uruguay","USA","Uzbekistan","Vanuatu","Vatican City State","Venezuela","Vietnam","Virgin Islands (British)","Wallis and Futuna","Yemen","Zambia","Zimbabwe"];

// ─── Helpers ─────────────────────────────────────────────────────────────────

function esc(s) {
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function fmtDate(ts) {
  return new Date(ts).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function parseStorePrice(str) {
  if (!str) return null;
  const n = parseFloat(str.replace(/[^0-9.]/g, ""));
  return isNaN(n) ? null : n;
}

// Picks a representative price row for a "(Not Applicable)" (any color)
// wanted part from GET_PAB_PRICES_FOR_PART's full per-color result set --
// mirrors background.js's fetchPabPrice()'s own channel preference (pab
// over bap) for a single color, then picks the cheapest row within
// whichever channel is present, since "any color" means the cheapest
// available color is the honest representative price.
function pickCheapestPabRow(rows) {
  if (!rows || !rows.length) return null;
  const cheapest = list => list.reduce((a, b) => (b.price_cents ?? Infinity) < (a.price_cents ?? Infinity) ? b : a);
  const pab = rows.filter(r => r.channel === "pab");
  if (pab.length) return cheapest(pab);
  const bap = rows.filter(r => r.channel === "bap");
  if (bap.length) return cheapest(bap);
  return cheapest(rows);
}

// Rounds a dollar amount UP to the nearest cent -- used only for final
// "what you'll pay" totals, never for per-item/per-category display.
// The 1e-9 epsilon guards against float noise (e.g. 0.1+0.2=0.30000000000000004)
// spuriously ceiling-ing a value that's already an exact cent amount.
function ceilToCents(amount) {
  return Math.ceil(amount * 100 - 1e-9) / 100;
}

// Resolves the effective per-unit price for a lot given its ACTUAL full cart
// quantity (not a partial allocation amount) -- the tier that applies is
// determined by the real lot quantity, since that's what BrickLink actually
// bills, regardless of how we're internally attributing portions of it.
function tierPriceFor(tiers, lotQty) {
  if (!tiers?.length) return null;
  let price = tiers[0].price;
  for (const t of tiers) {
    if (lotQty >= t.minQty) price = t.price;
  }
  return price;
}
// Effective price for a cart part, preferring its tier table over the plain
// native/scraped price when available.
function effectivePrice(cartPart) {
  return tierPriceFor(cartPart?.priceTiers, cartPart?.qty ?? 0) ?? parseStorePrice(cartPart?.storePrice);
}

// Percent the store price is above (+) or below (-) the PAB price, or null if
// either price is unknown. Computed fresh at render time from real numbers --
// never scraped/stored, unlike the leaked BrickLink text this replaces.
function pctVsPab(storeNum, pabNum) {
  if (storeNum == null || pabNum == null || pabNum <= 0) return null;
  return ((storeNum - pabNum) / pabNum) * 100;
}

function isOverPAB(p) {
  const store = parseStorePrice(p.storePrice);
  if (store == null || !p.pabEntry?.price_cents) return false;
  return store >= p.pabEntry.price_cents / 100;
}

function cartSavings(parts) {
  let total = 0, count = 0;
  for (const p of parts) {
    const store = parseStorePrice(p.storePrice);
    if (store == null || !p.pabEntry?.price_cents) continue;
    const pab = p.pabEntry.price_cents / 100;
    if (store > pab) {
      total += (store - pab) * (p.qty ?? 1);
      count++;
    }
  }
  return { total, count };
}

function buildBlXml(items) {
  const lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<INVENTORY>'];
  for (const { partNo, colorId, qty, maxPrice } of items) {
    lines.push('<ITEM>',
      '<ITEMTYPE>P</ITEMTYPE>',
      `<ITEMID>${partNo}</ITEMID>`,
      `<COLOR>${colorId}</COLOR>`,
      maxPrice ? `<MAXPRICE>${maxPrice}</MAXPRICE>` : null,
      `<MINQTY>${qty}</MINQTY>`,
      '<CONDITION>X</CONDITION>',
      '<NOTIFY>N</NOTIFY>',
      '</ITEM>');
  }
  lines.push('</INVENTORY>');
  return lines.filter(Boolean).join('\n');
}

async function queueBlUpload(items) {
  if (!items.length) return;
  const xml = buildBlXml(items);
  const listName = (currentDetail.list?.name || "bricklink").replace(/[/\\?%*:|"<>]/g, "-").trim();
  await chrome.storage.local.set({ pendingBLUpload: { xml, listName } });
  chrome.runtime.sendMessage({ type: "QUEUE_BL_UPLOAD" });
}

function blWlItems(parts, channel) {
  return parts
    .filter(p => {
      const ch = effectiveChannel(p);
      if (channel === "bl")  return ch === null;
      if (channel === "pab") return ch === "pab";
      if (channel === "bap") return ch === "bap";
      return ch === null || ch === "pab" || ch === "bap"; // "all"
    })
    .map(p => ({
      partNo:   p.partNo   || p.pabEntry?.design_id,
      colorId:  p.colorId  ?? p.pabEntry?.bl_color_id,
      qty:      Math.max(1, isLegoCart() ? (p.qty ?? p.quantity ?? 1) : (p.want ?? 1) - (p.have ?? 0)),
      maxPrice: p.pabEntry?.price_cents ? (p.pabEntry.price_cents / 100).toFixed(4) : null,
    }))
    .filter(i => i.partNo && i.colorId && i.qty > 0);
}

function legoCartSummary(parts) {
  const pab = parts.filter(p => p.channel === "pab");
  const bap = parts.filter(p => p.channel === "bap");
  const pabPcs = pab.reduce((s, p) => s + (p.qty || 0), 0);
  const bapPcs = bap.reduce((s, p) => s + (p.qty || 0), 0);
  const row = (label, lots, pcs) =>
    `<div style="display:flex;gap:24px;padding:6px 0;border-bottom:1px solid #f3f4f6">
       <span style="font-weight:600;min-width:120px">${label}</span>
       <span>Lots <strong>${lots}</strong></span>
       <span>Pieces <strong>${pcs}</strong></span>
     </div>`;
  return `<div style="padding:12px 16px;background:#fff;border:1px solid #e5e7eb;border-radius:6px;margin-bottom:12px">
    ${row("PAB", pab.length, pabPcs)}
    ${row("STD", bap.length, bapPcs)}
    ${row("<strong>Total</strong>", parts.length, pabPcs + bapPcs)}
  </div>`;
}

const LEGO_CART_LOT_LIMIT = 200;
const LEGO_CART_QTY_LIMIT = 999;

// CSP-safe image fallback: replaces inline onerror= handlers.
// data-fb1 = first fallback src, data-fb2 = second (LEGO only).
document.addEventListener("error", e => {
  const img = e.target;
  if (!(img instanceof HTMLImageElement) || !img.classList.contains("part-img")) return;
  if (!img.dataset.e) {
    img.dataset.e = "1";
    if (img.dataset.fb1) { img.src = img.dataset.fb1; return; }
  } else if (!img.dataset.e2 && img.dataset.fb2) {
    img.dataset.e2 = "1";
    img.src = img.dataset.fb2; return;
  }
  img.style.display = "none";
}, true);

// Returns [{ cartId, role }] for a project, migrating from legacy legoCartId scalar on first read.
function getProjectLegoCarts(proj) {
  if (proj.legoCartIds) return proj.legoCartIds;
  return proj.legoCartId ? [{ cartId: proj.legoCartId, role: "main" }] : [];
}

// Returns the primary legoCart ID for backward-compat allocation code.
function primaryLegoCartId(proj) {
  const carts = getProjectLegoCarts(proj);
  return carts.find(c => c.role === "main")?.cartId ?? carts[0]?.cartId ?? null;
}

function legoCartOverLimit(parts) {
  const pabLots = parts.filter(p => p.channel === "pab").length;
  const bapLots = parts.filter(p => p.channel === "bap").length;
  return {
    pab: pabLots > LEGO_CART_LOT_LIMIT ? pabLots : 0,
    bap: bapLots > LEGO_CART_LOT_LIMIT ? bapLots : 0,
  };
}

const ROLE_LABELS = {
  main: "Main", overflow: "Overflow",
  "pab-only": "Bestseller Only", "bap-only": "Standard Only",
  "pab-overflow": "Bestseller Overflow", "bap-overflow": "Standard Overflow",
};

// ── GWP threshold-aware multi-cart allocation planning ──────────────────────
// Pure functions (no DOM/storage access) used by showLegoSaveDiff()'s save flow
// to decide which of a project's linked Pick-A-Brick carts each lot lands in.

// Largest-lot-value-first (first-fit-decreasing style) fill order. Heuristic,
// not an exact bin-pack solve: can overshoot a cart's GWP threshold by up to one
// lot's value, and never backtracks across carts to minimize total overshoot.
// Acceptable because hard lot/qty limits are unaffected either way, and the goal
// is "reduce which carts miss GWP," not exact optimization.
function sortByFillHeuristic(parts) {
  return [...parts].sort((a, b) => (b.qty * b.priceCents) - (a.qty * a.priceCents));
}

// Resolves, per channel, the ordered list of destination carts to fill in turn.
// main (if present) is always the primary for both channels; pab-only/bap-only
// only come into play when there's no main. Array order within a role is fill
// priority -- already load-bearing today (it's how the old overflowCarts[0]
// picked "the" overflow cart), just formalized here instead of accidental.
function resolveLegoDestinationChains(projLgCarts) {
  const byRole = role => projLgCarts.filter(c => c.role === role);
  const main = byRole("main")[0] ?? null;

  const pabPrimary = main ?? byRole("pab-only")[0] ?? null;
  const bapPrimary = main ?? byRole("bap-only")[0] ?? null;

  const sharedOverflow = byRole("overflow");
  const pabOverflow = [...byRole("pab-overflow"), ...sharedOverflow];
  const bapOverflow = [...byRole("bap-overflow"), ...sharedOverflow];

  return {
    pab: [pabPrimary, ...pabOverflow].filter(Boolean),
    bap: [bapPrimary, ...bapOverflow].filter(Boolean),
  };
}

// Fills `chain` with `parts` (already channel-filtered, each carrying
// qty/priceCents). lotCounts is keyed "${cartId}:${channel}" since LEGO's
// 200-lot cap applies per live channel-cart even when PAB+STD share one local
// cart record; dollarTotals is keyed by cartId alone since the GWP threshold is
// checked against the combined PAB+STD total per destination cart. Both maps
// are shared across the pab/bap/forced-overflow calls in planLegoDistribution
// so limits are enforced cumulatively, not reset per call.
function fillChannelIntoChain(parts, chain, channel, threshold, lotCounts, dollarTotals) {
  const placements = new Map(chain.map(c => [c.cart.id, []]));
  const forcedOverflow = [];
  const unplaced = [];

  // Pre-split any lot whose own qty exceeds the hard per-lot cap -- unaffected
  // by threshold/chain, identical to the original splitChannel_ behavior.
  const toPlace = [];
  for (const lot of parts) {
    if (lot.qty > LEGO_CART_QTY_LIMIT) {
      toPlace.push({ ...lot, qty: LEGO_CART_QTY_LIMIT });
      forcedOverflow.push({ ...lot, qty: lot.qty - LEGO_CART_QTY_LIMIT });
    } else {
      toPlace.push(lot);
    }
  }

  const sorted = sortByFillHeuristic(toPlace);
  let chainIdx = 0;
  for (const lot of sorted) {
    let placed = false;
    while (chainIdx < chain.length) {
      const dest = chain[chainIdx];
      const cartId = dest.cart.id;
      const lotKey = `${cartId}:${channel}`;
      const curLots  = lotCounts.get(lotKey) ?? 0;
      const curTotal = dollarTotals.get(cartId) ?? 0;

      if (curLots >= LEGO_CART_LOT_LIMIT) { chainIdx++; continue; }
      if (threshold > 0 && curTotal >= threshold) { chainIdx++; continue; }

      placements.get(cartId).push(lot);
      lotCounts.set(lotKey, curLots + 1);
      dollarTotals.set(cartId, curTotal + (lot.qty * lot.priceCents) / 100);
      placed = true;
      break;
    }
    if (!placed) unplaced.push(lot);
  }

  return { placements, forcedOverflow, unplaced };
}

// Top-level: resolves destination chains, fills PAB fully then BAP (fixed,
// deterministic order so a shared "overflow" cart's combined total reflects
// both channels), then folds forced (999-qty) overflow back through a second
// pass against the same chains/state rather than special-casing it -- it lands
// wherever there's still hard-limit room, same as any other lot.
function planLegoDistribution(newParts, projLgCarts, threshold) {
  const chains = resolveLegoDestinationChains(projLgCarts);
  const lotCounts = new Map();
  const dollarTotals = new Map();

  const pabParts = newParts.filter(p => p.channel === "pab");
  const bapParts = newParts.filter(p => p.channel === "bap");

  const pabResult = fillChannelIntoChain(pabParts, chains.pab, "pab", threshold, lotCounts, dollarTotals);
  const bapResult = fillChannelIntoChain(bapParts, chains.bap, "bap", threshold, lotCounts, dollarTotals);
  const forcedPab = fillChannelIntoChain(pabResult.forcedOverflow, chains.pab, "pab", threshold, lotCounts, dollarTotals);
  const forcedBap = fillChannelIntoChain(bapResult.forcedOverflow, chains.bap, "bap", threshold, lotCounts, dollarTotals);

  const perCart = new Map();
  const mergeInto = placements => {
    for (const [cartId, lots] of placements) {
      if (!lots.length) continue;
      if (!perCart.has(cartId)) perCart.set(cartId, []);
      perCart.get(cartId).push(...lots);
    }
  };
  mergeInto(pabResult.placements);
  mergeInto(bapResult.placements);
  mergeInto(forcedPab.placements);
  mergeInto(forcedBap.placements);

  return {
    perCart,
    unplaced: {
      pab: [...pabResult.unplaced, ...forcedPab.unplaced],
      bap: [...bapResult.unplaced, ...forcedBap.unplaced],
    },
    chains,
  };
}

function summaryPanel(parts, cart) {
  const cats = {
    pab: { lots: 0, pieces: 0, price: 0, hasPrice: true },
    bap: { lots: 0, pieces: 0, price: 0, hasPrice: true },
    bl:  { lots: 0, pieces: 0, price: 0, hasPrice: cart },
  };

  for (const p of parts) {
    const qty = cart ? (p.qty ?? 1) : (p.want ?? p.qty ?? 1);
    const ch = effectiveChannel(p);
    if (ch === "pab") {
      cats.pab.lots++;
      cats.pab.pieces += qty;
      cats.pab.price += (p.pabEntry.price_cents / 100) * qty;
    } else if (ch === "bap") {
      cats.bap.lots++;
      cats.bap.pieces += qty;
      cats.bap.price += (p.pabEntry.price_cents / 100) * qty;
    } else {
      cats.bl.lots++;
      cats.bl.pieces += qty;
      if (cart) {
        const sp = effectivePrice(p);
        if (sp) cats.bl.price += sp * qty;
      } else if (p.maxPrice != null) {
        cats.bl.price += p.maxPrice * qty;
        cats.bl.hasPrice = true;
      }
    }
  }

  const tot = {
    lots:   cats.pab.lots   + cats.bap.lots   + cats.bl.lots,
    pieces: cats.pab.pieces + cats.bap.pieces + cats.bl.pieces,
    price:  cats.pab.price  + cats.bap.price  + cats.bl.price,
  };

  const hasPab = !cart && cats.pab.lots > 0;
  const hasBap = !cart && cats.bap.lots > 0;
  const hasBl  = !cart && cats.bl.lots  > 0;
  const blPriceLabel = cart ? "Price" : "Max $";
  const totHasPrice  = cats.pab.hasPrice || cats.bap.hasPrice || cats.bl.hasPrice;

  if (cart) {
    return `
      <div style="background:#fff;border:1px solid #e1e4e8;border-radius:8px;padding:4px 20px 8px;margin-bottom:14px;font-size:16px">
        ${["pab","bap","bl"].map(k => {
          const d = cats[k]; if (!d.lots) return "";
          const lbl = k === "pab" ? "PAB" : k === "bap" ? "STD" : "BrickLink";
          const pl  = k === "bl" ? "Price" : "Price";
          const pr  = d.hasPrice ? `$${ceilToCents(d.price).toFixed(2)}` : "—";
          return `<div style="display:flex;align-items:center;gap:24px;padding:8px 0;border-bottom:1px solid #f3f4f6">
            <span style="font-weight:600;width:150px;flex-shrink:0">${lbl}</span>
            <span style="color:#6c757d;font-size:14px">Lot</span><span style="min-width:40px">${d.lots}</span>
            <span style="color:#6c757d;font-size:14px">Pieces</span><span style="min-width:50px">${d.pieces}</span>
            <span style="color:#6c757d;font-size:14px">${pl}</span><span style="font-weight:500">${pr}</span>
          </div>`;
        }).join("")}
        <div style="display:flex;align-items:baseline;gap:24px;padding:8px 0;border-bottom:1px solid #f3f4f6">
          <span style="font-weight:700;width:150px;flex-shrink:0">Total</span>
          <span style="color:#6c757d;font-size:14px">Lot</span><span style="min-width:40px;font-weight:600">${tot.lots}</span>
          <span style="color:#6c757d;font-size:14px">Pieces</span><span style="min-width:50px;font-weight:600">${tot.pieces}</span>
          <span style="color:#6c757d;font-size:14px">Price</span><span style="font-weight:700">${totHasPrice ? `$${ceilToCents(tot.price).toFixed(2)}` : "—"}</span>
        </div>
        ${(() => {
          const os = currentDetail.list?.orderSummary;
          if (!os || (!os.shipping && !os.orderTotal)) return "";
          const row = (label, val, bold) =>
            `<div style="display:flex;align-items:center;gap:24px;padding:8px 0;border-bottom:1px solid #f3f4f6">
               <span style="${bold ? "font-weight:700" : "font-weight:600"};width:150px;flex-shrink:0">${label}</span>
               <span style="color:#6c757d;font-size:14px;visibility:hidden">Lot</span><span style="min-width:40px"></span>
               <span style="color:#6c757d;font-size:14px;visibility:hidden">Pieces</span><span style="min-width:50px"></span>
               <span style="color:#6c757d;font-size:14px">Price</span>
               <span style="${bold ? "font-weight:700" : "font-weight:500"}">${val ?? "—"}</span>
             </div>`;
          const fmt = v => v ? v.replace(/^US\s+/, "") : v;
          const fmtShip = fmt(os.shipping);
          const fmtOrd  = fmt(os.orderTotal);
          const shipTbd = !fmtShip || fmtShip === fmtOrd;
          return `
            ${os.itemTotal  ? row("BrickLink Item Total", fmt(os.itemTotal)) : ""}
            ${shipTbd
              ? row("Shipping & Handling", '<span style="color:#9ca3af">TBD</span>')
              : row("Shipping & Handling", fmtShip)}
            ${os.orderTotal ? row("Order Total", fmtOrd, true) : ""}`;
        })()}
      </div>`;
  }

  // ── Wanted list: two action columns ──────────────────────────────────────────
  const BL_W  = "100px";
  const PAB_W = "120px";
  const BASE  = `width:100%;padding:5px 6px;font-size:13px;font-weight:600;border-radius:5px;cursor:pointer;white-space:nowrap;border:none`;

  function blBtn(wlCh, show) {
    return `<div style="width:${BL_W};flex-shrink:0">${show
      ? `<button class="channel-wl-btn" data-wl-channel="${wlCh}" style="${BASE};background:#f0f4ff;color:#2563eb;border:1px solid #bfdbfe">↑ BL WL</button>`
      : ""}</div>`;
  }

  function pabBtn(ch, label, show) {
    return `<div style="width:${PAB_W};flex-shrink:0">${show && ch
      ? `<button class="transfer-btn" data-channel="${ch}" style="${BASE};background:#006db7;color:#fff">${label}</button>`
      : ""}</div>`;
  }

  function stats(d, priceLabel) {
    const pr = d.hasPrice ? `$${d.price.toFixed(2)}` : "—";
    return `<div style="flex:1;display:flex;align-items:center;gap:20px">
      <span style="color:#6c757d;font-size:14px">Lot</span><span style="min-width:36px">${d.lots}</span>
      <span style="color:#6c757d;font-size:14px">Pieces</span><span style="min-width:46px">${d.pieces}</span>
      <span style="color:#6c757d;font-size:14px">${priceLabel}</span><span style="font-weight:500">${pr}</span>
    </div>`;
  }

  function row(label, d, priceLabel, wlCh, pabCh) {
    return `
      <div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid #f3f4f6">
        <span style="font-weight:600;width:130px;flex-shrink:0">${label}</span>
        ${stats(d, priceLabel)}
        ${blBtn(wlCh, d.lots > 0)}
        ${pabBtn(pabCh, "Transfer", d.lots > 0 && !!pabCh)}
      </div>`;
  }

  const totPabCh = hasPab && hasBap ? "both" : hasPab ? "pab" : hasBap ? "bap" : null;

  const csvRow = hasPab || hasBap ? `
    <div style="display:flex;justify-content:flex-end;padding:6px 0 0;gap:8px">
      <button class="csv-dl-btn" style="padding:4px 14px;font-size:13px;background:#fff;color:#374151;border:1px solid #d1d5db;border-radius:4px;cursor:pointer;white-space:nowrap">Download CSV</button>
    </div>` : "";

  return `
    <div style="background:#fff;border:1px solid #e1e4e8;border-radius:8px;padding:4px 20px 10px;margin-bottom:14px;font-size:16px">
      <div style="display:flex;align-items:center;gap:10px;padding:4px 0 6px">
        <span style="width:130px;flex-shrink:0"></span>
        <div style="flex:1"></div>
        <div style="width:${BL_W};flex-shrink:0;text-align:center;font-size:11px;color:#6c757d;font-weight:700;letter-spacing:.04em;text-transform:uppercase">Transfer to BL</div>
        <div style="width:${PAB_W};flex-shrink:0;text-align:center;font-size:11px;color:#6c757d;font-weight:700;letter-spacing:.04em;text-transform:uppercase">Transfer to PAB</div>
      </div>
      ${row("PAB", cats.pab, "Price", "pab", "pab")}
      ${row("STD", cats.bap, "Price", "bap", "bap")}
      ${row("BrickLink",      cats.bl,  blPriceLabel,  "bl",  null)}
      <div style="display:flex;align-items:center;gap:10px;padding:8px 0 2px">
        <span style="font-weight:700;width:130px;flex-shrink:0">Total</span>
        <div style="flex:1;display:flex;align-items:center;gap:20px">
          <span style="color:#6c757d;font-size:14px">Lot</span><span style="min-width:36px;font-weight:600">${tot.lots}</span>
          <span style="color:#6c757d;font-size:14px">Pieces</span><span style="min-width:46px;font-weight:600">${tot.pieces}</span>
          <span style="color:#6c757d;font-size:14px">Price</span><span style="font-weight:700">${totHasPrice ? `$${tot.price.toFixed(2)}` : "—"}</span>
        </div>
        ${blBtn("all", tot.lots > 0)}
        ${pabBtn(totPabCh, "Transfer All", hasPab || hasBap)}
      </div>
      ${csvRow}
    </div>`;
}

// ─── Detail view state ───────────────────────────────────────────────────────

let currentDetail = null; // { listType, listId, list, parts: [...with pabEntry] }
let currentTab = "all";
let currentSort = "name_color";
let currentSortDir = "asc";
let legoCartSortPref   = "name"; // "name" | "default" | "parts" | "saved"
let blCartSortPref     = "name";
let wantedListSortPref = "name";
let currentPabRegion = "en-us";
let pendingQtyEditIdx = null;
let currentProjectTab = "all";
let poolSort    = "name_color";
let poolSortDir = "asc";
let selectedPoolKeys    = new Set();
let showAllocatedParts  = false;
let showExcludedParts   = false;
let selectedLegoKeys    = new Set();
let selectedBlKeys      = new Map(); // cartId -> Set<key>
let selectedScratchKeys = new Set();
let estBlShipping       = {};        // cartId -> estimated shipping amount
let blCartSort          = new Map(); // cartId -> sort key
let blCartSortDir       = new Map(); // cartId -> "asc"|"desc"

// ─── Router ──────────────────────────────────────────────────────────────────

function navigate(view) {
  location.hash = view;
  const baseView = view.startsWith("list/")    ? "lists"
                 : view.startsWith("project/") ? "projects"
                 : view;
  for (const el of document.querySelectorAll(".nav-item[data-view]")) {
    el.classList.toggle("active", el.dataset.view === baseView);
  }
  const content = document.getElementById("content");
  if (view === "lists")               renderLists(content);
  else if (view === "projects")       renderProjects(content);
  else if (view === "settings")       renderSettings(content);
  else if (view === "info")           renderInfo(content);
  else if (view.startsWith("list/")) {
    const parts = view.split("/");
    renderListDetail(parts[1], parts[2], content);
  }
  else if (view.startsWith("project/")) {
    renderProjectDetail(view.split("/")[1], content);
  }
}

// ─── Lists view ──────────────────────────────────────────────────────────────

async function renderLists(content) {
  const { wantedLists = [], carts = [], legoCarts = [] } = await chrome.storage.local.get(["wantedLists", "carts", "legoCarts"]);

  function applyListSort(arr, pref) {
    const sorted = [...arr];
    if      (pref === "name")  sorted.sort((a, b) => (a.name ?? "").localeCompare(b.name ?? ""));
    else if (pref === "parts") sorted.sort((a, b) => (b.partsCount ?? 0) - (a.partsCount ?? 0));
    else if (pref === "saved") sorted.sort((a, b) => new Date(b.savedAt ?? b.importedAt ?? 0) - new Date(a.savedAt ?? a.importedAt ?? 0));
    // "default" keeps insertion order (newest first)
    return sorted;
  }
  const sortedLegoCarts   = applyListSort(legoCarts,     legoCartSortPref);
  const sortedBlCarts     = applyListSort(carts,         blCartSortPref);
  const sortedWantedLists = applyListSort(wantedLists,   wantedListSortPref);

  function sortDropdown(id, pref) {
    return `<select id="${id}" style="font-size:11px;padding:2px 6px;border:1px solid #d1d5db;border-radius:4px;color:#374151;background:#fff">
      <option value="name"${pref    === "name"    ? " selected" : ""}>Name</option>
      <option value="parts"${pref   === "parts"   ? " selected" : ""}>Most Parts</option>
      <option value="saved"${pref   === "saved"   ? " selected" : ""}>Last Saved</option>
      <option value="default"${pref === "default" ? " selected" : ""}>Last Created</option>
    </select>`;
  }

  function listTable(items, type, showRename = false) {
    if (!items.length) return null;
    return `<table>
      <thead><tr><th>Name</th><th>Type</th><th>Parts</th><th>Saved</th><th></th></tr></thead>
      <tbody>
        ${items.map(l => `
          <tr>
            <td class="name-cell" data-id="${esc(l.id)}" data-key="${type}" style="display:flex;align-items:center;gap:6px">
              <button class="list-open-btn" style="background:none;border:none;padding:0;cursor:pointer;font-weight:600;color:#1e2330;text-align:left;" data-type="${type}" data-id="${esc(l.id)}">${esc(l.name)}</button>
              ${(showRename || l.userCreated) ? `<button class="btn rename-btn" data-id="${esc(l.id)}" data-key="${type}" style="font-size:11px;padding:1px 6px;opacity:0.45;flex-shrink:0" title="Rename">✎</button>` : ""}
            </td>
            <td><span class="type-badge">${type === "legoCarts" ? "LEGO" : "BrickLink"}</span></td>
            <td>${l.partsCount}</td>
            <td>${fmtDate(l.importedAt ?? l.savedAt)}</td>
            <td>
              <button class="btn btn-danger del-btn" data-id="${esc(l.id)}" data-key="${type}">Delete</button>
            </td>
          </tr>`).join("")}
      </tbody>
    </table>`;
  }

  content.innerHTML = `
    <div class="page-title">Parts Lists</div>

    <div class="section">
      <div class="section-header">
        <span>Wanted Lists</span>
        <div style="display:flex;align-items:center;gap:6px;margin-left:auto">
          ${sortDropdown("wanted-sort", wantedListSortPref)}
          <button class="new-list-btn" data-key="wantedLists" style="font-size:12px;padding:2px 10px;background:#1e2330;color:#fff;border:none;border-radius:4px;cursor:pointer">+ New</button>
        </div>
      </div>
      ${listTable(sortedWantedLists, "wantedLists", true) ?? `<div class="section-empty">No wanted lists imported yet.<br>Open a BrickLink wanted list and click <strong>Save to MOC Source</strong>.</div>`}
    </div>

    <div class="section">
      <div class="section-header">
        <span>BrickLink Carts</span>
        <div style="display:flex;align-items:center;gap:6px;margin-left:auto">
          ${sortDropdown("bl-cart-sort", blCartSortPref)}
        </div>
      </div>
      ${listTable(sortedBlCarts, "carts", true) ?? `<div class="section-empty">No carts imported yet.<br>Open a BrickLink store cart and click <strong>Save to MOC Source</strong>.</div>`}
    </div>

    <div class="section">
      <div class="section-header">
        <span>Pick-A-Brick Carts</span>
        <div style="display:flex;align-items:center;gap:6px;margin-left:auto">
          ${sortDropdown("lego-cart-sort", legoCartSortPref)}
          <button class="new-list-btn" data-key="legoCarts" style="font-size:12px;padding:2px 10px;background:#1e2330;color:#fff;border:none;border-radius:4px;cursor:pointer">+ New</button>
        </div>
      </div>
      ${listTable(sortedLegoCarts, "legoCarts", true) ?? `<div class="section-empty">No Pick-A-Brick carts saved yet.<br>Transfer parts to your Pick-A-Brick cart and click <strong>Save Cart</strong>.</div>`}
    </div>

    ${footerCardsHtml()}
  `;

  content.querySelector("#wanted-sort")?.addEventListener("change", e => {
    wantedListSortPref = e.target.value;
    renderLists(content);
  });
  content.querySelector("#bl-cart-sort")?.addEventListener("change", e => {
    blCartSortPref = e.target.value;
    renderLists(content);
  });
  content.querySelector("#lego-cart-sort")?.addEventListener("change", e => {
    legoCartSortPref = e.target.value;
    renderLists(content);
  });

  for (const btn of content.querySelectorAll(".list-open-btn")) {
    btn.addEventListener("click", () => navigate(`list/${btn.dataset.type}/${btn.dataset.id}`));
  }

  for (const btn of content.querySelectorAll(".del-btn")) {
    btn.addEventListener("click", async () => {
      const key = btn.dataset.key;
      const id  = btn.dataset.id;
      const { [key]: arr = [] } = await chrome.storage.local.get(key);
      await chrome.storage.local.set({ [key]: arr.filter(item => item.id !== id) });
      renderLists(content);
    });
  }

  for (const btn of content.querySelectorAll(".rename-btn")) {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      const id  = btn.dataset.id;
      const key = btn.dataset.key;
      const td  = content.querySelector(`.name-cell[data-id="${id}"][data-key="${key}"]`);
      const currentName = td.querySelector(".list-open-btn").textContent;

      // Hide existing td children rather than replacing them — avoids mid-click
      // DOM removal that can cause Chrome to auto-focus an adjacent element and
      // race against input.focus().
      for (const child of td.children) child.style.display = "none";
      const input = document.createElement("input");
      input.className = "rename-input";
      input.type = "text";
      input.value = currentName;
      input.style.cssText = "font-size:14px;padding:2px 6px;border:1px solid #2563eb;border-radius:4px;min-width:200px;box-sizing:border-box;flex:1";
      td.appendChild(input);

      let saved = false;
      async function saveRename() {
        if (saved) return;
        saved = true;
        const newName = input.value.trim() || currentName;
        if (newName !== currentName) {
          const { [key]: arr = [] } = await chrome.storage.local.get(key);
          const item = arr.find(x => x.id === id);
          if (item) { item.name = newName; await chrome.storage.local.set({ [key]: arr }); }
        }
        renderLists(content);
      }

      input.addEventListener("keydown", e => {
        if (e.key === "Enter")  { e.preventDefault(); saveRename(); }
        if (e.key === "Escape") { saved = true; renderLists(content); }
      });
      // Defer blur listener so it doesn't fire from the same click that opened the input
      setTimeout(() => {
        input.focus();
        input.select();
        input.addEventListener("blur", saveRename);
      }, 0);
    });
  }

  for (const btn of content.querySelectorAll(".new-list-btn")) {
    btn.addEventListener("click", async () => {
      const key = btn.dataset.key;
      const { [key]: arr = [] } = await chrome.storage.local.get(key);
      const now = new Date().toISOString();
      const newId = crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2) + Date.now().toString(36);
      const newItem = {
        id: newId,
        name: key === "legoCarts" ? `Pick-A-Brick Cart ${fmtDate(now)}` : `New List`,
        parts: [],
        partsCount: 0,
        userCreated: true,
        ...(key === "legoCarts" ? { savedAt: now } : { importedAt: now }),
      };
      arr.unshift(newItem);
      await chrome.storage.local.set({ [key]: arr });
      await renderLists(content);
      content.querySelector(`.rename-btn[data-id="${newId}"]`)?.click();
    });
  }
}

// ─── Projects view ───────────────────────────────────────────────────────────

async function renderProjects(content) {
  const { projects = [], wantedLists = [], carts = [], legoCarts = [] } =
    await chrome.storage.local.get(["projects", "wantedLists", "carts", "legoCarts"]);

  const wlMap  = Object.fromEntries(wantedLists.map(l => [l.id, l]));
  const blMap  = Object.fromEntries(carts.map(l => [l.id, l]));
  const lgMap  = Object.fromEntries(legoCarts.map(l => [l.id, l]));

  function poolPieceCount(p) {
    return (p.wantedListIds ?? []).reduce((s, id) => s + (wlMap[id]?.partsCount ?? 0), 0);
  }

  function metaChips(p) {
    const chips = [];
    const wlCount = (p.wantedListIds ?? []).length;
    const blCount = (p.blCartIds ?? []).length;
    if (wlCount) chips.push(`${wlCount} wanted list${wlCount !== 1 ? "s" : ""}`);
    if (blCount) chips.push(`${blCount} BL cart${blCount !== 1 ? "s" : ""}`);
    const lgCartCount = getProjectLegoCarts(p).filter(c => lgMap[c.cartId]).length;
    if (lgCartCount > 0) chips.push(`${lgCartCount} Pick-A-Brick cart${lgCartCount > 1 ? "s" : ""}`);
    return chips.length
      ? chips.map(c => `<span style="display:inline-block;padding:1px 7px;border-radius:3px;font-size:11px;background:#f0f4ff;color:#2563eb;margin-right:4px">${esc(c)}</span>`).join("")
      : `<span style="font-size:11px;color:#9ca3af">Not configured</span>`;
  }

  const cardsHtml = projects.map(p => {
    const pieces = poolPieceCount(p);
    return `
      <div style="background:#fff;border:1px solid #e1e4e8;border-radius:8px;padding:14px 18px;margin-bottom:10px;display:flex;align-items:center;gap:14px">
        <div style="flex:1;min-width:0">
          <div class="project-name-cell" data-id="${esc(p.id)}" style="display:flex;align-items:center;gap:8px;margin-bottom:5px">
            <button class="project-open-btn" data-id="${esc(p.id)}"
              style="background:none;border:none;padding:0;cursor:pointer;font-weight:600;font-size:14px;color:#1e2330;text-align:left">${esc(p.name)}</button>
            <button class="btn project-rename-btn" data-id="${esc(p.id)}"
              style="font-size:11px;padding:1px 6px;opacity:0.4;flex-shrink:0" title="Rename">✎</button>
          </div>
          <div>${metaChips(p)}</div>
        </div>
        <div style="text-align:right;flex-shrink:0;min-width:64px">
          <div style="font-size:20px;font-weight:700;color:#1e2330">${pieces.toLocaleString()}</div>
          <div style="font-size:11px;color:#6c757d">pieces</div>
        </div>
        <div style="flex-shrink:0;font-size:12px;color:#9ca3af;min-width:80px;text-align:right">${fmtDate(p.createdAt)}</div>
        <button class="btn btn-danger project-del-btn" data-id="${esc(p.id)}">Delete</button>
      </div>`;
  }).join("");

  content.innerHTML = `
    <div class="page-title">Projects</div>
    <div class="section">
      <div class="section-header">
        <span>My Projects</span>
        <button id="new-project-btn" style="margin-left:auto;font-size:12px;padding:2px 10px;background:#1e2330;color:#fff;border:none;border-radius:4px;cursor:pointer">+ New Project</button>
      </div>
      ${projects.length
        ? `<div style="padding:12px 14px">${cardsHtml}</div>`
        : `<div class="section-empty">No projects yet.<br>Create a project to plan your sourcing across multiple lists and carts.</div>`}
    </div>`;

  content.querySelector("#new-project-btn").addEventListener("click", async () => {
    const { projects: cur = [] } = await chrome.storage.local.get("projects");
    const id = crypto.randomUUID?.() ?? (Math.random().toString(36).slice(2) + Date.now().toString(36));
    cur.unshift({
      id,
      name: "New Project",
      createdAt: Date.now(),
      wantedListIds: [],
      blCartIds: [],
      legoCartIds: [],
      scratchWantedListId: null,
      allocations: {},
    });
    await chrome.storage.local.set({ projects: cur });
    await renderProjects(content);
    content.querySelector(`.project-rename-btn[data-id="${id}"]`)?.click();
  });

  for (const btn of content.querySelectorAll(".project-open-btn")) {
    btn.addEventListener("click", () => navigate(`project/${btn.dataset.id}`));
  }

  for (const btn of content.querySelectorAll(".project-del-btn")) {
    btn.addEventListener("click", async () => {
      const { projects: cur = [] } = await chrome.storage.local.get("projects");
      await chrome.storage.local.set({ projects: cur.filter(p => p.id !== btn.dataset.id) });
      renderProjects(content);
    });
  }

  for (const btn of content.querySelectorAll(".project-rename-btn")) {
    btn.addEventListener("click", () => {
      const id   = btn.dataset.id;
      const cell = content.querySelector(`.project-name-cell[data-id="${id}"]`);
      const currentName = cell.querySelector(".project-open-btn").textContent;

      cell.innerHTML = `<input class="project-rename-input" type="text" value="${esc(currentName)}"
        style="font-size:14px;padding:2px 6px;border:1px solid #2563eb;border-radius:4px;min-width:200px;box-sizing:border-box">`;
      const input = cell.querySelector(".project-rename-input");
      input.focus(); input.select();

      let saved = false;
      async function saveRename() {
        if (saved) return; saved = true;
        const newName = input.value.trim() || currentName;
        if (newName !== currentName) {
          const { projects: cur = [] } = await chrome.storage.local.get("projects");
          const proj = cur.find(p => p.id === id);
          if (proj) { proj.name = newName; await chrome.storage.local.set({ projects: cur }); }
        }
        renderProjects(content);
      }

      input.addEventListener("keydown", e => {
        if (e.key === "Enter")  { e.preventDefault(); saveRename(); }
        if (e.key === "Escape") { saved = true; renderProjects(content); }
      });
      input.addEventListener("blur", saveRename);
    });
  }
}

// ─── Project detail view ─────────────────────────────────────────────────────

async function renderProjectDetail(id, content) {
  // renderProjectDetail(id, content) is called repeatedly on the same
  // persistent `content` node (after saves, back-button, etc.) -- without
  // this, each call's addEventListener("click", ...) calls below stack a
  // fresh set of listeners on top of every prior render's, so a single click
  // fires N times after N renders (confirmed bug, 2026-07-16: dialogs/saves
  // needing 3 closes after the view had re-rendered 3 times). Tear down the
  // previous render's listeners before this render attaches its own.
  content._projectDetailCleanup?.();
  const _cleanupFns = [];
  content._projectDetailCleanup = () => { _cleanupFns.forEach(fn => fn()); _cleanupFns.length = 0; };
  function addListener(type, handler) {
    content.addEventListener(type, handler);
    _cleanupFns.push(() => content.removeEventListener(type, handler));
  }
  const addClick = handler => addListener("click", handler);

  // Auto-refresh when cart data changes underneath this tab (e.g. content.js
  // rescraping BrickLink in another tab) -- otherwise this view's blCartList
  // snapshot goes stale while left open, and totals silently drift from what's
  // actually in storage. Debounced so a burst of writes collapses into one
  // re-render; cleaned up via the same pattern as the DOM listeners above so
  // re-renders don't stack duplicate storage listeners.
  let storageRefreshTimer = null;
  function onCartStorageChanged(changes, area) {
    if (area !== "local" || (!changes.carts && !changes.legoCarts)) return;
    clearTimeout(storageRefreshTimer);
    storageRefreshTimer = setTimeout(() => { refresh(); }, 500);
  }
  chrome.storage.onChanged.addListener(onCartStorageChanged);
  _cleanupFns.push(() => {
    chrome.storage.onChanged.removeListener(onCartStorageChanged);
    clearTimeout(storageRefreshTimer);
  });

  const { projects = [], wantedLists = [], carts = [], legoCarts = [] } =
    await chrome.storage.local.get(["projects", "wantedLists", "carts", "legoCarts"]);
  const { ignoreLegoFees = false } = await chrome.storage.sync.get({ ignoreLegoFees: false });
  const project = projects.find(p => p.id === id);

  if (!project) {
    content.innerHTML = `
      <div class="detail-header">
        <button class="back-btn" id="back-btn">← Projects</button>
      </div>
      <div style="padding:24px;color:#6c757d;font-size:13px">Project not found.</div>`;
    content.querySelector("#back-btn").addEventListener("click", () => navigate("projects"));
    return;
  }

  const wlMap = Object.fromEntries(wantedLists.map(l => [l.id, l]));
  const blMap = Object.fromEntries(carts.map(l => [l.id, l]));
  const lgMap = Object.fromEntries(legoCarts.map(l => [l.id, l]));

  const poolMap = new Map();
  for (const lid of project.wantedListIds ?? []) {
    const list = wlMap[lid];
    if (!list) continue;
    for (const p of (list.parts ?? [])) {
      const key  = `${p.partNo}_${p.colorId}`;
      // Pool tracks what's still needed, not raw Want -- pieces already on hand
      // (Have) count as already satisfied, same as Copy to BL/PAB and every
      // other quantity consumer in this codebase (Math.max(0, want - have)).
      const need = Math.max(0, (p.want ?? p.qty ?? 1) - (p.have ?? 0));
      if (poolMap.has(key)) {
        poolMap.get(key).wantedQty += need;
      } else {
        poolMap.set(key, { ...p, wantedQty: need, pabEntry: null });
      }
    }
  }
  // Fully-satisfied parts (need === 0 across all pool lists) don't belong in
  // the pool at all -- nothing left to source for them.
  const poolParts = [...poolMap.values()].filter(p => p.wantedQty > 0);
  const totalPoolPieces = poolParts.reduce((s, p) => s + p.wantedQty, 0);

  const _projLgCarts = getProjectLegoCarts(project).map(c => ({ ...c, cart: lgMap[c.cartId] })).filter(c => c.cart);
  const legoCart     = _projLgCarts.find(c => c.role === "main")?.cart ?? _projLgCarts[0]?.cart ?? null;
  const blCartList  = (project.blCartIds ?? []).map(i => blMap[i]).filter(Boolean);
  const scratchList = project.scratchWantedListId ? wlMap[project.scratchWantedListId] : null;

  // ── allocation helpers ────────────────────────────────────────────────────

  function allocRemaining(allocs, key, wantedQty) {
    const a = allocs[key];
    if (!a) return wantedQty;
    const used = (a.legoQty ?? 0) + Object.values(a.storeQty ?? {}).reduce((s, v) => s + v, 0);
    return wantedQty - used;
  }

  // Bidirectional cart sync. Mutates allocs in-place. Returns count of adjustments.
  // Pass 1 — reduce: cap allocs to cart qty; remove allocs for parts gone from cart.
  // Pass 2 — fill:   for parts with scratch qty, fill back into any cart that has capacity.
  function pruneStaleAllocations(allocs, cartList) {
    let changed = 0;

    // Pass 1: reduce
    for (const [key, a] of Object.entries(allocs)) {
      if (!a.storeQty) continue;
      const [partNo, colorId] = key.split("_");
      for (const cartId of Object.keys(a.storeQty)) {
        const allocQty = a.storeQty[cartId] ?? 0;
        if (allocQty <= 0) continue;
        const cart = cartList.find(c => c.id === cartId);
        if (!cart) continue;
        const totalCartQty = (cart.parts ?? [])
          .filter(cp => cp.partNo === partNo && String(cp.colorId) === String(colorId))
          .reduce((s, cp) => s + (cp.qty ?? 1), 0);
        if (!totalCartQty) {
          delete a.storeQty[cartId]; changed++;
        } else if (allocQty > totalCartQty) {
          a.storeQty[cartId] = totalCartQty; changed++;
        }
      }
      if ((a.legoQty ?? 0) === 0 && !Object.keys(a.storeQty ?? {}).length && !a.excluded) {
        delete allocs[key];
      }
    }

    return changed;
  }

  // ── section builders ──────────────────────────────────────────────────────

  function buildSectionActionBar(selCount, srcType, srcCartId, targets) {
    if (!selCount) return "";
    const btns = targets.map(t => {
      const isSelf = t.type === srcType && t.cartId === srcCartId;
      if (isSelf) return "";
      const s = t.type === "lego"
        ? `style="font-size:12px;background:#eff6ff;border-color:#93c5fd;color:#1d4ed8"`
        : t.type === "pool"
        ? `style="font-size:12px;color:#6c757d"`
        : `style="font-size:12px"`;
      return `<button class="btn section-move-btn"
        data-src-type="${srcType}" data-src-cart="${esc(srcCartId ?? "")}"
        data-tgt-type="${t.type}" data-tgt-cart="${esc(t.cartId ?? "")}"
        ${s}>${t.label}</button>`;
    }).filter(Boolean).join(" ");
    return `<div style="display:flex;align-items:center;gap:8px;padding:6px 12px;background:#f8f9fa;border-bottom:1px solid #e1e4e8;flex-wrap:wrap">
      <span style="font-size:12px;color:#6c757d;flex-shrink:0">${selCount} selected</span>
      ${btns}
    </div>`;
  }

  function buildAllocRows(entries, sectionType, sectionCartId, selSet) {
    if (!entries.length) {
      return `<div style="font-size:12px;color:#9ca3af;padding:8px 14px 10px">Nothing allocated yet.</div>`;
    }
    if (sectionType === "bl") {
      const sort = blCartSort.get(sectionCartId) || "name_color";
      const d    = blCartSortDir.get(sectionCartId) === "desc" ? -1 : 1;
      const cart = blCartList.find(c => c.id === sectionCartId);
      entries = [...entries].sort((a, b) => {
        const pa = poolParts.find(p => `${p.partNo}_${p.colorId}` === a.key);
        const pb = poolParts.find(p => `${p.partNo}_${p.colorId}` === b.key);
        const na = (pa?.pabEntry?.bl_part_name || pa?.name || "").toLowerCase();
        const nb = (pb?.pabEntry?.bl_part_name || pb?.name || "").toLowerCase();
        const ca = (pa?.pabEntry?.bl_color_name || String(pa?.colorId ?? "")).toLowerCase();
        const cb = (pb?.pabEntry?.bl_color_name || String(pb?.colorId ?? "")).toLowerCase();
        const ia = pa?.partNo || "", ib = pb?.partNo || "";
        switch (sort) {
          case "partid_color": return d * (ia.localeCompare(ib, undefined, { numeric: true }) || ca.localeCompare(cb));
          case "partid":       return d * ia.localeCompare(ib, undefined, { numeric: true });
          case "color":        return d * (ca.localeCompare(cb) || na.localeCompare(nb));
          case "store_price": {
            const cpa = cart?.parts?.find(cp => cp.partNo === pa?.partNo && String(cp.colorId) === String(pa?.colorId));
            const cpb = cart?.parts?.find(cp => cp.partNo === pb?.partNo && String(cp.colorId) === String(pb?.colorId));
            return d * ((effectivePrice(cpa) ?? -1) - (effectivePrice(cpb) ?? -1));
          }
          case "pab_price": return d * ((pa?.pabEntry?.price_cents ?? -1) - (pb?.pabEntry?.price_cents ?? -1));
          case "channel": {
            const o = { pab: 0, bap: 1 };
            return d * ((o[pa?.pabEntry?.channel] ?? 2) - (o[pb?.pabEntry?.channel] ?? 2) || na.localeCompare(nb));
          }
          default: return d * (na.localeCompare(nb) || ca.localeCompare(cb));
        }
      });
    }
    if (sectionType === "lego") {
      const d = legoSectionSortDir === "desc" ? -1 : 1;
      entries = [...entries].sort((a, b) => {
        const pa = poolParts.find(p => `${p.partNo}_${p.colorId}` === a.key);
        const pb = poolParts.find(p => `${p.partNo}_${p.colorId}` === b.key);
        const na = (pa?.pabEntry?.bl_part_name || pa?.name || "").toLowerCase();
        const nb = (pb?.pabEntry?.bl_part_name || pb?.name || "").toLowerCase();
        const ca = (pa?.pabEntry?.bl_color_name || String(pa?.colorId ?? "")).toLowerCase();
        const cb = (pb?.pabEntry?.bl_color_name || String(pb?.colorId ?? "")).toLowerCase();
        const ia = pa?.partNo || "", ib = pb?.partNo || "";
        switch (legoSectionSort) {
          case "partid_color": return d * (ia.localeCompare(ib, undefined, { numeric: true }) || ca.localeCompare(cb));
          case "partid":       return d * ia.localeCompare(ib, undefined, { numeric: true });
          case "color":        return d * (ca.localeCompare(cb) || na.localeCompare(nb));
          case "pab_price":    return d * ((pa?.pabEntry?.price_cents ?? -1) - (pb?.pabEntry?.price_cents ?? -1));
          case "channel": {
            const o = { pab: 0, bap: 1 };
            return d * ((o[pa?.pabEntry?.channel] ?? 2) - (o[pb?.pabEntry?.channel] ?? 2) || na.localeCompare(nb));
          }
          default: return d * (na.localeCompare(nb) || ca.localeCompare(cb));
        }
      });
    }
    const allSelected = entries.every(e => selSet?.has(e.key));
    const showStore   = sectionType === "bl";
    const blCart      = showStore ? blCartList.find(c => c.id === sectionCartId) : null;
    const colHdr = `
      <div style="display:flex;align-items:center;gap:8px;padding:3px 12px;border-bottom:1px solid #e1e4e8;background:#fafbfc">
        <input type="checkbox" class="section-sel-all"
          data-section-type="${sectionType}" data-section-cart="${esc(sectionCartId ?? "")}"
          ${allSelected ? "checked" : ""}
          style="cursor:pointer;flex-shrink:0">
        <div style="font-size:10px;color:#9ca3af;flex-shrink:0;width:54px;text-transform:uppercase;letter-spacing:.04em">Part</div>
        <div style="width:36px;flex-shrink:0"></div>
        <div style="flex:1;font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:.04em">Name</div>
        ${showStore ? `<div style="font-size:10px;color:#9ca3af;flex-shrink:0;width:52px;text-align:right;text-transform:uppercase;letter-spacing:.04em">Store $</div>` : ""}
        <div style="font-size:10px;color:#9ca3af;flex-shrink:0;width:52px;text-align:right;text-transform:uppercase;letter-spacing:.04em">PAB $</div>
        <div style="font-size:10px;color:#9ca3af;flex-shrink:0;width:46px;text-align:center;text-transform:uppercase;letter-spacing:.04em">Ch</div>
        <div style="font-size:10px;color:#9ca3af;flex-shrink:0;width:24px;text-align:right;text-transform:uppercase;letter-spacing:.04em">Qty</div>
        <div style="width:26px;flex-shrink:0"></div>
      </div>`;
    const rows = entries.map(({ key, qty, cartPart: lotCartPart }) => {
      const part      = poolParts.find(p => `${p.partNo}_${p.colorId}` === key);
      const name      = part?.pabEntry?.bl_part_name || part?.name || key;
      const color     = part?.pabEntry?.bl_color_name || part?.colorName || "";
      const colorHex  = part?.pabEntry?.bl_color_hex;
      const pabPrice  = part?.pabEntry?.price_formatted || "—";
      const ch        = part?.pabEntry?.channel;
      const badge     = ch === "pab"
        ? `<span style="padding:1px 5px;border-radius:3px;font-size:10px;font-weight:700;background:#dcfce7;color:#16a34a">PAB</span>`
        : ch === "bap"
        ? `<span style="padding:1px 5px;border-radius:3px;font-size:10px;font-weight:700;background:#fef9c3;color:#ca8a04">STD</span>`
        : part?.pabEntry
        ? `<span style="padding:1px 5px;border-radius:3px;font-size:10px;font-weight:700;background:#f3f4f6;color:#6c757d">BL</span>`
        : `<span style="color:#9ca3af">—</span>`;
      const cartPart  = lotCartPart ?? blCart?.parts?.find(cp => cp.partNo === part?.partNo && String(cp.colorId) === String(part?.colorId));
      const storeNum  = effectivePrice(cartPart);
      const pabNum    = part?.pabEntry?.price_cents ? part.pabEntry.price_cents / 100 : null;
      const pabCheaper = showStore && storeNum != null && pabNum != null && pabNum < storeNum;
      const storeColor = pabCheaper ? "#dc2626" : "#374151";
      const pct        = pctVsPab(storeNum, pabNum);
      const pctBadge    = pct != null
        ? `<div style="font-size:10px;font-weight:700;color:${pct < 0 ? "#16a34a" : "#dc2626"}">${pct < 0 ? "▼" : "▲"}${Math.abs(pct).toFixed(0)}%</div>`
        : "";
      const storeCell = showStore
        ? `<div style="font-size:12px;color:${storeColor};flex-shrink:0;width:52px;text-align:right">${storeNum != null ? `$${storeNum.toFixed(2)}` : "—"}${pctBadge}</div>`
        : "";
      const rowBg     = pabCheaper ? "background:#fff5f5;" : "";
      const img = part?.imageUrl
        ? `<img src="${esc(part.imageUrl)}" style="width:36px;height:28px;object-fit:contain;flex-shrink:0">`
        : `<div style="width:36px;flex-shrink:0"></div>`;
      const isChecked = selSet?.has(key) ?? false;
      return `
        <div style="display:flex;align-items:center;gap:8px;padding:4px 12px;border-bottom:1px solid #f3f4f6;${rowBg}">
          <label style="cursor:pointer;display:flex;align-items:center;align-self:stretch;padding:0 4px;margin:0 -4px"><input type="checkbox" class="section-row-check"
            data-section-type="${sectionType}"
            data-section-cart="${esc(sectionCartId ?? "")}"
            data-key="${esc(key)}"
            ${isChecked ? "checked" : ""}
            style="cursor:pointer;flex-shrink:0"></label>
          <a href="https://www.bricklink.com/v2/catalog/catalogitem.page?P=${esc(part?.partNo || key.split('_')[0])}#T=C&C=${esc(String(part?.colorId ?? ''))}" target="_blank" rel="noopener" style="font-size:11px;font-family:monospace;color:#6c757d;flex-shrink:0;width:54px;text-decoration:none;display:flex;align-items:center;align-self:stretch" title="View on BrickLink">${esc(part?.partNo || key.split('_')[0])}</a>
          ${img}
          <div style="flex:1;min-width:0;font-size:12px;line-height:1.3">${esc(name)}<br><span style="display:inline-flex;align-items:center;gap:3px;color:#9ca3af;font-size:11px">${colorHex ? `<span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#${esc(colorHex)};border:1px solid rgba(0,0,0,0.2);flex-shrink:0"></span>` : ""}${esc(color)}</span></div>
          ${storeCell}
          <div style="font-size:12px;color:#6c757d;flex-shrink:0;width:52px;text-align:right">${pabPrice}</div>
          <div style="flex-shrink:0;width:46px;text-align:center">${badge}</div>
          <div style="font-size:13px;font-weight:600;flex-shrink:0;width:24px;text-align:right">${qty}</div>
          <button class="btn btn-danger"
            data-unalloc-key="${esc(key)}"
            data-unalloc-type="${sectionType}"
            data-unalloc-cart="${esc(sectionCartId ?? "")}"
            style="padding:1px 6px;font-size:12px;flex-shrink:0">×</button>
        </div>`;
    }).join("");
    return `${colHdr}<div style="max-height:460px;overflow-y:auto">${rows}</div>`;
  }

  function buildLegoSection(allocs) {
    const allLegoAllocs = Object.entries(allocs)
      .filter(([, a]) => (a.legoQty ?? 0) > 0)
      .map(([key, a]) => ({ key, qty: a.legoQty }));
    if (!legoCart && !allLegoAllocs.length) {
      return `
        <div class="section-header"><span>Pick-A-Brick Cart</span></div>
        <div class="section-empty" style="padding:16px">No Pick-A-Brick cart selected. <button class="proj-configure-link back-btn" style="font-size:12px;color:#2563eb">Configure</button> to add one.</div>`;
    }
    const getChannel = key => poolParts.find(p => `${p.partNo}_${p.colorId}` === key)?.pabEntry?.channel;
    const bsCount    = allLegoAllocs.filter(e => getChannel(e.key) === "pab").length;
    const stdCount   = allLegoAllocs.filter(e => getChannel(e.key) === "bap").length;
    const legoAllocs = legoSectionTab === "pab" ? allLegoAllocs.filter(e => getChannel(e.key) === "pab")
                     : legoSectionTab === "bap" ? allLegoAllocs.filter(e => getChannel(e.key) === "bap")
                     : allLegoAllocs;
    const allocPcs   = legoAllocs.reduce((s, e) => s + e.qty, 0);
    const selCount   = legoAllocs.filter(e => selectedLegoKeys.has(e.key)).length;
    const targets    = [
      ...blCartList.map(c => ({ type: "bl",   cartId: c.id, label: `→ ${esc(c.name)}` })),
      { type: "pool", cartId: "", label: "Return to pool" }
    ];
    const tabStyle = (key, bg) => {
      const active = legoSectionTab === key;
      return `padding:5px 10px;font-size:12px;border:none;background:${active ? bg : "transparent"};
              color:${active ? "#111" : "#6c757d"};cursor:pointer;border-bottom:2px solid ${active ? "#374151" : "transparent"};
              font-weight:${active ? "600" : "400"}`;
    };
    // Cost summary
    let legoParts = 0, legoBsParts = 0, legoStdParts = 0, legoPartsKnown = true;
    for (const { key, qty } of allLegoAllocs) {
      const part = poolParts.find(p => `${p.partNo}_${p.colorId}` === key);
      if (part?.pabEntry?.price_cents) {
        const cost = (part.pabEntry.price_cents / 100) * qty;
        legoParts += cost;
        if (part.pabEntry.channel === "pab") legoBsParts += cost;
        else if (part.pabEntry.channel === "bap") legoStdParts += cost;
      } else legoPartsKnown = false;
    }
    const svcFee   = (!ignoreLegoFees && legoPartsKnown && legoParts < 14 && allLegoAllocs.length > 0) ? 7 : 0;
    const legShip  = ignoreLegoFees ? 0 : legoParts >= 35 ? 0 : legoParts <= 25 ? 4.95 : 6.95;
    const legoGrand = legoParts + svcFee + legShip;
    const legoSummary = allLegoAllocs.length === 0 ? "" : `
      <div style="display:flex;flex-wrap:wrap;align-items:center;gap:12px;padding:5px 14px;background:#f8f9fa;border-bottom:1px solid #e1e4e8;font-size:12px;color:#374151">
        <span>Parts: <strong>${legoPartsKnown ? `$${ceilToCents(legoParts).toFixed(2)}` : `~$${ceilToCents(legoParts).toFixed(2)}`}</strong></span>
        ${legoBsParts > 0 ? `<span style="color:#15803d">BS: <strong>$${ceilToCents(legoBsParts).toFixed(2)}</strong></span>` : ""}
        ${legoStdParts > 0 ? `<span style="color:#ca8a04">STD: <strong>$${ceilToCents(legoStdParts).toFixed(2)}</strong></span>` : ""}
        ${svcFee ? `<span style="color:#dc2626">Service fee: <strong>$7.00</strong> <span style="color:#9ca3af;font-weight:400">(under $14 order)</span></span>` : ""}
        ${!ignoreLegoFees ? `<span>Shipping: <strong>${legShip === 0 ? "Free" : `$${legShip.toFixed(2)}`}</strong></span>` : ""}
        ${(!ignoreLegoFees || svcFee) ? `<span style="margin-left:auto;font-weight:700">Total: ${legoPartsKnown ? `$${ceilToCents(legoGrand).toFixed(2)}` : `~$${ceilToCents(legoGrand).toFixed(2)}`}</span>` : ""}
      </div>`;
    const legoSortOpts = [
      ["name_color",  "Name+Color"],
      ["partid_color","Part+Color"],
      ["partid",      "Part ID"],
      ["color",       "Color"],
      ["pab_price",   "PAB $"],
      ["channel",     "Channel"],
    ].map(([v, l]) => `<option value="${v}"${legoSectionSort === v ? " selected" : ""}>${l}</option>`).join("");
    return `
      <div class="section-header">
        <span>Pick-A-Brick Cart</span>
        ${allLegoAllocs.length > 0 ? `
          <div style="display:flex;align-items:center;gap:4px">
            <span style="font-size:11px;color:#6c757d;font-weight:400;margin-right:2px">Transfer:</span>
            <button class="lego-proj-transfer-btn btn" data-channel="pab" style="font-size:11px;padding:2px 8px;background:#dcfce7;color:#15803d;border-color:#86efac">PAB</button>
            ${stdCount > 0 ? `<button class="lego-proj-transfer-btn btn" data-channel="bap" style="font-size:11px;padding:2px 8px;background:#fef9c3;color:#a16207;border-color:#fde047">STD</button>` : ""}
            <button class="lego-proj-transfer-btn btn" data-channel="both" style="font-size:11px;padding:2px 8px">ALL</button>
          </div>` : ""}
      </div>
      <div style="display:flex;align-items:center;gap:12px;padding:8px 12px;border-bottom:1px solid #e1e4e8">
        <div style="flex:1">
          ${legoCart
            ? `<div style="font-size:13px;font-weight:600">${esc(legoCart.name)}</div>
               ${_projLgCarts.length > 1 ? `<div style="font-size:11px;color:#6c757d;margin-top:2px">${_projLgCarts.slice(1).map(c => `${esc(c.cart.name)} <span style="opacity:0.7">(${ROLE_LABELS[c.role] ?? c.role})</span>`).join(" · ")}</div>` : ""}`
            : `<div style="font-size:12px;color:#d97706">No Pick-A-Brick cart linked — <button class="proj-configure-link back-btn" style="font-size:12px;color:#2563eb;background:none;border:none;padding:0;cursor:pointer">Configure</button> to add one</div>`}
          <div style="font-size:12px;color:#6c757d">${allLegoAllocs.length} lots · ${allocPcs.toLocaleString()} pieces assigned</div>
        </div>
        ${legoCart ? `
          <button class="btn lego-save-btn" style="font-size:12px;background:#1e2330;color:#fff;border-color:#1e2330">Save to Cart ↓</button>
          <button class="btn open-cart-btn" data-type="legoCarts" data-id="${esc(legoCart.id)}" style="font-size:12px">Open ↗</button>
        ` : ""}
      </div>
      <div style="display:flex;align-items:center;gap:6px;padding:4px 12px;border-bottom:1px solid #e1e4e8;background:#fafbfc">
        <select class="lego-sort" style="font-size:11px;padding:2px 4px;border:1px solid #d1d5db;border-radius:3px;color:#374151">${legoSortOpts}</select>
        <button class="btn lego-sort-dir" style="font-size:11px;padding:2px 5px;background:#fff;border:1px solid #d1d5db;color:#374151">${legoSectionSortDir === "desc" ? "↓" : "↑"}</button>
      </div>
      ${legoSummary}
      <div style="display:flex;border-bottom:1px solid #e1e4e8;background:#fafbfc">
        <button class="lego-tab-btn" data-lego-tab="all" style="${tabStyle("all","#f3f4f6")}">All (${allLegoAllocs.length})</button>
        <button class="lego-tab-btn" data-lego-tab="pab" style="${tabStyle("pab","#dcfce7")}">PAB (${bsCount})</button>
        <button class="lego-tab-btn" data-lego-tab="bap" style="${tabStyle("bap","#fef3c7")}">STD (${stdCount})</button>
      </div>
      ${buildSectionActionBar(selCount, "lego", "", targets)}
      ${buildAllocRows(legoAllocs, "lego", "", selectedLegoKeys)}`;
  }

  // Distributes an allocated quantity across a part+color's physical lots in a
  // cart, cheapest lot first. Shared by buildBlSection (per-cart total) and
  // buildGrandTotal (project-wide total) so they can never disagree about which
  // lots an allocation actually covers.
  function distributeLots(cart, partNo, colorId, allocQty) {
    // colorId arrives pre-stringified from an allocation key split
    // (`${partNo}_${colorId}`.split("_")), so a wildcard allocation's
    // colorId -- real JS null, meaning "(Not Applicable)"/any color -- shows
    // up here as the literal string "null". Match on partNo alone in that
    // case, mirroring the same relaxation in the Auto Allocate click
    // handler's own cart-lot scan -- otherwise a real cart lot (which always
    // has one concrete, non-null color) can never match, and the allocated
    // quantity silently vanishes from both buildBlSection's line-item table
    // and buildGrandTotal's dollar total, which both share this function.
    // Found 2026-07-28: recorded correctly in proj.allocations, just never
    // rendered or totaled.
    const isWildcard = colorId == null || colorId === "null";
    const matchingLots = (cart.parts ?? [])
      .filter(cp => cp.partNo === partNo && (isWildcard || String(cp.colorId) === String(colorId)))
      .map(cp => ({ cp, price: parseStorePrice(cp.storePrice) ?? Infinity }))
      .sort((a, b) => a.price - b.price);
    const result = [];
    let remaining = allocQty;
    for (const { cp } of matchingLots) {
      if (remaining <= 0) break;
      const take = Math.min(remaining, cp.qty ?? 1);
      result.push({ cartPart: cp, qty: take });
      remaining -= take;
    }
    return result;
  }

  function buildBlSection(cart, allocs) {
    // Build one row per lot, but only up to the allocated qty for each part+color.
    // Takes cheapest lots first so expensive extras don't appear when allocQty < total cart qty.
    const blAllocs = [];
    for (const [key, alloc] of Object.entries(allocs)) {
      const allocQty = alloc.storeQty?.[cart.id] ?? 0;
      if (allocQty <= 0) continue;
      const [partNo, colorId] = key.split("_");
      for (const { cartPart, qty } of distributeLots(cart, partNo, colorId, allocQty)) {
        blAllocs.push({ key, qty, cartPart });
      }
    }
    const allocPcs   = blAllocs.reduce((s, e) => s + e.qty, 0);
    const selSet     = selectedBlKeys.get(cart.id) ?? new Set();
    const selCount   = blAllocs.filter(e => selSet.has(e.key)).length;
    const targets    = [
      ...blCartList.filter(c => c.id !== cart.id).map(c => ({ type: "bl", cartId: c.id, label: `→ ${esc(c.name)}` })),
      { type: "lego", cartId: "", label: "→ Pick-A-Brick Cart" },
      { type: "pool", cartId: "", label: "Return to pool" }
    ];
    // Cost summary
    let blTotal = 0, blTotalKnown = true;
    let pabPartsTotal = 0, pabNetPartsOnly = 0, pabNetLots = 0, blPabTotal = 0;
    for (const { key, qty, cartPart } of blAllocs) {
      const part     = poolParts.find(p => `${p.partNo}_${p.colorId}` === key);
      const blPrice  = effectivePrice(cartPart);
      if (blPrice != null) blTotal += blPrice * qty;
      else blTotalKnown = false;
      if (blPrice != null) {
        const pabCents = part?.pabEntry?.price_cents;
        // BL-only parts (no PAB price) are neutral — excluded from PAB comparison
        if (pabCents != null) {
          pabPartsTotal   += (pabCents / 100) * qty;
          pabNetPartsOnly += (pabCents / 100 - blPrice) * qty;
          blPabTotal      += blPrice * qty;
        }
        pabNetLots++;
      }
    }
    const rawShip      = cart.orderSummary?.shipping?.replace(/^US\s+/, "");
    const rawOrderTot  = cart.orderSummary?.orderTotal?.replace(/^US\s+/, "");
    const shipNum      = parseStorePrice(rawShip);
    // TBD: not captured, is $0, or BL DOM bled the order total into the shipping field
    const shipIsTbd    = shipNum == null || shipNum === 0 || rawShip === rawOrderTot;
    const estShipVal   = estBlShipping[cart.id] ?? "";
    const effShip      = shipIsTbd ? (estBlShipping[cart.id] ?? 0) : (shipNum ?? 0);
    // vs-PAB: pure part-price delta only (no shipping, no LEGO fees — those belong in totals)
    const pabNetTotal  = pabNetPartsOnly;
    const shipKnown    = !shipIsTbd || (estBlShipping[cart.id] != null);
    const blTotalStr   = blAllocs.length ? `${blTotalKnown ? "" : "~"}$${ceilToCents(blTotal).toFixed(2)}` : null;
    const blGrandStr   = blTotalStr ? `${blTotalKnown && !shipIsTbd ? "" : "~"}$${ceilToCents(blTotal + effShip).toFixed(2)}` : null;
    // Show PAB-comparable store subtotal when BL-only parts are present, so the savings
    // figure isn't confusingly close to the full cart total.
    const hasBLOnly    = blPabTotal < blTotal - 0.001;
    const pabNetStr    = pabNetLots > 0 && pabPartsTotal > 0 && pabNetTotal !== 0
      ? `PAB Savings $${Math.abs(pabNetTotal).toFixed(2)}`
      : null;
    const pabNetColor  = pabNetTotal > 0 ? "#16a34a" : pabNetTotal < 0 ? "#dc2626" : "#6b7280";
    const blSummary    = blTotalStr ? `
      <div style="display:flex;flex-wrap:wrap;align-items:center;gap:12px;padding:5px 14px;background:#f8f9fa;border-bottom:1px solid #e1e4e8;font-size:12px;color:#374151">
        <span>Parts: <strong>${blTotalStr}</strong></span>
        ${shipIsTbd
          ? `<label style="display:flex;align-items:center;gap:4px;color:#6c757d">Est. ship: <input type="number" class="bl-est-ship" data-cart-id="${esc(cart.id)}" min="0" step="0.01" value="${estShipVal}" placeholder="0.00" style="width:68px;padding:1px 5px;border:1px solid #d1d5db;border-radius:3px;font-size:12px;color:#374151"></label>`
          : `<span>Shipping: <strong>${rawShip}</strong></span>`}
        ${pabNetStr ? `<span style="color:${pabNetColor};font-weight:600">${esc(pabNetStr)}</span>` : ""}
        ${blGrandStr ? `<span style="margin-left:auto;font-weight:700">Total: ${blGrandStr}</span>` : ""}
      </div>` : "";
    const selBtnStyle = "font-size:11px;padding:2px 7px;background:#fff;border:1px solid #d1d5db;color:#374151";
    const cartSort    = blCartSort.get(cart.id)    || "name_color";
    const cartSortDir = blCartSortDir.get(cart.id) || "asc";
    const sortOpts    = [
      ["name_color",  "Name+Color"],
      ["partid_color","Part+Color"],
      ["partid",      "Part ID"],
      ["color",       "Color"],
      ["store_price", "Store $"],
      ["pab_price",   "PAB $"],
      ["channel",     "Channel"],
    ].map(([v, l]) => `<option value="${v}"${cartSort === v ? " selected" : ""}>${l}</option>`).join("");
    return `
      <div class="section-header">
        <span>${esc(cart.name)}</span>
        <button class="btn bl-cart-refresh-btn" data-cart-id="${esc(cart.id)}" style="margin-left:auto;font-size:12px" title="Reload cart from saved data and clear stale allocations">↻ Refresh</button>
        <button class="btn bl-cart-save-btn" data-cart-id="${esc(cart.id)}" style="font-size:12px;background:#1e2330;color:#fff;border-color:#1e2330">Save Cart ↓</button>
      </div>
      <div style="display:flex;align-items:center;gap:6px;padding:6px 12px;border-bottom:1px solid #e1e4e8;flex-wrap:wrap">
        <div style="font-size:12px;color:#6c757d">${blAllocs.length} lots · ${allocPcs.toLocaleString()} pieces assigned</div>
        <select class="bl-cart-sort" data-cart-id="${esc(cart.id)}" style="font-size:11px;padding:2px 4px;border:1px solid #d1d5db;border-radius:3px;color:#374151;margin-left:6px">${sortOpts}</select>
        <button class="btn bl-cart-sort-dir" data-cart-id="${esc(cart.id)}" style="${selBtnStyle};padding:2px 5px">${cartSortDir === "desc" ? "↓" : "↑"}</button>
        <div style="flex:1"></div>
        <button class="btn bl-sel-channel" data-cart-id="${esc(cart.id)}" data-channel="pab" style="${selBtnStyle};background:#f0fdf4;border-color:#86efac" title="Select all PAB parts">☑ PAB</button>
        <button class="btn bl-sel-channel" data-cart-id="${esc(cart.id)}" data-channel="bap" style="${selBtnStyle};background:#fef9c3;border-color:#fcd34d" title="Select all STD parts">☑ STD</button>
        <button class="btn bl-sel-pab-cheaper" data-cart-id="${esc(cart.id)}" style="${selBtnStyle}" title="Select all where store price exceeds PAB price">☑ PAB cheaper</button>
        <button class="btn open-cart-btn" data-type="carts" data-id="${esc(cart.id)}" style="font-size:12px">Open ↗</button>
      </div>
      ${blSummary}
      ${buildSectionActionBar(selCount, "bl", cart.id, targets)}
      ${buildAllocRows(blAllocs, "bl", cart.id, selSet)}`;
  }

  function buildScratchSection(allocs) {
    let scratchEntries = poolParts
      .filter(p => {
        const a = allocs[`${p.partNo}_${p.colorId}`];
        if (!a) return true;
        if (a.removed || a.excluded) return false;
        const total = (a.legoQty ?? 0) + Object.values(a.storeQty ?? {}).reduce((s, v) => s + v, 0);
        return total === 0;
      })
      .map(p => ({ key: `${p.partNo}_${p.colorId}`, qty: p.wantedQty, p }));
    const scratchPieces = scratchEntries.reduce((s, e) => s + e.qty, 0);
    const selCount      = scratchEntries.filter(e => selectedScratchKeys.has(e.key)).length;
    const targets       = [
      { type: "lego", cartId: "", label: "→ Pick-A-Brick Cart" },
      ...blCartList.map(c => ({ type: "bl", cartId: c.id, label: `→ ${esc(c.name)}` }))
    ];
    const header = `
      <div class="section-header">
        <span>Scratch Space</span>
        <span style="font-size:12px;color:#9ca3af;font-weight:400;margin-left:8px">${scratchList ? `linked to ${esc(scratchList.name)}` : "ephemeral"}</span>
        <button class="btn scratch-save-btn" style="margin-left:auto;font-size:12px;background:#1e2330;color:#fff;border-color:#1e2330">Save to List ↓</button>
      </div>`;
    if (!poolParts.length) {
      return `${header}<div style="padding:10px 16px;font-size:13px;color:#9ca3af">No parts in pool yet.</div>`;
    }
    if (!scratchEntries.length) {
      return `${header}<div style="padding:10px 16px;font-size:12px;color:#9ca3af">All parts allocated.</div>`;
    }
    const scratchD = scratchSortDir === "desc" ? -1 : 1;
    scratchEntries = [...scratchEntries].sort((a, b) => {
      const pa = a.p, pb = b.p;
      const na = (pa.pabEntry?.bl_part_name || pa.name || "").toLowerCase();
      const nb = (pb.pabEntry?.bl_part_name || pb.name || "").toLowerCase();
      const ca = (pa.pabEntry?.bl_color_name || String(pa.colorId ?? "")).toLowerCase();
      const cb = (pb.pabEntry?.bl_color_name || String(pb.colorId ?? "")).toLowerCase();
      const ia = pa.partNo || "", ib = pb.partNo || "";
      switch (scratchSort) {
        case "partid_color": return scratchD * (ia.localeCompare(ib, undefined, { numeric: true }) || ca.localeCompare(cb));
        case "partid":       return scratchD * ia.localeCompare(ib, undefined, { numeric: true });
        case "color":        return scratchD * (ca.localeCompare(cb) || na.localeCompare(nb));
        case "pab_price":    return scratchD * ((pa.pabEntry?.price_cents ?? -1) - (pb.pabEntry?.price_cents ?? -1));
        case "channel": {
          const o = { pab: 0, bap: 1 };
          return scratchD * ((o[pa.pabEntry?.channel] ?? 2) - (o[pb.pabEntry?.channel] ?? 2) || na.localeCompare(nb));
        }
        default: return scratchD * (na.localeCompare(nb) || ca.localeCompare(cb));
      }
    });
    const allScratchSelected = scratchEntries.every(e => selectedScratchKeys.has(e.key));
    const scratchColHdr = `
      <div style="display:flex;align-items:center;gap:8px;padding:3px 12px;border-bottom:1px solid #e1e4e8;background:#fafbfc">
        <input type="checkbox" class="section-sel-all"
          data-section-type="scratch" data-section-cart=""
          ${allScratchSelected ? "checked" : ""}
          style="cursor:pointer;flex-shrink:0">
        <div style="font-size:10px;color:#9ca3af;flex-shrink:0;width:54px;text-transform:uppercase;letter-spacing:.04em">Part</div>
        <div style="width:36px;flex-shrink:0"></div>
        <div style="flex:1;font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:.04em">Name</div>
        <div style="font-size:10px;color:#9ca3af;flex-shrink:0;width:52px;text-align:right;text-transform:uppercase;letter-spacing:.04em">PAB $</div>
        <div style="font-size:10px;color:#9ca3af;flex-shrink:0;width:46px;text-align:center;text-transform:uppercase;letter-spacing:.04em">Ch</div>
        <div style="font-size:10px;color:#9ca3af;flex-shrink:0;width:24px;text-align:right;text-transform:uppercase;letter-spacing:.04em">Qty</div>
      </div>`;
    const rows = scratchEntries.map(({ key, qty, p }) => {
      const name     = p.pabEntry?.bl_part_name  || p.name      || "";
      const color    = p.pabEntry?.bl_color_name || p.colorName || "";
      const colorHex = p.pabEntry?.bl_color_hex;
      const price    = p.pabEntry?.price_formatted || "—";
      const ch       = p.pabEntry?.channel;
      const badge    = ch === "pab"
        ? `<span style="padding:1px 5px;border-radius:3px;font-size:10px;font-weight:700;background:#dcfce7;color:#16a34a">PAB</span>`
        : ch === "bap"
        ? `<span style="padding:1px 5px;border-radius:3px;font-size:10px;font-weight:700;background:#fef9c3;color:#ca8a04">STD</span>`
        : p.pabEntry
        ? `<span style="padding:1px 5px;border-radius:3px;font-size:10px;font-weight:700;background:#f3f4f6;color:#6c757d">BL</span>`
        : `<span style="color:#9ca3af">—</span>`;
      const img      = p.imageUrl
        ? `<img src="${esc(p.imageUrl)}" style="width:36px;height:28px;object-fit:contain;flex-shrink:0">`
        : `<div style="width:36px;flex-shrink:0"></div>`;
      return `
        <div style="display:flex;align-items:center;gap:8px;padding:4px 12px;border-bottom:1px solid #f3f4f6">
          <label style="cursor:pointer;display:flex;align-items:center;align-self:stretch;padding:0 4px;margin:0 -4px"><input type="checkbox" class="section-row-check"
            data-section-type="scratch" data-section-cart="" data-key="${esc(key)}"
            ${selectedScratchKeys.has(key) ? "checked" : ""}
            style="cursor:pointer;flex-shrink:0"></label>
          <a href="https://www.bricklink.com/v2/catalog/catalogitem.page?P=${esc(p.partNo || '')}#T=C&C=${esc(String(p.colorId ?? ''))}" target="_blank" rel="noopener" style="font-size:11px;font-family:monospace;color:#6c757d;flex-shrink:0;width:54px;text-decoration:none;display:flex;align-items:center;align-self:stretch" title="View on BrickLink">${esc(p.partNo || "")}</a>
          ${img}
          <div style="flex:1;min-width:0;font-size:12px;line-height:1.3">${esc(name)}<br><span style="display:inline-flex;align-items:center;gap:3px;color:#9ca3af;font-size:11px">${colorHex ? `<span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#${esc(colorHex)};border:1px solid rgba(0,0,0,0.2);flex-shrink:0"></span>` : ""}${esc(color)}</span></div>
          <div style="font-size:12px;color:#6c757d;flex-shrink:0;width:52px;text-align:right">${price}</div>
          <div style="flex-shrink:0;width:46px;text-align:center">${badge}</div>
          <div style="font-size:13px;font-weight:600;flex-shrink:0;width:24px;text-align:right">${qty}</div>
        </div>`;
    }).join("");
    const scratchSortOpts = [
      ["name_color",  "Name+Color"],
      ["partid_color","Part+Color"],
      ["partid",      "Part ID"],
      ["color",       "Color"],
      ["pab_price",   "PAB $"],
      ["channel",     "Channel"],
    ].map(([v, l]) => `<option value="${v}"${scratchSort === v ? " selected" : ""}>${l}</option>`).join("");
    return `${header}
      <div style="display:flex;align-items:center;gap:6px;padding:4px 12px;border-bottom:1px solid #f3f4f6">
        <span style="font-size:12px;color:#6c757d">${scratchEntries.length} lots · ${scratchPieces.toLocaleString()} pieces</span>
        <select class="scratch-sort" style="font-size:11px;padding:2px 4px;border:1px solid #d1d5db;border-radius:3px;color:#374151;margin-left:4px">${scratchSortOpts}</select>
        <button class="btn scratch-sort-dir" style="font-size:11px;padding:2px 5px;background:#fff;border:1px solid #d1d5db;color:#374151">${scratchSortDir === "desc" ? "↓" : "↑"}</button>
      </div>
      ${buildSectionActionBar(selCount, "scratch", "", targets)}
      ${scratchColHdr}
      <div style="max-height:460px;overflow-y:auto">${rows}</div>`;
  }

  // ── actions ───────────────────────────────────────────────────────────────

  let currentAllocs      = project.allocations ?? {};
  {
    const cleared = pruneStaleAllocations(currentAllocs, blCartList);
    if (cleared) {
      project.allocations = currentAllocs;
      await chrome.storage.local.set({ projects });
    }
  }
  let legoSectionTab     = "all";
  let legoSectionSort    = "name_color";
  let legoSectionSortDir = "asc";
  let scratchSort        = "name_color";
  let scratchSortDir     = "asc";
  estBlShipping       = project.estimatedShipping ?? {};

  function isPabEligible(key) {
    const ch = poolParts.find(p => `${p.partNo}_${p.colorId}` === key)?.pabEntry?.channel;
    return ch === "pab" || ch === "bap";
  }

  async function onMove(targetType, cartId) {
    if (!selectedPoolKeys.size) return;
    if (targetType === "lego") {
      const nonPab = [...selectedPoolKeys].filter(key => !isPabEligible(key));
      for (const key of nonPab) selectedPoolKeys.delete(key);
      if (nonPab.length) {
        const names = nonPab.slice(0, 8).map(key => {
          const part = poolParts.find(p => `${p.partNo}_${p.colorId}` === key);
          return `• ${part?.pabEntry?.bl_part_name || part?.name || key}`;
        });
        const extra = nonPab.length > 8 ? `\n+ ${nonPab.length - 8} more` : "";
        if (!selectedPoolKeys.size) {
          alert(`None of the selected parts are available on LEGO PAB/BAP:\n${names.join("\n")}${extra}`);
          return;
        }
        if (!confirm(`${nonPab.length} selected part(s) are not on LEGO PAB/BAP and will be skipped:\n${names.join("\n")}${extra}\n\nMove the ${selectedPoolKeys.size} PAB/BAP part(s) to Pick-A-Brick Cart?`)) return;
      }
      if (!selectedPoolKeys.size) return;
    }
    if (targetType === "bl") {
      const tgtCart = blCartList.find(c => c.id === cartId);
      const missing = [...selectedPoolKeys].filter(key => {
        const part = poolParts.find(p => `${p.partNo}_${p.colorId}` === key);
        return !tgtCart?.parts?.some(cp => cp.partNo === part?.partNo && String(cp.colorId) === String(part?.colorId));
      });
      if (missing.length) {
        const names = missing.slice(0, 5).map(key => {
          const part = poolParts.find(p => `${p.partNo}_${p.colorId}` === key);
          return `• ${part?.pabEntry?.bl_part_name || part?.name || key}`;
        });
        const extra = missing.length > 5 ? `\n+ ${missing.length - 5} more` : "";
        if (!confirm(`${missing.length} part(s) are not stocked in "${tgtCart?.name}":\n${names.join("\n")}${extra}\n\nAllocate anyway?`)) return;
      }
    }
    const { projects: allProjects = [] } = await chrome.storage.local.get("projects");
    const proj = allProjects.find(p => p.id === id);
    if (!proj) return;
    if (!proj.allocations) proj.allocations = {};
    for (const key of selectedPoolKeys) {
      const part = poolParts.find(p => `${p.partNo}_${p.colorId}` === key);
      if (!part) continue;
      const rem = allocRemaining(proj.allocations, key, part.wantedQty);
      if (rem <= 0) continue;
      if (!proj.allocations[key]) proj.allocations[key] = { legoQty: 0, storeQty: {} };
      if (targetType === "lego") {
        proj.allocations[key].legoQty = (proj.allocations[key].legoQty ?? 0) + rem;
      } else {
        if (!proj.allocations[key].storeQty) proj.allocations[key].storeQty = {};
        proj.allocations[key].storeQty[cartId] = (proj.allocations[key].storeQty[cartId] ?? 0) + rem;
      }
    }
    await chrome.storage.local.set({ projects: allProjects });
    selectedPoolKeys.clear();
    await refresh();
  }

  async function onSectionMove(srcType, srcCartId, tgtType, tgtCartId) {
    let selKeys;
    if (srcType === "lego")    selKeys = [...selectedLegoKeys];
    else if (srcType === "bl") selKeys = [...(selectedBlKeys.get(srcCartId) ?? new Set())];
    else                       selKeys = [...selectedScratchKeys];
    if (!selKeys.length) return;

    if (tgtType === "lego") {
      const nonPab = selKeys.filter(key => !isPabEligible(key));
      selKeys = selKeys.filter(isPabEligible);
      if (nonPab.length) {
        const names = nonPab.slice(0, 8).map(key => {
          const part = poolParts.find(p => `${p.partNo}_${p.colorId}` === key);
          return `• ${part?.pabEntry?.bl_part_name || part?.name || key}`;
        });
        const extra = nonPab.length > 8 ? `\n+ ${nonPab.length - 8} more` : "";
        if (!selKeys.length) {
          alert(`None of the selected parts are available on LEGO PAB/BAP:\n${names.join("\n")}${extra}`);
          return;
        }
        if (!confirm(`${nonPab.length} selected part(s) are not on LEGO PAB/BAP and will be skipped:\n${names.join("\n")}${extra}\n\nMove the ${selKeys.length} PAB/BAP part(s) to Pick-A-Brick Cart?`)) return;
      }
      if (!selKeys.length) return;
    }
    if (tgtType === "bl") {
      const tgtCartObj = blCartList.find(c => c.id === tgtCartId);
      const missing = selKeys.filter(key => {
        const part = poolParts.find(p => `${p.partNo}_${p.colorId}` === key);
        return !tgtCartObj?.parts?.some(cp => cp.partNo === part?.partNo && String(cp.colorId) === String(part?.colorId));
      });
      if (missing.length) {
        const names = missing.slice(0, 5).map(key => {
          const part = poolParts.find(p => `${p.partNo}_${p.colorId}` === key);
          return `• ${part?.pabEntry?.bl_part_name || part?.name || key}`;
        });
        const extra = missing.length > 5 ? `\n+ ${missing.length - 5} more` : "";
        if (!confirm(`${missing.length} part(s) are not stocked in "${tgtCartObj?.name}":\n${names.join("\n")}${extra}\n\nAllocate anyway?`)) return;
      }
    }

    const { projects: allProjects = [] } = await chrome.storage.local.get("projects");
    const proj = allProjects.find(p => p.id === id);
    if (!proj) return;
    if (!proj.allocations) proj.allocations = {};

    for (const key of selKeys) {
      const part = poolParts.find(p => `${p.partNo}_${p.colorId}` === key);
      if (!part) continue;

      let moveQty = 0;
      if (srcType === "lego") {
        moveQty = proj.allocations[key]?.legoQty ?? 0;
        if (proj.allocations[key]) proj.allocations[key].legoQty = 0;
      } else if (srcType === "bl") {
        moveQty = proj.allocations[key]?.storeQty?.[srcCartId] ?? 0;
        if (proj.allocations[key]?.storeQty) delete proj.allocations[key].storeQty[srcCartId];
      } else { // scratch = move remaining unallocated qty
        moveQty = allocRemaining(proj.allocations, key, part.wantedQty);
      }
      if (moveQty <= 0) continue;

      if (tgtType !== "pool") {
        if (!proj.allocations[key]) proj.allocations[key] = { legoQty: 0, storeQty: {} };
        if (tgtType === "lego") {
          proj.allocations[key].legoQty = (proj.allocations[key].legoQty ?? 0) + moveQty;
        } else {
          if (!proj.allocations[key].storeQty) proj.allocations[key].storeQty = {};
          proj.allocations[key].storeQty[tgtCartId] = (proj.allocations[key].storeQty[tgtCartId] ?? 0) + moveQty;
        }
      }
      // Prune empty record
      const a = proj.allocations[key];
      if (a && (a.legoQty ?? 0) === 0 && !Object.keys(a.storeQty ?? {}).length) delete proj.allocations[key];
    }

    await chrome.storage.local.set({ projects: allProjects });
    if (srcType === "lego")    selectedLegoKeys.clear();
    else if (srcType === "bl") selectedBlKeys.get(srcCartId)?.clear();
    else                       selectedScratchKeys.clear();
    // Re-render directly (skip pruneStaleAllocations — its Pass 2 would re-fill parts
    // just returned to pool, since the part is still in the cart with unallocated qty).
    currentAllocs = proj.allocations;
    renderProjectPool(content, poolParts, currentAllocs, legoCart, blCartList, onMove, project);
    refreshLegoSection();
    for (const c of blCartList) refreshBlSection(c.id);
    refreshScratch();
    refreshGrandTotal();
  }

  async function onUnallocate(targetType, cartId, key) {
    const { projects: allProjects = [] } = await chrome.storage.local.get("projects");
    const proj = allProjects.find(p => p.id === id);
    if (!proj?.allocations?.[key]) return;
    if (targetType === "lego") {
      proj.allocations[key].legoQty = 0;
    } else if (cartId) {
      if (proj.allocations[key].storeQty) delete proj.allocations[key].storeQty[cartId];
    }
    const a = proj.allocations[key];
    if ((a.legoQty ?? 0) === 0 && !Object.keys(a.storeQty ?? {}).length) delete proj.allocations[key];
    await chrome.storage.local.set({ projects: allProjects });
    currentAllocs = proj.allocations;
    renderProjectPool(content, poolParts, currentAllocs, legoCart, blCartList, onMove, project);
    refreshLegoSection();
    for (const c of blCartList) refreshBlSection(c.id);
    refreshScratch();
    refreshGrandTotal();
  }

  function setHtmlPreserveScroll(el, html) {
    if (!el) return;
    const scroller = el.querySelector("[style*='overflow-y:auto']");
    const top = scroller?.scrollTop ?? 0;
    el.innerHTML = html;
    if (top > 0) {
      const newScroller = el.querySelector("[style*='overflow-y:auto']");
      if (newScroller) newScroller.scrollTop = top;
    }
  }

  function refreshLegoSection()      { setHtmlPreserveScroll(content.querySelector("#lego-section"),                                    buildLegoSection(currentAllocs)); }
  function refreshBlSection(cartId)  { const el = content.querySelector(`[data-bl-section="${esc(cartId)}"]`); const c = blCartList.find(x => x.id === cartId); if (c) setHtmlPreserveScroll(el, buildBlSection(c, currentAllocs)); }
  function refreshScratch()          { setHtmlPreserveScroll(content.querySelector("#scratch-section"),                                  buildScratchSection(currentAllocs)); }
  function refreshGrandTotal()       { const el = content.querySelector("#grand-total-section"); if (el) el.innerHTML = buildGrandTotal(); }

  function buildGrandTotal() {
    let grand = 0, grandKnown = true;
    // pabPartsTotal: what those BL-allocated parts would cost on LEGO direct (PAB-available only)
    // blAllPartsTotal: BL store cost of all allocated parts (PAB + BL-only); blPabTotal: PAB-comparable only
    let pabPartsTotal = 0, pabNetPartsOnly = 0, pabNetLots = 0, blPabTotal = 0, blAllPartsTotal = 0;
    const cartRows = [];

    for (const cart of blCartList) {
      const blAllocs = [];
      for (const [key, alloc] of Object.entries(currentAllocs)) {
        const allocQty = alloc.storeQty?.[cart.id] ?? 0;
        if (allocQty <= 0) continue;
        const [partNo, colorId] = key.split("_");
        for (const { cartPart, qty } of distributeLots(cart, partNo, colorId, allocQty)) {
          blAllocs.push({ key, qty, cartPart });
        }
      }
      if (!blAllocs.length) continue;
      let total = 0, totalKnown = true;
      for (const { key, qty, cartPart } of blAllocs) {
        const part = poolParts.find(p => `${p.partNo}_${p.colorId}` === key);
        const pr   = effectivePrice(cartPart);
        if (pr != null) {
          total += pr * qty;
          blAllPartsTotal += pr * qty;
          const pabCents = part?.pabEntry?.price_cents;
          if (pabCents != null) {
            pabPartsTotal   += (pabCents / 100) * qty;
            pabNetPartsOnly += (pabCents / 100 - pr) * qty;
            blPabTotal      += pr * qty;
          }
          pabNetLots++;
        } else {
          totalKnown = false;
        }
      }
      const rawS   = cart.orderSummary?.shipping?.replace(/^US\s+/, "");
      const rawO   = cart.orderSummary?.orderTotal?.replace(/^US\s+/, "");
      const sNum   = parseStorePrice(rawS);
      const isTbd  = sNum == null || sNum === 0 || rawS === rawO;
      const effS   = isTbd ? (estBlShipping[cart.id] ?? 0) : (sNum ?? 0);
      const cartGrand = total + effS;
      grand += cartGrand;
      if (!totalKnown || (isTbd && !(estBlShipping[cart.id] > 0))) grandKnown = false;
      cartRows.push(`<span style="font-size:12px;color:#374151">${esc(cart.name)}: <strong>${totalKnown ? "" : "~"}$${ceilToCents(cartGrand).toFixed(2)}</strong>${isTbd && !(estBlShipping[cart.id] > 0) ? `<span style="color:#9ca3af;font-size:11px"> (ship TBD)</span>` : ""}</span>`);
    }

    // LEGO allocations contribute to grand total but are already priced at PAB — no vs-PAB delta
    const legoAllocs = Object.entries(currentAllocs).filter(([, a]) => (a.legoQty ?? 0) > 0).map(([key, a]) => ({ key, qty: a.legoQty }));
    if (legoAllocs.length > 0) {
      let legoParts = 0, legoPartsKnown = true;
      for (const { key, qty } of legoAllocs) {
        const part = poolParts.find(p => `${p.partNo}_${p.colorId}` === key);
        if (part?.pabEntry?.price_cents) legoParts += (part.pabEntry.price_cents / 100) * qty;
        else legoPartsKnown = false;
      }
      const svcFee  = (!ignoreLegoFees && legoPartsKnown && legoParts < 14) ? 7 : 0;
      const legShip = ignoreLegoFees ? 0 : legoParts >= 35 ? 0 : legoParts <= 25 ? 4.95 : 6.95;
      const legoGrand = legoParts + svcFee + legShip;
      grand += legoGrand;
      if (!legoPartsKnown) grandKnown = false;
      cartRows.push(`<span style="font-size:12px;color:#374151">LEGO: <strong>${legoPartsKnown ? "" : "~"}$${ceilToCents(legoGrand).toFixed(2)}</strong></span>`);
    }

    if (!cartRows.length) return "";

    // vs-PAB: pure part-price delta for PAB-eligible BL-allocated parts (no shipping, no LEGO fees)
    // BL-only parts contribute $0 savings; show the PAB-comparable subtotals when BL-only parts
    // are present so the savings figure isn't confusingly close to the full store total.
    const pabNetTotal   = pabNetPartsOnly;
    const hasBLOnly     = blPabTotal < blAllPartsTotal - 0.001;
    const pabSavedStr   = pabNetLots > 0 && pabPartsTotal > 0 && pabNetTotal !== 0
      ? `PAB Savings $${Math.abs(pabNetTotal).toFixed(2)}`
      : null;
    const pabSavedColor = pabNetTotal > 0 ? "#16a34a" : pabNetTotal < 0 ? "#dc2626" : "#6b7280";
    return `<div style="display:flex;flex-wrap:wrap;align-items:center;gap:16px;padding:10px 16px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:6px">
      <span style="font-size:13px;font-weight:700;color:#0369a1">Grand Total</span>
      ${cartRows.join("")}
      ${pabSavedStr ? `<span style="font-size:12px;color:${pabSavedColor};font-weight:600">${esc(pabSavedStr)}</span>` : ""}
      <span style="margin-left:auto;font-size:14px;font-weight:700;color:#0369a1">${grandKnown ? "" : "~"}$${ceilToCents(grand).toFixed(2)}</span>
    </div>`;
  }

  async function saveEstShipping() {
    const { projects: allProjects = [] } = await chrome.storage.local.get("projects");
    const proj = allProjects.find(p => p.id === id);
    if (!proj) return;
    proj.estimatedShipping = estBlShipping;
    await chrome.storage.local.set({ projects: allProjects });
  }

  function showLegoSaveDiff() {
    if (!legoCart) return;
    if (document.querySelector(".lego-diff-modal")) return;

    // Build the new parts list from current LEGO allocations, with priceCents
    // attached -- needed by the fill heuristic and every $ total below. PAB
    // pricing has no bulk tiers (unlike BL store carts), so a flat multiply is
    // correct: qty * priceCents/100, no distributeLots/tierPriceFor involved.
    const newParts = Object.entries(currentAllocs)
      .filter(([, a]) => (a.legoQty ?? 0) > 0)
      .map(([key, a]) => {
        const part = poolParts.find(p => `${p.partNo}_${p.colorId}` === key);
        const eid  = part?.pabEntry?.element_id;
        if (!eid) return null;
        return {
          elementId:  eid,
          designId:   part.pabEntry.design_id || part.partNo,
          name:       part.pabEntry.bl_part_name || part.name || key,
          qty:        a.legoQty,
          channel:    part.pabEntry.channel,
          priceCents: part.pabEntry.price_cents ?? 0,
        };
      }).filter(Boolean);

    // Parts with no resolved pab/bap channel have no destination chain to route
    // through -- preserved as-is into the primary cart, same as today.
    const routedParts = newParts.filter(p => p.channel === "pab" || p.channel === "bap");
    const otherParts   = newParts.filter(p => p.channel !== "pab" && p.channel !== "bap");

    const overflowCarts = _projLgCarts.filter(c =>
      ["overflow", "pab-overflow", "bap-overflow"].includes(c.role)
    );
    const hasConfiguredOverflow = overflowCarts.length > 0;
    const threshold = project.gwpThreshold ?? 0;

    const plan = planLegoDistribution(routedParts, _projLgCarts, threshold);

    // otherParts always land in the primary (main-or-first) cart, unrouted --
    // matches today's unconditional keepList.push(otherParts_) exactly.
    if (otherParts.length) {
      if (!plan.perCart.has(legoCart.id)) plan.perCart.set(legoCart.id, []);
      plan.perCart.get(legoCart.id).unshift(...otherParts);
    }

    const totalUnplaced = plan.unplaced.pab.length + plan.unplaced.bap.length;

    let fallbackCart = null; // only set when auto-creating the no-overflow-configured catch-all
    if (totalUnplaced > 0 && !hasConfiguredOverflow) {
      // No overflow-family cart configured at all -- same escape hatch as
      // before: dump everything unplaced into one brand-new uncapped,
      // threshold-less cart rather than blocking the save. A threshold-aware
      // auto-created cart would just need its own overflow in turn, which is
      // exactly what the "configure an overflow cart" nudge below is for.
      fallbackCart = {
        id:         String(Date.now()),
        name:       `${legoCart.name} — Overflow`,
        savedAt:    new Date().toISOString(),
        locale:     legoCart.locale,
        partsCount: totalUnplaced,
        parts:      [...plan.unplaced.pab, ...plan.unplaced.bap],
      };
    }
    // Real exhaustion: overflow carts ARE configured but every destination in
    // the chain is already at its hard 200-lot cap. Never silently drop parts
    // -- block save and point at Setup instead.
    const isExhausted = totalUnplaced > 0 && hasConfiguredOverflow;

    // One diff section per destination cart actually touched by the plan (or
    // that currently holds parts belonging to this project's cart set, so a
    // cart the plan emptied out still shows its removals).
    const sectionCartIds = new Set([
      ...plan.perCart.keys(),
      ..._projLgCarts.filter(c => (c.cart.parts ?? []).length).map(c => c.cartId),
    ]);
    const sections = _projLgCarts
      .filter(c => sectionCartIds.has(c.cartId))
      .map(c => {
        const plannedParts = plan.perCart.get(c.cartId) ?? [];
        const curParts = c.cart.parts ?? [];
        const curMap = new Map(curParts.map(p => [p.elementId, p]));
        const newMap = new Map(plannedParts.map(p => [p.elementId, p]));
        return {
          cartRef: c,
          plannedParts,
          added:     plannedParts.filter(p => !curMap.has(p.elementId)),
          removed:   curParts.filter(p => !newMap.has(p.elementId)),
          changed:   plannedParts.filter(p => { const cur = curMap.get(p.elementId); return cur && cur.qty !== p.qty; }),
          unchanged: plannedParts.filter(p => { const cur = curMap.get(p.elementId); return cur && cur.qty === p.qty; }),
          total:     plannedParts.reduce((s, p) => s + (p.qty * p.priceCents) / 100, 0),
        };
      })
      // Primary (main-or-first) first, then the rest in configured order.
      .sort((a, b) => (a.cartRef.cart.id === legoCart.id ? -1 : 0) - (b.cartRef.cart.id === legoCart.id ? -1 : 0));

    const noChanges = !isExhausted && !fallbackCart &&
      sections.every(s => s.added.length === 0 && s.removed.length === 0 && s.changed.length === 0);

    const fmt = p => `<div style="padding:2px 0;font-size:12px">${esc(p.name)}<span style="color:#9ca3af;margin-left:6px">${p.elementId}</span></div>`;
    const fmtChg = (p, curMap) => {
      const old = curMap.get(p.elementId)?.qty ?? "?";
      return `<div style="padding:2px 0;font-size:12px">${esc(p.name)} <span style="color:#9ca3af">${old} → <strong>${p.qty}</strong></span></div>`;
    };

    const sectionHtml = sections.map(s => {
      const curMap = new Map((s.cartRef.cart.parts ?? []).map(p => [p.elementId, p]));
      const roleLabel = ROLE_LABELS[s.cartRef.role] ?? s.cartRef.role;
      return `
        <div style="margin-bottom:14px;padding-bottom:12px;border-bottom:1px solid #f3f4f6">
          <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px">
            <div style="font-size:13px;font-weight:700">${esc(s.cartRef.cart.name)} <span style="font-weight:400;color:#9ca3af;font-size:11px">(${esc(roleLabel)})</span></div>
            <div style="font-size:11px;color:#6c757d">${s.plannedParts.length} lots · $${ceilToCents(s.total).toFixed(2)}</div>
          </div>
          ${s.added.length ? `<div style="margin-bottom:8px"><div style="font-size:11px;font-weight:700;color:#16a34a;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Added (${s.added.length})</div>${s.added.map(fmt).join("")}</div>` : ""}
          ${s.removed.length ? `<div style="margin-bottom:8px"><div style="font-size:11px;font-weight:700;color:#dc2626;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Removed (${s.removed.length})</div>${s.removed.map(fmt).join("")}</div>` : ""}
          ${s.changed.length ? `<div style="margin-bottom:8px"><div style="font-size:11px;font-weight:700;color:#d97706;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Qty changed (${s.changed.length})</div>${s.changed.map(p => fmtChg(p, curMap)).join("")}</div>` : ""}
          ${!s.added.length && !s.removed.length && !s.changed.length ? `<div style="font-size:12px;color:#9ca3af">No changes.</div>` : ""}
        </div>`;
    }).join("");

    const fallbackHtml = fallbackCart ? `
      <div style="background:#fefce8;border:1px solid #fde047;border-radius:6px;padding:10px 14px;margin-top:8px;font-size:13px">
        <div style="font-weight:700;color:#a16207;margin-bottom:4px">No overflow cart configured</div>
        <div style="color:#854d0e">"${esc(fallbackCart.name)}" will be created to hold ${fallbackCart.partsCount} lots that don't fit in ${esc(legoCart.name)}.</div>
      </div>` : "";

    const stuckChannels = [
      plan.unplaced.pab.length ? `${plan.unplaced.pab.length} Bestseller` : null,
      plan.unplaced.bap.length ? `${plan.unplaced.bap.length} Standard` : null,
    ].filter(Boolean);
    const exhaustedHtml = isExhausted ? `
      <div style="background:#fef2f2;border:1px solid #fca5a5;border-radius:6px;padding:10px 14px;margin-top:8px;font-size:13px">
        <div style="font-weight:700;color:#dc2626;margin-bottom:4px">&#9888; Not enough cart capacity</div>
        <div style="color:#7f1d1d">Every configured cart is at the ${LEGO_CART_LOT_LIMIT}-lot limit — <strong>${stuckChannels.join(" and ")} lots</strong> have nowhere to go.</div>
        <div style="margin-top:6px"><button id="lego-diff-add-overflow-cart" style="padding:5px 12px;font-size:12px;background:#fff;border:1px solid #d1d5db;border-radius:4px;cursor:pointer">Add Overflow Cart to Project &#8594;</button></div>
      </div>` : "";

    const modal = document.createElement("div");
    modal.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9999;display:flex;align-items:center;justify-content:center;padding:16px";
    modal.innerHTML = `
      <div style="background:#fff;border-radius:8px;padding:24px;max-width:520px;width:100%;max-height:80vh;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,0.3)">
        <div style="font-size:16px;font-weight:700;margin-bottom:4px">Save to Pick-A-Brick Cart${sections.length > 1 || fallbackCart ? "s" : ""}</div>
        <div style="font-size:12px;color:#6c757d;margin-bottom:16px">${sections.length} destination cart${sections.length === 1 ? "" : "s"}${threshold > 0 ? ` · GWP threshold $${threshold.toFixed(2)}` : ""}</div>
        ${noChanges ? `<div style="padding:12px;background:#f0fdf4;border-radius:6px;font-size:13px;color:#16a34a">No changes — cart${sections.length === 1 ? " is" : "s are"} already up to date.</div>` : `
          <div style="overflow-y:auto;flex:1;min-height:0">${sectionHtml}</div>`}
        ${fallbackHtml}
        ${exhaustedHtml}
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px;padding-top:16px;border-top:1px solid #f3f4f6">
          <button id="lego-diff-cancel" class="btn">Cancel</button>
          ${!noChanges && !isExhausted ? `<button id="lego-diff-save-plan" class="btn btn-danger">${sections.length > 1 || fallbackCart ? `Save → ${sections.length + (fallbackCart ? 1 : 0)} carts` : "Replace Cart"}</button>` : ""}
        </div>
      </div>`;

    modal.className = "lego-diff-modal";
    document.body.appendChild(modal);

    modal.querySelector("#lego-diff-cancel").addEventListener("click", () => modal.remove());
    modal.addEventListener("click", e => { if (e.target === modal) modal.remove(); });

    modal.querySelector("#lego-diff-add-overflow-cart")?.addEventListener("click", () => {
      modal.remove();
      renderProjectSetup(id, content);
    });

    modal.querySelector("#lego-diff-save-plan")?.addEventListener("click", async () => {
      const { legoCarts: allCarts = [] } = await chrome.storage.local.get("legoCarts");

      for (const s of sections) {
        const cartToUpdate = allCarts.find(c => c.id === s.cartRef.cartId);
        if (!cartToUpdate) continue;
        cartToUpdate.parts      = s.plannedParts;
        cartToUpdate.savedAt    = new Date().toISOString();
        cartToUpdate.partsCount = s.plannedParts.length;
        if (cartToUpdate.id === legoCart.id) legoCart.parts = s.plannedParts; // in-memory ref
      }
      if (fallbackCart) allCarts.push(fallbackCart);

      await chrome.storage.local.set({ legoCarts: allCarts });
      modal.remove();
      refreshLegoSection();
      refreshGrandTotal();

      const toastParts = sections
        .filter(s => s.plannedParts.length)
        .map(s => {
          const cleared = threshold > 0 && s.total >= threshold ? ", cleared GWP" : "";
          return `${s.cartRef.cart.name}: ${s.plannedParts.length} lots ($${ceilToCents(s.total).toFixed(2)}${cleared})`;
        });
      if (fallbackCart) toastParts.push(`${fallbackCart.name}: ${fallbackCart.partsCount} lots`);
      const toast = document.createElement("div");
      toast.style.cssText = "position:fixed;top:20px;left:50%;transform:translateX(-50%);background:#15803d;color:#fff;padding:10px 24px;border-radius:6px;font-size:14px;font-weight:600;z-index:9999;box-shadow:0 4px 12px rgba(0,0,0,.2);max-width:80vw";
      toast.textContent = `Saved. ${toastParts.join(" · ") || "No changes."}`;
      document.body.appendChild(toast);
      setTimeout(() => toast.remove(), 4500);
    });
  }

  function showBlCartSave(cart) {
    const poolKeys = new Set(poolParts.map(p => `${p.partNo}_${p.colorId}`));

    // Compute per-lot new quantities. Sort cheapest-first so we keep the best lots
    // and remove expensive extras when the same part has multiple listings.
    const allocLeft = {};
    for (const [key, alloc] of Object.entries(currentAllocs)) {
      const q = alloc.storeQty?.[cart.id] ?? 0;
      if (q > 0) allocLeft[key] = q;
    }
    const cartParts = cart.parts ?? [];
    const sorted = cartParts
      .map((cp, idx) => ({ cp, idx, key: `${cp.partNo}_${cp.colorId}`, price: effectivePrice(cp) ?? Infinity }))
      .sort((a, b) => a.price - b.price);
    const lotNewQty = new Map(); // original index -> newQty
    const allocLeftCopy = { ...allocLeft };
    for (const { cp, idx, key } of sorted) {
      if (!poolKeys.has(key)) {
        // Imported cart part not in pool — not allocated, remove from cart
        lotNewQty.set(idx, 0);
        continue;
      }
      const remaining = allocLeftCopy[key] ?? 0;
      const oldQty = cp.qty ?? 1;
      const newQty = Math.min(oldQty, remaining);
      allocLeftCopy[key] = Math.max(0, remaining - oldQty);
      lotNewQty.set(idx, newQty);
    }

    const changes = [];
    cartParts.forEach((cp, idx) => {
      const key = `${cp.partNo}_${cp.colorId}`;
      const oldQty = cp.qty ?? 1;
      const newQty = lotNewQty.get(idx) ?? 0;
      if (newQty === oldQty) return;
      const pp = poolParts.find(p => `${p.partNo}_${p.colorId}` === key);
      changes.push({
        partNo: cp.partNo, colorId: cp.colorId, condition: cp.condition, storePrice: cp.storePrice,
        name: pp?.pabEntry?.bl_part_name || pp?.name || cp.name || cp.partNo,
        colorName: pp?.pabEntry?.bl_color_name || cp.colorName || String(cp.colorId),
        oldQty, newQty
      });
    });

    const removed   = changes.filter(c => c.newQty === 0);
    const reduced   = changes.filter(c => c.newQty > 0);
    const noChanges = changes.length === 0;
    const fmt    = c => `<div style="padding:2px 0;font-size:12px">${esc(c.name)}<span style="color:#9ca3af;margin-left:6px">${esc(c.colorName)}</span></div>`;
    const fmtRed = c => `<div style="padding:2px 0;font-size:12px">${esc(c.name)} <span style="color:#9ca3af">${esc(c.colorName)}</span> <span style="color:#9ca3af">${c.oldQty} → <strong>${c.newQty}</strong></span></div>`;

    // Close any existing save modal (prevents duplicate if user clicks twice)
    document.querySelectorAll(".bl-cart-save-modal").forEach(m => m.remove());
    const modal = document.createElement("div");
    modal.className = "bl-cart-save-modal";
    modal.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9999;display:flex;align-items:center;justify-content:center;padding:16px";
    modal.innerHTML = `
      <div style="background:#fff;border-radius:8px;padding:24px;max-width:480px;width:100%;max-height:80vh;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,0.3)">
        <div style="font-size:16px;font-weight:700;margin-bottom:4px">Save BL Store Cart</div>
        <div style="font-size:12px;color:#6c757d;margin-bottom:16px">Updating <strong>${esc(cart.name)}</strong></div>
        ${noChanges
          ? `<div style="padding:12px;background:#f0fdf4;border-radius:6px;font-size:13px;color:#16a34a">No changes — cart already matches your allocations.</div>`
          : `<div style="overflow-y:auto;flex:1;min-height:0">
              ${removed.length ? `<div style="margin-bottom:12px"><div style="font-size:11px;font-weight:700;color:#dc2626;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Removed (${removed.length})</div>${removed.map(fmt).join("")}</div>` : ""}
              ${reduced.length ? `<div style="margin-bottom:12px"><div style="font-size:11px;font-weight:700;color:#d97706;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Qty changed (${reduced.length})</div>${reduced.map(fmtRed).join("")}</div>` : ""}
            </div>
            <div style="font-size:12px;color:#6c757d;margin-top:12px;padding-top:12px;border-top:1px solid #f3f4f6">
              Items will be pre-selected for removal on the BL cart page next time you open it.
            </div>`}
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px">
          <button id="bl-cart-save-cancel" class="btn">Cancel</button>
          ${!noChanges ? `<button id="bl-cart-save-confirm" class="btn btn-danger">Update Cart</button>` : ""}
        </div>
      </div>`;
    document.body.appendChild(modal);
    modal.querySelector("#bl-cart-save-cancel").addEventListener("click", () => modal.remove());
    modal.addEventListener("click", e => { if (e.target === modal) modal.remove(); });

    const confirmBtn = modal.querySelector("#bl-cart-save-confirm");
    if (confirmBtn) {
      confirmBtn.addEventListener("click", async () => {
        const { carts = [] } = await chrome.storage.local.get("carts");
        const stored = carts.find(c => c.id === cart.id);
        if (stored) {
          stored.parts = (stored.parts ?? [])
            .map((cp, idx) => {
              const newQty = lotNewQty.get(idx) ?? 0;
              if (newQty === 0) return null;
              return newQty !== (cp.qty ?? 1) ? { ...cp, qty: newQty } : cp;
            })
            .filter(Boolean);
          stored.partsCount = stored.parts.length;
          await chrome.storage.local.set({ carts });
          Object.assign(cart, stored);
        }
        if (changes.length > 0) {
          const { pendingBlCartWriteback = {} } = await chrome.storage.local.get("pendingBlCartWriteback");
          const writebackKey = cart.storeUrl || cart.id;
          // condition/storePrice are tiebreakers only -- findArticle() matches primarily
          // on partNo+colorId, falling back to these when multiple lots of the same
          // part+color exist in the cart.
          pendingBlCartWriteback[writebackKey] = changes.map(c => ({ partNo: c.partNo, colorId: c.colorId, condition: c.condition, storePrice: c.storePrice, newQty: c.newQty, name: c.name, colorName: c.colorName }));
          await chrome.storage.local.set({ pendingBlCartWriteback });
        }
        modal.remove();
        refreshBlSection(cart.id);
        refreshGrandTotal();
      });
    }
  }

  function showPoolSave() {
    const wlCount = project.wantedListIds?.length ?? 0;
    if (!wlCount) return;

    // Build the new parts list — full wantedQty, excluding parts marked as removed from pool
    const newParts = poolParts.filter(p => !currentAllocs[`${p.partNo}_${p.colorId}`]?.excluded).map(p => ({
      partNo:    p.partNo,
      colorId:   p.colorId,
      colorName: p.pabEntry?.bl_color_name || p.colorName || "",
      name:      p.pabEntry?.bl_part_name  || p.name      || "",
      want:      p.wantedQty,
      have:      0,
      qty:       p.wantedQty,
      imageUrl:  p.imageUrl || null,
    }));

    const modal = document.createElement("div");
    modal.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9999;display:flex;align-items:center;justify-content:center;padding:16px";

    if (wlCount === 1) {
      // ── Single list: overwrite in-place ──────────────────────────────────────
      const wl     = wlMap[project.wantedListIds[0]];
      if (!wl) { alert("Source wanted list not found in storage."); return; }
      const curParts = wl.parts ?? [];
      const curMap   = new Map(curParts.map(p => [`${p.partNo}_${p.colorId}`, p]));
      const newMap   = new Map(newParts.map(p => [`${p.partNo}_${p.colorId}`, p]));
      const added    = newParts.filter(p => !curMap.has(`${p.partNo}_${p.colorId}`));
      const removed  = curParts.filter(p => !newMap.has(`${p.partNo}_${p.colorId}`));
      const changed  = newParts.filter(p => {
        const cur = curMap.get(`${p.partNo}_${p.colorId}`);
        return cur && (cur.want ?? cur.qty ?? 1) !== p.want;
      });
      const noChanges = !added.length && !removed.length && !changed.length;
      const fmt    = p => `<div style="padding:2px 0;font-size:12px">${esc(p.name || p.partNo)} <span style="color:#9ca3af">${esc(p.colorName)}</span></div>`;
      const fmtChg = p => {
        const old = curMap.get(`${p.partNo}_${p.colorId}`)?.want ?? "?";
        return `<div style="padding:2px 0;font-size:12px">${esc(p.name || p.partNo)}: ${old} → <strong>${p.want}</strong></div>`;
      };
      modal.innerHTML = `
        <div style="background:#fff;border-radius:8px;padding:24px;max-width:480px;width:100%;max-height:80vh;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,0.3)">
          <div style="font-size:16px;font-weight:700;margin-bottom:4px">Save to Wanted List</div>
          <div style="font-size:12px;color:#6c757d;margin-bottom:8px">Overwriting <strong>${esc(wl.name)}</strong> with current pool · ${newParts.length} lots</div>
          <div style="font-size:12px;background:#fef3c7;border:1px solid #fde68a;border-radius:4px;padding:8px 10px;margin-bottom:12px">This is destructive — the original list will be replaced.</div>
          ${noChanges
            ? `<div style="padding:12px;background:#f0fdf4;border-radius:6px;font-size:13px;color:#16a34a">No changes — list is already up to date.</div>`
            : `<div style="overflow-y:auto;flex:1;min-height:0">
                ${added.length   ? `<div style="margin-bottom:12px"><div style="font-size:11px;font-weight:700;color:#16a34a;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Added (${added.length})</div>${added.map(fmt).join("")}</div>` : ""}
                ${removed.length ? `<div style="margin-bottom:12px"><div style="font-size:11px;font-weight:700;color:#dc2626;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Removed — fully allocated (${removed.length})</div>${removed.map(fmt).join("")}</div>` : ""}
                ${changed.length ? `<div style="margin-bottom:12px"><div style="font-size:11px;font-weight:700;color:#d97706;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Qty reduced (${changed.length})</div>${changed.map(fmtChg).join("")}</div>` : ""}
              </div>`}
          <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px;padding-top:16px;border-top:1px solid #f3f4f6">
            <button id="pool-save-cancel" class="btn">Cancel</button>
            ${!noChanges ? `<button id="pool-save-confirm" class="btn btn-danger">Overwrite List</button>` : ""}
          </div>
        </div>`;
      document.body.appendChild(modal);
      modal.querySelector("#pool-save-cancel").addEventListener("click", () => modal.remove());
      modal.addEventListener("click", e => { if (e.target === modal) modal.remove(); });
      modal.querySelector("#pool-save-confirm")?.addEventListener("click", async () => {
        const { wantedLists = [] } = await chrome.storage.local.get("wantedLists");
        const target = wantedLists.find(w => w.id === wl.id);
        if (target) {
          target.parts      = newParts;
          target.partsCount = newParts.length;
          target.importedAt = new Date().toISOString();
          await chrome.storage.local.set({ wantedLists });
          Object.assign(wl, target);
        }
        modal.remove();
      });

    } else {
      // ── Multi list: create new combined list ──────────────────────────────────
      const sourceNames = (project.wantedListIds ?? [])
        .map(lid => wlMap[lid]?.name).filter(Boolean).join(", ");
      modal.innerHTML = `
        <div style="background:#fff;border-radius:8px;padding:24px;max-width:460px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,0.3)">
          <div style="font-size:16px;font-weight:700;margin-bottom:4px">Save as New Wanted List</div>
          <div style="font-size:12px;color:#6c757d;margin-bottom:4px">Combining ${wlCount} lists into a new wanted list · ${newParts.length} lots</div>
          <div style="font-size:12px;color:#9ca3af;margin-bottom:16px">Sources: ${esc(sourceNames)}</div>
          <div style="margin-bottom:12px">
            <label style="font-size:12px;font-weight:600;display:block;margin-bottom:4px">New list name</label>
            <input id="pool-new-name" type="text" value="${esc(project.name)} — Combined" style="width:100%;padding:6px 8px;border:1px solid #d1d5db;border-radius:4px;font-size:13px;box-sizing:border-box">
          </div>
          <label style="display:flex;align-items:center;gap:8px;font-size:13px;margin-bottom:16px;cursor:pointer">
            <input type="checkbox" id="pool-swap-project" checked>
            Replace project's source lists with this new list
          </label>
          <div style="display:flex;gap:8px;justify-content:flex-end">
            <button id="pool-save-cancel" class="btn">Cancel</button>
            <button id="pool-save-confirm" class="btn btn-primary" style="background:#1e2330;color:#fff;border-color:#1e2330">Create List</button>
          </div>
        </div>`;
      document.body.appendChild(modal);
      modal.querySelector("#pool-save-cancel").addEventListener("click", () => modal.remove());
      modal.addEventListener("click", e => { if (e.target === modal) modal.remove(); });
      modal.querySelector("#pool-save-confirm").addEventListener("click", async () => {
        const name    = modal.querySelector("#pool-new-name").value.trim() || `${project.name} — Combined`;
        const doSwap  = modal.querySelector("#pool-swap-project").checked;
        const { wantedLists = [], projects: allProjects = [] } = await chrome.storage.local.get(["wantedLists", "projects"]);
        const newList = {
          id:         crypto.randomUUID(),
          name,
          parts:      newParts,
          partsCount: newParts.length,
          importedAt: new Date().toISOString(),
        };
        wantedLists.push(newList);
        if (doSwap) {
          const proj = allProjects.find(p => p.id === id);
          if (proj) proj.wantedListIds = [newList.id];
        }
        await chrome.storage.local.set({ wantedLists, projects: allProjects });
        modal.remove();
        if (doSwap) renderProjectDetail(id, content);
      });
    }
  }

  function showScratchSave() {
    // Build the new parts list from pool parts with no allocation at all
    const scratchParts = poolParts
      .map(p => {
        const a = currentAllocs[`${p.partNo}_${p.colorId}`];
        const total = a ? (a.legoQty ?? 0) + Object.values(a.storeQty ?? {}).reduce((s, v) => s + v, 0) : 0;
        if (total > 0 || a?.removed || a?.excluded) return null;
        return {
          partNo:    p.partNo,
          colorId:   p.colorId,
          colorName: p.pabEntry?.bl_color_name || p.colorName || "",
          name:      p.pabEntry?.bl_part_name  || p.name      || "",
          want:      p.wantedQty,
          have:      0,
          qty:       p.wantedQty,
          imageUrl:  p.imageUrl || null,
        };
      }).filter(Boolean);

    const modal = document.createElement("div");
    modal.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9999;display:flex;align-items:center;justify-content:center;padding:16px";

    if (!scratchList) {
      // No linked list — prompt to create one or cancel
      modal.innerHTML = `
        <div style="background:#fff;border-radius:8px;padding:24px;max-width:400px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,0.3)">
          <div style="font-size:16px;font-weight:700;margin-bottom:8px">Save Scratch Space</div>
          <div style="font-size:13px;color:#6c757d;margin-bottom:16px">No wanted list is linked to this scratch space. Create a new list from the ${scratchParts.length} unallocated lot(s)?</div>
          <div style="margin-bottom:12px">
            <label style="font-size:12px;font-weight:600;display:block;margin-bottom:4px">New list name</label>
            <input id="scratch-new-name" type="text" value="${esc(project.name)} — Scratch" style="width:100%;padding:6px 8px;border:1px solid #d1d5db;border-radius:4px;font-size:13px;box-sizing:border-box">
          </div>
          <div style="display:flex;gap:8px;justify-content:flex-end">
            <button id="scratch-cancel" class="btn">Cancel</button>
            <button id="scratch-create" class="btn btn-primary" style="background:#1e2330;color:#fff;border-color:#1e2330">Create List</button>
          </div>
        </div>`;
      document.body.appendChild(modal);
      modal.querySelector("#scratch-cancel").addEventListener("click", () => modal.remove());
      modal.addEventListener("click", e => { if (e.target === modal) modal.remove(); });
      modal.querySelector("#scratch-create").addEventListener("click", async () => {
        const name = modal.querySelector("#scratch-new-name").value.trim() || `${project.name} — Scratch`;
        const { wantedLists = [], projects: allProjects = [] } = await chrome.storage.local.get(["wantedLists", "projects"]);
        const newList = {
          id:         crypto.randomUUID(),
          name,
          parts:      scratchParts,
          partsCount: scratchParts.length,
          importedAt: new Date().toISOString(),
        };
        wantedLists.push(newList);
        const proj = allProjects.find(p => p.id === id);
        if (proj) proj.scratchWantedListId = newList.id;
        await chrome.storage.local.set({ wantedLists, projects: allProjects });
        Object.assign(scratchList ?? {}, newList); // won't help if null — page re-render needed
        modal.remove();
        renderProjectDetail(id, content); // reload to pick up new scratchList reference
      });
      return;
    }

    // Linked list exists — show what will be overwritten
    const curParts  = scratchList.parts ?? [];
    const curMap    = new Map(curParts.map(p => [`${p.partNo}_${p.colorId}`, p]));
    const newMap    = new Map(scratchParts.map(p => [`${p.partNo}_${p.colorId}`, p]));
    const added     = scratchParts.filter(p => !curMap.has(`${p.partNo}_${p.colorId}`));
    const removed   = curParts.filter(p => !newMap.has(`${p.partNo}_${p.colorId}`));
    const changed   = scratchParts.filter(p => {
      const cur = curMap.get(`${p.partNo}_${p.colorId}`);
      return cur && (cur.want ?? cur.qty ?? 1) !== p.want;
    });
    const noChanges = added.length === 0 && removed.length === 0 && changed.length === 0;
    const fmt       = p => `<div style="padding:2px 0;font-size:12px">${esc(p.name || p.partNo)} <span style="color:#9ca3af">${esc(p.colorName)}</span></div>`;
    const fmtChg    = p => {
      const old = curMap.get(`${p.partNo}_${p.colorId}`)?.want ?? "?";
      return `<div style="padding:2px 0;font-size:12px">${esc(p.name || p.partNo)}: ${old} → <strong>${p.want}</strong></div>`;
    };
    modal.innerHTML = `
      <div style="background:#fff;border-radius:8px;padding:24px;max-width:480px;width:100%;max-height:80vh;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,0.3)">
        <div style="font-size:16px;font-weight:700;margin-bottom:4px">Save Scratch Space</div>
        <div style="font-size:12px;color:#6c757d;margin-bottom:16px">Overwriting <strong>${esc(scratchList.name)}</strong> · ${scratchParts.length} lots</div>
        ${noChanges
          ? `<div style="padding:12px;background:#f0fdf4;border-radius:6px;font-size:13px;color:#16a34a">No changes — list is already up to date.</div>`
          : `<div style="overflow-y:auto;flex:1;min-height:0">
              ${added.length   ? `<div style="margin-bottom:12px"><div style="font-size:11px;font-weight:700;color:#16a34a;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Added (${added.length})</div>${added.map(fmt).join("")}</div>` : ""}
              ${removed.length ? `<div style="margin-bottom:12px"><div style="font-size:11px;font-weight:700;color:#dc2626;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Removed (${removed.length})</div>${removed.map(fmt).join("")}</div>` : ""}
              ${changed.length ? `<div style="margin-bottom:12px"><div style="font-size:11px;font-weight:700;color:#d97706;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Qty changed (${changed.length})</div>${changed.map(fmtChg).join("")}</div>` : ""}
            </div>`}
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px;padding-top:16px;border-top:1px solid #f3f4f6">
          <button id="scratch-cancel" class="btn">Cancel</button>
          ${!noChanges ? `<button id="scratch-confirm" class="btn btn-danger">Overwrite List</button>` : ""}
        </div>
      </div>`;
    document.body.appendChild(modal);
    modal.querySelector("#scratch-cancel").addEventListener("click", () => modal.remove());
    modal.addEventListener("click", e => { if (e.target === modal) modal.remove(); });
    const confirmBtn = modal.querySelector("#scratch-confirm");
    if (confirmBtn) {
      confirmBtn.addEventListener("click", async () => {
        const { wantedLists = [] } = await chrome.storage.local.get("wantedLists");
        const wl = wantedLists.find(w => w.id === scratchList.id);
        if (wl) {
          wl.parts      = scratchParts;
          wl.partsCount = scratchParts.length;
          wl.importedAt = new Date().toISOString();
          await chrome.storage.local.set({ wantedLists });
          Object.assign(scratchList, wl);
        }
        modal.remove();
      });
    }
  }

  async function reloadSourceData() {
    const { carts = [], legoCarts = [], wantedLists = [] } =
      await chrome.storage.local.get(["carts", "legoCarts", "wantedLists"]);
    for (const cart of blCartList) {
      const fresh = carts.find(c => c.id === cart.id);
      if (fresh) Object.assign(cart, fresh);
    }
    if (legoCart) {
      const fresh = legoCarts.find(c => c.id === legoCart.id);
      if (fresh) Object.assign(legoCart, fresh);
    }
    if (scratchList) {
      const fresh = wantedLists.find(w => w.id === scratchList.id);
      if (fresh) Object.assign(scratchList, fresh);
    }
  }

  async function refresh() {
    const { projects: allProjects = [] } = await chrome.storage.local.get("projects");
    await reloadSourceData();
    const proj = allProjects.find(p => p.id === id);
    if (!proj) return;
    currentAllocs = proj.allocations ?? {};
    const cleared = pruneStaleAllocations(currentAllocs, blCartList);
    if (cleared) {
      proj.allocations = currentAllocs;
      await chrome.storage.local.set({ projects: allProjects });
    }
    renderProjectPool(content, poolParts, currentAllocs, legoCart, blCartList, onMove, project);
    refreshLegoSection();
    for (const c of blCartList) refreshBlSection(c.id);
    refreshScratch();
    refreshGrandTotal();
  }

  function showStoreSavingsScanner(cart) {
    // Uses imported storePrice (actual BL store prices from cart pages) vs PAB.
    // No BL price guide (min/avg) — the OAuth API can't query other sellers' inventories.

    function parseStorePrice(s) {
      if (s == null) return null;
      const n = parseFloat(String(s).replace(/[^0-9.]/g, ""));
      return isNaN(n) || n <= 0 ? null : n;
    }

    // Build price maps for EVERY project BL store (cartId → Map(key → price))
    const allPriceMaps = new Map();
    for (const c of blCartList) {
      allPriceMaps.set(c.id, new Map(
        (c.parts ?? []).flatMap(p => {
          const price = parseStorePrice(p.storePrice);
          return price != null ? [[`${p.partNo}_${p.colorId}`, price]] : [];
        })
      ));
    }
    const thisStoreMap = allPriceMaps.get(cart.id) ?? new Map();

    function poolQty(part) { return part.wantedQty ?? 1; }

    // For each pool part, compute:
    //   cheaperHere: this store < cheapest other project store AND < PAB
    //   pabCheaper:  PAB < this store's price
    const cheaperHere = []; // { part, thisPrice, bestOther: { price, cartName }, pabCents }
    const pabCheaper  = []; // { part, thisPrice, pabCents }
    const seen = new Set();

    for (const part of poolParts) {
      const key = `${part.partNo}_${part.colorId}`;
      if (seen.has(key)) continue;
      seen.add(key);
      if (currentAllocs[key]?.excluded || currentAllocs[key]?.removed) continue;

      const thisPrice = thisStoreMap.get(key);
      const pabCents  = part.pabEntry?.price_cents;
      const pabPrice  = pabCents != null ? pabCents / 100 : null;

      // Find the cheapest OTHER project store that carries this part
      let bestOther = null;
      for (const [cid, m] of allPriceMaps) {
        if (cid === cart.id) continue;
        const price = m.get(key);
        if (price != null && (bestOther == null || price < bestOther.price)) {
          bestOther = { price, cartName: blCartList.find(c => c.id === cid)?.name || "" };
        }
      }

      // cheaperHere: this store has the part, is cheaper than the best other store, AND cheaper than PAB
      if (thisPrice != null && bestOther != null && thisPrice < bestOther.price - 0.001) {
        if (pabPrice == null || thisPrice < pabPrice - 0.001) {
          cheaperHere.push({ part, thisPrice, bestOther, pabCents });
        }
      }

      // pabCheaper: PAB is cheaper than this store's price
      if (thisPrice != null && pabPrice != null && pabPrice < thisPrice - 0.001) {
        pabCheaper.push({ part, thisPrice, pabCents });
      }
    }

    cheaperHere.sort((a, b) =>
      (b.bestOther.price - b.thisPrice) * poolQty(b.part) -
      (a.bestOther.price - a.thisPrice) * poolQty(a.part));
    pabCheaper.sort((a, b) =>
      (b.thisPrice - b.pabCents / 100) * poolQty(b.part) -
      (a.thisPrice - a.pabCents / 100) * poolQty(a.part));

    const hereSavings = cheaperHere.reduce((s, r) => s + (r.bestOther.price - r.thisPrice) * poolQty(r.part), 0);
    const pabSavings  = pabCheaper.reduce((s, r) => s + (r.thisPrice - r.pabCents / 100) * poolQty(r.part), 0);

    // ── render ────────────────────────────────────────────────────────────────
    const modal = document.createElement("div");
    modal.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9999;display:flex;align-items:center;justify-content:center;padding:16px";

    // Columns: chk | part | CH | this store $ | other stores $ | PAB $ | save/ea | total
    const COLS = "16px 1fr 36px 60px 68px 58px 52px 62px";

    function chBadge(part) {
      const ch = part.pabEntry?.channel;
      if (ch === "pab") return `<span style="background:#16a34a;color:#fff;font-size:10px;font-weight:700;padding:1px 4px;border-radius:3px">PAB</span>`;
      if (ch === "bap") return `<span style="background:#d97706;color:#fff;font-size:10px;font-weight:700;padding:1px 4px;border-radius:3px">STD</span>`;
      return `<span style="background:#6b7280;color:#fff;font-size:10px;font-weight:700;padding:1px 4px;border-radius:3px">BL</span>`;
    }

    function fmtRow(r, section) {
      const key     = `${r.part.partNo}_${r.part.colorId}`;
      const ch      = r.part.pabEntry?.channel || "bl";
      const name    = r.part.pabEntry?.bl_part_name || r.part.name || r.part.partNo;
      const color   = r.part.pabEntry?.bl_color_name || r.part.colorName || "";
      const qty     = poolQty(r.part);
      const isHere  = section === "here";
      const thisPriceStr  = `$${r.thisPrice.toFixed(2)}`;
      const otherStr      = isHere ? `$${r.bestOther.price.toFixed(2)}` : "—";
      const pabStr        = r.pabCents != null ? `$${(r.pabCents / 100).toFixed(2)}` : "—";
      const subNote       = isHere && r.bestOther.cartName ? ` · vs ${esc(r.bestOther.cartName)}` : "";
      const saving        = isHere ? (r.bestOther.price - r.thisPrice) : (r.thisPrice - r.pabCents / 100);
      return `
        <div style="display:grid;grid-template-columns:${COLS};gap:6px;align-items:center;padding:4px 0;border-bottom:1px solid #f3f4f6;font-size:12px">
          <input type="checkbox" class="scan-row-chk" data-section="${section}" data-ch="${ch}" data-key="${esc(key)}" style="margin:0;cursor:pointer">
          <div>
            <div style="font-weight:500">${esc(name)}</div>
            <div style="color:#9ca3af;font-size:11px">${esc(color)} · ×${qty}${subNote}</div>
          </div>
          <div style="text-align:center">${chBadge(r.part)}</div>
          <div style="text-align:right;color:${isHere ? "#16a34a" : "#374151"}">${thisPriceStr}</div>
          <div style="text-align:right;color:#374151">${otherStr}</div>
          <div style="text-align:right;color:${!isHere ? "#16a34a" : "#374151"}">${pabStr}</div>
          <div style="text-align:right;color:#374151">$${saving.toFixed(2)}</div>
          <div style="text-align:right;font-weight:600;color:#16a34a">$${(saving * qty).toFixed(2)}</div>
        </div>`;
    }

    const colHeader = `
      <div style="display:grid;grid-template-columns:${COLS};gap:6px;padding:3px 0 5px;border-bottom:1px solid #e5e7eb;font-size:11px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:.04em">
        <div></div><div>Part</div><div style="text-align:center">CH</div>
        <div style="text-align:right">Here $</div><div style="text-align:right">Other stores</div>
        <div style="text-align:right">PAB</div><div style="text-align:right">Save/ea</div><div style="text-align:right">Total</div>
      </div>`;

    function filterBtns(section, actionLabel, actionDisabled = "") {
      const fBtn = (label, ch, color) =>
        `<button class="btn scan-filter-btn" data-section="${section}" data-ch="${ch}" style="font-size:11px;padding:2px 7px${color ? `;color:${color}` : ""}">${label}</button>`;
      return `
        <div style="display:flex;gap:5px;align-items:center;flex-wrap:wrap;margin:4px 0 6px">
          ${fBtn("☑ PAB", "pab", "#16a34a")}
          ${fBtn("☑ STD", "bap", "#ca8a04")}
          ${fBtn("☑ BL only",    "bl",  "#6b7280")}
          ${fBtn("☑ All",        "all")}
          <button class="btn scan-action-btn" data-section="${section}" style="margin-left:auto;font-size:11px;padding:2px 10px;background:#1e2330;color:#fff" ${actionDisabled}>${actionLabel}</button>
        </div>`;
    }

    const sectionHtml = (title, color, rows, section, total, actionLabel, actionDisabled) =>
      rows.length === 0 ? "" : `
        <div style="margin-bottom:14px">
          <div style="font-size:11px;font-weight:700;color:${color};text-transform:uppercase;letter-spacing:.05em">${title} (${rows.length} lot${rows.length !== 1 ? "s" : ""} · save $${total.toFixed(2)})</div>
          ${filterBtns(section, actionLabel, actionDisabled)}
          ${colHeader}${rows.map(r => fmtRow(r, section)).join("")}
        </div>`;

    const allClear = cheaperHere.length === 0 && pabCheaper.length === 0;
    const bodyHtml = allClear
      ? `<div style="padding:12px;background:#f0fdf4;border-radius:6px;font-size:13px;color:#16a34a">All clear — this store's prices are the best option for all shared pool parts.</div>`
      : `<div style="overflow-y:auto;flex:1;min-height:0">
           ${sectionHtml("Cheaper here — consolidate from other stores", "#16a34a", cheaperHere, "here", hereSavings, "→ This Cart")}
           ${sectionHtml("PAB cheaper than this store — move to Pick-A-Brick cart", "#2563eb", pabCheaper, "pab", pabSavings, "→ Pick-A-Brick Cart", legoCart ? "" : "disabled")}
         </div>
         <div style="margin-top:10px;padding:10px 0;border-top:1px solid #f3f4f6;display:flex;gap:20px;font-size:12px;color:#374151">
           ${cheaperHere.length ? `<span>Consolidation savings: <strong style="color:#16a34a">$${hereSavings.toFixed(2)}</strong></span>` : ""}
           ${pabCheaper.length  ? `<span>PAB savings: <strong style="color:#2563eb">$${pabSavings.toFixed(2)}</strong></span>` : ""}
           <span style="margin-left:auto;font-weight:700">Total opportunity: $${(hereSavings + pabSavings).toFixed(2)}</span>
         </div>`;

    modal.innerHTML = `
      <div style="background:#fff;border-radius:8px;padding:24px;max-width:680px;width:100%;max-height:82vh;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,0.3)">
        <div style="font-size:16px;font-weight:700;margin-bottom:2px">Savings Scanner — ${esc(cart.name)}</div>
        <div style="font-size:12px;color:#6c757d;margin-bottom:14px">Compares this store's prices against other project stores and PAB</div>
        ${bodyHtml}
        <div style="display:flex;justify-content:flex-end;margin-top:16px;padding-top:14px;border-top:1px solid #f3f4f6">
          <button class="savings-modal-close btn">Close</button>
        </div>
      </div>`;
    modal.querySelector(".savings-modal-close").addEventListener("click", () => modal.remove());
    modal.addEventListener("click", e => { if (e.target === modal) modal.remove(); });
    document.body.appendChild(modal);

    // ── handlers ─────────────────────────────────────────────────────────────
    async function bulkMove(rows, action) {
      const { projects: allProjects = [] } = await chrome.storage.local.get("projects");
      const proj = allProjects.find(p => p.id === id);
      if (!proj) return;
      for (const r of rows) {
        const key = `${r.part.partNo}_${r.part.colorId}`;
        const qty = poolQty(r.part);
        if (!proj.allocations[key]) proj.allocations[key] = { legoQty: 0, storeQty: {} };
        if (action === "here") {
          // Consolidate to this BL cart — clear LEGO and all other store allocations
          proj.allocations[key].legoQty  = 0;
          proj.allocations[key].storeQty = { [cart.id]: qty };
        } else {
          // Move to LEGO cart — clear all store allocations
          proj.allocations[key].legoQty  = qty;
          proj.allocations[key].storeQty = {};
        }
      }
      await chrome.storage.local.set({ projects: allProjects });
      currentAllocs = proj.allocations;
    }

    function refreshAll() {
      refreshLegoSection();
      for (const c of blCartList) refreshBlSection(c.id);
      renderProjectPool(content, poolParts, currentAllocs, legoCart, blCartList, onMove, project);
      refreshGrandTotal();
    }

    modal.addEventListener("click", async e => {
      const filterBtn = e.target.closest(".scan-filter-btn");
      if (filterBtn) {
        const { section, ch } = filterBtn.dataset;
        const chks = [...modal.querySelectorAll(`.scan-row-chk[data-section="${section}"]`)];
        const targets = ch === "all" ? chks : chks.filter(c => c.dataset.ch === ch);
        const anyUnchecked = targets.some(c => !c.checked);
        targets.forEach(c => c.checked = anyUnchecked);
        return;
      }

      const actionBtn = e.target.closest(".scan-action-btn");
      if (!actionBtn || actionBtn.disabled) return;
      const { section } = actionBtn.dataset;

      const checkedKeys = new Set(
        [...modal.querySelectorAll(`.scan-row-chk[data-section="${section}"]:checked`)]
          .map(c => c.dataset.key)
      );
      if (!checkedKeys.size) {
        const orig = actionBtn.textContent;
        actionBtn.textContent = "Nothing selected";
        setTimeout(() => { actionBtn.textContent = orig; }, 1500);
        return;
      }

      actionBtn.disabled = true;
      actionBtn.textContent = "Moving…";

      const pool = section === "here" ? cheaperHere : pabCheaper;
      const rows = pool.filter(r => checkedKeys.has(`${r.part.partNo}_${r.part.colorId}`));
      await bulkMove(rows, section === "here" ? "here" : "pab");

      actionBtn.textContent = "✓ Done";
      actionBtn.style.background = "#16a34a";
      refreshAll();
    });
  }

  // ── initial render ────────────────────────────────────────────────────────

  content.innerHTML = `
    <div class="detail-header">
      <button class="back-btn" id="back-btn">← Projects</button>
      <div style="flex:1">
        <div style="display:flex;align-items:center;gap:10px">
          <div class="page-title" style="margin:0">${esc(project.name)}</div>
          <button class="btn" id="configure-btn" style="font-size:12px;padding:2px 8px;opacity:0.6">⚙ Configure</button>
          <button class="btn btn-danger" id="reset-btn" style="font-size:12px;padding:2px 8px">↺ Reset</button>
        </div>
        <div class="detail-meta">Created ${fmtDate(project.createdAt)} · ${poolParts.length} lots · ${totalPoolPieces.toLocaleString()} pieces in pool</div>
      </div>
    </div>

    <div id="grand-total-section" style="margin-bottom:14px">${buildGrandTotal()}</div>

    <div id="auto-alloc-bar" style="background:#f0fdf4;border:1.5px solid #86efac;border-radius:8px;padding:12px 16px;display:flex;align-items:center;gap:14px;margin-bottom:14px;flex-wrap:wrap">
      <button id="auto-alloc-btn" class="btn" style="background:#16a34a;color:#fff;font-weight:700;font-size:14px;padding:7px 22px;border:none;flex-shrink:0">⚡ Auto Allocate</button>
      <label id="auto-alloc-std-label" style="display:none;align-items:center;gap:6px;font-size:13px;color:#374151;cursor:pointer;flex-shrink:0">
        <input type="checkbox" id="auto-alloc-domestic-only" style="cursor:pointer">
        Domestic PAB only (skip STD)
      </label>
      <span style="font-size:12px;color:#4b7c5a">Allocate every pool part to its cheapest source — BL stores or Pick a Brick cart.</span>
    </div>

    <div id="pool-section" style="margin-bottom:14px">
      <div class="section">
        <div class="section-header"><span>Wanted List Pool</span><span style="font-size:12px;color:#9ca3af;font-weight:400;margin-left:8px">loading prices…</span></div>
        <div class="section-empty">Loading PAB prices…</div>
      </div>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;align-items:start;margin-bottom:20px">
      <div style="display:flex;flex-direction:column;gap:14px">
        <div id="lego-section" class="section">${buildLegoSection(currentAllocs)}</div>
        <div id="scratch-section" class="section">${buildScratchSection(currentAllocs)}</div>
      </div>
      <div style="display:flex;flex-direction:column;gap:14px">
        ${blCartList.length
          ? blCartList.map(c => `<div class="section" data-bl-section="${esc(c.id)}">${buildBlSection(c, currentAllocs)}</div>`).join("")
          : `<div class="section" style="grid-column:1/-1">
              <div class="section-header"><span>BrickLink Store Carts</span></div>
              <div class="section-empty" style="padding:16px">No BL carts added. <button class="proj-configure-link back-btn" style="font-size:12px;color:#2563eb">Configure</button> to add some.</div>
            </div>`}
      </div>
    </div>`;

  content.querySelector("#back-btn").addEventListener("click", () => navigate("projects"));
  content.querySelector("#configure-btn").addEventListener("click", () => renderProjectSetup(id, content));
  content.querySelector("#reset-btn").addEventListener("click", async () => {
    if (!confirm("Reset all allocations? This will clear any manual moves and re-detect parts from your BL store carts.")) return;
    await reloadSourceData();
    const { projects: allProjects = [] } = await chrome.storage.local.get("projects");
    const proj = allProjects.find(p => p.id === id);
    if (!proj) return;
    proj.allocations  = {};
    proj.autoAlloced  = false;
    // Re-run auto-allocation from BL store carts and LEGO cart
    for (const poolPart of poolParts) {
      const key = `${poolPart.partNo}_${poolPart.colorId}`;
      for (const cart of blCartList) {
        const cartPart = (cart.parts ?? []).find(cp =>
          cp.partNo === poolPart.partNo && String(cp.colorId) === String(poolPart.colorId)
        );
        if (!cartPart) continue;
        proj.allocations[key] = { legoQty: 0, storeQty: { [cart.id]: Math.min(poolPart.wantedQty, cartPart.qty ?? 1) } };
        break;
      }
      // Not matched to any BL cart — check LEGO cart by elementId
      if (!proj.allocations[key] && legoCart) {
        const eid = poolPart.pabEntry?.element_id;
        const lgPart = eid ? (legoCart.parts ?? []).find(p => p.elementId === eid) : null;
        if (lgPart) proj.allocations[key] = { legoQty: Math.min(poolPart.wantedQty, lgPart.qty ?? 1), storeQty: {} };
      }
    }
    proj.autoAlloced = true;
    await chrome.storage.local.set({ projects: allProjects });
    selectedPoolKeys.clear();
    selectedLegoKeys.clear();
    selectedBlKeys.clear();
    selectedScratchKeys.clear();
    await refresh();
  });

  content.querySelector("#auto-alloc-btn").addEventListener("click", async () => {
    const btn = content.querySelector("#auto-alloc-btn");
    const domesticOnly = content.querySelector("#auto-alloc-domestic-only")?.checked ?? false;

    btn.disabled = true;
    btn.textContent = "Allocating…";

    const { projects: allProjects = [] } = await chrome.storage.local.get("projects");
    const proj = allProjects.find(p => p.id === id);
    if (!proj) { btn.disabled = false; btn.textContent = "⚡ Auto Allocate"; return; }

    // Wipe allocations but preserve excluded/removed flags
    const freshAllocs = {};
    for (const [key, a] of Object.entries(currentAllocs)) {
      if (a.excluded || a.removed) freshAllocs[key] = { ...a };
    }
    proj.allocations = freshAllocs;

    for (const poolPart of poolParts) {
      const key = `${poolPart.partNo}_${poolPart.colorId}`;
      if (proj.allocations[key]?.excluded || proj.allocations[key]?.removed) continue;

      const pabCents = poolPart.pabEntry?.price_cents;
      const channel  = poolPart.pabEntry?.channel;
      const legoEligible = pabCents && (!domesticOnly || channel === "pab");
      const legoPrice = legoEligible ? pabCents / 100 : Infinity;

      // Collect every individual lot across all BL store carts, sorted cheapest first.
      // This lets us split allocation across carts when one cart's cheapest lot runs out.
      // poolPart.colorId === null means the original want was "(Not Applicable)"
      // (any color accepted) -- match on partNo alone so a lot already sitting
      // in a cart under ANY color still counts toward this want, instead of
      // requiring an exact match against whatever color pabEntry happened to
      // price it at for display. Found 2026-07-28: without this, a real BL
      // cart lot in one color and this want's own PAB routing (a different,
      // arbitrarily-priced color) were treated as two unrelated demands,
      // risking a real double-buy.
      const allLots = [];
      for (const cart of blCartList) {
        for (const cp of (cart.parts ?? [])) {
          if (cp.partNo !== poolPart.partNo) continue;
          if (poolPart.colorId != null && String(cp.colorId) !== String(poolPart.colorId)) continue;
          const sp = parseStorePrice(cp.storePrice);
          if (sp == null) continue;
          allLots.push({ cartId: cart.id, qty: cp.qty ?? 1, price: sp });
        }
      }
      allLots.sort((a, b) => a.price - b.price);

      if (legoPrice === Infinity && !allLots.length) continue;

      // Greedily fill from cheapest lots, stopping when LEGO becomes cheaper
      let remaining = poolPart.wantedQty;
      const storeQty = {};
      for (const lot of allLots) {
        if (remaining <= 0) break;
        if (lot.price >= legoPrice) break;
        const take = Math.min(remaining, lot.qty);
        storeQty[lot.cartId] = (storeQty[lot.cartId] ?? 0) + take;
        remaining -= take;
      }

      if (remaining > 0 && legoPrice < Infinity) {
        proj.allocations[key] = { legoQty: remaining, storeQty };
      } else if (Object.keys(storeQty).length) {
        proj.allocations[key] = { legoQty: 0, storeQty };
      } else {
        proj.allocations[key] = { legoQty: poolPart.wantedQty, storeQty: {} };
      }
    }

    proj.autoAlloced = true;
    await chrome.storage.local.set({ projects: allProjects });
    currentAllocs = proj.allocations;

    selectedPoolKeys.clear();
    selectedLegoKeys.clear();
    selectedBlKeys.clear();
    selectedScratchKeys.clear();

    renderProjectPool(content, poolParts, currentAllocs, legoCart, blCartList, onMove, project);
    refreshLegoSection();
    for (const c of blCartList) refreshBlSection(c.id);
    refreshScratch();
    refreshGrandTotal();

    btn.disabled = false;
    btn.textContent = "✓ Done";
    setTimeout(() => { btn.textContent = "⚡ Auto Allocate"; }, 2500);
  });

  addClick(async e => {
    const unBtn = e.target.closest("[data-unalloc-key]");
    if (unBtn) {
      e.stopPropagation();
      await onUnallocate(unBtn.dataset.unallocType, unBtn.dataset.unallocCart || null, unBtn.dataset.unallocKey);
      return;
    }
    const moveBtn = e.target.closest(".section-move-btn");
    if (moveBtn) {
      const { srcType, srcCart, tgtType, tgtCart } = moveBtn.dataset;
      await onSectionMove(srcType, srcCart || null, tgtType, tgtCart || null);
      return;
    }
    const legoSaveBtn = e.target.closest(".lego-save-btn");
    if (legoSaveBtn) { showLegoSaveDiff(); return; }
    const scratchSaveBtn = e.target.closest(".scratch-save-btn");
    if (scratchSaveBtn) { showScratchSave(); return; }
    const poolSaveBtn = e.target.closest(".pool-save-btn");
    if (poolSaveBtn) { showPoolSave(); return; }
    const blCartRefreshBtn = e.target.closest(".bl-cart-refresh-btn");
    if (blCartRefreshBtn) {
      await refresh();
      return;
    }
    const blCartSaveBtn = e.target.closest(".bl-cart-save-btn");
    if (blCartSaveBtn) {
      const cid = blCartSaveBtn.dataset.cartId;
      const cart = blCartList.find(c => c.id === cid);
      if (cart) showBlCartSave(cart);
      return;
    }

    const excludeBtn = e.target.closest(".pool-exclude-btn");
    if (excludeBtn) {
      const key = excludeBtn.dataset.key;
      const { projects: allProjects = [] } = await chrome.storage.local.get("projects");
      const proj = allProjects.find(p => p.id === id);
      if (!proj) return;
      if (!proj.allocations) proj.allocations = {};
      proj.allocations[key] = { excluded: true, legoQty: 0, storeQty: {} };
      await chrome.storage.local.set({ projects: allProjects });
      currentAllocs = proj.allocations;
      selectedPoolKeys.delete(key);
      renderProjectPool(content, poolParts, currentAllocs, legoCart, blCartList, onMove, project);
      refreshLegoSection();
      for (const c of blCartList) refreshBlSection(c.id);
      refreshGrandTotal();
      return;
    }

    const restoreBtn = e.target.closest(".pool-restore-btn");
    if (restoreBtn) {
      const key = restoreBtn.dataset.key;
      const { projects: allProjects = [] } = await chrome.storage.local.get("projects");
      const proj = allProjects.find(p => p.id === id);
      if (!proj) return;
      if (proj.allocations?.[key]) delete proj.allocations[key];
      await chrome.storage.local.set({ projects: allProjects });
      currentAllocs = proj.allocations ?? {};
      renderProjectPool(content, poolParts, currentAllocs, legoCart, blCartList, onMove, project);
      refreshLegoSection();
      for (const c of blCartList) refreshBlSection(c.id);
      refreshGrandTotal();
      return;
    }

    const deleteBtn = e.target.closest(".pool-delete-btn");
    if (deleteBtn) {
      const key = deleteBtn.dataset.key;
      const { projects: allProjects = [] } = await chrome.storage.local.get("projects");
      const proj = allProjects.find(p => p.id === id);
      if (!proj) return;
      if (!proj.allocations) proj.allocations = {};
      proj.allocations[key] = { removed: true, legoQty: 0, storeQty: {} };
      await chrome.storage.local.set({ projects: allProjects });
      currentAllocs = proj.allocations;
      selectedPoolKeys.delete(key);
      renderProjectPool(content, poolParts, currentAllocs, legoCart, blCartList, onMove, project);
      refreshLegoSection();
      for (const c of blCartList) refreshBlSection(c.id);
      refreshScratch();
      refreshGrandTotal();
      return;
    }

    const blSortDirBtn = e.target.closest(".bl-cart-sort-dir");
    if (blSortDirBtn) {
      const cid = blSortDirBtn.dataset.cartId;
      blCartSortDir.set(cid, blCartSortDir.get(cid) === "desc" ? "asc" : "desc");
      refreshBlSection(cid);
      return;
    }
    const legoSortDirBtn = e.target.closest(".lego-sort-dir");
    if (legoSortDirBtn) {
      legoSectionSortDir = legoSectionSortDir === "desc" ? "asc" : "desc";
      refreshLegoSection();
      return;
    }
    const scratchSortDirBtn = e.target.closest(".scratch-sort-dir");
    if (scratchSortDirBtn) {
      scratchSortDir = scratchSortDir === "desc" ? "asc" : "desc";
      refreshScratch();
      return;
    }
    const legoTabBtn = e.target.closest(".lego-tab-btn");
    if (legoTabBtn) { legoSectionTab = legoTabBtn.dataset.legoTab; refreshLegoSection(); return; }
    const channelSelBtn = e.target.closest(".bl-sel-channel");
    if (channelSelBtn) {
      const cid = channelSelBtn.dataset.cartId;
      const ch  = channelSelBtn.dataset.channel;
      if (!selectedBlKeys.has(cid)) selectedBlKeys.set(cid, new Set());
      const selSet = selectedBlKeys.get(cid);
      for (const [key, a] of Object.entries(currentAllocs)) {
        if (!(a.storeQty?.[cid] > 0)) continue;
        const part = poolParts.find(p => `${p.partNo}_${p.colorId}` === key);
        if (part?.pabEntry?.channel === ch) selSet.add(key);
      }
      refreshBlSection(cid);
      return;
    }
    const pabCheaperBtn = e.target.closest(".bl-sel-pab-cheaper");
    if (pabCheaperBtn) {
      const cid  = pabCheaperBtn.dataset.cartId;
      const cart = blCartList.find(c => c.id === cid);
      if (!selectedBlKeys.has(cid)) selectedBlKeys.set(cid, new Set());
      const selSet = selectedBlKeys.get(cid);
      for (const [key, a] of Object.entries(currentAllocs)) {
        if (!(a.storeQty?.[cid] > 0)) continue;
        const part     = poolParts.find(p => `${p.partNo}_${p.colorId}` === key);
        const cartPart = cart?.parts?.find(cp => cp.partNo === part?.partNo && String(cp.colorId) === String(part?.colorId));
        const storeNum = parseStorePrice(cartPart?.storePrice);
        const pabNum   = part?.pabEntry?.price_cents ? part.pabEntry.price_cents / 100 : null;
        if (storeNum != null && pabNum != null && pabNum < storeNum) selSet.add(key);
      }
      refreshBlSection(cid);
      return;
    }
    if (e.target.classList.contains("proj-configure-link")) { renderProjectSetup(id, content); return; }
    const openBtn = e.target.closest(".open-cart-btn");
    if (openBtn) navigate(`list/${openBtn.dataset.type}/${openBtn.dataset.id}`);
  });

  addClick(async e => {
    const transferBtn = e.target.closest(".lego-proj-transfer-btn");
    if (!transferBtn) return;
    const channel = transferBtn.dataset.channel;
    // Use legoCart.parts when saved (same source as the LEGO cart list view).
    // Fall back to pool allocations if no cart is linked or cart has no saved parts.
    const sourceParts = legoCart?.parts?.length
      ? legoCart.parts.filter(p =>
          p.elementId && (channel === "both" ? (p.channel === "pab" || p.channel === "bap") : p.channel === channel)
        ).map(p => ({ elementId: p.elementId, qty: p.qty ?? p.quantity ?? 1, channel: p.channel }))
      : Object.entries(currentAllocs)
          .filter(([, a]) => (a.legoQty ?? 0) > 0)
          .map(([key, a]) => {
            const part = poolParts.find(p => `${p.partNo}_${p.colorId}` === key);
            const ch = part?.pabEntry?.channel;
            if (!part?.pabEntry?.element_id) return null;
            if (channel !== "both" && ch !== channel) return null;
            return { elementId: part.pabEntry.element_id, qty: a.legoQty, channel: ch };
          }).filter(Boolean);
    const items = sourceParts.filter(i => i.qty > 0);
    if (!items.length) return;
    const origLabel = transferBtn.textContent;
    transferBtn.disabled = true;
    transferBtn.textContent = "Opening…";
    await chrome.runtime.sendMessage({ type: "QUEUE_TRANSFER", items, channel });
    transferBtn.textContent = "Sent!";
    setTimeout(() => { transferBtn.disabled = false; transferBtn.textContent = origLabel; }, 3000);
  });

  addListener("change", e => {
    // Select-all checkbox for a section
    const selAll = e.target.closest(".section-sel-all");
    if (selAll) {
      const { sectionType, sectionCart } = selAll.dataset;
      if (sectionType === "lego") {
        const keys = Object.entries(currentAllocs).filter(([, a]) => (a.legoQty ?? 0) > 0).map(([k]) => k);
        if (selAll.checked) keys.forEach(k => selectedLegoKeys.add(k));
        else                keys.forEach(k => selectedLegoKeys.delete(k));
        refreshLegoSection();
      } else if (sectionType === "bl") {
        const keys = Object.entries(currentAllocs).filter(([, a]) => (a.storeQty?.[sectionCart] ?? 0) > 0).map(([k]) => k);
        if (!selectedBlKeys.has(sectionCart)) selectedBlKeys.set(sectionCart, new Set());
        if (selAll.checked) keys.forEach(k => selectedBlKeys.get(sectionCart).add(k));
        else                keys.forEach(k => selectedBlKeys.get(sectionCart).delete(k));
        refreshBlSection(sectionCart);
      } else if (sectionType === "scratch") {
        const keys = poolParts.filter(p => allocRemaining(currentAllocs, `${p.partNo}_${p.colorId}`, p.wantedQty) > 0).map(p => `${p.partNo}_${p.colorId}`);
        if (selAll.checked) keys.forEach(k => selectedScratchKeys.add(k));
        else                keys.forEach(k => selectedScratchKeys.delete(k));
        refreshScratch();
      }
      return;
    }
    // BL cart sort dropdown
    const blSortSel = e.target.closest(".bl-cart-sort");
    if (blSortSel) {
      blCartSort.set(blSortSel.dataset.cartId, blSortSel.value);
      refreshBlSection(blSortSel.dataset.cartId);
      return;
    }
    const legoSortSel = e.target.closest(".lego-sort");
    if (legoSortSel) {
      legoSectionSort = legoSortSel.value;
      refreshLegoSection();
      return;
    }
    const scratchSortSel = e.target.closest(".scratch-sort");
    if (scratchSortSel) {
      scratchSort = scratchSortSel.value;
      refreshScratch();
      return;
    }
    // Estimated shipping input for BL carts
    const estShipEl = e.target.closest(".bl-est-ship");
    if (estShipEl) {
      const cid = estShipEl.dataset.cartId;
      const val = parseFloat(estShipEl.value);
      if (!isNaN(val) && val >= 0) estBlShipping[cid] = val;
      else delete estBlShipping[cid];
      saveEstShipping();
      refreshBlSection(cid);
      refreshGrandTotal();
      return;
    }
    // Individual row checkbox
    const chk = e.target.closest(".section-row-check");
    if (!chk) return;
    const { sectionType, sectionCart, key } = chk.dataset;
    if (sectionType === "lego") {
      if (chk.checked) selectedLegoKeys.add(key); else selectedLegoKeys.delete(key);
      refreshLegoSection();
    } else if (sectionType === "bl") {
      if (!selectedBlKeys.has(sectionCart)) selectedBlKeys.set(sectionCart, new Set());
      if (chk.checked) selectedBlKeys.get(sectionCart).add(key); else selectedBlKeys.get(sectionCart).delete(key);
      refreshBlSection(sectionCart);
    } else if (sectionType === "scratch") {
      if (chk.checked) selectedScratchKeys.add(key); else selectedScratchKeys.delete(key);
      refreshScratch();
    }
  });

  if (!poolParts.length) {
    content.querySelector("#pool-section").innerHTML = `
      <div class="section">
        <div class="section-header"><span>Wanted List Pool</span></div>
        <div class="section-empty">${
          !project.wantedListIds?.length
            ? `No wanted lists added to pool. <button class="proj-configure-link back-btn" style="font-size:12px;color:#2563eb">Configure</button> to add some.`
            : "The selected wanted lists have no parts."
        }</div>
      </div>`;
    return;
  }

  currentProjectTab   = "all";
  legoSectionTab      = "all";
  selectedPoolKeys.clear();
  selectedLegoKeys.clear();
  selectedBlKeys.clear();
  selectedScratchKeys.clear();
  showAllocatedParts  = false;
  showExcludedParts   = false;

  await Promise.allSettled(poolParts.map(async (p, i) => {
    // colorId === null means the original want was "(Not Applicable)" (any
    // color accepted) -- see collectWantedListParts() in content.js. There's
    // no single (part, color) to price, so pull every in-stock color for
    // this part_no and show the cheapest as a representative price. This is
    // display/pricing only -- poolParts[i].colorId is deliberately left
    // untouched (still null) so Auto Allocate still treats it as "any color"
    // rather than locking onto whichever color happened to be cheapest here.
    if (p.colorId == null) {
      const rows = await chrome.runtime.sendMessage({
        type: "GET_PAB_PRICES_FOR_PART", partNo: p.partNo,
      });
      poolParts[i].pabEntry = pickCheapestPabRow(rows);
      return;
    }
    poolParts[i].pabEntry = await chrome.runtime.sendMessage({
      type: "GET_PAB_PRICE", partNo: p.partNo, colorId: p.colorId,
    });
  }));

  // Show "Domestic only" checkbox only if pool has any STD (bap) channel parts
  if (poolParts.some(p => p.pabEntry?.channel === "bap")) {
    const stdLabel = content.querySelector("#auto-alloc-std-label");
    if (stdLabel) stdLabel.style.display = "flex";
  }


  // One-time auto-allocation: match pool parts against BL store carts and LEGO cart on first open
  if (!project.autoAlloced && (blCartList.length || legoCart)) {
    const { projects: allProjects = [] } = await chrome.storage.local.get("projects");
    const proj = allProjects.find(p => p.id === id);
    if (proj) {
      if (!proj.allocations) proj.allocations = {};
      let dirty = false;
      for (const poolPart of poolParts) {
        const key = `${poolPart.partNo}_${poolPart.colorId}`;
        if (proj.allocations[key]) continue;
        // Collect all lots across all carts, cheapest first
        const allLots = [];
        for (const cart of blCartList) {
          for (const cp of (cart.parts ?? [])) {
            if (cp.partNo !== poolPart.partNo || String(cp.colorId) !== String(poolPart.colorId)) continue;
            const sp = parseStorePrice(cp.storePrice);
            if (sp == null) continue;
            allLots.push({ cartId: cart.id, qty: cp.qty ?? 1, price: sp });
          }
        }
        allLots.sort((a, b) => a.price - b.price);
        if (allLots.length) {
          let remaining = poolPart.wantedQty;
          const storeQty = {};
          for (const lot of allLots) {
            if (remaining <= 0) break;
            const take = Math.min(remaining, lot.qty);
            storeQty[lot.cartId] = (storeQty[lot.cartId] ?? 0) + take;
            remaining -= take;
          }
          proj.allocations[key] = { legoQty: 0, storeQty };
          dirty = true;
        }
        // Not matched to any BL cart — check LEGO cart by elementId
        if (!proj.allocations[key] && legoCart) {
          const eid = poolPart.pabEntry?.element_id;
          const lgPart = eid ? (legoCart.parts ?? []).find(p => p.elementId === eid) : null;
          if (lgPart) {
            proj.allocations[key] = { legoQty: Math.min(poolPart.wantedQty, lgPart.qty ?? 1), storeQty: {} };
            dirty = true;
          }
        }
      }
      proj.autoAlloced = true;
      await chrome.storage.local.set({ projects: allProjects });
      currentAllocs = proj.allocations;
    }
  }

  renderProjectPool(content, poolParts, currentAllocs, legoCart, blCartList, onMove, project);
  refreshLegoSection();
  for (const c of blCartList) refreshBlSection(c.id);
  refreshScratch();
  refreshGrandTotal();
}

function renderProjectPool(content, parts, allocations, legoCart, blCartList, onMove, project) {
  const poolEl = content.querySelector("#pool-section");
  if (!poolEl) return;

  parts = parts.filter(p => !allocations[`${p.partNo}_${p.colorId}`]?.removed);

  function remQty(p) {
    const key = `${p.partNo}_${p.colorId}`;
    const a   = allocations[key];
    if (!a) return p.wantedQty;
    const used = (a.legoQty ?? 0) + Object.values(a.storeQty ?? {}).reduce((s, v) => s + v, 0);
    return p.wantedQty - used;
  }

  function sortPool(arr) {
    const dir = poolSortDir === "desc" ? -1 : 1;
    return [...arr].sort((a, b) => {
      const na = (a.pabEntry?.bl_part_name || a.name || "").toLowerCase();
      const nb = (b.pabEntry?.bl_part_name || b.name || "").toLowerCase();
      const ia = a.partNo || "", ib = b.partNo || "";
      const ca = (a.pabEntry?.bl_color_name || String(a.colorId ?? "")).toLowerCase();
      const cb = (b.pabEntry?.bl_color_name || String(b.colorId ?? "")).toLowerCase();
      switch (poolSort) {
        case "partid_color": return dir * (ia.localeCompare(ib, undefined, { numeric: true }) || ca.localeCompare(cb));
        case "partid":       return dir * ia.localeCompare(ib, undefined, { numeric: true });
        case "color":        return dir * (ca.localeCompare(cb) || na.localeCompare(nb));
        case "pab_price":    return dir * ((a.pabEntry?.price_cents ?? -1) - (b.pabEntry?.price_cents ?? -1));
        case "channel": {
          const o = { pab: 0, bap: 1 };
          return dir * ((o[a.pabEntry?.channel] ?? 2) - (o[b.pabEntry?.channel] ?? 2) || na.localeCompare(nb));
        }
        default: return dir * (na.localeCompare(nb) || ca.localeCompare(cb));
      }
    });
  }

  function hasAnyAlloc(p) {
    const a = allocations[`${p.partNo}_${p.colorId}`];
    if (!a) return false;
    return (a.legoQty ?? 0) + Object.values(a.storeQty ?? {}).reduce((s, v) => s + v, 0) > 0;
  }

  const tab           = currentProjectTab;
  const excludedParts = parts.filter(p => allocations[`${p.partNo}_${p.colorId}`]?.excluded);
  const activeParts   = parts.filter(p => !allocations[`${p.partNo}_${p.colorId}`]?.excluded);
  const unallocParts  = activeParts.filter(p => !hasAnyAlloc(p));
  const allocedParts  = activeParts.filter(p => hasAnyAlloc(p));

  const totalLots      = activeParts.length;
  const totalPiecesAll = activeParts.reduce((s, p) => s + p.wantedQty, 0);
  const allocedLots    = allocedParts.length;
  const unallocLots    = unallocParts.length;
  const unallocPieces  = unallocParts.reduce((s, p) => s + remQty(p), 0);
  const allocedPieces  = totalPiecesAll - unallocPieces;

  const pabParts = unallocParts.filter(p => p.pabEntry?.channel === "pab");
  const stdParts = unallocParts.filter(p => p.pabEntry?.channel === "bap");
  const blParts  = unallocParts.filter(p => !p.pabEntry?.channel);
  const counts   = { all: unallocParts.length, pab: pabParts.length, std: stdParts.length, bl: blParts.length };
  const filtered = sortPool(tab === "pab" ? pabParts : tab === "std" ? stdParts : tab === "bl" ? blParts : unallocParts);

  const allSelected  = filtered.length > 0 && filtered.every(p => selectedPoolKeys.has(`${p.partNo}_${p.colorId}`));
  const someSelected = !allSelected && filtered.some(p => selectedPoolKeys.has(`${p.partNo}_${p.colorId}`));
  const selCount     = filtered.filter(p => selectedPoolKeys.has(`${p.partNo}_${p.colorId}`)).length;

  const tabBar = ["all","pab","std","bl"].map(k => {
    const label = { all: "All", pab: "PAB", std: "STD", bl: "BrickLink" }[k];
    return `<button class="tab${tab === k ? " active" : ""}" data-project-tab="${k}">${label} (${counts[k]})</button>`;
  }).join("");

  const moveTargets = [
    `<button class="btn move-btn" data-move-type="lego" data-move-cart="" style="font-size:12px;background:#eff6ff;border-color:#93c5fd;color:#1d4ed8">→ Pick-A-Brick Cart</button>`,
    ...(blCartList ?? []).map(c =>
      `<button class="btn move-btn" data-move-type="bl" data-move-cart="${esc(c.id)}" style="font-size:12px">→ ${esc(c.name)}</button>`)
  ].join(" ");

  const actionBar = selCount > 0 ? `
    <div style="display:flex;align-items:center;gap:8px;padding:7px 14px;background:#f8f9fa;border-bottom:1px solid #e1e4e8;flex-wrap:wrap">
      <span style="font-size:12px;color:#6c757d;flex-shrink:0">${selCount} selected</span>
      ${moveTargets}
    </div>` : "";

  function buildRow(p, dimmed) {
    const key   = `${p.partNo}_${p.colorId}`;
    const name     = p.pabEntry?.bl_part_name  || p.name      || "";
    const color    = p.pabEntry?.bl_color_name || p.colorName || "";
    const colorHex = p.pabEntry?.bl_color_hex;
    const price    = p.pabEntry?.price_formatted || "—";
    const ch       = p.pabEntry?.channel;
    const badge    = ch === "pab"
      ? `<span style="padding:1px 6px;border-radius:3px;font-size:11px;font-weight:700;background:#dcfce7;color:#16a34a">PAB</span>`
      : ch === "bap"
      ? `<span style="padding:1px 6px;border-radius:3px;font-size:11px;font-weight:700;background:#fef9c3;color:#ca8a04">STD</span>`
      : `<span style="padding:1px 6px;border-radius:3px;font-size:11px;font-weight:700;background:#f3f4f6;color:#6c757d">BL</span>`;
    const elemId  = p.pabEntry?.element_id;
    const rem     = remQty(p);
    const checked = selectedPoolKeys.has(key) && !dimmed;
    return `<tr${dimmed ? ' style="opacity:0.4"' : ""}>
      <td style="padding:4px 8px${dimmed ? "" : ";cursor:pointer"}">${dimmed ? "" : `<input type="checkbox" class="pool-row-check" data-key="${esc(key)}" ${checked ? "checked" : ""} style="cursor:pointer">`}</td>
      <td style="padding:0"><a href="https://www.bricklink.com/v2/catalog/catalogitem.page?P=${esc(p.partNo || '')}#T=C&C=${esc(String(p.colorId ?? ''))}" target="_blank" rel="noopener" style="display:block;padding:4px 8px;font-size:12px;font-family:monospace;color:inherit;text-decoration:none" title="View on BrickLink">${esc(p.partNo || "")}${elemId ? `<br><span style="color:#9ca3af">${elemId}</span>` : ""}</a></td>
      <td>${p.imageUrl ? `<img src="${esc(p.imageUrl)}" style="width:60px;height:45px;object-fit:contain">` : ""}</td>
      <td>${esc(name)}</td>
      <td><span style="display:inline-flex;align-items:center;gap:4px">${colorHex ? `<span style="display:inline-block;width:12px;height:12px;border-radius:2px;background:#${esc(colorHex)};border:1px solid rgba(0,0,0,0.2);flex-shrink:0"></span>` : ""}${esc(color)}</span></td>
      <td style="text-align:right;white-space:nowrap">
        <div style="font-size:11px;color:#6c757d">Wanted ${p.wantedQty}</div>
        <div style="font-size:11px;font-weight:600${rem < 0 ? ";color:#dc2626" : ""}">Assigned ${p.wantedQty - rem}</div>
      </td>
      <td>${price}</td>
      <td>${badge}</td>
      <td style="padding:2px 6px;white-space:nowrap">
        <button class="btn pool-exclude-btn" data-key="${esc(key)}" title="Exclude from pool" style="font-size:11px;padding:1px 5px;color:#9ca3af;border-color:#e5e7eb">×</button>
        <button class="btn pool-delete-btn" data-key="${esc(key)}" title="Permanently remove from pool" style="font-size:11px;padding:1px 5px;color:#dc2626;border-color:#fca5a5;margin-left:3px">🗑</button>
      </td>
    </tr>`;
  }

  function buildExcludedRow(p) {
    const key      = `${p.partNo}_${p.colorId}`;
    const name     = p.pabEntry?.bl_part_name  || p.name      || "";
    const color    = p.pabEntry?.bl_color_name || p.colorName || "";
    const colorHex = p.pabEntry?.bl_color_hex;
    return `<tr style="opacity:0.5">
      <td></td>
      <td style="padding:4px 8px;font-size:12px;font-family:monospace;color:#9ca3af">${esc(p.partNo || "")}</td>
      <td>${p.imageUrl ? `<img src="${esc(p.imageUrl)}" style="width:60px;height:45px;object-fit:contain;filter:grayscale(1)">` : ""}</td>
      <td style="text-decoration:line-through;color:#9ca3af">${esc(name)}</td>
      <td style="color:#9ca3af"><span style="display:inline-flex;align-items:center;gap:4px">${colorHex ? `<span style="display:inline-block;width:12px;height:12px;border-radius:2px;background:#${esc(colorHex)};border:1px solid rgba(0,0,0,0.2);flex-shrink:0;opacity:0.6"></span>` : ""}${esc(color)}</span></td>
      <td style="text-align:right;font-size:11px;color:#9ca3af">Wanted ${p.wantedQty}</td>
      <td></td><td></td>
      <td style="padding:2px 6px;white-space:nowrap">
        <button class="btn pool-restore-btn" data-key="${esc(key)}" title="Restore to pool" style="font-size:11px;padding:1px 5px;color:#2563eb;border-color:#bfdbfe">↩</button>
        <button class="btn pool-delete-btn" data-key="${esc(key)}" title="Permanently remove from pool" style="font-size:11px;padding:1px 5px;color:#dc2626;border-color:#fca5a5;margin-left:3px">🗑</button>
      </td>
    </tr>`;
  }

  const mainRows    = filtered.map(p => buildRow(p, false)).join("");
  const allocedRows = showAllocatedParts
    ? allocedParts
        .filter(p => {
          const ch = p.pabEntry?.channel;
          return tab === "pab" ? ch === "pab" : tab === "std" ? ch === "bap" : tab === "bl" ? !ch : true;
        })
        .map(p => buildRow(p, true)).join("")
    : "";
  const excludedRows = showExcludedParts ? excludedParts.map(buildExcludedRow).join("") : "";

  const bottomToggles = [
    allocedParts.length > 0
      ? `<button class="btn" id="toggle-alloc-btn" style="font-size:12px;color:#6c757d">${showAllocatedParts ? "Hide" : "Show"} ${allocedParts.length} allocated</button>`
      : "",
    excludedParts.length > 0
      ? `<button class="btn" id="toggle-excl-btn" style="font-size:12px;color:#dc2626">${showExcludedParts ? "Hide" : "Show"} ${excludedParts.length} removed</button>`
      : "",
  ].filter(Boolean).join(" ");
  const showToggleBar = bottomToggles ? `
    <div style="padding:6px 14px;border-top:1px solid #f3f4f6;display:flex;gap:8px;justify-content:center">
      ${bottomToggles}
    </div>` : "";

  poolEl.innerHTML = `
    <div class="section">
      <div class="section-header">
        <span>Wanted List Pool</span>
        <span style="font-size:12px;color:#9ca3af;font-weight:400;margin-left:8px">${totalLots} lots · ${totalPiecesAll.toLocaleString()} pieces</span>
        <span style="font-size:11px;font-weight:400;margin-left:6px;color:#9ca3af">·</span>
        <span style="font-size:11px;font-weight:400;margin-left:6px;color:#16a34a">${allocedLots} lots / ${allocedPieces.toLocaleString()} pcs allocated</span>
        <span style="font-size:11px;font-weight:400;margin-left:6px;color:#9ca3af">·</span>
        <span style="font-size:11px;font-weight:400;margin-left:6px;color:#d97706">${unallocLots} lots / ${unallocPieces.toLocaleString()} pcs remaining</span>
        <div style="margin-left:auto;display:flex;align-items:center;gap:6px">
          ${(project?.wantedListIds?.length === 1)
            ? `<button class="btn pool-save-btn" style="font-size:12px;background:#1e2330;color:#fff;border-color:#1e2330">Save to List ↓</button>`
            : (project?.wantedListIds?.length > 1)
            ? `<button class="btn pool-save-btn" style="font-size:12px;background:#1e2330;color:#fff;border-color:#1e2330">Save as New List ↓</button>`
            : ""}
          <label style="font-size:11px;color:#9ca3af">Sort:</label>
          <select id="pool-sort-select" style="font-size:11px;padding:2px 4px;border:1px solid #d1d5db;border-radius:3px">
            ${[["name_color","Name, Color"],["partid_color","Part, Color"],["partid","Part"],["color","Color"],["pab_price","PAB Price"],["channel","Channel"]]
              .map(([v,l])=>`<option value="${v}"${poolSort===v?" selected":""}>${l}</option>`).join("")}
          </select>
          <select id="pool-sort-dir" style="font-size:11px;padding:2px 4px;border:1px solid #d1d5db;border-radius:3px">
            <option value="asc"${poolSortDir==="asc"?" selected":""}>↑ Asc</option>
            <option value="desc"${poolSortDir==="desc"?" selected":""}>↓ Desc</option>
          </select>
        </div>
      </div>
      <div class="tab-bar">${tabBar}</div>
      ${actionBar}
      ${(filtered.length || (showAllocatedParts && allocedParts.length) || (showExcludedParts && excludedParts.length))
        ? `<div style="max-height:460px;overflow-y:auto">
            <table>
              <thead><tr>
                <th style="width:32px;padding:4px 8px"><input type="checkbox" id="pool-select-all" ${allSelected ? "checked" : ""} style="cursor:pointer"></th>
                <th>Part</th><th>Image</th><th>Name</th><th>Color</th>
                <th style="text-align:right;white-space:nowrap">Wanted / Assigned</th><th>PAB Price</th><th>Channel</th>
                <th style="width:30px"></th>
              </tr></thead>
              <tbody>${mainRows}${allocedRows}${excludedRows}</tbody>
            </table>
          </div>
          ${showToggleBar}`
        : `<div class="section-empty">No parts in this tab.</div>${showToggleBar}`}
    </div>`;

  // Header checkbox indeterminate state (must be set via JS, not HTML attribute)
  const hdrChk = poolEl.querySelector("#pool-select-all");
  if (hdrChk) hdrChk.indeterminate = someSelected;

  for (const btn of poolEl.querySelectorAll("[data-project-tab]")) {
    btn.addEventListener("click", () => {
      currentProjectTab = btn.dataset.projectTab;
      renderProjectPool(content, parts, allocations, legoCart, blCartList, onMove, project);
    });
  }

  if (hdrChk) {
    hdrChk.addEventListener("change", () => {
      if (hdrChk.checked) filtered.forEach(p => selectedPoolKeys.add(`${p.partNo}_${p.colorId}`));
      else                 filtered.forEach(p => selectedPoolKeys.delete(`${p.partNo}_${p.colorId}`));
      renderProjectPool(content, parts, allocations, legoCart, blCartList, onMove, project);
    });
  }

  for (const chk of poolEl.querySelectorAll(".pool-row-check")) {
    chk.addEventListener("change", () => {
      if (chk.checked) selectedPoolKeys.add(chk.dataset.key);
      else             selectedPoolKeys.delete(chk.dataset.key);
      renderProjectPool(content, parts, allocations, legoCart, blCartList, onMove, project);
    });
  }
  poolEl.addEventListener("click", e => {
    const td = e.target.closest("td");
    if (!td) return;
    const cb = td.querySelector(".pool-row-check");
    if (!cb || e.target === cb) return;
    cb.checked = !cb.checked;
    cb.dispatchEvent(new Event("change", { bubbles: true }));
  });

  for (const btn of poolEl.querySelectorAll(".move-btn")) {
    btn.addEventListener("click", () => onMove(btn.dataset.moveType, btn.dataset.moveCart || null));
  }

  poolEl.querySelector("#toggle-alloc-btn")?.addEventListener("click", () => {
    showAllocatedParts = !showAllocatedParts;
    renderProjectPool(content, parts, allocations, legoCart, blCartList, onMove, project);
  });
  poolEl.querySelector("#toggle-excl-btn")?.addEventListener("click", () => {
    showExcludedParts = !showExcludedParts;
    renderProjectPool(content, parts, allocations, legoCart, blCartList, onMove, project);
  });

  poolEl.querySelector("#pool-sort-select")?.addEventListener("change", e => {
    poolSort = e.target.value;
    renderProjectPool(content, parts, allocations, legoCart, blCartList, onMove);
  });
  poolEl.querySelector("#pool-sort-dir")?.addEventListener("change", e => {
    poolSortDir = e.target.value;
    renderProjectPool(content, parts, allocations, legoCart, blCartList, onMove);
  });
}

// ─── Project setup view ──────────────────────────────────────────────────────

async function renderProjectSetup(id, content) {
  const { projects = [], wantedLists = [], carts = [], legoCarts = [] } =
    await chrome.storage.local.get(["projects", "wantedLists", "carts", "legoCarts"]);
  const project = projects.find(p => p.id === id);
  if (!project) { navigate("projects"); return; }

  const wlChecked  = new Set(project.wantedListIds ?? []);
  const blChecked  = new Set(project.blCartIds ?? []);
  const scratchId  = project.scratchWantedListId ?? "";

  function checkRow(inputType, name, value, checked, label, meta) {
    return `
      <label style="display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:1px solid #f3f4f6;cursor:pointer">
        <input type="${inputType}" name="${name}" value="${esc(value)}" ${checked ? "checked" : ""}
          style="width:15px;height:15px;flex-shrink:0;cursor:pointer">
        <span style="flex:1;font-size:13px">${esc(label)}</span>
        ${meta ? `<span style="font-size:12px;color:#6c757d;flex-shrink:0">${meta}</span>` : ""}
      </label>`;
  }

  const wlRowsHtml = wantedLists.length
    ? wantedLists.map(l => checkRow("checkbox", "wl-pool", l.id, wlChecked.has(l.id), l.name, `${(l.partsCount ?? 0).toLocaleString()} parts`)).join("")
    : `<div style="color:#9ca3af;font-size:12px;padding:8px 0">No wanted lists imported yet.</div>`;

  const blRowsHtml = carts.length
    ? carts.map(l => checkRow("checkbox", "bl-cart", l.id, blChecked.has(l.id), l.name, `${(l.partsCount ?? 0).toLocaleString()} parts`)).join("")
    : `<div style="color:#9ca3af;font-size:12px;padding:8px 0">No BL store carts imported yet.</div>`;

  const lgRoleOptions = sel => [
    ["main",         "Main"],
    ["overflow",     "Overflow"],
    ["pab-only",     "Bestseller Only"],
    ["bap-only",     "Standard Only"],
    ["pab-overflow", "Bestseller Overflow"],
    ["bap-overflow", "Standard Overflow"],
  ].map(([v, l]) => `<option value="${v}"${sel === v ? " selected" : ""}>${l}</option>`).join("");

  const lgCartOptions = sel =>
    `<option value=""${!sel ? " selected" : ""}>(select cart)</option>` +
    legoCarts.map(l => `<option value="${esc(l.id)}"${sel === l.id ? " selected" : ""}>${esc(l.name)} · ${(l.partsCount ?? 0).toLocaleString()} parts</option>`).join("");

  function buildLgRow(cartId = "", role = "overflow") {
    return `<div class="lego-cart-row" style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #f3f4f6">
      <select class="lego-cart-sel" style="flex:1;font-size:12px;padding:4px 6px;border:1px solid #d1d5db;border-radius:4px">${lgCartOptions(cartId)}</select>
      <select class="lego-cart-role-sel" style="font-size:12px;padding:4px 6px;border:1px solid #d1d5db;border-radius:4px">${lgRoleOptions(role)}</select>
      <button class="lego-cart-remove-btn" style="background:none;border:none;color:#dc2626;font-size:14px;padding:2px 6px;cursor:pointer" title="Remove">✕</button>
    </div>`;
  }

  const existingLgRows = getProjectLegoCarts(project).map(c => buildLgRow(c.cartId, c.role)).join("");

  function scratchOptions(excludeIds) {
    const available = wantedLists.filter(l => !excludeIds.has(l.id));
    if (!available.length) return `<option value="">None (no available lists)</option>`;
    return `<option value="">None — unallocated parts will be ephemeral</option>` +
      available.map(l => `<option value="${esc(l.id)}" ${scratchId === l.id && !excludeIds.has(l.id) ? "selected" : ""}>${esc(l.name)}</option>`).join("");
  }

  content.innerHTML = `
    <div class="detail-header">
      <button class="back-btn" id="back-btn">← ${esc(project.name)}</button>
      <div>
        <div style="font-size:18px;font-weight:700;color:#1e2330">Configure Project</div>
        <div class="detail-meta">${esc(project.name)}</div>
      </div>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px">
      <div class="section">
        <div class="section-header">
          <span>Wanted List Pool</span>
          <span style="font-size:11px;color:#9ca3af;font-weight:400;margin-left:8px">quantities summed across all selected</span>
        </div>
        <div style="padding:4px 16px 6px" id="wl-pool-rows">${wlRowsHtml}</div>
      </div>

      <div class="section">
        <div class="section-header">
          <span>BrickLink Store Carts</span>
          <span style="font-size:11px;color:#9ca3af;font-weight:400;margin-left:8px">read-only price reference</span>
        </div>
        <div style="padding:4px 16px 6px">${blRowsHtml}</div>
      </div>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:18px">
      <div class="section">
        <div class="section-header">
          <span>Pick-A-Brick Carts</span>
          ${legoCarts.length ? `<button id="add-lego-cart-btn" class="btn" style="margin-left:auto;font-size:12px;padding:2px 10px;background:#1e2330;color:#fff;border:none">+ Add Cart</button>` : ""}
        </div>
        <div style="padding:4px 16px 6px">
          ${legoCarts.length
            ? `<div id="lego-cart-rows">${existingLgRows || ""}</div>`
            : `<div style="color:#9ca3af;font-size:12px;padding:8px 0">No Pick-A-Brick carts saved yet. Save a cart from a LEGO PAB transfer first.</div>`}
        </div>
        <div style="display:flex;align-items:center;gap:6px;padding:2px 16px 10px">
          <label for="gwp-threshold-input" style="font-size:11px;color:#6c757d">GWP threshold $</label>
          <input id="gwp-threshold-input" type="number" min="0" step="1" placeholder="off"
            value="${project.gwpThreshold || ""}"
            style="width:70px;font-size:12px;padding:3px 6px;border:1px solid #d1d5db;border-radius:4px">
          <span style="font-size:11px;color:#9ca3af">each destination cart's combined total tries to clear this before spilling to the next</span>
        </div>
      </div>

      <div class="section">
        <div class="section-header">
          <span>Scratch Space</span>
          <span style="font-size:11px;color:#9ca3af;font-weight:400;margin-left:8px">persist unallocated parts between sessions</span>
        </div>
        <div style="padding:12px 16px">
          <div style="font-size:12px;color:#6c757d;margin-bottom:8px">
            Link an existing wanted list. Pool lists are excluded.
          </div>
          <select id="scratch-select" style="width:100%;padding:6px 8px;border:1px solid #d1d5db;border-radius:4px;font-size:13px">
            ${scratchOptions(wlChecked)}
          </select>
        </div>
      </div>
    </div>

    <div style="display:flex;gap:10px">
      <button id="save-btn" style="padding:8px 22px;background:#1e2330;color:#fff;border:none;border-radius:5px;font-size:13px;font-weight:600;cursor:pointer">Save</button>
      <button id="cancel-btn" style="padding:8px 18px;background:#fff;color:#374151;border:1px solid #d1d5db;border-radius:5px;font-size:13px;cursor:pointer">Cancel</button>
    </div>`;

  const scratchSelect = content.querySelector("#scratch-select");

  // Keep scratch dropdown in sync: exclude lists checked as pool sources
  content.querySelectorAll("input[name='wl-pool']").forEach(cb => {
    cb.addEventListener("change", () => {
      const checked = new Set([...content.querySelectorAll("input[name='wl-pool']:checked")].map(el => el.value));
      const prev = scratchSelect.value;
      scratchSelect.innerHTML = scratchOptions(checked);
      if (prev && !checked.has(prev)) scratchSelect.value = prev;
    });
  });

  // ── LEGO cart multi-row editor ───────────────────────────────────────────────
  const lgRowsContainer = content.querySelector("#lego-cart-rows");

  // Wire remove buttons on existing rows
  lgRowsContainer?.querySelectorAll(".lego-cart-remove-btn").forEach(btn => {
    btn.addEventListener("click", () => btn.closest(".lego-cart-row").remove());
  });

  // Add Cart button appends a blank row, defaulting to "Main" -- unless a
  // Main row already exists, since only one cart can hold that role (see the
  // demote-on-change handler below).
  content.querySelector("#add-lego-cart-btn")?.addEventListener("click", () => {
    if (!lgRowsContainer) return;
    const hasMain = [...lgRowsContainer.querySelectorAll(".lego-cart-role-sel")].some(sel => sel.value === "main");
    lgRowsContainer.insertAdjacentHTML("beforeend", buildLgRow("", hasMain ? "overflow" : "main"));
    const newRow = lgRowsContainer.lastElementChild;
    newRow.querySelector(".lego-cart-remove-btn").addEventListener("click", () => newRow.remove());
  });

  // Enforce single-cart-per-primary-role: main, pab-only, and bap-only are each
  // consulted as `[0]` by resolveLegoDestinationChains(), so a second row with
  // the same role would silently be unreachable. Demote the previous holder to
  // Overflow when a new row claims one of these roles. overflow/pab-overflow/
  // bap-overflow are legitimately multi-cart chains and are left alone.
  const SINGLE_CART_ROLES = new Set(["main", "pab-only", "bap-only"]);
  lgRowsContainer?.addEventListener("change", e => {
    if (!e.target.classList.contains("lego-cart-role-sel") || !SINGLE_CART_ROLES.has(e.target.value)) return;
    const role = e.target.value;
    for (const sel of lgRowsContainer.querySelectorAll(".lego-cart-role-sel")) {
      if (sel !== e.target && sel.value === role) sel.value = "overflow";
    }
  });

  content.querySelector("#back-btn").addEventListener("click", () => renderProjectDetail(id, content));
  content.querySelector("#cancel-btn").addEventListener("click", () => renderProjectDetail(id, content));

  content.querySelector("#save-btn").addEventListener("click", async () => {
    const newWlIds        = [...content.querySelectorAll("input[name='wl-pool']:checked")].map(el => el.value);
    const newBlIds        = [...content.querySelectorAll("input[name='bl-cart']:checked")].map(el => el.value);
    const newLegoCartIds  = [...content.querySelectorAll(".lego-cart-row")]
      .map(row => ({ cartId: row.querySelector(".lego-cart-sel").value, role: row.querySelector(".lego-cart-role-sel").value }))
      .filter(c => c.cartId);
    const newScratch = scratchSelect.value || null;
    const gwpVal = parseFloat(content.querySelector("#gwp-threshold-input")?.value);
    const newGwpThreshold = (!isNaN(gwpVal) && gwpVal > 0) ? gwpVal : null;

    const { projects: cur = [], wantedLists = [], carts = [] } =
      await chrome.storage.local.get(["projects", "wantedLists", "carts"]);
    const proj = cur.find(p => p.id === id);
    if (proj) {
      const oldBlSet  = new Set(proj.blCartIds ?? []);
      const newBlSet  = new Set(newBlIds);
      const removedIds = [...oldBlSet].filter(cid => !newBlSet.has(cid));
      const addedIds   = newBlIds.filter(cid => !oldBlSet.has(cid));

      if (!proj.allocations) proj.allocations = {};

      // Removed carts: free their allocations back to scratch/pool
      for (const cid of removedIds) {
        for (const key of Object.keys(proj.allocations)) {
          const a = proj.allocations[key];
          if (a.storeQty?.[cid] != null) delete a.storeQty[cid];
          if ((a.legoQty ?? 0) === 0 && !Object.keys(a.storeQty ?? {}).length)
            delete proj.allocations[key];
        }
      }

      // Added carts: pull from LEGO/scratch into new cart (not from other BL carts)
      if (addedIds.length) {
        // Build wantedQty map from the (new) pool wanted lists
        const wantedQtyMap = {};
        for (const lid of newWlIds) {
          const wl = wantedLists.find(w => w.id === lid);
          for (const p of wl?.parts ?? []) {
            const key  = `${p.partNo}_${p.colorId}`;
            const need = Math.max(0, (p.want ?? p.qty ?? 1) - (p.have ?? 0));
            wantedQtyMap[key] = (wantedQtyMap[key] ?? 0) + need;
          }
        }

        for (const newCid of addedIds) {
          const cart = carts.find(c => c.id === newCid);
          for (const cp of cart?.parts ?? []) {
            const key       = `${cp.partNo}_${cp.colorId}`;
            const wantedQty = wantedQtyMap[key];
            if (!wantedQty) continue; // not in pool

            const a          = proj.allocations[key];
            // qty locked in other retained BL carts — leave those alone
            const otherBLqty = a?.storeQty
              ? Object.entries(a.storeQty)
                  .filter(([cid]) => cid !== newCid && newBlSet.has(cid))
                  .reduce((s, [, v]) => s + v, 0)
              : 0;
            const available = wantedQty - otherBLqty;
            if (available <= 0) continue;

            if (!proj.allocations[key]) proj.allocations[key] = { legoQty: 0, storeQty: {} };
            proj.allocations[key].legoQty = 0; // clear any LEGO allocation
            if (!proj.allocations[key].storeQty) proj.allocations[key].storeQty = {};
            proj.allocations[key].storeQty[newCid] = available;
          }
        }
      }

      proj.wantedListIds       = newWlIds;
      proj.blCartIds           = newBlIds;
      proj.legoCartIds         = newLegoCartIds;
      delete proj.legoCartId;
      proj.scratchWantedListId = newScratch;
      proj.gwpThreshold        = newGwpThreshold;
      await chrome.storage.local.set({ projects: cur });
    }
    renderProjectDetail(id, content);
  });
}

// ─── Settings view ───────────────────────────────────────────────────────────

async function renderSettings(content) {
  const sync = await chrome.storage.sync.get({
    storeLocation:      "anywhere",
    pabRegion:          "en-us",
    filterLotsOverMax:  true,
    filterLotsBelowQty: false,
    ignoreLegoFees:     false,
    blCondition:        "U",
    wantedListPageSize: 10000,
  });

  content.innerHTML = `
    <div class="page-title">Settings</div>

    <div class="settings-card">
      <h3>PAB Price Region</h3>
      <div class="field">
        <label for="pabRegion">Show prices for</label>
        <select id="pabRegion">
          <optgroup label="North America">
            <option value="en-us">United States</option>
            <option value="en-ca">Canada</option>
          </optgroup>
          <optgroup label="Europe">
            <option value="en-gb">United Kingdom</option>
            <option value="de-de">Germany</option>
            <option value="fr-fr">France</option>
            <option value="nl-nl">Netherlands</option>
            <option value="es-es">Spain</option>
            <option value="it-it">Italy</option>
            <option value="pt-pt">Portugal</option>
            <option value="sv-se">Sweden</option>
            <option value="nb-no">Norway</option>
            <option value="da-dk">Denmark</option>
            <option value="fi-fi">Finland</option>
            <option value="pl-pl">Poland</option>
            <option value="cs-cz">Czech Republic</option>
          </optgroup>
          <optgroup label="Oceania">
            <option value="en-au">Australia</option>
            <option value="en-nz">New Zealand</option>
          </optgroup>
        </select>
      </div>
    </div>

    <div class="settings-card">
      <h3>Buy Page — Store Filter</h3>
      <!-- Store location select temporarily hidden -- the feature it drives is
           disabled in content.js (was firing mid-render on large Buy All pages).
           Re-show this when that's re-enabled. -->
      <div class="field" style="display:none">
        <label for="storeLocation">Store location</label>
        <select id="storeLocation">
          <option value="anywhere">Anywhere</option>
          <optgroup label="Region">
            <option value="region:Africa">Africa</option>
            <option value="region:Asia">Asia</option>
            <option value="region:Australia &amp; Oceania">Australia &amp; Oceania</option>
            <option value="region:Europe">Europe</option>
            <option value="region:European Union">European Union</option>
            <option value="region:Middle East">Middle East</option>
            <option value="region:North America">North America</option>
            <option value="region:South America">South America</option>
          </optgroup>
          <optgroup label="Country" id="countryGroup"></optgroup>
        </select>
      </div>
      <label class="field-check">
        <input type="checkbox" id="filterLotsOverMax">
        Auto-check "Lots over max price"
      </label>
      <label class="field-check">
        <input type="checkbox" id="filterLotsBelowQty">
        Auto-check "Lots below Wanted qty"
      </label>
    </div>

    <div class="settings-card">
      <h3>BrickLink Page Sizes</h3>
      <div class="field">
        <label for="wantedListPageSize">Wanted list items per page</label>
        <select id="wantedListPageSize">
          <option value="100">100</option>
          <option value="500">500</option>
          <option value="1000">1000</option>
          <option value="2500">2500</option>
          <option value="5000">5000</option>
          <option value="10000">10000 (default)</option>
        </select>
      </div>
      <p style="font-size:12px;color:#6c757d;margin:4px 0 0">
        MOC Source auto-redirects BrickLink wanted list pages to load this many items at once.
      </p>
    </div>

    <div class="settings-card">
      <h3>Store Shop — Fill Button</h3>
      <div class="field">
        <label for="blCondition">Part condition preference</label>
        <select id="blCondition">
          <option value="N">New only</option>
          <option value="U">Used only (prefer Used, fall back to New)</option>
        </select>
      </div>
      <p style="font-size:12px;color:#6c757d;margin:4px 0 0">
        Controls which lots the "Fill Wanted Qtys" button adds to cart when a store has
        both New and Used available. If your preferred condition is absent for a part,
        the other condition is used as a fallback.
      </p>
    </div>

    <div class="settings-card">
      <h3>Project — LEGO Fees</h3>
      <label class="field-check">
        <input type="checkbox" id="ignoreLegoFees">
        Ignore LEGO fees &amp; shipping in cart cost estimates
      </label>
      <p style="font-size:12px;color:#6c757d;margin:6px 0 0 24px">
        When unchecked, the project view calculates the $7 service fee (orders under $14)
        and PAB delivery ($4.95 ≤$25 · $6.95 $25–$35 · Free ≥$35).
        Enable this if you plan to pad your order above the thresholds.
      </p>
    </div>

    <div class="saved-msg" id="savedMsg">Saved</div>
  `;

  // Populate country list
  const group = content.querySelector("#countryGroup");
  for (const name of BL_COUNTRIES) {
    const opt = document.createElement("option");
    opt.value = `country:${name}`;
    opt.textContent = name;
    group.appendChild(opt);
  }

  // Set current values
  content.querySelector("#pabRegion").value        = sync.pabRegion;
  content.querySelector("#storeLocation").value    = sync.storeLocation;
  content.querySelector("#filterLotsOverMax").checked  = sync.filterLotsOverMax;
  content.querySelector("#filterLotsBelowQty").checked = sync.filterLotsBelowQty;
  content.querySelector("#ignoreLegoFees").checked     = sync.ignoreLegoFees;
  content.querySelector("#blCondition").value      = sync.blCondition;
  content.querySelector("#wantedListPageSize").value = String(sync.wantedListPageSize);

  const save = async () => {
    await chrome.storage.sync.set({
      pabRegion:          content.querySelector("#pabRegion").value,
      storeLocation:      content.querySelector("#storeLocation").value,
      filterLotsOverMax:  content.querySelector("#filterLotsOverMax").checked,
      filterLotsBelowQty: content.querySelector("#filterLotsBelowQty").checked,
      ignoreLegoFees:     content.querySelector("#ignoreLegoFees").checked,
      blCondition:        content.querySelector("#blCondition").value,
      wantedListPageSize: parseInt(content.querySelector("#wantedListPageSize").value, 10),
    });
    const msg = content.querySelector("#savedMsg");
    msg.classList.add("show");
    setTimeout(() => msg.classList.remove("show"), 1500);
  };

  for (const el of content.querySelectorAll("select, input[type=checkbox]")) {
    el.addEventListener("change", save);
  }
}

// ─── Info view ───────────────────────────────────────────────────────────────

// Shared Links / Disclaimer / License cards — shown on the Info page and
// again at the bottom of the Lists page so they're visible without a click.
function footerCardsHtml() {
  return `
    <div class="info-card">
      <h3>Links</h3>
      <p>MOC Source is free and open source, built by AFOLs for AFOLs. Visit the website for the full user guide. If it's helped you save money sourcing parts, consider supporting the server costs:</p>
      <div class="donate-links">
        <a href="https://api.moc-source.com" target="_blank">Website</a>
        <a href="https://api.moc-source.com/guide" target="_blank">Guide</a>
        <a href="https://www.patreon.com/c/MocSource" target="_blank">Patreon</a>
        <a href="https://www.paypal.com/ncp/payment/SAACTUBPTPBSS" target="_blank">PayPal</a>
      </div>
    </div>

    <div class="info-card">
      <h3>Disclaimer</h3>
      <p>MOC Source is a community tool and is not authorized by or affiliated with the LEGO Group. Price data is sourced from LEGO's public PAB service and may not always be accurate or current. Always verify before purchasing.</p>
      <p style="margin-top:8px">LEGO® is a trademark of the LEGO Group.</p>
      <p style="margin-top:8px">The term "BrickLink" is a trademark of the LEGO Group BrickLink. This application uses the BrickLink API but is not endorsed or certified by LEGO BrickLink, Inc.</p>
    </div>

    <div class="info-card">
      <h3>License</h3>
      <p>MOC Source is open source under the <a href="https://www.gnu.org/licenses/agpl-3.0.html" target="_blank">AGPL-3.0</a> license. Source code on <a href="https://github.com/vaultcrest/moc-source" target="_blank">GitHub</a>.</p>
    </div>`;
}

function renderInfo(content) {
  content.innerHTML = `
    <div class="page-title">Info</div>

    <div class="info-card">
      <h3>What's New</h3>
      <div style="font-size:12px;color:#6b7280;margin-bottom:8px">v0.3.0</div>
      <ul style="margin:0;padding-left:18px;font-size:13px;line-height:1.8">
        <li>PAB stock availability now checked <strong>hourly</strong> — out-of-stock and back-in-stock changes are detected within the hour</li>
        <li>Full PAB prices refreshed <strong>daily</strong> across all 18 regions</li>
        <li>Stock data sourced from regional warehouse groups: US&nbsp;&amp;&nbsp;Canada share inventory; EU, UK, AU, and NZ share inventory from LEGO's Poland distribution center</li>
        <li>Cart Jigsaw: project workspace for splitting parts across PAB and BrickLink store carts</li>
        <li>BrickLink store cart writeback — sync allocations back to your BL cart</li>
        <li>Color swatches next to color names on all list views</li>
        <li>BrickLink catalog links on all part ID cells</li>
        <li>Larger checkbox hit areas on all list views</li>
        <li>Pool part removal — permanently hide a part from the project pool and all cart views</li>
      </ul>
    </div>

    ${footerCardsHtml()}
  `;
}

// ─── List detail view ────────────────────────────────────────────────────────

async function splitLegoCart(content) {
  const parts = currentDetail.parts;
  const limit = LEGO_CART_LOT_LIMIT;

  const pabParts   = parts.filter(p => p.channel === "pab");
  const bapParts   = parts.filter(p => p.channel === "bap");
  const otherParts = parts.filter(p => p.channel !== "pab" && p.channel !== "bap");

  const pabKeep     = pabParts.slice(0, limit);
  const pabOverflow = pabParts.slice(limit);
  const bapKeep     = bapParts.slice(0, limit);
  const bapOverflow = bapParts.slice(limit);

  const overflowParts = [...pabOverflow, ...bapOverflow];
  if (!overflowParts.length) return;

  const keepParts = [...pabKeep, ...bapKeep, ...otherParts];

  const { legoCarts = [] } = await chrome.storage.local.get("legoCarts");
  const origIdx = legoCarts.findIndex(c => c.id === currentDetail.listId);
  if (origIdx === -1) return;

  legoCarts[origIdx].parts = keepParts.map(({ pabEntry: _, _i: __, ...rest }) => rest);
  legoCarts[origIdx].partsCount = keepParts.length;

  const now = Date.now();
  const overflowCart = {
    id: String(now),
    name: `${legoCarts[origIdx].name} (Part 2)`,
    savedAt: now,
    locale: legoCarts[origIdx].locale,
    partsCount: overflowParts.length,
    parts: overflowParts.map(({ pabEntry: _, _i: __, ...rest }) => rest),
  };
  legoCarts.push(overflowCart);

  await chrome.storage.local.set({ legoCarts });

  currentDetail.list = legoCarts[origIdx];
  currentDetail.parts = keepParts;
  renderDetailView(content);

  const toast = document.createElement("div");
  toast.style.cssText = "position:fixed;top:20px;left:50%;transform:translateX(-50%);background:#15803d;color:#fff;padding:10px 24px;border-radius:6px;font-size:14px;font-weight:600;z-index:9999;box-shadow:0 4px 12px rgba(0,0,0,.2)";
  toast.textContent = `Split complete. "${overflowCart.name}" created with ${overflowParts.length} lots.`;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

async function renderListDetail(listType, listId, content) {
  const { [listType]: arr = [] } = await chrome.storage.local.get(listType);
  const list = arr.find(l => l.id === listId);
  if (!list) { navigate("lists"); return; }

  const { pabRegion = "en-us" } = await chrome.storage.sync.get({ pabRegion: "en-us" });
  currentPabRegion = pabRegion || "en-us";
  currentDetail = { listType, listId, list, parts: list.parts.map(p => ({ ...p, pabEntry: null })) };
  currentTab = "all";
  currentSort = "name_color";
  renderDetailView(content);

  if (isLegoCart()) {
    await Promise.allSettled(currentDetail.parts.map(async (_, i) => {
      const p = currentDetail.parts[i];
      currentDetail.parts[i].pabEntry = await chrome.runtime.sendMessage({
        type: "GET_PAB_PRICE_BY_ELEMENT", elementId: p.elementId,
      });
    }));
  } else {
    await Promise.allSettled(currentDetail.parts.map(async (_, i) => {
      const p = currentDetail.parts[i];
      // colorId === null means "(Not Applicable)" (any color accepted) --
      // see collectWantedListParts() in content.js. Same wildcard branch as
      // the project pool's own fetch (renderProjectDetail, ~2993-2999): pull
      // every in-stock color and show the cheapest as a representative
      // price, since there's no single (part, color) to look up.
      if (p.colorId == null) {
        const rows = await chrome.runtime.sendMessage({
          type: "GET_PAB_PRICES_FOR_PART", partNo: p.partNo,
        });
        currentDetail.parts[i].pabEntry = pickCheapestPabRow(rows);
        return;
      }
      currentDetail.parts[i].pabEntry = await chrome.runtime.sendMessage({
        type: "GET_PAB_PRICE", partNo: p.partNo, colorId: p.colorId,
      });
    }));
  }
  // Skip re-render if user is actively editing a qty cell — save/cancel will re-render
  if (!content.querySelector(".qty-edit")) {
    renderDetailView(content);
  }
}

function isCart()      { return currentDetail.listType === "carts"; }
function isLegoCart()  { return currentDetail.listType === "legoCarts"; }

// Returns the effective channel for a part, respecting manual overrides.
// p.forceChannel = "bl" → treat as BrickLink regardless of pabEntry.
// p.forceChannel = "pab" → use the natural pabEntry.channel (clears bl override).
function effectiveChannel(p) {
  if (p.forceChannel === "bl") return null;
  return p.pabEntry?.channel ?? null;
}

let moveWarning = null;

function legoEffective(p) {
  if (p.forceChannel === "bl") return null;
  // For LEGO cart parts, use pabEntry channel when loaded, else fall back to saved p.channel
  const ec = effectiveChannel(p);
  return ec !== null ? ec : (p.channel ?? null);
}

function tabCounts() {
  const parts = currentDetail.parts;
  const ch = isLegoCart() ? legoEffective : effectiveChannel;
  const counts = {
    all:     parts.length,
    pab:     parts.filter(p => ch(p) === "pab").length,
    std:     parts.filter(p => ch(p) === "bap").length,
    na:      parts.filter(p => !ch(p)).length,
  };
  if (isCart()) counts.flagged = parts.filter(p => (isOverPAB(p) && !p.excluded) || p.flagged).length;
  return counts;
}

function sortParts(arr) {
  const dir = currentSortDir === "desc" ? -1 : 1;
  return [...arr].sort((a, b) => {
    const na = (a.pabEntry?.bl_part_name || a.name || "").toLowerCase();
    const nb = (b.pabEntry?.bl_part_name || b.name || "").toLowerCase();
    const ia = a.partNo || "";
    const ib = b.partNo || "";
    const colorA = (a.pabEntry?.bl_color_name || String(a.colorId ?? "")).toLowerCase();
    const colorB = (b.pabEntry?.bl_color_name || String(b.colorId ?? "")).toLowerCase();
    switch (currentSort) {
      case "name_color":   return dir * (na.localeCompare(nb) || colorA.localeCompare(colorB));
      case "partid_color": return dir * (ia.localeCompare(ib, undefined, { numeric: true }) || colorA.localeCompare(colorB));
      case "name":         return dir * na.localeCompare(nb);
      case "partid":       return dir * ia.localeCompare(ib, undefined, { numeric: true });
      case "color":        return dir * (colorA.localeCompare(colorB) || na.localeCompare(nb));
      case "want":         return dir * ((a.want ?? 1) - (b.want ?? 1));
      case "need": {
        const needA = Math.max(0, (a.want ?? 1) - (a.have ?? 0));
        const needB = Math.max(0, (b.want ?? 1) - (b.have ?? 0));
        return dir * (needA - needB);
      }
      case "max_price":    return dir * ((a.maxPrice ?? -1) - (b.maxPrice ?? -1));
      case "qty":          return dir * ((a.qty ?? 0) - (b.qty ?? 0));
      case "store_price": {
        const sa = effectivePrice(a) ?? -1;
        const sb = effectivePrice(b) ?? -1;
        return dir * (sa - sb);
      }
      case "pab_price": {
        const pa = a.pabEntry?.price_cents ?? -1;
        const pb = b.pabEntry?.price_cents ?? -1;
        return dir * (pa - pb);
      }
      case "channel": {
        const chOrder = { pab: 0, bap: 1 };
        const effA = isLegoCart() ? legoEffective(a) : effectiveChannel(a);
        const effB = isLegoCart() ? legoEffective(b) : effectiveChannel(b);
        return dir * ((chOrder[effA] ?? 2) - (chOrder[effB] ?? 2) || na.localeCompare(nb));
      }
      default:             return dir * na.localeCompare(nb);
    }
  });
}

function filteredParts() {
  const p = currentDetail.parts;
  const indexed = p.map((x, i) => ({ ...x, _i: i }));
  let result;
  if (isLegoCart()) {
    if (currentTab === "pab")      result = indexed.filter(x => legoEffective(x) === "pab");
    else if (currentTab === "std") result = indexed.filter(x => legoEffective(x) === "bap");
    else if (currentTab === "na")  result = indexed.filter(x => !legoEffective(x));
    else result = indexed;
  } else {
    if (currentTab === "pab")          result = indexed.filter(x => effectiveChannel(x) === "pab");
    else if (currentTab === "std")     result = indexed.filter(x => effectiveChannel(x) === "bap");
    else if (currentTab === "na")      result = indexed.filter(x => !effectiveChannel(x));
    else if (currentTab === "flagged") result = indexed.filter(x => (isOverPAB(x) && !x.excluded) || x.flagged);
    else result = indexed;
  }
  return sortParts(result);
}

function renderDetailView(content) {
  const { list, listType } = currentDetail;
  const counts = tabCounts();
  const parts = filteredParts();
  const cart = isCart();

  const tabLabels = { all: "All", pab: "PAB", std: "STD", na: "BrickLink", flagged: "To Remove" };
  const showStd = currentPabRegion === "en-us" || currentPabRegion === "en-ca";
  const legocart = isLegoCart();
  const tabKeys = legocart
    ? ["all", "pab", "std", "na"]
    : cart
      ? ["all", "pab", ...(showStd ? ["std"] : []), "na", "flagged"]
      : ["all", "pab", ...(showStd ? ["std"] : []), "na"];
  const colCount = legocart ? 9 : cart ? 10 : 11;

  const headers = legocart
    ? `<th><input type="checkbox" id="select-all-check" style="cursor:pointer"></th><th>Part</th><th>Image</th><th>Name</th><th>Color</th><th>Qty</th><th>PAB Price</th><th>Channel</th><th></th>`
    : cart
      ? `<th><input type="checkbox" id="select-all-check" style="cursor:pointer"></th><th>Part</th><th>Image</th><th>Name</th><th>Color</th><th>Qty</th><th>Store Price</th><th>PAB Price</th><th>Channel</th><th></th>`
      : `<th><input type="checkbox" id="select-all-check" style="cursor:pointer"></th><th>Part</th><th>Image</th><th>Name</th><th>Color</th><th>Want / Have</th><th>Need</th><th>Max $</th><th>PAB Price</th><th>Channel</th><th></th>`;

  const sortOptDefs = legocart ? [
    ["partid",       "Part"],
    ["partid_color", "Part, Color"],
    ["name",         "Name"],
    ["name_color",   "Name, Color"],
    ["color",        "Color"],
    ["qty",          "Qty"],
    ["pab_price",    "PAB Price"],
    ["channel",      "Channel"],
  ] : cart ? [
    ["partid",       "Part"],
    ["partid_color", "Part, Color"],
    ["name",         "Name"],
    ["name_color",   "Name, Color"],
    ["color",        "Color"],
    ["qty",          "Qty"],
    ["store_price",  "Store Price"],
    ["pab_price",    "PAB Price"],
    ["channel",      "Channel"],
  ] : [
    ["partid",       "Part"],
    ["partid_color", "Part, Color"],
    ["name",         "Name"],
    ["name_color",   "Name, Color"],
    ["color",        "Color"],
    ["want",         "Want Qty"],
    ["need",         "Need"],
    ["max_price",    "Max $"],
    ["pab_price",    "PAB Price"],
    ["channel",      "Channel"],
  ];
  const sortOpts = sortOptDefs
    .map(([v, l]) => `<option value="${v}"${currentSort === v ? " selected" : ""}>${l}</option>`)
    .join("");

  const dirOpts = [["asc","Ascending"],["desc","Descending"]]
    .map(([v, l]) => `<option value="${v}"${currentSortDir === v ? " selected" : ""}>${l}</option>`).join("");

  const sortControl = `
    <div style="display:flex;align-items:center;gap:10px">
      <div style="display:flex;align-items:center;gap:6px">
        <label style="font-size:12px;color:#6c757d" for="sort-select">Sort:</label>
        <select id="sort-select" style="font-size:12px;padding:3px 6px;border:1px solid #d1d5db;border-radius:4px">${sortOpts}</select>
      </div>
      <select id="sort-dir-select" style="font-size:12px;padding:3px 6px;border:1px solid #d1d5db;border-radius:4px">${dirOpts}</select>
    </div>`;

  const wantedMoveBtn = !cart && (
    (currentTab === "pab" || currentTab === "std")
      ? `<button class="btn move-to-bl-btn" style="font-size:12px">→ BrickLink</button>`
      : currentTab === "na"
      ? `<button class="btn move-to-pab-btn" style="font-size:12px">→ PAB</button>`
      : currentTab === "all"
      ? `<button class="btn move-to-bl-btn" style="font-size:12px">→ BrickLink</button>
         <button class="btn move-to-pab-btn" style="font-size:12px">→ PAB</button>`
      : ""
  );
  const selBlBtn  = `<button class="btn cart-select-bl-cheaper-btn"  style="font-size:12px;background:#fff;color:#374151;border:1px solid #d1d5db" title="Select items where BL store price is cheaper than PAB">☑ BL cheaper</button>`;
  const selPabBtn = `<button class="btn cart-select-pab-cheaper-btn" style="font-size:12px;background:#fff;color:#374151;border:1px solid #d1d5db" title="Select items where PAB price is ≤ BL store price">☑ PAB ≤ store</button>`;
  const cartMoveBtns = cart && currentTab !== "flagged" ? (
    (currentTab === "pab" || currentTab === "std")
      ? `<button class="btn cart-to-bl-btn" style="font-size:12px">→ BrickLink</button>${selBlBtn}`
      : currentTab === "na"
      ? `<button class="btn cart-to-pab-btn" style="font-size:12px">→ PAB</button>${selPabBtn}`
      : `<button class="btn cart-to-bl-btn" style="font-size:12px">→ BrickLink</button>${selBlBtn}
         <button class="btn cart-to-pab-btn" style="font-size:12px">→ PAB</button>${selPabBtn}`
  ) : "";
  const transferBtns = `
    <div style="position:relative;display:inline-flex;gap:4px">
      <button class="btn copy-to-btn" style="font-size:12px">Copy to ▾</button>
      <button class="btn move-to-btn" style="font-size:12px">Move to ▾</button>
      <div class="transfer-dropdown" style="display:none;position:absolute;top:calc(100% + 4px);left:0;z-index:200;background:#fff;border:1px solid #d1d5db;border-radius:6px;box-shadow:0 4px 12px rgba(0,0,0,.12);min-width:220px;padding:4px 0"></div>
    </div>
  `;
  const toolBar = `
    <div class="section-header" style="padding:7px 16px;min-height:0">
      <div style="display:flex;align-items:center;gap:8px">
        <span class="selected-count-label" style="font-size:12px;color:#6c757d">0 selected</span>
        ${cart && currentTab === "flagged"
          ? `<button class="btn bulk-keep-btn" style="font-size:12px">Keep Selected</button>`
          : `<button class="btn btn-danger bulk-remove-btn" style="font-size:12px">Remove Selected</button>`}
        ${!cart ? (wantedMoveBtn || "") : cartMoveBtns}
        ${transferBtns}
        ${moveWarning ? `<span style="color:#dc2626;font-size:12px">⚠ ${esc(moveWarning)}</span>` : ""}
      </div>
      ${sortControl}
    </div>`;

  const savings = cart ? cartSavings(currentDetail.parts) : null;
  const savingsBanner = savings?.count > 0
    ? `<div style="font-size:16px;color:#dc2626;margin-top:4px">${savings.count} part${savings.count !== 1 ? "s" : ""} are cheaper on PAB — switch to save ~$${savings.total.toFixed(2)}</div>`
    : "";

  const refreshBtn = cart && list.storeUrl
    ? `<a href="${esc(list.storeUrl)}" target="_blank" class="btn" style="font-size:12px;text-decoration:none">↻ Open cart</a>`
    : "";

  const legoOverLimit = legocart ? legoCartOverLimit(currentDetail.parts) : { pab: 0, bap: 0 };
  const overLimitBanner = (legoOverLimit.pab || legoOverLimit.bap) ? `
    <div style="background:#fef2f2;border:1px solid #fca5a5;border-radius:6px;padding:12px 16px;margin-bottom:12px;font-size:14px">
      <div style="font-weight:700;color:#dc2626;margin-bottom:6px">&#9888; Cart exceeds LEGO's transfer limit</div>
      <div style="color:#7f1d1d;margin-bottom:4px">You can transfer up to ${LEGO_CART_LOT_LIMIT} Bestseller and ${LEGO_CART_LOT_LIMIT} Standard lots per order.</div>
      ${legoOverLimit.pab ? `<div style="color:#dc2626">PAB Bestseller: <strong>${legoOverLimit.pab} lots</strong> — ${legoOverLimit.pab - LEGO_CART_LOT_LIMIT} over the limit</div>` : ""}
      ${legoOverLimit.bap ? `<div style="color:#dc2626">PAB Standard: <strong>${legoOverLimit.bap} lots</strong> — ${legoOverLimit.bap - LEGO_CART_LOT_LIMIT} over the limit</div>` : ""}
      <div style="margin-top:10px">
        <button class="lego-split-btn btn" style="background:#dc2626;color:#fff;border:none;font-size:13px;font-weight:600;padding:6px 18px;border-radius:5px;cursor:pointer">Split Cart</button>
        <span style="font-size:12px;color:#7f1d1d;margin-left:10px">Keeps the first ${LEGO_CART_LOT_LIMIT} lots of each type here — moves the excess to a new cart.</span>
      </div>
    </div>` : "";

  content.innerHTML = `
    <div class="detail-header">
      <button class="back-btn">← Lists</button>
      <div style="flex:1">
        <div style="display:flex;align-items:center;gap:10px">
          <div class="page-title" style="margin:0">${esc(list.name)}</div>
          <button class="detail-rename-btn btn" style="font-size:12px;padding:2px 8px;opacity:0.5" title="Rename">✎</button>
          ${refreshBtn}
        </div>
        <div class="detail-meta">${list.partsCount} parts · ${cart ? "Cart" : "Wanted List"} · ${fmtDate(list.importedAt)}</div>
        ${savingsBanner}
      </div>
    </div>

    ${overLimitBanner}
    ${summaryPanel(currentDetail.parts, cart)}

    <div class="tab-bar">
      ${tabKeys.map(t => `
        <button class="tab${currentTab === t ? " active" : ""}" data-tab="${t}">
          ${tabLabels[t]} (${counts[t] ?? 0})
        </button>`).join("")}
    </div>

    <div class="section">
      ${toolBar}
      <table>
        <thead><tr>${headers}</tr></thead>
        <tbody>
          ${parts.map(p => legocart ? buildLegoCartRow(p, p._i) : cart ? buildCartRow(p, p._i) : buildWantedRow(p, p._i)).join("")
            || `<tr><td colspan="${colCount}" style="text-align:center;padding:32px;color:#6c757d">No parts in this view</td></tr>`}
        </tbody>
      </table>
      ${!cart && !legocart && parts.length > 0 ? `
      <div style="display:flex;justify-content:flex-end;padding:8px 16px;border-top:1px solid #f3f4f6">
        <button class="tab-all-blwl-btn" style="padding:3px 12px;font-size:13px;background:#fff;color:#374151;border:1px solid #d1d5db;border-radius:4px;cursor:pointer">
          Upload ${parts.length} lot${parts.length !== 1 ? "s" : ""} to BL WL
        </button>
      </div>` : ""}
    </div>
  `;

  attachDetailListeners(content);
}

function colorCell(p) {
  if (p.pabEntry && p.pabEntry.bl_color_name) {
    const bl = esc(p.pabEntry.bl_color_name);
    const lego = p.pabEntry.lego_color_name ? `<div style="color:#adb5bd;font-size:11px">[${esc(p.pabEntry.lego_color_name)}]</div>` : "";
    const hex = p.pabEntry.bl_color_hex;
    const swatch = hex ? `<span style="display:inline-block;width:12px;height:12px;border-radius:2px;background:#${esc(hex)};border:1px solid rgba(0,0,0,0.2);vertical-align:middle;margin-right:5px;flex-shrink:0"></span>` : "";
    return `<div style="display:flex;align-items:center">${swatch}<div><strong>${bl}</strong>${lego}</div></div>`;
  }
  // Never print a raw colorId -- for a wildcard part (colorId === null,
  // "(Not Applicable)") that renders as the literal text "null" via template
  // interpolation, which is a real regression a user hit live 2026-07-28.
  // Fall back to colorName (set by collectWantedListParts() for wildcard
  // rows) before ever falling back to a bare numeric id.
  if (p.colorName) return `<span style="color:#888">${esc(p.colorName)}</span>`;
  if (p.colorId != null) return `<span style="color:#888">Color ${esc(String(p.colorId))}</span>`;
  return `<span style="color:#adb5bd">—</span>`;
}

function pabCells(p) {
  if (p.pabEntry === null)          return ['<span style="color:#adb5bd">…</span>', '<span style="color:#adb5bd;font-size:11px">…</span>'];
  if (!p.pabEntry)                  return ["—", '<span style="color:#adb5bd;font-size:11px">N/A</span>'];
  if (p.pabEntry.channel == null)   return ["—", '<span style="background:#f8f9fa;border:1px solid #dee2e6;color:#6c757d;padding:2px 7px;border-radius:3px;font-size:11px;font-weight:600">BrickLink</span>'];
  const badge = p.pabEntry.channel === "pab"
    ? '<span style="background:#dcfce7;color:#16a34a;padding:2px 7px;border-radius:3px;font-size:11px;font-weight:700">PAB</span>'
    : '<span style="background:#fef9c3;color:#ca8a04;padding:2px 7px;border-radius:3px;font-size:11px;font-weight:700">STD</span>';
  return [p.pabEntry.price_formatted, badge];
}

function buildLegoCartRow(p, idx) {
  const blPartNo = p.pabEntry?.bl_part_no || null;
  const partNo   = blPartNo || p.pabEntry?.design_id || p.designId || "";
  const colorId  = p.pabEntry?.bl_color_id;
  const legoImg  = `https://www.lego.com/cdn/product-assets/product.img.xx_small.png/biasedutils/element/${p.elementId}.png`;
  const imgSrc   = colorId && blPartNo
    ? `https://img.bricklink.com/ItemImage/PT/${colorId}/${blPartNo}.t1.png`
    : legoImg;
  const pnSrc    = colorId && blPartNo
    ? `https://img.bricklink.com/ItemImage/PN/${colorId}/${blPartNo}.png`
    : null;
  const [pabPrice, channelBadge] = pabCells(p);
  const displayName = p.pabEntry?.bl_part_name || p.name || "";

  const partLink = (blPartNo && colorId)
    ? `<a href="https://www.bricklink.com/v2/catalog/catalogitem.page?P=${esc(blPartNo)}#T=C&C=${esc(String(colorId))}" target="_blank" rel="noopener" style="color:#6c757d;text-decoration:none" title="View on BrickLink">${esc(partNo)}</a>`
    : esc(partNo);

  return `
    <tr data-idx="${idx}">
      <td style="cursor:pointer"><input type="checkbox" class="row-check" data-idx="${idx}" style="cursor:pointer"></td>
      <td style="font-family:monospace;font-size:13px">
        ${partLink}
        ${p.elementId ? `<div style="font-size:10px;color:#adb5bd;margin-top:2px">${p.elementId}</div>` : ""}
      </td>
      <td><img class="part-img" src="${esc(imgSrc)}" data-fb1="${esc(pnSrc||legoImg)}" data-fb2="${esc(legoImg)}"></td>
      <td style="max-width:160px">${displayName}</td>
      <td>${colorCell(p)}</td>
      <td><strong>${p.qty ?? 0}</strong></td>
      <td>${pabPrice}</td>
      <td>${channelBadge}</td>
      <td><button class="btn btn-danger part-del-btn" data-idx="${idx}" style="padding:3px 8px;font-size:11px">×</button></td>
    </tr>`;
}

function buildWantedRow(p, idx) {
  const imgSrc   = p.imageUrl || `https://img.bricklink.com/ItemImage/PT/${p.colorId}/${p.partNo}.t1.png`;
  const pnImgSrc = `https://img.bricklink.com/ItemImage/PN/${p.colorId}/${p.partNo}.png`;
  const need = Math.max(0, (p.want ?? 1) - (p.have ?? 0));
  const [pabPrice, channelBadge] = pabCells(p);
  const displayName = p.pabEntry?.bl_part_name || p.name || "";
  const maxPriceStr = p.maxPrice != null ? `$${p.maxPrice.toFixed(2)}` : `<span style="color:#adb5bd">—</span>`;

  return `
    <tr data-idx="${idx}">
      <td style="cursor:pointer"><input type="checkbox" class="row-check" data-idx="${idx}" style="cursor:pointer"></td>
      <td style="font-family:monospace;font-size:13px">
        <a href="https://www.bricklink.com/v2/catalog/catalogitem.page?P=${esc(p.partNo)}#T=C&C=${esc(String(p.colorId ?? ''))}" target="_blank" rel="noopener" style="color:#6c757d;text-decoration:none" title="View on BrickLink">${esc(p.partNo)}</a>
        ${p.pabEntry?.element_id ? `<div style="font-size:10px;color:#adb5bd;margin-top:2px">${p.pabEntry.element_id}</div>` : ""}
      </td>
      <td><img class="part-img" src="${esc(imgSrc)}" data-fb1="${esc(pnImgSrc)}"></td>
      <td style="max-width:160px">${displayName}</td>
      <td>${colorCell(p)}</td>
      <td class="qty-cell" data-idx="${idx}">
        <span class="qty-display">
          <span style="color:#888;font-size:12px">W:</span> <strong>${p.want ?? 1}</strong>
          &nbsp;<span style="color:#888;font-size:12px">H:</span> <strong>${p.have ?? 0}</strong>
        </span>
      </td>
      <td><span class="${need === 0 ? "need-zero" : "need-qty"}">${need}</span></td>
      <td style="color:#555">${maxPriceStr}</td>
      <td>${pabPrice}</td>
      <td>${channelBadge}</td>
      <td><button class="btn btn-danger part-del-btn" data-idx="${idx}" style="padding:3px 8px;font-size:11px">×</button></td>
    </tr>`;
}

function buildCartRow(p, idx) {
  const imgSrc   = p.imageUrl || `https://img.bricklink.com/ItemImage/PT/${p.colorId}/${p.partNo}.t1.png`;
  const pnImgSrc = `https://img.bricklink.com/ItemImage/PN/${p.colorId}/${p.partNo}.png`;
  const [pabPrice, channelBadge] = pabCells(p);
  const displayName = p.pabEntry?.bl_part_name || p.name || "";
  const flagged = p.flagged;
  const storeNum = effectivePrice(p);
  const pabNum = p.pabEntry?.price_cents ? p.pabEntry.price_cents / 100 : null;
  const overPAB = storeNum != null && pabNum != null && storeNum > pabNum;
  const rowStyle = overPAB ? ' style="background:#fff5f5"' : '';
  const pct = pctVsPab(storeNum, pabNum);
  const pctBadge = pct != null
    ? `<div style="font-size:10px;font-weight:700;color:${pct < 0 ? "#16a34a" : "#dc2626"}">${pct < 0 ? "▼" : "▲"}${Math.abs(pct).toFixed(0)}%</div>`
    : "";
  const flagBtn = flagged
    ? `<button class="btn flag-btn" data-idx="${idx}" style="border-color:#6c757d;color:#6c757d;padding:3px 8px;font-size:11px">↩ Keep</button>`
    : `<button class="btn btn-danger flag-btn" data-idx="${idx}" style="padding:3px 8px;font-size:11px">Remove</button>`;

  return `
    <tr data-idx="${idx}"${rowStyle}>
      <td style="cursor:pointer"><input type="checkbox" class="row-check" data-idx="${idx}" style="cursor:pointer"></td>
      <td style="font-family:monospace;font-size:13px">
        <a href="https://www.bricklink.com/v2/catalog/catalogitem.page?P=${esc(p.partNo)}#T=C&C=${esc(String(p.colorId ?? ''))}" target="_blank" rel="noopener" style="color:#6c757d;text-decoration:none" title="View on BrickLink">${esc(p.partNo)}</a>
        ${p.pabEntry?.element_id ? `<div style="font-size:10px;color:#adb5bd;margin-top:2px">${p.pabEntry.element_id}</div>` : ""}
      </td>
      <td><img class="part-img" src="${esc(imgSrc)}" data-fb1="${esc(pnImgSrc)}"></td>
      <td style="max-width:160px">${displayName}</td>
      <td>${colorCell(p)}</td>
      <td><strong>${p.qty ?? 1}</strong></td>
      <td>${storeNum != null ? `$${storeNum.toFixed(2)}${pctBadge}` : `<span style="color:#adb5bd">—</span>`}</td>
      <td>${pabPrice}</td>
      <td>${channelBadge}</td>
      <td>${flagBtn}</td>
    </tr>`;
}

function showTransferWarning(skippedParts, isMove) {
  return new Promise(resolve => {
    const overlay = document.createElement("div");
    overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:500;display:flex;align-items:center;justify-content:center";

    const rows = skippedParts.map(p => {
      const name  = p.pabEntry?.bl_part_name || esc(p.name || p.partNo || "Unknown");
      const color = p.pabEntry?.bl_color_name || p.colorName || (p.colorId ? `Color ${p.colorId}` : "");
      return `<div style="padding:5px 0;border-bottom:1px solid #f3f4f6;font-size:13px">${name}${color ? ` <span style="color:#9ca3af;font-size:11px">[${esc(color)}]</span>` : ""}</div>`;
    }).join("");

    overlay.innerHTML = `
      <div style="background:#fff;border-radius:8px;box-shadow:0 8px 32px rgba(0,0,0,.2);max-width:480px;width:90%;padding:24px">
        <div style="font-weight:700;font-size:16px;margin-bottom:8px">Some parts can't go to a Pick-A-Brick cart</div>
        <div style="color:#6c757d;font-size:14px;margin-bottom:10px">
          The following ${skippedParts.length} part${skippedParts.length !== 1 ? "s" : ""} ${skippedParts.length !== 1 ? "are" : "is"} BrickLink-only and will be skipped:
        </div>
        <div style="max-height:200px;overflow-y:auto;border:1px solid #e5e7eb;border-radius:6px;padding:6px 12px;margin-bottom:12px;background:#f9fafb">
          ${rows}
        </div>
        <div style="color:#6c757d;font-size:13px;margin-bottom:20px">
          The remaining PAB/Standard parts will still be ${isMove ? "moved" : "copied"}.
        </div>
        <div style="display:flex;gap:8px;justify-content:flex-end">
          <button class="warn-cancel btn" style="font-size:13px">Cancel</button>
          <button class="warn-ok btn" style="font-size:13px;background:#1e2330;color:#fff;border-color:#1e2330">OK, proceed</button>
        </div>
      </div>`;

    document.body.appendChild(overlay);
    overlay.querySelector(".warn-cancel").addEventListener("click", () => { overlay.remove(); resolve(false); });
    overlay.querySelector(".warn-ok").addEventListener("click",     () => { overlay.remove(); resolve(true);  });
    overlay.addEventListener("click", e => { if (e.target === overlay) { overlay.remove(); resolve(false); } });
  });
}

function attachDetailListeners(content) {
  // Called repeatedly on the same persistent `content` node (tab switches, sort
  // changes, renames, etc. all re-render then call this again) -- tear down the
  // previous render's content-level listeners before attaching a fresh set, same
  // pattern as renderProjectDetail's cleanup (see its comment for the full story).
  content._detailListenersCleanup?.();
  const _cleanupFns = [];
  content._detailListenersCleanup = () => { _cleanupFns.forEach(fn => fn()); _cleanupFns.length = 0; };
  function addListener(type, handler) {
    content.addEventListener(type, handler);
    _cleanupFns.push(() => content.removeEventListener(type, handler));
  }
  const addClick = handler => addListener("click", handler);

  content.querySelector(".back-btn")?.addEventListener("click", () => navigate("lists"));

  content.querySelector(".detail-rename-btn")?.addEventListener("click", e => {
    e.stopPropagation();
    const titleEl = content.querySelector(".page-title");
    const currentName = currentDetail.list.name;
    titleEl.outerHTML = `<input class="detail-rename-input" type="text" value="${esc(currentName)}"
      style="font-size:22px;font-weight:700;padding:2px 6px;border:1px solid #2563eb;border-radius:4px;width:320px;box-sizing:border-box;margin:0">`;
    const input = content.querySelector(".detail-rename-input");
    let saved = false;
    async function saveRename() {
      if (saved) return;
      saved = true;
      const newName = input.value.trim() || currentName;
      if (newName !== currentName) {
        const { listType, listId } = currentDetail;
        const { [listType]: arr = [] } = await chrome.storage.local.get(listType);
        const item = arr.find(x => x.id === listId);
        if (item) { item.name = newName; await chrome.storage.local.set({ [listType]: arr }); }
        currentDetail.list.name = newName;
      }
      renderDetailView(content);
    }
    input.addEventListener("keydown", e => {
      if (e.key === "Enter")  { e.preventDefault(); saveRename(); }
      if (e.key === "Escape") { saved = true; renderDetailView(content); }
    });
    setTimeout(() => {
      input.focus();
      input.select();
      input.addEventListener("blur", saveRename);
    }, 0);
  });

  for (const tab of content.querySelectorAll(".tab[data-tab]")) {
    tab.addEventListener("click", () => {
      currentTab = tab.dataset.tab;
      moveWarning = null;
      renderDetailView(content);
    });
  }

  content.querySelector("#sort-select")?.addEventListener("change", e => {
    currentSort = e.target.value;
    renderDetailView(content);
  });
  content.querySelector("#sort-dir-select")?.addEventListener("change", e => {
    currentSortDir = e.target.value;
    renderDetailView(content);
  });

  // ── Common: checkbox select-all + count ──────────────────────────────────────
  function getRowChecks() { return [...content.querySelectorAll(".row-check")]; }
  const countLabel = content.querySelector(".selected-count-label");

  function syncSelectAll() {
    const checks = getRowChecks();
    const n = checks.filter(c => c.checked).length;
    const selectAll = content.querySelector("#select-all-check");
    if (selectAll) {
      selectAll.checked = n === checks.length && checks.length > 0;
      selectAll.indeterminate = n > 0 && n < checks.length;
    }
    if (countLabel) countLabel.textContent = `${n} selected`;
  }

  content.querySelector("#select-all-check")?.addEventListener("change", e => {
    for (const cb of getRowChecks()) cb.checked = e.target.checked;
    syncSelectAll();
  });
  addListener("change", e => {
    if (e.target.classList.contains("row-check")) syncSelectAll();
  });
  // Prevent blur-on-mousedown from firing before the click handler runs.
  // Without this, clicking a qty-cell fires blur on the active input (moving focus to body)
  // before our click handler sets pendingQtyEditIdx, so the blur save sees no pending cell.
  addListener("mousedown", e => {
    const cell = e.target.closest(".qty-cell");
    if (!cell || cell.querySelector(".qty-edit")) return;
    e.preventDefault();
  });
  addClick(e => {
    const td = e.target.closest("td");
    if (!td) return;
    const cb = td.querySelector("input.row-check");
    if (!cb || e.target === cb) return;
    cb.checked = !cb.checked;
    cb.dispatchEvent(new Event("change", { bubbles: true }));
  });

  // ── Common: Remove Selected (hard delete from list) ───────────────────────────
  content.querySelector(".bulk-remove-btn")?.addEventListener("click", async () => {
    const checked = getRowChecks().filter(c => c.checked);
    if (!checked.length) return;
    const removeIdxs = new Set(checked.map(c => parseInt(c.dataset.idx, 10)));
    currentDetail.parts = currentDetail.parts.filter((_, i) => !removeIdxs.has(i));
    currentDetail.list.partsCount = currentDetail.parts.length;
    await savePartsToStorage();
    renderDetailView(content);
  });

  // ── Common: Copy / Move to another list ─────────────────────────────────────
  const transferDropdown = content.querySelector(".transfer-dropdown");
  let pendingTransferAction = "copy";

  async function doTransfer(targetKey, targetId, isMove) {
    const checks = getRowChecks().filter(c => c.checked);
    const sourceIdxs = checks.length > 0
      ? checks.map(c => parseInt(c.dataset.idx, 10))
      : filteredParts().map(p => p._i);
    const sourceParts = sourceIdxs.map(i => currentDetail.parts[i]);

    const { [targetKey]: arr = [] } = await chrome.storage.local.get(targetKey);
    const target = arr.find(l => l.id === targetId);
    if (!target) return;

    const sourceIsLego = isLegoCart();
    const targetIsLego = targetKey === "legoCarts";
    let partsToAdd = [];

    if (!sourceIsLego && !targetIsLego) {
      // Wanted / Cart → Wanted: strip cart-only fields, map qty→want
      partsToAdd = sourceParts.map(({ pabEntry, _i, storePrice, imageUrl, flagged, excluded, forceChannel, ...p }) => ({
        ...p,
        want: p.want ?? p.qty ?? 1,
        have: p.have ?? 0,
      }));
    } else if (sourceIsLego && targetIsLego) {
      // LEGO → LEGO
      partsToAdd = sourceParts.map(({ pabEntry, _i, ...p }) => ({ ...p }));
    } else if (sourceIsLego && !targetIsLego) {
      // LEGO → Wanted (use pabEntry for BL fields)
      partsToAdd = sourceParts.map(p => {
        const partNo  = p.pabEntry?.bl_part_no || p.pabEntry?.design_id || p.designId;
        const colorId = p.pabEntry?.bl_color_id;
        if (!partNo || !colorId) return null;
        return {
          partNo,
          colorId,
          name:     p.pabEntry?.bl_part_name || p.name,
          want:     p.qty || 1,
          have:     0,
          qty:      p.qty || 1,
          // maxPrice intentionally omitted -- the PAB price isn't a meaningful
          // "max price" for the resulting Wanted List entry, and buildWantedRow's
          // p.maxPrice != null check already treats a missing field as "no max set".
        };
      }).filter(Boolean);
    } else {
      // Wanted / Cart → LEGO (PAB items only)
      const pabOk  = sourceParts.filter(p => p.pabEntry?.channel === "pab" || p.pabEntry?.channel === "bap");
      const blOnly = sourceParts.filter(p => !p.pabEntry?.channel || (p.pabEntry.channel !== "pab" && p.pabEntry.channel !== "bap"));
      if (blOnly.length > 0) {
        const proceed = await showTransferWarning(blOnly, isMove);
        if (!proceed) return;
      }
      partsToAdd = pabOk.map(p => {
        const elementId = p.pabEntry?.element_id;
        if (!elementId) return null;
        return {
          elementId,
          designId: p.pabEntry?.design_id || p.partNo,
          name:     p.pabEntry?.bl_part_name || p.name,
          qty:      Math.max(1, (isLegoCart() || isCart()) ? (p.qty ?? 1) : (p.want ?? 1) - (p.have ?? 0)),
          channel:  p.pabEntry?.channel,
        };
      }).filter(Boolean);
    }

    // Merge into target, accumulating quantities on duplicates
    for (const part of partsToAdd) {
      if (targetIsLego) {
        const ex = target.parts.find(x => x.elementId === part.elementId);
        if (ex) ex.qty = (ex.qty || 0) + (part.qty || 0);
        else target.parts.push(part);
      } else {
        const ex = target.parts.find(x => x.partNo === part.partNo && String(x.colorId) === String(part.colorId));
        if (ex) {
          ex.want = (ex.want || 0) + (part.want || 0);
          ex.qty  = Math.max(0, ex.want - (ex.have || 0));
        } else {
          target.parts.push(part);
        }
      }
    }
    target.partsCount = target.parts.length;
    await chrome.storage.local.set({ [targetKey]: arr });

    if (isMove) {
      const removeSet = new Set(sourceIdxs);
      currentDetail.parts = currentDetail.parts.filter((_, i) => !removeSet.has(i));
      currentDetail.list.partsCount = currentDetail.parts.length;
      await savePartsToStorage();
    }
    renderDetailView(content);
  }

  async function buildTransferDropdown() {
    const { wantedLists = [], legoCarts = [] } = await chrome.storage.local.get(["wantedLists", "legoCarts"]);
    const isLego = isLegoCart();
    let html = "";

    const legoTargets   = legoCarts.filter(c => !(isLego && c.id === currentDetail.listId));
    const wantedTargets = wantedLists.filter(l => !(!isLego && l.id === currentDetail.listId));

    const itemStyle = "display:block;width:100%;text-align:left;padding:5px 12px;border:none;background:none;cursor:pointer;font-size:13px;color:#1e2330";
    const headStyle = "padding:4px 12px 2px;font-size:10px;color:#9ca3af;font-weight:700;text-transform:uppercase;letter-spacing:0.06em";

    if (legoTargets.length) {
      html += `<div style="${headStyle}">Pick-A-Brick Carts${!isLego ? " — PAB items only" : ""}</div>`;
      for (const c of legoTargets)
        html += `<button class="transfer-target-btn" data-key="legoCarts" data-id="${esc(c.id)}" style="${itemStyle}">${esc(c.name)}</button>`;
    }
    if (wantedTargets.length) {
      if (legoTargets.length) html += `<div style="border-top:1px solid #f3f4f6;margin:4px 0"></div>`;
      html += `<div style="${headStyle}">Wanted Lists</div>`;
      for (const l of wantedTargets)
        html += `<button class="transfer-target-btn" data-key="wantedLists" data-id="${esc(l.id)}" style="${itemStyle}">${esc(l.name)}</button>`;
    }
    if (!html) html = `<div style="padding:8px 12px;font-size:13px;color:#9ca3af">No other lists available</div>`;

    transferDropdown.innerHTML = html;
    for (const btn of transferDropdown.querySelectorAll(".transfer-target-btn")) {
      btn.addEventListener("mouseenter", () => { btn.style.background = "#f9fafb"; });
      btn.addEventListener("mouseleave", () => { btn.style.background = ""; });
      btn.addEventListener("click", async () => {
        transferDropdown.style.display = "none";
        await doTransfer(btn.dataset.key, btn.dataset.id, pendingTransferAction === "move");
      });
    }
  }

  if (transferDropdown) {
    for (const btn of content.querySelectorAll(".copy-to-btn, .move-to-btn")) {
      btn.addEventListener("click", async e => {
        e.stopPropagation();
        const action = btn.classList.contains("move-to-btn") ? "move" : "copy";
        const alreadyOpen = transferDropdown.style.display !== "none" && pendingTransferAction === action;
        transferDropdown.style.display = "none";
        if (alreadyOpen) return;
        pendingTransferAction = action;
        await buildTransferDropdown();
        transferDropdown.style.display = "block";
        setTimeout(() => {
          document.addEventListener("click", function closeDD() {
            transferDropdown.style.display = "none";
            document.removeEventListener("click", closeDD);
          });
        }, 10);
      });
    }
  }

  // ── Wanted list / LEGO cart ──────────────────────────────────────────────────
  if (!isCart()) {
    for (const cell of content.querySelectorAll(".qty-cell")) {
      cell.addEventListener("click", e => {
        e.stopPropagation();
        if (cell.querySelector(".qty-edit")) return;
        // If another cell is being edited, mark this one to re-open after its save re-renders
        if (content.querySelector(".qty-edit")) {
          pendingQtyEditIdx = parseInt(cell.dataset.idx, 10);
        }
        openQtyEdit(cell, content);
      });
    }
    for (const btn of content.querySelectorAll(".part-del-btn")) {
      btn.addEventListener("click", async () => {
        const idx = parseInt(btn.dataset.idx, 10);
        currentDetail.parts.splice(idx, 1);
        await savePartsToStorage();
        renderDetailView(content);
      });
    }

    // Move selected PAB → BrickLink
    content.querySelector(".move-to-bl-btn")?.addEventListener("click", async () => {
      let moved = 0;
      for (const cb of getRowChecks()) {
        if (!cb.checked) continue;
        currentDetail.parts[parseInt(cb.dataset.idx, 10)].forceChannel = "bl";
        moved++;
      }
      if (!moved) return;
      moveWarning = null;
      currentTab = "na";
      renderDetailView(content);
      await savePartsToStorage();
    });

    // Move selected BrickLink → PAB (only if item has a PAB price)
    content.querySelector(".move-to-pab-btn")?.addEventListener("click", async () => {
      const checked = getRowChecks().filter(c => c.checked);
      if (!checked.length) return;
      const cantMove = [];
      for (const cb of checked) {
        const idx = parseInt(cb.dataset.idx, 10);
        const p = currentDetail.parts[idx];
        if (p.pabEntry?.channel) {
          delete currentDetail.parts[idx].forceChannel;
        } else {
          cantMove.push(p.pabEntry?.bl_part_name || p.name || p.partNo || `row ${idx}`);
        }
      }
      moveWarning = cantMove.length
        ? `${cantMove.length} item${cantMove.length !== 1 ? "s" : ""} not on PAB: ${cantMove.slice(0, 3).join(", ")}${cantMove.length > 3 ? "…" : ""}`
        : null;
      if (!cantMove.length) currentTab = "pab";
      renderDetailView(content);
      await savePartsToStorage();
    });
  }

  // ── BL cart ──────────────────────────────────────────────────────────────────
  if (isCart()) {
    for (const btn of content.querySelectorAll(".flag-btn")) {
      btn.addEventListener("click", async () => {
        const idx = parseInt(btn.dataset.idx, 10);
        currentDetail.parts[idx].flagged = !currentDetail.parts[idx].flagged;
        await savePartsToStorage();
        renderDetailView(content);
      });
    }

    content.querySelector(".bulk-keep-btn")?.addEventListener("click", async () => {
      for (const cb of getRowChecks()) {
        if (!cb.checked) continue;
        const idx = parseInt(cb.dataset.idx, 10);
        currentDetail.parts[idx].excluded = true;
        currentDetail.parts[idx].flagged = false;
      }
      await savePartsToStorage();
      renderDetailView(content);
    });

    // Move selected PAB → BrickLink channel
    content.querySelector(".cart-to-bl-btn")?.addEventListener("click", async () => {
      let moved = 0;
      for (const cb of getRowChecks()) {
        if (!cb.checked) continue;
        currentDetail.parts[parseInt(cb.dataset.idx, 10)].forceChannel = "bl";
        moved++;
      }
      if (!moved) return;
      moveWarning = null;
      currentTab = "na";
      renderDetailView(content);
      await savePartsToStorage();
    });

    // Move selected BrickLink → PAB (only if item has a PAB price)
    content.querySelector(".cart-to-pab-btn")?.addEventListener("click", async () => {
      const checked = getRowChecks().filter(c => c.checked);
      if (!checked.length) return;
      const cantMove = [];
      for (const cb of checked) {
        const idx = parseInt(cb.dataset.idx, 10);
        const p = currentDetail.parts[idx];
        if (p.pabEntry?.channel) {
          delete currentDetail.parts[idx].forceChannel;
        } else {
          cantMove.push(p.pabEntry?.bl_part_name || p.name || p.partNo || `row ${idx}`);
        }
      }
      moveWarning = cantMove.length
        ? `${cantMove.length} item${cantMove.length !== 1 ? "s" : ""} not on PAB: ${cantMove.slice(0, 3).join(", ")}${cantMove.length > 3 ? "…" : ""}`
        : null;
      if (!cantMove.length) currentTab = "pab";
      renderDetailView(content);
      await savePartsToStorage();
    });

    // Auto-select visible rows where BL store price < PAB price
    content.querySelector(".cart-select-bl-cheaper-btn")?.addEventListener("click", () => {
      for (const cb of getRowChecks()) {
        const p = currentDetail.parts[parseInt(cb.dataset.idx, 10)];
        const sp = parseStorePrice(p.storePrice);
        const pp = p.pabEntry?.price_cents ? p.pabEntry.price_cents / 100 : null;
        cb.checked = sp !== null && pp !== null && sp < pp;
      }
      syncSelectAll();
    });

    // Auto-select visible rows where PAB price ≤ BL store price (and has PAB price)
    content.querySelector(".cart-select-pab-cheaper-btn")?.addEventListener("click", () => {
      for (const cb of getRowChecks()) {
        const p = currentDetail.parts[parseInt(cb.dataset.idx, 10)];
        const sp = parseStorePrice(p.storePrice);
        const pp = p.pabEntry?.price_cents ? p.pabEntry.price_cents / 100 : null;
        cb.checked = sp !== null && pp !== null && pp <= sp;
      }
      syncSelectAll();
    });
  }

  for (const btn of content.querySelectorAll(".transfer-btn")) {
    btn.addEventListener("click", async () => {
      const channel = btn.dataset.channel; // "pab", "bap", or "both"

      if (isLegoCart()) {
        const over = legoCartOverLimit(currentDetail.parts);
        if ((channel === "pab" || channel === "both") && over.pab
         || (channel === "bap" || channel === "both") && over.bap) {
          const origLabel = btn.textContent;
          btn.textContent = "Over limit — split first";
          btn.style.background = "#dc2626";
          setTimeout(() => { btn.textContent = origLabel; btn.style.background = ""; }, 3000);
          return;
        }
      }

      const items = currentDetail.parts
        .filter(p => {
          const eid = isLegoCart() ? p.elementId       : p.pabEntry?.element_id;
          const ch  = isLegoCart() ? p.channel         : p.pabEntry?.channel;
          return eid && (channel === "both" ? (ch === "pab" || ch === "bap") : ch === channel);
        })
        .map(p => ({
          elementId: isLegoCart() ? p.elementId        : p.pabEntry.element_id,
          qty: Math.max(1, isLegoCart() ? (p.qty ?? p.quantity ?? 1) : (p.want ?? 1) - (p.have ?? 0)),
          channel:   isLegoCart() ? p.channel          : p.pabEntry.channel,
        }))
        .filter(i => i.qty > 0);

      if (items.length === 0) return;

      const origLabel = btn.textContent;
      btn.disabled = true;
      btn.textContent = "Opening…";
      await chrome.runtime.sendMessage({ type: "QUEUE_TRANSFER", items, channel });
      btn.textContent = "Sent!";
      setTimeout(() => { btn.disabled = false; btn.textContent = origLabel; }, 3000);
    });
  }

  content.querySelector(".lego-split-btn")?.addEventListener("click", () => splitLegoCart(content));

  for (const btn of content.querySelectorAll(".csv-dl-btn")) {
    btn.addEventListener("click", () => {
      const rows = [["name", "elementId", "quantity"]];
      for (const p of currentDetail.parts) {
        const eid = isLegoCart() ? p.elementId       : p.pabEntry?.element_id;
        const ch  = isLegoCart() ? p.channel         : p.pabEntry?.channel;
        if (!eid) continue;
        if (ch !== "pab" && ch !== "bap") continue;
        const qty = Math.max(1, isLegoCart() ? (p.qty ?? p.quantity ?? 1) : (p.want ?? 1) - (p.have ?? 0));
        if (qty <= 0) continue;
        const name = (isLegoCart() ? p.name : (p.pabEntry?.lego_name || p.pabEntry?.bl_part_name || "")).replace(/"/g, '""');
        rows.push([`"${name}"`, eid, qty]);
      }
      const csv = rows.map(r => r.join(",")).join("\n");
      const listName = (currentDetail.list?.name || "pab-parts").replace(/[/\\?%*:|"<>]/g, "-").trim();
      const a = Object.assign(document.createElement("a"), {
        href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })),
        download: `${listName}.csv`,
      });
      a.click();
      URL.revokeObjectURL(a.href);
    });
  }

  for (const btn of content.querySelectorAll(".channel-wl-btn")) {
    btn.addEventListener("click", async () => {
      await queueBlUpload(blWlItems(currentDetail.parts, btn.dataset.wlChannel));
    });
  }

  for (const btn of content.querySelectorAll(".row-blwl-btn")) {
    btn.addEventListener("click", async () => {
      const p = currentDetail.parts[parseInt(btn.dataset.idx, 10)];
      if (!p?.partNo || !p?.colorId) return;
      const qty = Math.max(1, (p.want ?? 1) - (p.have ?? 0));
      if (qty <= 0) return;
      await queueBlUpload([{
        partNo:   p.partNo,
        colorId:  p.colorId,
        qty,
        maxPrice: p.pabEntry?.price_cents ? (p.pabEntry.price_cents / 100).toFixed(4) : null,
      }]);
    });
  }

  content.querySelector(".tab-all-blwl-btn")?.addEventListener("click", async () => {
    await queueBlUpload(blWlItems(filteredParts(), "all"));
  });

  if (pendingQtyEditIdx !== null) {
    const idx = pendingQtyEditIdx;
    pendingQtyEditIdx = null;
    const pendingCell = content.querySelector(`.qty-cell[data-idx="${idx}"]`);
    if (pendingCell) openQtyEdit(pendingCell, content);
  }
}

function openQtyEdit(cell, content) {
  const idx = parseInt(cell.dataset.idx, 10);
  const part = currentDetail.parts[idx];
  cell.innerHTML = `
    <div class="qty-edit">
      <label>Want<input type="number" class="want-input" min="0" value="${part.want}" style="width:52px"></label>
      <label>Have<input type="number" class="have-input" min="0" value="${part.have}" style="width:52px"></label>
    </div>`;

  const wantInput = cell.querySelector(".want-input");
  const haveInput = cell.querySelector(".have-input");
  wantInput.focus();

  let done = false;
  async function save() {
    if (done || !cell.isConnected) return;
    done = true;
    const want = Math.max(0, parseInt(wantInput.value, 10) || 0);
    const have = Math.max(0, parseInt(haveInput.value, 10) || 0);
    currentDetail.parts[idx].want = want;
    currentDetail.parts[idx].have = have;
    currentDetail.parts[idx].qty  = Math.max(0, want - have);
    await savePartsToStorage();
    renderDetailView(content);
  }

  for (const input of [wantInput, haveInput]) {
    input.addEventListener("keydown", e => {
      if (e.key === "Enter") save();
      if (e.key === "Escape") { done = true; pendingQtyEditIdx = null; renderDetailView(content); }
    });
    input.addEventListener("blur", () => {
      setTimeout(() => {
        if (cell.contains(document.activeElement)) return;
        // If focus moved outside all qty-cells, user clicked away — cancel any pending re-open
        if (!document.activeElement?.closest?.(".qty-cell")) pendingQtyEditIdx = null;
        save();
      }, 10);
    });
  }
}

async function savePartsToStorage() {
  const { listType, listId } = currentDetail;
  const { [listType]: arr = [] } = await chrome.storage.local.get(listType);
  const listIdx = arr.findIndex(l => l.id === listId);
  if (listIdx === -1) return;
  // Strip pabEntry before saving (runtime data, not persistent)
  arr[listIdx].parts = currentDetail.parts.map(({ pabEntry, _i, ...rest }) => rest);
  arr[listIdx].partsCount = arr[listIdx].parts.length;
  await chrome.storage.local.set({ [listType]: arr });
}

// ─── Init ─────────────────────────────────────────────────────────────────────

for (const item of document.querySelectorAll(".nav-item[data-view]")) {
  item.addEventListener("click", () => navigate(item.dataset.view));
}

const initial = location.hash.replace("#", "") || "lists";
const validTopLevel = ["lists", "projects", "settings", "info"];
navigate(
  initial.startsWith("list/")    ? initial :
  initial.startsWith("project/") ? initial :
  validTopLevel.includes(initial) ? initial : "lists"
);
