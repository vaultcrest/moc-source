// ─── State ───────────────────────────────────────────────────────────────────

function escHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

const rowPrices   = new Map(); // row element → PAB/STD price in dollars (number)
const rowChannels = new Map(); // row element → "pab" | "bap" | "na"

function pabPageUrl(locale, elementId) {
  const base = `https://www.lego.com/${locale || "en-us"}/pick-and-build/pick-a-brick`;
  return elementId ? `${base}?query=${elementId}` : base;
}

// ─── Import helpers ──────────────────────────────────────────────────────────

function uid() {
  return crypto.randomUUID ? crypto.randomUUID()
       : Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function getWantedListName() {
  const h = document.querySelector("h2.tight, .wl-grid-name, .wl-page-title");
  if (h?.textContent?.trim()) return h.textContent.trim();
  const m = document.title.match(/Wanted List[:\s]*(.+)/i);
  if (m?.[1]?.trim()) return m[1].trim();
  return `Wanted List — ${new Date().toLocaleDateString()}`;
}

function getCartName() {
  // a.js-store-link.link-white contains the store display name cleanly
  const nameEl = document.querySelector("a.js-store-link.link-white, span.js-store-name");
  const text = nameEl?.textContent?.trim();
  if (text) return text;
  // Fall back to URL username: store.bricklink.com/username#/cart
  const username = location.pathname.replace(/^\/+/, "").split("/")[0];
  if (username && username !== "cart") return username;
  return `Cart — ${new Date().toLocaleDateString()}`;
}

function getOrderSummary() {
  const summary = {};
  const labels = { "Item Total": "itemTotal", "Shipping & Handling": "shipping", "Order Total": "orderTotal" };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode: n => {
      const t = n.textContent.trim();
      return Object.keys(labels).some(k => t.startsWith(k)) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
    }
  });
  let node;
  while ((node = walker.nextNode())) {
    const t = node.textContent.trim();
    const key = Object.keys(labels).find(k => t.startsWith(k));
    if (!key) continue;
    let el = node.parentElement;
    for (let i = 0; i < 2 && el; i++) {
      const m = el.textContent.match(/(?:US )?\$([\d,]+\.?\d*)/);
      if (m) { summary[labels[key]] = `$${m[1]}`; break; }
      el = el.parentElement;
    }
  }
  return summary;
}

function collectWantedListParts() {
  const parts = [];
  for (const img of document.querySelectorAll("img.wl-item-img")) {
    const match = img.src.match(/\/ItemImage\/P[TN]\/(\d+)\/([^.]+)\.t\d\.png/);
    if (!match) continue;
    const row = img.closest(".table-row");
    if (!row) continue;
    const colorId = parseInt(match[1], 10);
    const partNo = match[2];
    const qtyCell = row.querySelector(".wl-col-quantity");
    const qtyText = qtyCell?.textContent || "";
    const wantMatch = qtyText.match(/Want:\s*(\d+)/i);
    const haveMatch = qtyText.match(/Have:\s*(\d+)/i);
    const want = parseInt(wantMatch?.[1] || "1", 10) || 1;
    const have = parseInt(haveMatch?.[1] || "0", 10) || 0;
    const qty = Math.max(0, want - have);
    const nameEl = row.querySelector(".wl-col-desc a");
    const name = nameEl?.textContent?.trim() || "";
    // Max price: .wl-hover-editable inside .wl-col-price, shows "-" when not set
    const priceEditable = row.querySelector(".wl-col-price .wl-hover-editable");
    const maxPriceText = priceEditable?.textContent?.trim() || "";
    const maxPrice = maxPriceText && maxPriceText !== "-"
      ? parseFloat(maxPriceText.replace(/[^0-9.]/g, "")) || null
      : null;
    parts.push({ partNo, colorId, want, have, qty, name, imageUrl: img.src, maxPrice });
  }
  return parts;
}

function collectCartParts() {
  const parts = [];
  for (const article of document.querySelectorAll("article.store-cart-item")) {
    const img = article.querySelector("img[src*='ItemImage/PT/'], img[src*='ItemImage/PN/']");
    if (!img) continue;
    const match = img.src.match(/\/ItemImage\/P[TN]\/(\d+)\/([^.]+)\.t\d\.png/);
    if (!match) continue;
    const colorId = parseInt(match[1], 10);
    const partNo = match[2];
    const qtyEl = article.querySelector("input[type='number']") ||
                  article.querySelector("[class*='qty']");
    const qty = Math.max(1, parseInt(qtyEl?.value || qtyEl?.textContent?.trim() || "1", 10) || 1);
    const priceCell = article.querySelector("div.price-col");
    let storePrice = null;
    if (priceCell) {
      const clone = priceCell.cloneNode(true);
      clone.querySelectorAll(".moc-source-badge, .moc-source-verdict-caption").forEach(el => el.remove());
      const text = clone.textContent.trim();
      if (text) storePrice = text;
    }
    // Detect condition (New vs Used) from the cart item DOM
    let condition = "N";
    const condEl = article.querySelector("[class*='condition' i], [class*='Condition'], .lot-condition");
    if (condEl) {
      condition = /used/i.test(condEl.textContent) ? "U" : "N";
    } else {
      // Fallback: scan article text but only look at small descriptive spans to avoid false positives
      const descSpans = article.querySelectorAll("span, div.item-condition, .description");
      for (const el of descSpans) {
        const t = el.textContent.trim();
        if (/^used$/i.test(t)) { condition = "U"; break; }
        if (/^new$/i.test(t)) { condition = "N"; break; }
      }
    }
    parts.push({ partNo, colorId, qty, name: "", imageUrl: img.src, storePrice, condition });
  }
  return parts;
}

// ─── DOM helpers ────────────────────────────────────────────────────────────

function extractRows() {
  const results = [];

  // Wanted list (www.bricklink.com/v2/wanted/) — images have class wl-item-img, row is .table-row
  for (const img of document.querySelectorAll("img.wl-item-img")) {
    const match = img.src.match(/\/ItemImage\/P[TN]\/(\d+)\/([^.]+)\.t\d\.png/);
    if (!match) continue;
    const row = img.closest(".table-row");
    if (!row || row.dataset.mocSourceDone) continue;
    results.push({ row, partNo: match[2], colorId: parseInt(match[1], 10) });
  }

  // Cart (store.bricklink.com/#/cart) — row is article.store-cart-item
  for (const img of document.querySelectorAll("article.store-cart-item img[src*='ItemImage/PT/'], article.store-cart-item img[src*='ItemImage/PN/']")) {
    const match = img.src.match(/\/ItemImage\/P[TN]\/(\d+)\/([^.]+)\.t\d\.png/);
    if (!match) continue;
    const row = img.closest("article.store-cart-item");
    if (!row || row.dataset.mocSourceDone) continue;
    results.push({ row, partNo: match[2], colorId: parseInt(match[1], 10) });
  }

  // Store listing (store.bricklink.com/#/shop) — row is article.component
  for (const img of document.querySelectorAll("article.component img[src*='ItemImage/PT/'], article.component img[src*='ItemImage/PN/']")) {
    const match = img.src.match(/\/ItemImage\/P[TN]\/(\d+)\/([^.]+)\.t\d\.png/);
    if (!match) continue;
    const row = img.closest("article.component");
    if (!row || row.dataset.mocSourceDone) continue;
    results.push({ row, partNo: match[2], colorId: parseInt(match[1], 10) });
  }

  // Buy page store selection modal — div.cart-item-row
  for (const img of document.querySelectorAll("div.cart-item-row img[src*='ItemImage/PT/'], div.cart-item-row img[src*='ItemImage/PN/']")) {
    const match = img.src.match(/\/ItemImage\/P[TN]\/(\d+)\/([^.]+)\.t\d\.png/);
    if (!match) continue;
    const row = img.closest("div.cart-item-row");
    if (!row || row.dataset.mocSourceDone) continue;
    results.push({ row, partNo: match[2], colorId: parseInt(match[1], 10) });
  }

  return results;
}

function scrapeRowPrice(row) {
  const clone = row.cloneNode(true);
  clone.querySelectorAll(".moc-source-badge, .moc-source-verdict-caption, div.addToCart, .in-wanted-list, img").forEach(el => el.remove());
  const m = clone.textContent.match(/\$([\d,]+\.\d+)/);
  return m ? parseFloat(m[1].replace(/,/g, "")) : null;
}

function computeVerdict(pabEntry, storePrice) {
  if (storePrice == null || !pabEntry?.channel) return null;
  const channelPrice = pabEntry.price_cents != null ? pabEntry.price_cents / 100 : null;
  const avgPrice = pabEntry.bl_avg_price_cents != null ? pabEntry.bl_avg_price_cents / 100 : null;
  const beatsChannel = channelPrice != null && storePrice < channelPrice;
  const beatsAvg = avgPrice != null && storePrice < avgPrice;
  if (!beatsChannel && !beatsAvg) return null;
  const full = beatsChannel && (avgPrice == null || beatsAvg);
  return { level: full ? "full" : "mixed", channelPrice, avgPrice };
}

function injectBadge(row, pabEntry, storePrice) {
  if (row.dataset.mocSourceDone) return;
  row.dataset.mocSourceDone = "1";

  const badge = document.createElement("span");
  badge.className = "moc-source-badge";
  badge.style.cssText =
    "display:block;margin-top:2px;padding:1px 5px;border-radius:3px;font-size:11px;font-weight:bold;white-space:nowrap;width:fit-content;";

  if (pabEntry && pabEntry.channel === "pab") {
    badge.textContent = `PAB ${pabEntry.price_formatted}`;
    badge.style.background = "#d4edda";
    badge.style.color = "#155724";
  } else if (pabEntry && pabEntry.channel === "bap") {
    badge.textContent = `STD ${pabEntry.price_formatted}`;
    badge.style.background = "#fff3cd";
    badge.style.color = "#856404";
  } else {
    badge.textContent = "PAB: N/A";
    badge.style.background = "#f8f9fa";
    badge.style.color = "#6c757d";
  }

  if (pabEntry && pabEntry.channel) {
    const url = pabPageUrl(pabEntry.locale, pabEntry.element_id);
    badge.style.cursor = "pointer";
    badge.title = "Open in LEGO Pick a Brick";
    badge.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); window.open(url, "_blank"); });
  }

  // Wanted list   → inside .wl-col-price
  // Store cart    → inside div.price-col
  // Store listing → before div.addToCart
  // Buy page modal→ inside div.cart-item-price
  // Fallback      → append to row
  const priceCell = row.querySelector(".wl-col-price")
                 ?? row.querySelector("div.price-col")
                 ?? row.querySelector("div.cart-item-price");
  const addToCart = row.querySelector("div.addToCart");
  if (priceCell) {
    priceCell.appendChild(badge);
  } else if (addToCart) {
    addToCart.insertAdjacentElement("beforebegin", badge);
  } else {
    row.appendChild(badge);
  }

  const verdict = computeVerdict(pabEntry, storePrice);
  if (verdict) {
    const washColor = verdict.level === "full" ? "#effaf1" : "#fefaec";
    row.style.borderLeft = verdict.level === "full" ? "4px solid #16a34a" : "4px solid #d97706";
    row.style.background = washColor;
    row.style.paddingLeft = "10px";

    // Store listing page renders the right-hand "Add to Cart" column (div.buy) as its
    // own panel with an opaque background, which otherwise paints over the row's wash.
    const buyPanel = row.querySelector(".buy");
    if (buyPanel) buyPanel.style.background = washColor;

    const caption = document.createElement("span");
    caption.className = "moc-source-verdict-caption";
    caption.style.cssText =
      `display:block;margin-top:2px;font-size:10.5px;font-weight:700;color:${verdict.level === "full" ? "#15803d" : "#b45309"};`;
    const parts = [];
    if (verdict.channelPrice != null) parts.push(`${pabEntry.channel === "pab" ? "PAB" : "STD"} $${verdict.channelPrice.toFixed(2)}`);
    if (verdict.avgPrice != null) parts.push(`BL avg $${verdict.avgPrice.toFixed(2)}`);
    caption.textContent = `▼ below ${parts.join(" and ")}`;
    badge.insertAdjacentElement("afterend", caption);
  }

  rowChannels.set(row, pabEntry?.channel ?? "na");
  if (pabEntry && pabEntry.price_cents) {
    rowPrices.set(row, pabEntry.price_cents / 100);
  }
}

function injectFillWantedQtyButton() {
  if (location.hostname !== "store.bricklink.com") return;
  if (!location.hash.startsWith("#/shop")) return;
  if (document.querySelector(".moc-fill-wanted-btn")) return;

  // Only active when browsing a store filtered by a wanted list
  const oIdx = location.hash.indexOf("?o=");
  if (oIdx === -1) return;
  let hashO = {};
  try { hashO = JSON.parse(decodeURIComponent(location.hash.slice(oIdx + 3))); } catch {
    try { hashO = JSON.parse(location.hash.slice(oIdx + 3)); } catch {}
  }
  if (!hashO.bOnWantedList) return;

  const container = document.querySelector("div.view-items.store-items");
  if (!container) return;

  const btn = document.createElement("button");
  btn.className = "moc-fill-wanted-btn";
  btn.textContent = "Fill Wanted Qtys";
  btn.style.cssText = "display:inline-block;padding:6px 14px;background:#1e2330;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:13px;font-weight:500;margin-bottom:10px;";

  btn.addEventListener("click", async () => {
    const { blCondition = "U" } = await chrome.storage.sync.get({ blCondition: "U" });
    const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
    const articles = [...document.querySelectorAll("article.item.component.table-row")];

    // Returns the article with the lowest store price in a Map<article, price|null>.
    // Falls back to the first entry when all prices are unknown.
    function cheapestIn(map) {
      let bestArt = null, bestPrice = Infinity;
      for (const [art, price] of map) {
        const p = (price != null) ? price : Infinity;
        if (bestArt === null || p < bestPrice) { bestArt = art; bestPrice = p; }
      }
      return { art: bestArt, price: bestPrice };
    }

    // Pass 1: group valid articles by part+color key.
    // Skips rows already in cart (re-filling them triggers a BL cart error).
    // Stores the extracted store price per article for cheapest-lot selection in pass 2.
    const byPart = new Map(); // partKey → { N: Map<article, price|null>, U: Map<article, price|null> }
    for (const article of articles) {
      const stockEl  = article.querySelector(".buy p strong span");
      const wantedEl = article.querySelector(".in-wanted-list .wanted-condition > span:first-child .text");
      const input    = article.querySelector("input.addToCartQty");
      if (!stockEl || !wantedEl || !input) continue;
      if ((parseInt(stockEl.textContent.trim(), 10) || 0) <= 0) continue;
      if ((parseInt(wantedEl.textContent.trim(), 10) || 0) <= 0) continue;

      const cartQtyEl = article.querySelector(".cart-qty");
      const alreadyInCart = cartQtyEl
        ? (parseInt((cartQtyEl.textContent.match(/(\d+)/) || [])[1] || "0", 10) || 0)
        : 0;
      if (alreadyInCart > 0) continue;

      const condEl = article.querySelector("[class*='condition' i], [class*='Condition'], .lot-condition");
      let cond = "N";
      if (condEl) {
        cond = /used/i.test(condEl.textContent) ? "U" : "N";
      } else {
        const c = article.cloneNode(true);
        c.querySelectorAll(".in-wanted-list, div.addToCart, .moc-source-badge").forEach(el => el.remove());
        if (/\bused\b/i.test(c.textContent)) cond = "U";
      }

      // Extract store price so pass 2 can pick cheapest when multiple lots exist
      const storePrice = scrapeRowPrice(article);

      const img = article.querySelector("img[src*='ItemImage/PT/'], img[src*='ItemImage/PN/']");
      const m = img?.src.match(/\/ItemImage\/P[TN]\/(\d+)\/([^.]+)\.t\d\.png/);
      const partKey = m ? `${m[2]}:${m[1]}` : article.dataset.id || Math.random().toString();

      if (!byPart.has(partKey)) byPart.set(partKey, { N: new Map(), U: new Map() });
      byPart.get(partKey)[cond].set(article, storePrice);
    }

    // Pass 2: pick one lot per part — the cheapest within the preferred condition,
    // but cross to the other condition if it's strictly cheaper.
    // Falls back to the other condition when the preferred one has no lots in this store.
    const toFill = new Set();
    for (const { N: newArts, U: usedArts } of byPart.values()) {
      const bestNew  = cheapestIn(newArts);
      const bestUsed = cheapestIn(usedArts);
      let pick = null;
      if (blCondition === "N") {
        if (bestNew.art && bestUsed.art)  pick = bestUsed.price < bestNew.price ? bestUsed.art : bestNew.art;
        else                              pick = bestNew.art ?? bestUsed.art;
      } else {
        if (bestNew.art && bestUsed.art)  pick = bestNew.price < bestUsed.price ? bestNew.art : bestUsed.art;
        else                              pick = bestUsed.art ?? bestNew.art;
      }
      if (pick) toFill.add(pick);
    }

    let filled = 0, alreadyFull = 0, pabSkipped = 0, condSkipped = 0;

    for (const article of articles) {
      const stockEl  = article.querySelector(".buy p strong span");
      const wantedEl = article.querySelector(".in-wanted-list .wanted-condition > span:first-child .text");
      const input    = article.querySelector("input.addToCartQty");
      if (!stockEl || !wantedEl || !input) continue;

      // Already in cart — skip to avoid BL cart error
      const cartQtyEl = article.querySelector(".cart-qty");
      const alreadyInCart = cartQtyEl
        ? (parseInt((cartQtyEl.textContent.match(/(\d+)/) || [])[1] || "0", 10) || 0)
        : 0;
      if (alreadyInCart > 0) { alreadyFull++; continue; }

      if (!toFill.has(article)) { condSkipped++; continue; }

      const storeStock = parseInt(stockEl.textContent.trim(), 10) || 0;
      const wantedQty  = parseInt(wantedEl.textContent.trim(), 10) || 0;
      if (storeStock <= 0 || wantedQty <= 0) continue;

      // Skip if store price >= PAB price — only for PAB channel items.
      // STD (BAP) items always added regardless of price.
      const pabPrice = rowPrices.get(article);
      if (pabPrice !== undefined && rowChannels.get(article) === "pab") {
        const storePrice = scrapeRowPrice(article);
        if (storePrice !== null && storePrice >= pabPrice) { pabSkipped++; continue; }
      }

      const qty = Math.min(wantedQty, storeStock);
      nativeSetter.call(input, String(qty));
      input.dispatchEvent(new Event("input",  { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      filled++;
    }

    const parts = [`✓ ${filled} set`];
    if (alreadyFull  > 0) parts.push(`${alreadyFull} already in cart`);
    if (condSkipped  > 0) parts.push(`${condSkipped} skipped`);
    if (pabSkipped   > 0) parts.push(`${pabSkipped} PAB ≤ store`);
    btn.textContent = parts.join(" · ");
    setTimeout(() => { btn.textContent = "Fill Wanted Qtys"; }, 3000);
  });

  container.insertAdjacentElement("beforebegin", btn);
}

function injectFillButton() {
  if (rowPrices.size === 0) return;
  if (document.querySelector(".moc-fill-btn")) return;

  const applyPriceBtn = [...document.querySelectorAll("button.bl-btn")]
    .find(b => b.textContent.trim() === "Price");
  if (!applyPriceBtn) return;

  const btn = document.createElement("button");
  btn.className = "moc-fill-btn bl-btn";
  btn.textContent = "Set PAB";
  btn.addEventListener("click", fillMaxPrices);
  applyPriceBtn.insertAdjacentElement("afterend", btn);
}

function fillMaxPrices() {
  const nativeSetter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, "value"
  ).set;

  let filled = 0;
  for (const [row, price] of rowPrices) {
    const priceCell = row.querySelector(".wl-col-price.wl-edit-cell");
    if (!priceCell) continue;
    const input = priceCell.querySelector("input");
    if (input) {
      nativeSetter.call(input, price.toFixed(2));
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      filled++;
    }
  }

  if (filled === 0) {
    alert("Click the Edit button first to make prices editable, then try again.");
  }
}

function injectImportButton() {
  if (!location.pathname.startsWith("/v2/wanted/search.page")) return;
  if (document.querySelector(".moc-import-btn")) return;
  // h2.tight is the wanted list name heading
  const titleEl = document.querySelector("h2.tight, .wl-grid-name, .wl-page-title");
  if (!titleEl) return;
  // Capture name BEFORE appending button so textContent stays clean
  const listName = titleEl.textContent.trim();
  const btn = document.createElement("button");
  btn.className = "moc-import-btn bl-btn";
  btn.textContent = "Save to MOC Source";
  btn.style.cssText = "margin-left:10px;vertical-align:middle;font-size:13px;";
  btn.addEventListener("click", async () => {
    const parts = collectWantedListParts();
    if (!parts.length) return;
    const { wantedLists = [] } = await chrome.storage.local.get("wantedLists");
    const existingIdx = wantedLists.findIndex(l => l.name === listName);
    const entry = {
      id: existingIdx !== -1 ? wantedLists[existingIdx].id : uid(),
      name: listName,
      partsCount: parts.length,
      importedAt: Date.now(),
      parts,
    };
    if (existingIdx !== -1) {
      wantedLists[existingIdx] = entry;
    } else {
      wantedLists.push(entry);
    }
    await chrome.storage.local.set({ wantedLists });
    chrome.runtime.sendMessage({ type: "OPEN_MOC_SOURCE" });
  });
  titleEl.appendChild(btn);
}

function injectCartImportButton() {
  if (location.hostname !== "store.bricklink.com") return;
  if (!location.hash.includes("cart")) return;
  if (document.querySelector(".moc-cart-import-btn")) return;
  if (!document.querySelector("article.store-cart-item")) return;
  const heading = [...document.querySelectorAll("h1,h2,h3")].find(el => /Shopping Cart/i.test(el.textContent));
  if (!heading) return;

  const saveBtn = document.createElement("button");
  saveBtn.className = "moc-cart-import-btn";
  saveBtn.textContent = "Save to MOC Source";
  saveBtn.style.cssText = "display:inline-block;vertical-align:middle;padding:6px 14px;background:#1e2330;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:13px;font-weight:500;";
  saveBtn.addEventListener("click", async () => {
    const parts = collectCartParts();
    if (!parts.length) return;
    const { carts = [] } = await chrome.storage.local.get("carts");
    const name = getCartName();
    const existingIdx = carts.findIndex(c => c.name === name);
    const storeUsername = location.pathname.replace(/^\/+/, "").split("/")[0] || null;
    const entry = {
      id: existingIdx !== -1 ? carts[existingIdx].id : uid(),
      name,
      storeUrl: `${location.origin}${location.pathname}#/cart`,
      storeUsername,
      partsCount: parts.length,
      importedAt: Date.now(),
      orderSummary: getOrderSummary(),
      parts,
    };
    if (existingIdx !== -1) {
      carts[existingIdx] = entry;
    } else {
      carts.push(entry);
    }
    await chrome.storage.local.set({ carts });
    chrome.runtime.sendMessage({ type: "OPEN_MOC_SOURCE" });
  });

  const updateBtn = document.createElement("button");
  updateBtn.className = "moc-cart-update-btn";
  updateBtn.textContent = "Update cart from MOC Source";
  updateBtn.style.cssText = "display:inline-block;vertical-align:middle;padding:6px 14px;background:#fff;color:#1e2330;border:1px solid #1e2330;border-radius:4px;cursor:pointer;font-size:13px;font-weight:500;margin-left:8px;";
  updateBtn.addEventListener("click", () => applyBlCartWriteback());

  heading.insertAdjacentHTML("beforeend", "&nbsp;&nbsp;");
  heading.appendChild(saveBtn);
  heading.appendChild(updateBtn);
}

// ─── Auto page-size ──────────────────────────────────────────────────────────

async function enforcePageSize() {
  if (!location.pathname.startsWith("/v2/wanted/search.page")) return;
  const { wantedListPageSize = 10000 } = await chrome.storage.sync.get({ wantedListPageSize: 10000 });
  const url = new URL(location.href);
  if (url.searchParams.get("pageSize") === String(wantedListPageSize)) return;
  url.searchParams.set("pageSize", String(wantedListPageSize));
  location.replace(url.toString());
}

async function enforceStorePageSize() {
  return; // disabled — pgSize injection was corrupting the hash / fighting BL pagination
  if (location.hostname !== "store.bricklink.com") return;
  if (!location.hash.startsWith("#/shop")) return;
  const { storePageSize = 500 } = await chrome.storage.sync.get({ storePageSize: 500 });
  const hash = location.hash;
  const oIdx = hash.indexOf("?o=");
  let o = {};
  if (oIdx !== -1) {
    try { o = JSON.parse(decodeURIComponent(hash.slice(oIdx + 3))); } catch {
      try { o = JSON.parse(hash.slice(oIdx + 3)); } catch {}
    }
  }
  if (o.pgSize === storePageSize) return;
  o.pgSize = storePageSize;
  const basePath = oIdx !== -1 ? hash.slice(0, oIdx) : hash;
  const newUrl = new URL(location.href);
  newUrl.hash = basePath.slice(1) + "?o=" + encodeURIComponent(JSON.stringify(o));
  location.replace(newUrl.toString());
}

// ─── Buy page auto-settings ──────────────────────────────────────────────────

// Radio values on buy.page: 0=Anywhere, 1=region, 2=country
// select with 8 options = region; select with 200+ options = country

async function setupBuyPage() {
  if (!location.pathname.startsWith("/v2/wanted/buy.page")) return;

  const { storeLocation, filterLotsOverMax, filterLotsBelowQty } = await chrome.storage.sync.get({
    storeLocation:      "anywhere",
    filterLotsOverMax:  true,
    filterLotsBelowQty: false,
  });

  // Wait for radio buttons to render, then give React time to attach handlers
  await new Promise(resolve => {
    const check = () => document.querySelector("input[type=radio][value='0']");
    if (check()) return setTimeout(resolve, 1400);
    const obs = new MutationObserver(() => {
      if (check()) { obs.disconnect(); setTimeout(resolve, 1400); }
    });
    obs.observe(document.body, { childList: true, subtree: true });
    setTimeout(resolve, 6000);
  });

  // Apply checkbox filters per settings
  for (const cb of document.querySelectorAll("input[type=checkbox]")) {
    const lbl = cb.labels?.[0] || document.querySelector(`label[for="${cb.id}"]`) || cb.closest("label");
    if (!lbl) continue;
    const text = lbl.textContent;
    if (text.includes("Lots over max price")  && filterLotsOverMax  && !cb.checked) cb.click();
    if (text.includes("Lots below Wanted qty") && filterLotsBelowQty && !cb.checked) cb.click();
  }

  // Set store location -- disabled for now. It was firing its radio/select
  // clicks mid-render on large "Buy All" pages and fighting BrickLink's own
  // load; re-enable once that's sorted out. storeLocation is read above but
  // intentionally unused below.
  void storeLocation;
}

// ─── BrickLink XML Upload ────────────────────────────────────────────────────

function parseWlJson() {
  for (const script of document.querySelectorAll("script:not([src])")) {
    const m = script.textContent.match(/var wlJson = (\{.+\});/);
    if (m) { try { return JSON.parse(m[1]); } catch {} }
  }
  return null;
}

function buildXmlUploadOverlay(xml, defaultName) {
  document.getElementById("moc-bl-overlay")?.remove();

  const wlData = parseWlJson();
  const lists = wlData?.lists ?? [];

  const el = document.createElement("div");
  el.id = "moc-bl-overlay";
  Object.assign(el.style, {
    position: "fixed", top: "50%", left: "50%",
    transform: "translate(-50%,-50%)",
    zIndex: "999999",
    background: "#1e2330", color: "#fff",
    borderRadius: "16px",
    padding: "36px 44px",
    width: "min(660px,92vw)",
    boxShadow: "0 16px 80px rgba(0,0,0,.75)",
    fontFamily: "sans-serif",
    fontSize: "18px", lineHeight: "1.6",
    boxSizing: "border-box",
  });

  const safeDefault = defaultName.replace(/"/g, "&quot;");
  const selectOptions = lists.length
    ? lists.map(l => `<option value="${l.id}">${escHtml(l.name)} (${l.num})</option>`).join("")
    : `<option value="0">Default Wanted List</option>`;

  el.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px">
      <span style="font-weight:700;font-size:22px">MOC Source → BrickLink WL</span>
      <button id="moc-bl-x" style="background:none;border:none;color:#8b9ab0;font-size:24px;cursor:pointer;padding:0 0 0 16px">✕</button>
    </div>
    <div style="margin-bottom:16px">
      <label style="display:flex;align-items:center;gap:10px;cursor:pointer;margin-bottom:10px">
        <input type="radio" name="bl-wl-type" value="existing" id="bl-opt-existing" checked>
        <span>Add to existing list</span>
      </label>
      <div style="padding-left:26px">
        <select id="bl-wl-select" style="width:100%;padding:8px 10px;border-radius:6px;border:1px solid #374151;background:#0f1624;color:#fff;font-size:16px">
          ${selectOptions}
        </select>
      </div>
    </div>
    <div style="margin-bottom:28px">
      <label style="display:flex;align-items:center;gap:10px;cursor:pointer;margin-bottom:10px">
        <input type="radio" name="bl-wl-type" value="new" id="bl-opt-new">
        <span>Create new list</span>
      </label>
      <div style="padding-left:26px">
        <input type="text" id="bl-wl-new-name" placeholder="New list name" value="${safeDefault}"
          style="width:100%;padding:8px 10px;border-radius:6px;border:1px solid #374151;background:#0f1624;color:#fff;font-size:16px;box-sizing:border-box">
      </div>
    </div>
    <div id="moc-bl-status" style="min-height:22px;margin-bottom:16px;color:#f87171;font-size:15px"></div>
    <div style="display:flex;gap:14px">
      <button id="moc-bl-upload" style="background:#2563eb;border:none;color:#fff;font-size:17px;font-weight:600;border-radius:8px;padding:10px 24px;cursor:pointer">Upload to BrickLink</button>
      <button id="moc-bl-cancel" style="background:#2d3547;border:none;color:#8b9ab0;font-size:17px;border-radius:8px;padding:10px 24px;cursor:pointer">Cancel</button>
    </div>
  `;

  document.body.appendChild(el);

  const selEl  = el.querySelector("#bl-wl-select");
  const newEl  = el.querySelector("#bl-wl-new-name");
  const optEx  = el.querySelector("#bl-opt-existing");
  const optNew = el.querySelector("#bl-opt-new");
  const status = el.querySelector("#moc-bl-status");

  function syncToggle() {
    const isNew = optNew.checked;
    selEl.disabled  = isNew;  selEl.style.opacity  = isNew ? "0.35" : "1";
    newEl.disabled  = !isNew; newEl.style.opacity  = isNew ? "1" : "0.35";
  }
  syncToggle();
  el.querySelectorAll("input[name=bl-wl-type]").forEach(r => r.addEventListener("change", syncToggle));

  const close = () => el.remove();
  el.querySelector("#moc-bl-x").addEventListener("click", close);
  el.querySelector("#moc-bl-cancel").addEventListener("click", close);

  el.querySelector("#moc-bl-upload").addEventListener("click", async () => {
    const isNew = optNew.checked;
    const wantedMoreID      = isNew ? -1 : parseInt(selEl.value, 10);
    const strWantedMoreName = isNew ? newEl.value.trim() : "";
    if (isNew && !strWantedMoreName) { status.textContent = "Please enter a list name."; return; }

    const uploadBtn = el.querySelector("#moc-bl-upload");
    uploadBtn.disabled = true;
    uploadBtn.textContent = "Parsing XML…";
    status.textContent = "";

    try {
      console.log('[MOC] BL upload XML:', xml);
      const parseParams = { xmlStr: xml };
      if (!isNew) parseParams.wantedMoreID = String(wantedMoreID);
      const r1 = await fetch("/ajax/clone/wanted/uploadXML.ajax", {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams(parseParams),
      });
      const d1 = await r1.json();
      const validItems = (d1.wantedItems || []).filter(r => r.itemID > 0);
      if (d1.returnCode !== 0 && validItems.length === 0) {
        console.log('[MOC] uploadXML response:', JSON.stringify(d1));
        throw new Error(`Parse error (code ${d1.returnCode})`);
      }
      const skipped = (d1.wantedItems || []).length - validItems.length;
      if (skipped > 0) status.textContent = `⚠ ${skipped} item(s) not found on BrickLink — uploading the rest…`;
      if (d1.returnCode !== 0) console.log('[MOC] uploadXML partial result (code', d1.returnCode, ') — skipped', skipped, 'items');

      const resolvedListId = isNew ? -1 : wantedMoreID;
      const itemsToUpload = validItems
        .map(r => ({
          wantedID:         isNew ? 0 : (r.wantedID || 0),
          wantedMoreID:     resolvedListId,
          itemID:           r.itemID,
          colorID:          r.colorID,
          wantedNew:        r.wantedNew,
          wantedNotify:     r.wantedNotify,
          wantedQtyFilled:  (r.wantedQtyFilled || 0) + (r.prevWantedQtyFilled || 0),
          wantedQty:        (r.wantedQty || 0) + (isNew ? 0 : (r.prevWantedQty || 0)),
          wantedRemarks:    r.wantedRemarks,
          wantedPrice:      r.wantedPriceRaw,
        }));

      uploadBtn.textContent = `Adding ${itemsToUpload.length} lots…`;

      const uploadParams = {
        wantedItemStr: JSON.stringify(itemsToUpload),
        wantedMoreID: String(isNew ? -1 : wantedMoreID),
        uploadFrom: "90",
        sourceLocation: "90",
      };
      if (isNew) {
        uploadParams.wantedMoreName = strWantedMoreName;
      }

      const r2 = await fetch("/ajax/clone/wanted/upload.ajax", {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams(uploadParams),
      });
      const d2 = await r2.json();
      if (d2.returnCode !== 0) throw new Error(`Upload error (code ${d2.returnCode})`);

      const added = d2.n4ItemQty ?? itemsToUpload.length;
      const listId = d2.wantedMoreID ?? (isNew ? null : wantedMoreID);
      const { wantedListPageSize: uploadPageSize = 10000 } = await chrome.storage.sync.get({ wantedListPageSize: 10000 });
      const listUrl = listId
        ? `/v2/wanted/search.page?wantedMoreID=${listId}&pageSize=${uploadPageSize}`
        : "/v2/wanted/list.page";

      el.innerHTML = `
        <div style="font-weight:700;font-size:22px;margin-bottom:20px">MOC Source → BrickLink WL</div>
        <div style="color:#4ade80;margin-bottom:28px;font-size:20px">Done! ${added} lot${added !== 1 ? "s" : ""} added to your wanted list.</div>
        <div style="display:flex;gap:14px">
          <button id="moc-bl-view" style="background:#2563eb;border:none;color:#fff;font-size:17px;font-weight:600;border-radius:8px;padding:10px 24px;cursor:pointer">View Wanted List</button>
          <button id="moc-bl-done" style="background:#2d3547;border:none;color:#8b9ab0;font-size:17px;border-radius:8px;padding:10px 24px;cursor:pointer">Dismiss</button>
        </div>
      `;
      el.querySelector("#moc-bl-done").addEventListener("click", close);
      el.querySelector("#moc-bl-view").addEventListener("click", () => {
        location.href = listUrl;
      });
    } catch (e) {
      status.textContent = `Error: ${e.message}`;
      uploadBtn.disabled = false;
      uploadBtn.textContent = "Upload to BrickLink";
    }
  });
}

(async () => {
  if (!location.pathname.startsWith("/v2/wanted/upload.page")) return;
  const { pendingBLUpload } = await chrome.storage.local.get("pendingBLUpload");
  if (!pendingBLUpload) return;
  await chrome.storage.local.remove("pendingBLUpload");
  buildXmlUploadOverlay(pendingBLUpload.xml, pendingBLUpload.listName);
})();

// ─── BL cart writeback ───────────────────────────────────────────────────────

async function applyBlCartWriteback() {
  if (location.hostname !== "store.bricklink.com" || !location.hash.includes("cart")) return;
  const { pendingBlCartWriteback = {}, carts = [] } = await chrome.storage.local.get(["pendingBlCartWriteback", "carts"]);
  const url = `${location.origin}${location.pathname}#/cart`;
  // Primary lookup by storeUrl; fall back to cart.id for carts imported before storeUrl was tracked
  let changes = pendingBlCartWriteback[url];
  let writebackKey = url;
  if (!changes?.length) {
    const matchedCart = carts.find(c => c.storeUrl === url);
    if (matchedCart?.id) {
      changes = pendingBlCartWriteback[matchedCart.id];
      writebackKey = matchedCart.id;
    }
  }
  if (!changes?.length) {
    const t = document.createElement("div");
    t.style.cssText = "position:fixed;bottom:20px;right:20px;z-index:99999;background:#374151;color:#fff;padding:8px 14px;border-radius:5px;font-size:13px;box-shadow:0 2px 8px rgba(0,0,0,0.3)";
    t.textContent = "No pending updates for this cart.";
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 2500);
    return;
  }

  // Re-query live DOM on every call — BL React re-renders after each save
  function findArticle(partNo, colorId, storePrice) {
    return [...document.querySelectorAll("article.store-cart-item")].find(a => {
      const img = a.querySelector("img[src*='ItemImage/PT/'], img[src*='ItemImage/PN/']");
      if (!img) return false;
      const m = img.src.match(/\/ItemImage\/P[TN]\/(\d+)\/([^.]+)\.t\d\.png/);
      if (!m || parseInt(m[1], 10) !== colorId || m[2] !== partNo) return false;
      if (!storePrice) return true;
      const priceCell = a.querySelector("div.price-col");
      if (!priceCell) return true;
      const clone = priceCell.cloneNode(true);
      clone.querySelectorAll(".moc-source-badge, .moc-source-verdict-caption").forEach(el => el.remove());
      return clone.textContent.trim() === storePrice;
    });
  }

  const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;

  // Resolve live DOM quantities — compare actual cart state vs allocation target
  const allQtyChanges = changes.filter(c => c.newQty > 0).map(c => {
    const article = findArticle(c.partNo, c.colorId, c.storePrice);
    const liveQty = article ? (parseInt(article.querySelector("input[type='number']")?.value, 10) || 0) : null;
    return { ...c, liveQty };
  });
  // Items already at target qty or not in DOM are skipped
  const qtyChanges = allQtyChanges.filter(c => c.liveQty !== null && c.liveQty !== c.newQty);
  const removals   = changes.filter(c => c.newQty === 0);
  if (qtyChanges.length === 0 && removals.length === 0) return;

  // ── Single combined modal for both qty changes and removals ───────────────
  const qtyHtml = qtyChanges.length ? `
    <div style="margin-bottom:${removals.length ? "12px" : "0"}">
      <div style="font-size:11px;font-weight:700;color:#d97706;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Qty Changed (${qtyChanges.length})</div>
      ${qtyChanges.map(c => `<div style="padding:2px 0;font-size:12px;display:flex;gap:8px">
        <span style="flex:1">${c.name || c.partNo} <span style="color:#9ca3af">${c.colorName || String(c.colorId)}</span></span>
        <span style="color:#9ca3af;white-space:nowrap">${c.liveQty} → <strong style="color:#fff">${c.newQty}</strong></span>
      </div>`).join("")}
    </div>` : "";

  const removeHtml = removals.length ? `
    <div>
      <div style="font-size:11px;font-weight:700;color:#dc2626;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Removed (${removals.length})</div>
      ${removals.map(c => {
        const qty = parseInt(findArticle(c.partNo, c.colorId, c.storePrice)
                      ?.querySelector("input[type='number']")?.value || "0", 10) || "?";
        return `<div style="padding:2px 0;font-size:12px;display:flex;gap:8px">
          <span style="min-width:28px;text-align:right;color:#9ca3af;font-size:12px;flex-shrink:0">×${qty}</span>
          <span style="flex:1">${escHtml(c.name || c.partNo)}</span>
          <span style="color:#9ca3af;font-size:12px;flex-shrink:0">${escHtml(c.colorName || String(c.colorId))}</span>
        </div>`;
      }).join("")}
    </div>` : "";

  const overlay = document.createElement("div");
  overlay.style.cssText = "position:fixed;inset:0;z-index:99999;background:rgba(0,0,0,0.55);display:flex;align-items:center;justify-content:center";
  overlay.innerHTML = `
    <div style="background:#1e2330;color:#fff;border-radius:8px;padding:24px;min-width:380px;max-width:520px;max-height:80vh;display:flex;flex-direction:column;gap:16px;box-shadow:0 8px 32px rgba(0,0,0,0.5)">
      <div style="font-weight:700;font-size:15px">MOC Source — Update Cart</div>
      <div style="flex:1;overflow-y:auto;max-height:380px">${qtyHtml}${removeHtml}</div>
      <button id="moc-apply-btn" style="background:#dc2626;border:none;color:#fff;padding:8px 16px;border-radius:5px;cursor:pointer;font-size:13px;font-weight:600;width:100%">Apply all changes</button>
      <button id="moc-cancel-btn" style="background:transparent;border:1px solid rgba(255,255,255,0.25);color:#9ca3af;padding:6px 16px;border-radius:5px;cursor:pointer;font-size:12px">Cancel</button>
    </div>`;

  document.body.appendChild(overlay);
  overlay.querySelector("#moc-cancel-btn").addEventListener("click", () => overlay.remove());

  overlay.querySelector("#moc-apply-btn").addEventListener("click", async () => {
    const applyBtn  = overlay.querySelector("#moc-apply-btn");
    const cancelBtn = overlay.querySelector("#moc-cancel-btn");
    applyBtn.disabled  = true;
    cancelBtn.disabled = true;

    // Step 1: qty changes — sequential with re-lookup and delay to let BL save each
    let qtyDone = 0;
    for (const { partNo, colorId, storePrice, newQty } of qtyChanges) {
      const article = findArticle(partNo, colorId, storePrice);
      if (!article) continue;
      const input = article.querySelector("input[type='number']");
      if (!input || parseInt(input.value, 10) === newQty) continue;
      // focus() + native blur() fires real focusout — what React 17+ delegates onBlur through
      input.focus();
      nativeSetter.call(input, String(newQty));
      input.dispatchEvent(new Event("input",  { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      input.blur();
      qtyDone++;
      applyBtn.textContent = `Updating quantities… ${qtyDone} / ${qtyChanges.length}`;
      await new Promise(r => setTimeout(r, 600));
    }

    // Step 2: removals — sequential with re-lookup
    if (removals.length > 0) {
      window.dispatchEvent(new CustomEvent("moc:confirm-override"));
      let remDone = 0;
      for (const { partNo, colorId, storePrice } of removals) {
        const article = findArticle(partNo, colorId, storePrice);
        if (!article) { remDone++; applyBtn.textContent = `Removing… ${remDone} / ${removals.length}`; continue; }
        const link = [...article.querySelectorAll("a, button, [role='button']")]
          .find(el => /remove/i.test(el.textContent.trim()) && !/remove all/i.test(el.textContent));
        if (link) {
          link.click();
          remDone++;
          applyBtn.textContent = `Removing… ${remDone} / ${removals.length}`;
          await new Promise(r => {
            const ob = new MutationObserver(() => {
              if (!document.contains(article)) { ob.disconnect(); r(); }
            });
            ob.observe(document.body, { childList: true, subtree: true });
            setTimeout(() => { ob.disconnect(); r(); }, 500);
          });
        }
      }
      window.dispatchEvent(new CustomEvent("moc:confirm-restore"));
    }

    // Click BL's "Update Cart" button to commit all changes to the server
    const updateCartBtn = [...document.querySelectorAll("button.bl-btn.primaryBlue")]
      .find(b => /update cart/i.test(b.textContent));
    if (updateCartBtn) {
      applyBtn.textContent = "Saving to BL…";
      updateCartBtn.click();
      await new Promise(r => setTimeout(r, 1500));
    }

    // Update the stored cart snapshot so "Save Cart ↓" won't re-generate the same diff
    const { carts = [] } = await chrome.storage.local.get("carts");
    const cartIdx = carts.findIndex(c => c.storeUrl === writebackKey || c.id === writebackKey);
    if (cartIdx !== -1) {
      const cart = carts[cartIdx];
      for (const { partNo, colorId, storePrice, newQty } of qtyChanges) {
        const part = cart.parts?.find(p =>
          String(p.partNo) === String(partNo) &&
          String(p.colorId) === String(colorId) &&
          p.storePrice === storePrice
        );
        if (part) part.qty = newQty;
      }
      // Remove lots that were deleted
      cart.parts = cart.parts?.filter(p => !removals.some(r =>
        String(r.partNo) === String(p.partNo) &&
        String(r.colorId) === String(p.colorId) &&
        r.storePrice === p.storePrice
      ));
      carts[cartIdx] = cart;
      await chrome.storage.local.set({ carts });
    }

    delete pendingBlCartWriteback[writebackKey];
    await chrome.storage.local.set({ pendingBlCartWriteback });
    overlay.remove();
  });
}

// ─── Main ────────────────────────────────────────────────────────────────────

let runScheduled = false;

async function run() {
  const rows = extractRows();
  if (rows.length === 0) return;

  console.log(`[MOC Source] Processing ${rows.length} new rows`);
  injectImportButton();
  injectCartImportButton();
  injectFillWantedQtyButton();

  for (const { row, partNo, colorId } of rows) {
    const pabEntry = await chrome.runtime.sendMessage({
      type: "GET_PAB_PRICE",
      partNo,
      colorId,
    });
    const storePrice = scrapeRowPrice(row);
    injectBadge(row, pabEntry, storePrice);
  }

  injectFillButton();
}

function scheduleRun() {
  if (runScheduled) return;
  runScheduled = true;
  setTimeout(() => {
    runScheduled = false;
    run();
  }, 600);
}

function setupObserver() {
  const observer = new MutationObserver(scheduleRun);
  observer.observe(document.body, { childList: true, subtree: true });
  window.addEventListener("hashchange", scheduleRun);
}

enforcePageSize();
setupBuyPage();
setupObserver();
run();

// ─── Catalog item page PAB price injection ───────────────────────────────────

function isCatalogPage() {
  return location.pathname.startsWith("/v2/catalog/catalogitem.page");
}

function parseCatalogUrl() {
  const params  = new URLSearchParams(location.search);
  const partNo  = params.get("P");
  const hash    = new URLSearchParams(location.hash.replace(/^#/, ""));
  const cParam  = hash.get("C");
  // C=0 means "Not Applicable" or no color — treat same as absent
  const colorId = cParam && cParam !== "0" ? parseInt(cParam, 10) : null;
  return { partNo, colorId };
}

function findCatalogInjectTarget() {
  // Target: "Item Consists Of" column
  for (const el of document.querySelectorAll("b, strong, span, td, th, div")) {
    if (/^item\s+consists\s+of$/i.test(el.textContent.trim())) {
      return el.closest("td") ?? el.parentElement;
    }
  }
  // Fallback: "Item Info" column
  for (const el of document.querySelectorAll("b, strong, span, td, th, div")) {
    if (/^item\s+info$/i.test(el.textContent.trim())) {
      return el.closest("td") ?? el.parentElement;
    }
  }
  return document.querySelector("h1")?.parentElement ?? null;
}

function renderPabBadge(entry, noColor) {
  const hex    = entry.bl_color_hex ? `#${entry.bl_color_hex}` : null;
  const swatch = hex
    ? `<span style="display:inline-block;width:11px;height:11px;border-radius:2px;background:${hex};border:1px solid rgba(0,0,0,0.2);vertical-align:middle;margin-right:4px;flex-shrink:0"></span>`
    : "";
  const channelLabel = entry.channel === "pab" ? "PAB" : "STD";
  const channelColor = entry.channel === "pab" ? "#15803d" : "#ca8a04";
  const colorLine    = noColor
    ? `<div style="font-size:12px;color:#6b7280">N/A</div>`
    : entry.bl_color_name
    ? `<div style="display:flex;align-items:center;font-size:12px;color:#374151">${swatch}${entry.bl_color_name}</div>`
    : "";
  return `
    <div id="moc-pab-badge" style="display:block;
      background:#f0fdf4;border:1px solid #bbf7d0;border-radius:6px;
      padding:6px 10px;font-family:sans-serif;margin-top:8px;line-height:1.7">
      <div style="font-size:14px;font-weight:700;color:#111">${entry.price_formatted || "—"}${noColor ? `<span style="font-size:11px;font-weight:400;color:#6b7280;margin-left:5px">max price</span>` : ""}</div>
      <div style="font-size:12px;font-weight:600;color:${channelColor}">${channelLabel}</div>
      ${colorLine}
      <div style="font-size:11px;color:#9ca3af">via MOC Source</div>
    </div>`;
}

async function injectCatalogPabPrice() {
  if (!isCatalogPage()) return;

  document.getElementById("moc-pab-badge")?.remove();

  const { partNo, colorId } = parseCatalogUrl();
  if (!partNo) return;

  let entry = null;
  let noColor = false;

  if (colorId) {
    entry = await chrome.runtime.sendMessage({ type: "GET_PAB_PRICE", partNo, colorId });
    if (!entry || !entry.channel) return;
  } else {
    noColor = true;
    const all = await chrome.runtime.sendMessage({ type: "GET_PAB_PRICES_FOR_PART", partNo });
    if (!all || !all.length) return;
    entry = all[0]; // highest price first (API orders by price_cents desc)
  }

  if (!entry || !entry.channel) return;

  // Retry finding the target up to 5 times (page may still be rendering)
  let target = null;
  for (let i = 0; i < 5; i++) {
    target = findCatalogInjectTarget();
    if (target) break;
    await new Promise(r => setTimeout(r, 300));
  }
  if (!target) return;

  const wrapper = document.createElement("div");
  wrapper.innerHTML = renderPabBadge(entry, noColor);
  const badgeEl = wrapper.firstElementChild;
  const url = pabPageUrl(entry.locale, entry.element_id);
  badgeEl.style.cursor = "pointer";
  badgeEl.title = "Open in LEGO Pick a Brick";
  badgeEl.addEventListener("click", () => window.open(url, "_blank"));
  target.appendChild(badgeEl);
}

if (isCatalogPage()) {
  window.addEventListener("hashchange", () => injectCatalogPabPrice());
  const delay = document.readyState === "loading" ? 800 : 300;
  setTimeout(() => injectCatalogPabPrice(), delay);
}
