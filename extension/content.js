// ─── State ───────────────────────────────────────────────────────────────────

const rowPrices = new Map(); // row element → price in dollars (number)

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

function collectWantedListParts() {
  const parts = [];
  for (const img of document.querySelectorAll("img.wl-item-img")) {
    const match = img.src.match(/\/ItemImage\/PT\/(\d+)\/([^.]+)\.t\d\.png/);
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
    const img = article.querySelector("img[src*='ItemImage/PT/']");
    if (!img) continue;
    const match = img.src.match(/\/ItemImage\/PT\/(\d+)\/([^.]+)\.t\d\.png/);
    if (!match) continue;
    const colorId = parseInt(match[1], 10);
    const partNo = match[2];
    const qtyEl = article.querySelector("input[type='number']") ||
                  article.querySelector("[class*='qty']");
    const qty = Math.max(1, parseInt(qtyEl?.value || qtyEl?.textContent?.trim() || "1", 10) || 1);
    parts.push({ partNo, colorId, qty, name: "", imageUrl: img.src });
  }
  return parts;
}

// ─── DOM helpers ────────────────────────────────────────────────────────────

function extractRows() {
  const results = [];

  // Wanted list (www.bricklink.com/v2/wanted/) — images have class wl-item-img, row is .table-row
  for (const img of document.querySelectorAll("img.wl-item-img")) {
    const match = img.src.match(/\/ItemImage\/PT\/(\d+)\/([^.]+)\.t\d\.png/);
    if (!match) continue;
    const row = img.closest(".table-row");
    if (!row || row.dataset.mocSourceDone) continue;
    results.push({ row, partNo: match[2], colorId: parseInt(match[1], 10) });
  }

  // Cart (store.bricklink.com/#/cart) — row is article.store-cart-item
  for (const img of document.querySelectorAll("article.store-cart-item img[src*='ItemImage/PT/']")) {
    const match = img.src.match(/\/ItemImage\/PT\/(\d+)\/([^.]+)\.t\d\.png/);
    if (!match) continue;
    const row = img.closest("article.store-cart-item");
    if (!row || row.dataset.mocSourceDone) continue;
    results.push({ row, partNo: match[2], colorId: parseInt(match[1], 10) });
  }

  // Store listing (store.bricklink.com/#/shop) — row is article.component
  for (const img of document.querySelectorAll("article.component img[src*='ItemImage/PT/']")) {
    const match = img.src.match(/\/ItemImage\/PT\/(\d+)\/([^.]+)\.t\d\.png/);
    if (!match) continue;
    const row = img.closest("article.component");
    if (!row || row.dataset.mocSourceDone) continue;
    results.push({ row, partNo: match[2], colorId: parseInt(match[1], 10) });
  }

  // Buy page store selection modal — div.cart-item-row
  for (const img of document.querySelectorAll("div.cart-item-row img[src*='ItemImage/PT/']")) {
    const match = img.src.match(/\/ItemImage\/PT\/(\d+)\/([^.]+)\.t\d\.png/);
    if (!match) continue;
    const row = img.closest("div.cart-item-row");
    if (!row || row.dataset.mocSourceDone) continue;
    results.push({ row, partNo: match[2], colorId: parseInt(match[1], 10) });
  }

  return results;
}

function injectBadge(row, pabEntry) {
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

  if (pabEntry && pabEntry.price_cents) {
    rowPrices.set(row, pabEntry.price_cents / 100);
  }
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
  const firstItem = document.querySelector("article.store-cart-item");
  if (!firstItem) return;
  const container = firstItem.closest("section") || firstItem.parentElement;
  if (!container) return;
  const btn = document.createElement("button");
  btn.className = "moc-cart-import-btn";
  btn.textContent = "Save to MOC Source";
  btn.style.cssText = "display:block;margin-bottom:12px;padding:6px 14px;background:#1e2330;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:13px;font-weight:500;";
  btn.addEventListener("click", async () => {
    const parts = collectCartParts();
    if (!parts.length) return;
    const { carts = [] } = await chrome.storage.local.get("carts");
    const name = getCartName();
    const existingIdx = carts.findIndex(c => c.name === name);
    const entry = {
      id: existingIdx !== -1 ? carts[existingIdx].id : uid(),
      name,
      storeUrl: `${location.origin}${location.pathname}#/cart`,
      partsCount: parts.length,
      importedAt: Date.now(),
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
  container.insertAdjacentElement("beforebegin", btn);
}

// ─── Auto page-size ──────────────────────────────────────────────────────────

function enforcePageSize() {
  if (!location.pathname.startsWith("/v2/wanted/search.page")) return;
  const url = new URL(location.href);
  if (url.searchParams.get("pageSize") === "10000") return;
  url.searchParams.set("pageSize", "10000");
  location.replace(url.toString());
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

  // Set store location
  const regionSelect  = [...document.querySelectorAll("select")].find(s => s.options.length === 8);
  const countrySelect = [...document.querySelectorAll("select")].find(s => s.options.length > 100);

  if (storeLocation === "anywhere") {
    const r = document.querySelector("input[type=radio][value='0']");
    if (r && !r.checked) r.click();

  } else if (storeLocation.startsWith("region:")) {
    const regionName = storeLocation.slice(7); // e.g. "North America"
    const r = document.querySelector("input[type=radio][value='1']");
    if (r && !r.checked) r.click();
    if (regionSelect) {
      const opt = [...regionSelect.options].find(o => o.text === regionName);
      if (opt) {
        regionSelect.value = opt.value;
        regionSelect.dispatchEvent(new Event("input",  { bubbles: true }));
        regionSelect.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }

  } else if (storeLocation.startsWith("country:")) {
    const countryName = storeLocation.slice(8);
    const r = document.querySelector("input[type=radio][value='2']");
    if (r && !r.checked) r.click();
    if (countrySelect) {
      const opt = [...countrySelect.options].find(o => o.text === countryName);
      if (opt) {
        countrySelect.value = opt.value;
        countrySelect.dispatchEvent(new Event("input",  { bubbles: true }));
        countrySelect.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }
  }

}

// ─── Main ────────────────────────────────────────────────────────────────────

let runScheduled = false;

async function run() {
  const rows = extractRows();
  if (rows.length === 0) return;

  console.log(`[MOC Source] Processing ${rows.length} new rows`);
  injectImportButton();
  injectCartImportButton();

  for (const { row, partNo, colorId } of rows) {
    const pabEntry = await chrome.runtime.sendMessage({
      type: "GET_PAB_PRICE",
      partNo,
      colorId,
    });
    injectBadge(row, pabEntry);
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
