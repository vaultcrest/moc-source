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

// ─── Detail view state ───────────────────────────────────────────────────────

let currentDetail = null; // { listType, listId, list, parts: [...with pabEntry] }
let currentTab = "all";

// ─── Router ──────────────────────────────────────────────────────────────────

function navigate(view) {
  location.hash = view;
  const baseView = view.startsWith("list/") ? "lists" : view;
  for (const el of document.querySelectorAll(".nav-item[data-view]")) {
    el.classList.toggle("active", el.dataset.view === baseView);
  }
  const content = document.getElementById("content");
  if (view === "lists")          renderLists(content);
  else if (view === "settings")  renderSettings(content);
  else if (view === "info")      renderInfo(content);
  else if (view.startsWith("list/")) {
    const parts = view.split("/");
    renderListDetail(parts[1], parts[2], content);
  }
}

// ─── Lists view ──────────────────────────────────────────────────────────────

async function renderLists(content) {
  const { wantedLists = [], carts = [] } = await chrome.storage.local.get(["wantedLists", "carts"]);

  content.innerHTML = `
    <div class="page-title">Parts Lists</div>

    <div class="section">
      <div class="section-header"><span>Wanted Lists</span></div>
      ${wantedLists.length === 0
        ? `<div class="section-empty">No wanted lists imported yet.<br>Open a BrickLink wanted list and click <strong>Save to MOC Source</strong>.</div>`
        : `<table>
            <thead><tr><th>Name</th><th>Type</th><th>Parts</th><th>Imported</th><th></th></tr></thead>
            <tbody>
              ${wantedLists.map(l => `
                <tr>
                  <td><button class="list-open-btn" style="background:none;border:none;padding:0;cursor:pointer;font-weight:600;color:#1e2330;text-align:left;" data-type="wantedLists" data-id="${esc(l.id)}">${esc(l.name)}</button></td>
                  <td><span class="type-badge">BrickLink</span></td>
                  <td>${l.partsCount}</td>
                  <td>${fmtDate(l.importedAt)}</td>
                  <td><button class="btn btn-danger del-btn" data-id="${esc(l.id)}" data-key="wantedLists">Delete</button></td>
                </tr>`).join("")}
            </tbody>
          </table>`}
    </div>

    <div class="section">
      <div class="section-header"><span>Carts</span></div>
      ${carts.length === 0
        ? `<div class="section-empty">No carts imported yet.<br>Open a BrickLink store cart and click <strong>Save to MOC Source</strong>.</div>`
        : `<table>
            <thead><tr><th>Name</th><th>Type</th><th>Parts</th><th>Imported</th><th></th></tr></thead>
            <tbody>
              ${carts.map(c => `
                <tr>
                  <td><button class="list-open-btn" style="background:none;border:none;padding:0;cursor:pointer;font-weight:600;color:#1e2330;text-align:left;" data-type="carts" data-id="${esc(c.id)}">${esc(c.name)}</button></td>
                  <td><span class="type-badge">BrickLink</span></td>
                  <td>${c.partsCount}</td>
                  <td>${fmtDate(c.importedAt)}</td>
                  <td><button class="btn btn-danger del-btn" data-id="${esc(c.id)}" data-key="carts">Delete</button></td>
                </tr>`).join("")}
            </tbody>
          </table>`}
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

  currentDetail = { listType, listId, list, parts: list.parts.map(p => ({ ...p, pabEntry: null })) };
  currentTab = "all";
  renderDetailView(content);

  // Fetch all prices in parallel, update as they arrive
  await Promise.all(currentDetail.parts.map(async (_, i) => {
    const p = currentDetail.parts[i];
    currentDetail.parts[i].pabEntry = await chrome.runtime.sendMessage({
      type: "GET_PAB_PRICE", partNo: p.partNo, colorId: p.colorId,
    });
  }));

  renderDetailView(content);
}

function isCart() { return currentDetail.listType === "carts"; }

function tabCounts() {
  const parts = currentDetail.parts;
  const counts = {
    all:     parts.length,
    pab:     parts.filter(p => p.pabEntry?.channel === "pab").length,
    std:     parts.filter(p => p.pabEntry?.channel === "bap").length,
    na:      parts.filter(p => !p.pabEntry).length,
  };
  if (isCart()) counts.flagged = parts.filter(p => p.flagged).length;
  return counts;
}

function filteredParts() {
  const p = currentDetail.parts;
  const indexed = p.map((x, i) => ({ ...x, _i: i }));
  if (currentTab === "pab")     return indexed.filter(x => x.pabEntry?.channel === "pab");
  if (currentTab === "std")     return indexed.filter(x => x.pabEntry?.channel === "bap");
  if (currentTab === "na")      return indexed.filter(x => !x.pabEntry);
  if (currentTab === "flagged") return indexed.filter(x => x.flagged);
  return indexed;
}

function renderDetailView(content) {
  const { list, listType } = currentDetail;
  const counts = tabCounts();
  const parts = filteredParts();
  const cart = isCart();

  const tabLabels = { all: "All", pab: "PAB", std: "Standard", na: "Not on PAB", flagged: "To Remove" };
  const tabKeys = cart ? ["all", "pab", "std", "na", "flagged"] : ["all", "pab", "std", "na"];
  const colCount = cart ? 9 : 11;

  const headers = cart
    ? `<th></th><th>Part</th><th>Image</th><th>Name</th><th>Color</th><th>Qty</th><th>PAB Price</th><th>Channel</th><th></th>`
    : `<th></th><th>Part</th><th>Image</th><th>Name</th><th>Color</th><th>Want / Have</th><th>Need</th><th>Max $</th><th>PAB Price</th><th>Channel</th><th></th>`;

  const refreshBtn = cart && list.storeUrl
    ? `<a href="${esc(list.storeUrl)}" target="_blank" class="btn" style="font-size:12px;text-decoration:none">↻ Open cart</a>`
    : "";

  content.innerHTML = `
    <div class="detail-header">
      <button class="back-btn">← Lists</button>
      <div style="flex:1">
        <div style="display:flex;align-items:center;gap:10px">
          <div class="page-title" style="margin:0">${esc(list.name)}</div>
          ${refreshBtn}
        </div>
        <div class="detail-meta">${list.partsCount} parts · ${cart ? "Cart" : "Wanted List"} · ${fmtDate(list.importedAt)}</div>
      </div>
    </div>

    <div class="tab-bar">
      ${tabKeys.map(t => `
        <button class="tab${currentTab === t ? " active" : ""}" data-tab="${t}">
          ${tabLabels[t]} (${counts[t] ?? 0})
        </button>`).join("")}
    </div>

    <div class="section">
      <table>
        <thead><tr>${headers}</tr></thead>
        <tbody>
          ${parts.map(p => cart ? buildCartRow(p, p._i) : buildWantedRow(p, p._i)).join("")
            || `<tr><td colspan="${colCount}" style="text-align:center;padding:32px;color:#6c757d">No parts in this view</td></tr>`}
        </tbody>
      </table>
    </div>
  `;

  attachDetailListeners(content);
}

function colorCell(p) {
  if (p.pabEntry && p.pabEntry.bl_color_name) {
    const bl = esc(p.pabEntry.bl_color_name);
    const lego = p.pabEntry.lego_color_name ? `<div style="color:#adb5bd;font-size:11px">[${esc(p.pabEntry.lego_color_name)}]</div>` : "";
    return `<strong>${bl}</strong>${lego}`;
  }
  return `<span style="color:#888">${p.colorId}</span>`;
}

function pabCells(p) {
  if (p.pabEntry === null) return ['<span style="color:#adb5bd">…</span>', '<span style="color:#adb5bd;font-size:11px">…</span>'];
  if (!p.pabEntry)         return ["—", '<span style="color:#adb5bd;font-size:11px">N/A</span>'];
  const badge = p.pabEntry.channel === "pab"
    ? '<span style="background:#ffc107;color:#000;padding:2px 7px;border-radius:3px;font-size:11px;font-weight:600">Bestseller</span>'
    : '<span style="background:#0d6efd;color:#fff;padding:2px 7px;border-radius:3px;font-size:11px;font-weight:600">Standard</span>';
  return [p.pabEntry.price_formatted, badge];
}

function buildWantedRow(p, idx) {
  const imgSrc = p.imageUrl || `https://img.bricklink.com/ItemImage/PT/${p.colorId}/${p.partNo}.t1.png`;
  const need = Math.max(0, (p.want ?? 1) - (p.have ?? 0));
  const [pabPrice, channelBadge] = pabCells(p);
  const displayName = p.pabEntry?.bl_part_name || p.name || "";
  const maxPriceStr = p.maxPrice != null ? `$${p.maxPrice.toFixed(2)}` : `<span style="color:#adb5bd">—</span>`;

  return `
    <tr data-idx="${idx}">
      <td><input type="checkbox"></td>
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
  const rowStyle = flagged ? ' style="background:#fff5f5"' : '';
  const flagBtn = flagged
    ? `<button class="btn flag-btn" data-idx="${idx}" style="border-color:#6c757d;color:#6c757d;padding:3px 8px;font-size:11px">↩ Keep</button>`
    : `<button class="btn btn-danger flag-btn" data-idx="${idx}" style="padding:3px 8px;font-size:11px">Remove</button>`;

  return `
    <tr data-idx="${idx}"${rowStyle}>
      <td><input type="checkbox"></td>
      <td style="font-family:monospace;font-size:13px">
        ${esc(p.partNo)}
        ${p.pabEntry?.element_id ? `<div style="font-size:10px;color:#adb5bd;margin-top:2px">${p.pabEntry.element_id}</div>` : ""}
      </td>
      <td><img class="part-img" src="${esc(imgSrc)}" onerror="this.style.display='none'"></td>
      <td style="max-width:160px">${esc(displayName)}</td>
      <td>${colorCell(p)}</td>
      <td><strong>${p.qty ?? 1}</strong></td>
      <td>${pabPrice}</td>
      <td>${channelBadge}</td>
      <td>${flagBtn}</td>
    </tr>`;
}

function attachDetailListeners(content) {
  content.querySelector(".back-btn")?.addEventListener("click", () => navigate("lists"));

  for (const tab of content.querySelectorAll(".tab[data-tab]")) {
    tab.addEventListener("click", () => {
      currentTab = tab.dataset.tab;
      renderDetailView(content);
    });
  }

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
  }

  if (isCart()) {
    for (const btn of content.querySelectorAll(".flag-btn")) {
      btn.addEventListener("click", async () => {
        const idx = parseInt(btn.dataset.idx, 10);
        currentDetail.parts[idx].flagged = !currentDetail.parts[idx].flagged;
        await savePartsToStorage();
        renderDetailView(content);
      });
    }
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
navigate(initial.startsWith("list/") ? initial : (["lists","settings","info"].includes(initial) ? initial : "lists"));
