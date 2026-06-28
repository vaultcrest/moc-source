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
      qty:      Math.max(1, isLegoCart() ? (p.qty ?? 1) : (p.want ?? 1) - (p.have ?? 0)),
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
    ${row("PAB Bestseller", pab.length, pabPcs)}
    ${row("PAB Standard",  bap.length, bapPcs)}
    ${row("<strong>Total</strong>", parts.length, pabPcs + bapPcs)}
  </div>`;
}

function summaryPanel(parts, cart) {
  const cats = {
    pab: { lots: 0, pieces: 0, price: 0, hasPrice: true },
    bap: { lots: 0, pieces: 0, price: 0, hasPrice: true },
    bl:  { lots: 0, pieces: 0, price: 0, hasPrice: cart },
  };

  for (const p of parts) {
    const qty = cart ? (p.qty ?? 1) : (p.want ?? 1);
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
        const sp = parseStorePrice(p.storePrice);
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
          const lbl = k === "pab" ? "PAB Bestseller" : k === "bap" ? "PAB Standard" : "BrickLink";
          const pl  = k === "bl" ? "Price" : "Price";
          const pr  = d.hasPrice ? `$${d.price.toFixed(2)}` : "—";
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
          <span style="color:#6c757d;font-size:14px">Price</span><span style="font-weight:700">${totHasPrice ? `$${tot.price.toFixed(2)}` : "—"}</span>
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
          return `
            ${os.itemTotal  ? row("BrickLink Item Total", fmt(os.itemTotal)) : ""}
            ${os.shipping   ? row("Shipping & Handling",  fmt(os.shipping))  : ""}
            ${os.orderTotal ? row("Order Total",           fmt(os.orderTotal), true) : ""}`;
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
      ${row("PAB Bestseller", cats.pab, "Price",      "pab", "pab")}
      ${row("PAB Standard",   cats.bap, "Price",      "bap", "bap")}
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
let currentPabRegion = "en-us";

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
      <div class="section-header"><span>Wanted Lists</span><button class="new-list-btn" data-key="wantedLists" style="margin-left:auto;font-size:12px;padding:2px 10px;background:#1e2330;color:#fff;border:none;border-radius:4px;cursor:pointer">+ New</button></div>
      ${listTable(wantedLists, "wantedLists", true) ?? `<div class="section-empty">No wanted lists imported yet.<br>Open a BrickLink wanted list and click <strong>Save to MOC Source</strong>.</div>`}
    </div>

    <div class="section">
      <div class="section-header"><span>BrickLink Carts</span></div>
      ${listTable(carts, "carts", true) ?? `<div class="section-empty">No carts imported yet.<br>Open a BrickLink store cart and click <strong>Save to MOC Source</strong>.</div>`}
    </div>

    <div class="section">
      <div class="section-header"><span>LEGO Carts</span><button class="new-list-btn" data-key="legoCarts" style="margin-left:auto;font-size:12px;padding:2px 10px;background:#1e2330;color:#fff;border:none;border-radius:4px;cursor:pointer">+ New</button></div>
      ${listTable(legoCarts, "legoCarts", true) ?? `<div class="section-empty">No LEGO carts saved yet.<br>Transfer parts to your LEGO cart and click <strong>Save Cart</strong>.</div>`}
    </div>
  `;

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
    btn.addEventListener("click", () => {
      const id  = btn.dataset.id;
      const key = btn.dataset.key;
      const td  = content.querySelector(`.name-cell[data-id="${id}"][data-key="${key}"]`);
      const currentName = td.querySelector(".list-open-btn").textContent;

      td.innerHTML = `<input class="rename-input" type="text" value="${esc(currentName)}"
        style="font-size:14px;padding:2px 6px;border:1px solid #2563eb;border-radius:4px;width:100%;box-sizing:border-box">`;
      const input = td.querySelector(".rename-input");
      input.focus();
      input.select();

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
      input.addEventListener("blur", saveRename);
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
        name: key === "legoCarts" ? `LEGO Cart ${fmtDate(now)}` : `New List`,
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
    if (p.legoCartId && lgMap[p.legoCartId]) chips.push("1 LEGO cart");
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
      legoCartId: null,
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
  const { projects = [], wantedLists = [], carts = [], legoCarts = [] } =
    await chrome.storage.local.get(["projects", "wantedLists", "carts", "legoCarts"]);
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

  const poolLists  = (project.wantedListIds ?? []).map(i => wlMap[i]).filter(Boolean);
  const blCarts    = (project.blCartIds     ?? []).map(i => blMap[i]).filter(Boolean);
  const legoCart   = project.legoCartId ? lgMap[project.legoCartId] : null;
  const totalPieces = poolLists.reduce((s, l) => s + (l.partsCount ?? 0), 0);

  function listRows(items, emptyMsg) {
    if (!items.length) return `<div style="color:#9ca3af;font-size:12px;padding:6px 0">${emptyMsg}</div>`;
    return items.map(l => `
      <div style="display:flex;align-items:center;gap:10px;padding:5px 0;border-bottom:1px solid #f3f4f6">
        <span style="flex:1;font-size:13px">${esc(l.name)}</span>
        <span style="font-size:12px;color:#6c757d">${(l.partsCount ?? 0).toLocaleString()} parts</span>
      </div>`).join("");
  }

  content.innerHTML = `
    <div class="detail-header">
      <button class="back-btn" id="back-btn">← Projects</button>
      <div>
        <div style="font-size:18px;font-weight:700;color:#1e2330">${esc(project.name)}</div>
        <div class="detail-meta">Created ${fmtDate(project.createdAt)} · ${totalPieces.toLocaleString()} pieces in pool</div>
      </div>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px">
      <div class="section">
        <div class="section-header"><span>Wanted List Pool</span></div>
        <div style="padding:10px 16px">${listRows(poolLists, "No wanted lists added.")}</div>
      </div>
      <div class="section">
        <div class="section-header"><span>BrickLink Carts</span></div>
        <div style="padding:10px 16px">${listRows(blCarts, "No BL carts added.")}</div>
      </div>
    </div>

    <div class="section" style="margin-bottom:14px">
      <div class="section-header"><span>LEGO Cart</span></div>
      <div style="padding:10px 16px">
        ${legoCart
          ? `<div style="font-size:13px">${esc(legoCart.name)} <span style="color:#6c757d;font-size:12px">(${(legoCart.partsCount ?? 0).toLocaleString()} parts)</span></div>`
          : `<div style="color:#9ca3af;font-size:12px">No LEGO cart selected.</div>`}
      </div>
    </div>

    <div class="section">
      <div class="section-header"><span>Scratch Space</span></div>
      <div style="padding:10px 16px">
        ${project.scratchWantedListId && wlMap[project.scratchWantedListId]
          ? `<div style="font-size:13px">Linked to: ${esc(wlMap[project.scratchWantedListId].name)}</div>`
          : `<div style="color:#9ca3af;font-size:12px">No wanted list linked — unallocated parts will be ephemeral.</div>`}
      </div>
    </div>

    <div style="margin-top:18px;padding:16px 20px;background:#fff;border:1px solid #e1e4e8;border-radius:8px;display:flex;align-items:center;gap:14px">
      <div style="flex:1;font-size:13px;color:#6c757d">
        Configure this project to add wanted lists, BL carts, and a LEGO cart before allocating parts.
      </div>
      <button id="configure-btn" style="padding:7px 18px;background:#1e2330;color:#fff;border:none;border-radius:5px;font-size:13px;font-weight:600;cursor:pointer">Configure Project</button>
    </div>`;

  content.querySelector("#back-btn").addEventListener("click", () => navigate("projects"));
  content.querySelector("#configure-btn").addEventListener("click", () => {
    // Phase 2: renderProjectSetup(id, content)
    alert("Project setup coming in Phase 2.");
  });
}

// ─── Settings view ───────────────────────────────────────────────────────────

async function renderSettings(content) {
  const sync = await chrome.storage.sync.get({
    storeLocation:      "anywhere",
    pabRegion:          "en-us",
    filterLotsOverMax:  true,
    filterLotsBelowQty: false,
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
      <div class="field">
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

  const save = async () => {
    await chrome.storage.sync.set({
      pabRegion:          content.querySelector("#pabRegion").value,
      storeLocation:      content.querySelector("#storeLocation").value,
      filterLotsOverMax:  content.querySelector("#filterLotsOverMax").checked,
      filterLotsBelowQty: content.querySelector("#filterLotsBelowQty").checked,
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

function renderInfo(content) {
  content.innerHTML = `
    <div class="page-title">Info</div>

    <div class="info-card">
      <h3>Donation</h3>
      <p>MOC Source is free and open source, built by AFOLs for AFOLs. If it saves you time sourcing parts, consider supporting the server costs:</p>
      <div class="donate-links">
        <a href="https://www.patreon.com/c/MocSource" target="_blank">Patreon</a>
        <a href="https://www.paypal.com/ncp/payment/SAACTUBPTPBSS" target="_blank">PayPal</a>
      </div>
    </div>

    <div class="info-card">
      <h3>Disclaimer</h3>
      <p>MOC Source is a community tool and is not authorized by or affiliated with the LEGO Group. Price data is sourced from LEGO's public PAB service and may not always be accurate or current. Always verify before purchasing.</p>
      <p style="margin-top:8px">LEGO® is a trademark of the LEGO Group.</p>
    </div>

    <div class="info-card">
      <h3>License</h3>
      <p>MOC Source is open source under the <a href="https://www.gnu.org/licenses/agpl-3.0.html" target="_blank">AGPL-3.0</a> license. Source code on <a href="https://github.com/vaultcrest/moc-source" target="_blank">GitHub</a>.</p>
    </div>
  `;
}

// ─── List detail view ────────────────────────────────────────────────────────

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
    await Promise.all(currentDetail.parts.map(async (_, i) => {
      const p = currentDetail.parts[i];
      currentDetail.parts[i].pabEntry = await chrome.runtime.sendMessage({
        type: "GET_PAB_PRICE_BY_ELEMENT", elementId: p.elementId,
      });
    }));
  } else {
    await Promise.all(currentDetail.parts.map(async (_, i) => {
      const p = currentDetail.parts[i];
      currentDetail.parts[i].pabEntry = await chrome.runtime.sendMessage({
        type: "GET_PAB_PRICE", partNo: p.partNo, colorId: p.colorId,
      });
    }));
  }
  renderDetailView(content);
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
        const sa = parseStorePrice(a.storePrice) ?? -1;
        const sb = parseStorePrice(b.storePrice) ?? -1;
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

  const tabLabels = { all: "All", pab: "Bestseller", std: "Standard", na: "BrickLink", flagged: "To Remove" };
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

  content.innerHTML = `
    <div class="detail-header">
      <button class="back-btn">← Lists</button>
      <div style="flex:1">
        <div style="display:flex;align-items:center;gap:10px">
          <div class="page-title" style="margin:0">${esc(list.name)}</div>
          ${isLegoCart() ? `<button class="detail-rename-btn btn" style="font-size:12px;padding:2px 8px;opacity:0.5" title="Rename">✎</button>` : ""}
          ${refreshBtn}
        </div>
        <div class="detail-meta">${list.partsCount} parts · ${cart ? "Cart" : "Wanted List"} · ${fmtDate(list.importedAt)}</div>
        ${savingsBanner}
      </div>
    </div>

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
  return `<span style="color:#888">${p.colorId}</span>`;
}

function pabCells(p) {
  if (p.pabEntry === null)          return ['<span style="color:#adb5bd">…</span>', '<span style="color:#adb5bd;font-size:11px">…</span>'];
  if (!p.pabEntry)                  return ["—", '<span style="color:#adb5bd;font-size:11px">N/A</span>'];
  if (p.pabEntry.channel == null)   return ["—", '<span style="background:#f8f9fa;border:1px solid #dee2e6;color:#6c757d;padding:2px 7px;border-radius:3px;font-size:11px;font-weight:600">BrickLink</span>'];
  const badge = p.pabEntry.channel === "pab"
    ? '<span style="background:#ffc107;color:#000;padding:2px 7px;border-radius:3px;font-size:11px;font-weight:600">Bestseller</span>'
    : '<span style="background:#0d6efd;color:#fff;padding:2px 7px;border-radius:3px;font-size:11px;font-weight:600">Standard</span>';
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
  const [pabPrice, channelBadge] = pabCells(p);
  const displayName = p.pabEntry?.bl_part_name || p.name || "";

  return `
    <tr data-idx="${idx}">
      <td><input type="checkbox" class="row-check" data-idx="${idx}" style="cursor:pointer"></td>
      <td style="font-family:monospace;font-size:13px">
        ${esc(partNo)}
        ${p.elementId ? `<div style="font-size:10px;color:#adb5bd;margin-top:2px">${p.elementId}</div>` : ""}
      </td>
      <td><img class="part-img" src="${esc(imgSrc)}" onerror="if(this.src!=='${legoImg}'){this.src='${legoImg}'}else{this.style.display='none'}"></td>
      <td style="max-width:160px">${esc(displayName)}</td>
      <td>${colorCell(p)}</td>
      <td><strong>${p.qty ?? 0}</strong></td>
      <td>${pabPrice}</td>
      <td>${channelBadge}</td>
      <td><button class="btn btn-danger part-del-btn" data-idx="${idx}" style="padding:3px 8px;font-size:11px">×</button></td>
    </tr>`;
}

function buildWantedRow(p, idx) {
  const imgSrc = p.imageUrl || `https://img.bricklink.com/ItemImage/PT/${p.colorId}/${p.partNo}.t1.png`;
  const need = Math.max(0, (p.want ?? 1) - (p.have ?? 0));
  const [pabPrice, channelBadge] = pabCells(p);
  const displayName = p.pabEntry?.bl_part_name || p.name || "";
  const maxPriceStr = p.maxPrice != null ? `$${p.maxPrice.toFixed(2)}` : `<span style="color:#adb5bd">—</span>`;

  return `
    <tr data-idx="${idx}">
      <td><input type="checkbox" class="row-check" data-idx="${idx}" style="cursor:pointer"></td>
      <td style="font-family:monospace;font-size:13px">
        ${esc(p.partNo)}
        ${p.pabEntry?.element_id ? `<div style="font-size:10px;color:#adb5bd;margin-top:2px">${p.pabEntry.element_id}</div>` : ""}
      </td>
      <td><img class="part-img" src="${esc(imgSrc)}" onerror="this.style.display='none'"></td>
      <td style="max-width:160px">${esc(displayName)}</td>
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
  const imgSrc = p.imageUrl || `https://img.bricklink.com/ItemImage/PT/${p.colorId}/${p.partNo}.t1.png`;
  const [pabPrice, channelBadge] = pabCells(p);
  const displayName = p.pabEntry?.bl_part_name || p.name || "";
  const flagged = p.flagged;
  const storeNum = parseStorePrice(p.storePrice);
  const pabNum = p.pabEntry?.price_cents ? p.pabEntry.price_cents / 100 : null;
  const overPAB = storeNum != null && pabNum != null && storeNum > pabNum;
  const rowStyle = overPAB ? ' style="background:#fff5f5"' : '';
  const flagBtn = flagged
    ? `<button class="btn flag-btn" data-idx="${idx}" style="border-color:#6c757d;color:#6c757d;padding:3px 8px;font-size:11px">↩ Keep</button>`
    : `<button class="btn btn-danger flag-btn" data-idx="${idx}" style="padding:3px 8px;font-size:11px">Remove</button>`;

  return `
    <tr data-idx="${idx}"${rowStyle}>
      <td><input type="checkbox" class="row-check" data-idx="${idx}" style="cursor:pointer"></td>
      <td style="font-family:monospace;font-size:13px">
        ${esc(p.partNo)}
        ${p.pabEntry?.element_id ? `<div style="font-size:10px;color:#adb5bd;margin-top:2px">${p.pabEntry.element_id}</div>` : ""}
      </td>
      <td><img class="part-img" src="${esc(imgSrc)}" onerror="this.style.display='none'"></td>
      <td style="max-width:160px">${esc(displayName)}</td>
      <td>${colorCell(p)}</td>
      <td><strong>${p.qty ?? 1}</strong></td>
      <td>${p.storePrice ? esc(p.storePrice) : `<span style="color:#adb5bd">—</span>`}</td>
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
      const name  = esc(p.pabEntry?.bl_part_name || p.name || p.partNo || "Unknown");
      const color = p.pabEntry?.bl_color_name || p.colorName || (p.colorId ? `Color ${p.colorId}` : "");
      return `<div style="padding:5px 0;border-bottom:1px solid #f3f4f6;font-size:13px">${name}${color ? ` <span style="color:#9ca3af;font-size:11px">[${esc(color)}]</span>` : ""}</div>`;
    }).join("");

    overlay.innerHTML = `
      <div style="background:#fff;border-radius:8px;box-shadow:0 8px 32px rgba(0,0,0,.2);max-width:480px;width:90%;padding:24px">
        <div style="font-weight:700;font-size:16px;margin-bottom:8px">Some parts can't go to a LEGO cart</div>
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
  content.querySelector(".back-btn")?.addEventListener("click", () => navigate("lists"));

  content.querySelector(".detail-rename-btn")?.addEventListener("click", () => {
    const titleEl = content.querySelector(".page-title");
    const currentName = currentDetail.list.name;
    titleEl.outerHTML = `<input class="detail-rename-input" type="text" value="${esc(currentName)}"
      style="font-size:22px;font-weight:700;padding:2px 6px;border:1px solid #2563eb;border-radius:4px;width:320px;box-sizing:border-box;margin:0">`;
    const input = content.querySelector(".detail-rename-input");
    input.focus();
    input.select();
    let saved = false;
    async function saveRename() {
      if (saved) return;
      saved = true;
      const newName = input.value.trim() || currentName;
      if (newName !== currentName) {
        const { legoCarts = [] } = await chrome.storage.local.get("legoCarts");
        const item = legoCarts.find(x => x.id === currentDetail.listId);
        if (item) { item.name = newName; await chrome.storage.local.set({ legoCarts }); }
        currentDetail.list.name = newName;
      }
      renderDetailView(content);
    }
    input.addEventListener("keydown", e => {
      if (e.key === "Enter")  { e.preventDefault(); saveRename(); }
      if (e.key === "Escape") { saved = true; renderDetailView(content); }
    });
    input.addEventListener("blur", saveRename);
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
  content.addEventListener("change", e => {
    if (e.target.classList.contains("row-check")) syncSelectAll();
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
          maxPrice: p.pabEntry?.price_cents ? (p.pabEntry.price_cents / 100).toFixed(4) : null,
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
      html += `<div style="${headStyle}">LEGO Carts${!isLego ? " — PAB items only" : ""}</div>`;
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
      cell.addEventListener("click", () => openQtyEdit(cell, content));
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
      const items = currentDetail.parts
        .filter(p => {
          const ch = p.pabEntry?.channel;
          return p.pabEntry?.element_id && (channel === "both" ? (ch === "pab" || ch === "bap") : ch === channel);
        })
        .map(p => ({
          elementId: p.pabEntry.element_id,
          qty: Math.max(1, isLegoCart() ? (p.qty ?? 1) : (p.want ?? 1) - (p.have ?? 0)),
          channel: p.pabEntry.channel,
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

  for (const btn of content.querySelectorAll(".csv-dl-btn")) {
    btn.addEventListener("click", () => {
      const rows = [["name", "elementId", "quantity"]];
      for (const p of currentDetail.parts) {
        if (!p.pabEntry?.element_id) continue;
        if (p.pabEntry.channel !== "pab" && p.pabEntry.channel !== "bap") continue;
        const qty = Math.max(1, (p.want ?? 1) - (p.have ?? 0));
        if (qty <= 0) continue;
        const name = (p.pabEntry.lego_name || p.pabEntry.bl_part_name || "").replace(/"/g, '""');
        rows.push([`"${name}"`, p.pabEntry.element_id, qty]);
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

  async function save() {
    const want = Math.max(0, parseInt(wantInput.value, 10) || 0);
    const have = Math.max(0, parseInt(haveInput.value, 10) || 0);
    currentDetail.parts[idx].want = want;
    currentDetail.parts[idx].have = have;
    currentDetail.parts[idx].qty  = Math.max(0, want - have);
    await savePartsToStorage();
    renderDetailView(content);
  }

  for (const input of [wantInput, haveInput]) {
    input.addEventListener("keydown", e => { if (e.key === "Enter") save(); if (e.key === "Escape") renderDetailView(content); });
  }
  // Small delay so this click doesn't immediately re-trigger save via blur
  setTimeout(() => {
    document.addEventListener("click", function onOutside(e) {
      if (!cell.contains(e.target)) { document.removeEventListener("click", onOutside); save(); }
    });
  }, 50);
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
