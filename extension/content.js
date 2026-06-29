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
    const priceCell = article.querySelector("div.price-col");
    let storePrice = null;
    if (priceCell) {
      const clone = priceCell.cloneNode(true);
      clone.querySelectorAll(".moc-source-badge").forEach(el => el.remove());
      const text = clone.textContent.trim();
      if (text) storePrice = text;
    }
    parts.push({ partNo, colorId, qty, name: "", imageUrl: img.src, storePrice });
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
    const entry = {
      id: existingIdx !== -1 ? carts[existingIdx].id : uid(),
      name,
      storeUrl: `${location.origin}${location.pathname}#/cart`,
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
    ? lists.map(l => `<option value="${l.id}">${l.name} (${l.num})</option>`).join("")
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
      const listUrl = listId
        ? `/v2/wanted/search.page?wantedMoreID=${listId}&pageSize=10000`
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

  const articles = [...document.querySelectorAll("article.store-cart-item")];
  const toRemove = [], toUpdate = [];

  for (const { partNo, colorId, newQty } of changes) {
    const article = articles.find(a => {
      const img = a.querySelector("img[src*='ItemImage/PT/']");
      if (!img) return false;
      const m = img.src.match(/\/ItemImage\/PT\/(\d+)\/([^.]+)\.t\d\.png/);
      return m && parseInt(m[1], 10) === colorId && m[2] === partNo;
    });
    if (!article) continue;
    if (newQty === 0) {
      toRemove.push(article);
    } else {
      toUpdate.push({ article, newQty });
    }
  }

  if (toRemove.length === 0 && toUpdate.length === 0) return;

  // Apply qty changes immediately (auto-saves on blur in BL's cart)
  let qtyCount = 0;
  for (const { article, newQty } of toUpdate) {
    const input = article.querySelector("input[type='number']");
    if (input && parseInt(input.value, 10) !== newQty) {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      setter.call(input, String(newQty));
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      input.dispatchEvent(new FocusEvent("blur", { bubbles: true }));
      qtyCount++;
    }
  }

  // Build item metadata map from stored change metadata
  const labelMap = new Map();
  for (const c of changes) {
    labelMap.set(`${c.partNo}_${c.colorId}`, {
      name:      c.name      || c.partNo,
      colorName: c.colorName || String(c.colorId),
      newQty:    c.newQty,
    });
  }

  // Show modal summarising what was applied and listing items to remove
  const overlay = document.createElement("div");
  overlay.style.cssText = "position:fixed;inset:0;z-index:99999;background:rgba(0,0,0,0.55);display:flex;align-items:center;justify-content:center";

  const qtyPart    = qtyCount    ? `${qtyCount} qty change${qtyCount !== 1 ? "s" : ""} applied` : "";
  const removePart = toRemove.length ? `${toRemove.length} item${toRemove.length !== 1 ? "s" : ""} to remove` : "";
  const summary    = [qtyPart, removePart].filter(Boolean).join(" · ");

  const removeListHtml = toRemove.map(article => {
    const img = article.querySelector("img[src*='ItemImage/PT/']");
    const m   = img?.src.match(/\/ItemImage\/PT\/(\d+)\/([^.]+)\.t\d\.png/);
    const key = m ? `${m[2]}_${m[1]}` : "";
    const meta = labelMap.get(key);
    const name      = meta?.name      || (m ? m[2] : "Unknown part");
    const colorName = meta?.colorName || (m ? m[1] : "");
    const qty       = parseInt(article.querySelector("input[type='number']")?.value || "0", 10) || "?";
    return `<li style="padding:5px 0;border-bottom:1px solid #2a3142;font-size:13px;display:flex;gap:8px;align-items:baseline">
      <span style="min-width:28px;text-align:right;color:#9ca3af;font-size:12px;flex-shrink:0">×${qty}</span>
      <span style="flex:1">${name}</span>
      <span style="color:#9ca3af;font-size:12px;flex-shrink:0">${colorName}</span>
    </li>`;
  }).join("");

  overlay.innerHTML = `
    <div style="background:#1e2330;color:#fff;border-radius:8px;padding:24px;min-width:380px;max-width:520px;max-height:80vh;display:flex;flex-direction:column;gap:16px;box-shadow:0 8px 32px rgba(0,0,0,0.5)">
      <div style="font-weight:700;font-size:15px">MOC Source — Cart Update</div>
      <div style="font-size:13px;color:#9ca3af">${summary}</div>
      ${toRemove.length ? `
        <div style="flex:1;overflow-y:auto;max-height:340px">
          <div style="font-size:12px;color:#6b7280;margin-bottom:6px;font-weight:600">ITEMS TO REMOVE (${toRemove.length})</div>
          <ul style="margin:0;padding:0;list-style:none">${removeListHtml}</ul>
        </div>
        <button id="moc-remove-all-btn" style="background:#dc2626;border:none;color:#fff;padding:8px 16px;border-radius:5px;cursor:pointer;font-size:13px;font-weight:600;width:100%">Remove all ${toRemove.length} items from cart</button>
      ` : ""}
      <button id="moc-close-btn" style="background:transparent;border:1px solid rgba(255,255,255,0.25);color:#9ca3af;padding:6px 16px;border-radius:5px;cursor:pointer;font-size:12px">${toRemove.length ? "Cancel" : "Done"}</button>
    </div>`;

  document.body.appendChild(overlay);
  overlay.querySelector("#moc-close-btn").addEventListener("click", async () => {
    // If no removes pending (qty-only or user confirmed all done), clear the writeback
    if (!overlay.querySelector("#moc-remove-all-btn")) {
      delete pendingBlCartWriteback[writebackKey];
      await chrome.storage.local.set({ pendingBlCartWriteback });
    }
    overlay.remove();
  });

  const removeAllBtn = overlay.querySelector("#moc-remove-all-btn");
  if (removeAllBtn) {
    removeAllBtn.addEventListener("click", async () => {
      removeAllBtn.disabled = true;
      // Signal content_main.js (MAIN world) to override window.confirm
      window.dispatchEvent(new CustomEvent("moc:confirm-override"));
      let done = 0;
      for (const article of toRemove) {
        const link = [...article.querySelectorAll("a, button")].find(el => /^remove$/i.test(el.textContent.trim()));
        if (link) {
          link.click();
          done++;
          removeAllBtn.textContent = `Removing… ${done}/${toRemove.length}`;
          await new Promise(r => setTimeout(r, 150));
        }
      }
      window.dispatchEvent(new CustomEvent("moc:confirm-restore"));
      // Clear pending writeback now that removal is complete
      delete pendingBlCartWriteback[writebackKey];
      await chrome.storage.local.set({ pendingBlCartWriteback });
      overlay.remove();
    });
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
