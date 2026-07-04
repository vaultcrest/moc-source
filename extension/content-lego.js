// MOC Source — LEGO.com cart integration
// Runs on https://www.lego.com/* pages.
// Checks for a pending transfer queued by the extension SPA on page load,
// and exposes a message listener for foreground transfers.

let transferInProgress = false;

// ─── GQL spy listener (spy runs in MAIN world via content-lego-spy.js) ───────
// Cache any cart-related GraphQL responses intercepted by the MAIN-world spy.
const _legoCartCache = {};

window.addEventListener("message", e => {
  if (e.data?.type !== "__MOC_GQL__") return;
  const d = e.data.body?.data;
  if (!d) return;
  const keys = Object.keys(d);
  if (keys.some(k => k.toLowerCase().includes("cart"))) {
    console.log("[MOC] GQL spy:", e.data.url.split("/graphql/")[1], JSON.stringify(d).slice(0, 1000));
  }
  const carts =
    d?.elementCartsAddToCart?.carts ??
    d?.elementCarts?.carts ??
    d?.elementCart?.carts ??
    null;
  if (Array.isArray(carts)) {
    carts.forEach(c => { if (c?.id) _legoCartCache[c.id] = c; });
  }
});

const LEGO_GQL = "https://www.lego.com/api/graphql";

// ─── Locale format ───────────────────────────────────────────────────────────
// PAB search accepts "en-us" but the cart API requires "en-US" (uppercase region)
function cartLocale(locale) {
  const [lang, region] = locale.split("-");
  return region ? `${lang}-${region.toUpperCase()}` : locale;
}

// ─── Auth ─────────────────────────────────────────────────────────────────────

function getGqAuth() {
  // Split on "; " without decoding the whole string first —
  // decodeURIComponent on the full cookie string throws if any
  // other cookie contains invalid %XX sequences.
  for (const raw of document.cookie.split(";")) {
    const eq = raw.indexOf("=");
    if (eq === -1) continue;
    const key = raw.slice(0, eq).trim();
    if (key !== "gqauth") continue;
    const val = raw.slice(eq + 1).trim();
    try { return decodeURIComponent(val); } catch { return val; }
  }
  return null;
}

// Polls until the gqauth cookie is present (up to timeoutMs).
async function waitForAuth(timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const auth = getGqAuth();
      if (auth) return auth;
    } catch (e) {
      console.warn("MOC Source: getGqAuth error:", e);
    }
    await new Promise(r => setTimeout(r, 500));
  }
  return null;
}

// ─── LEGO cart GraphQL helpers ────────────────────────────────────────────────

// urlPath = the path segment after /api/graphql/ (may differ from operationName)
async function gql(urlPath, operationName, query, variables, auth, locale) {
  const headers = {
    "Content-Type": "application/json",
    "x-locale": locale,
  };
  if (auth) headers["authorization"] = auth;

  const res = await fetch(`${LEGO_GQL}/${urlPath}`, {
    method: "POST",
    cache: "no-cache",
    credentials: "include",
    headers,
    body: JSON.stringify({ operationName, variables, query }),
  });

  const json = await res.json().catch(() => null);
  if (!res.ok) {
    console.log(`[MOC] gql ${urlPath} ${res.status} full body:`, JSON.stringify(json));
    const detail = json?.errors?.[0]?.message ?? json?.message ?? JSON.stringify(json);
    throw new Error(`HTTP ${res.status} on ${urlPath}: ${detail}`);
  }
  if (json?.errors?.length) {
    console.log(`[MOC] gql ${urlPath} errors:`, JSON.stringify(json.errors));
    throw new Error(json.errors[0].message);
  }
  return json.data;
}

// Reads cart items from the rendered DOM by activating each tab and scanning
// for the elementId/designId text pattern (e.g. "302326/3023") and qty inputs.
async function readCart(_auth, _locale, cartType) {
  const tabLabel = cartType === "pab" ? "Bestseller" : "Standard";
  const tab = [...document.querySelectorAll('button[data-test="element-cart-tabs-child"]')]
    .find(el => el.textContent.trim().startsWith(tabLabel));
  if (!tab) return [];

  const alreadyActive = tab.classList.contains("V5AtfW_active") ||
                        tab.getAttribute("aria-selected") === "true";
  if (!alreadyActive) {
    tab.click();
    await new Promise(r => setTimeout(r, 600));
  }

  const items = [];
  const idRe = /^(\d{5,9})\/(\d+)$/;

  // Walk all text nodes looking for the "elementId/designId" pattern
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode: n => idRe.test(n.textContent.trim())
      ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP,
  });

  let node;
  while ((node = walker.nextNode())) {
    const [, sku, designId] = node.textContent.trim().match(idRe);
    let el = node.parentElement;
    let qty = 1;
    let name = "";
    for (let i = 0; i < 10 && el; i++) {
      if (!qty || qty === 1) {
        const inp = el.querySelector('input[type="number"], input[type="text"][value]');
        if (inp) qty = Math.max(1, parseInt(inp.value) || 1);
      }
      if (!name) {
        // Name is typically a heading or strong near the id text
        const h = el.querySelector('h1,h2,h3,h4,h5,h6,strong,[class*="name"],[class*="title"],[class*="heading"]');
        if (h && h.textContent.trim() && !idRe.test(h.textContent.trim())) {
          name = h.textContent.trim();
        }
      }
      if (qty > 1 && name) break;
      el = el.parentElement;
    }
    items.push({ sku, designId, quantity: qty, name });
  }

  console.log(`[MOC] readCart DOM (${cartType}): ${items.length} items`, items[0]);
  return items;
}

// Adds items not already in the cart.
async function addToCart(auth, locale, items, cartType) {
  const result = await gql(
    "AddToElementCart",         // URL path
    "ElementCartsAddToCart",    // operationName in body (different from URL path)
    `mutation ElementCartsAddToCart($items: [ElementInput!]!, $cartType: CartType!, $returnCarts: [CartType!]!) {
      elementCartsAddToCart(
        input: {items: $items, cartType: $cartType, returnCarts: $returnCarts}
      ) {
        carts {
          id
        }
      }
    }`,
    { items, cartType, returnCarts: [] },
    auth,
    locale
  );
  console.log("[MOC] addToCart result:", JSON.stringify(result));
  return result;
}

// ─── Transfer orchestration ───────────────────────────────────────────────────

// Sends a batch of ElementInput items to one cart type and returns counts.
async function pushToCart(auth, locale, toAdd, cartType, label, doneOffset, totalAll) {
  const BATCH = 50;
  let added = 0, failed = 0, lastError = null, limitReached = false;
  for (let i = 0; i < toAdd.length; i += BATCH) {
    const batch = toAdd.slice(i, i + BATCH);
    try {
      await addToCart(auth, locale, batch, cartType);
      added += batch.length;
    } catch (e) {
      lastError = e.message;
      console.warn(`MOC Source: ${label} batch failed:`, e.message);
      if (e.message.includes("MAX_LINE_ITEMS_REACHED")) {
        limitReached = true;
        failed += toAdd.length - i - added;
        break;
      }
      failed += batch.length;
    }
    showOverlay(
      failed ? `${label}… (${failed} failed)` : `${label}…`,
      doneOffset + added + failed,
      totalAll
    );
  }
  return { added, failed, lastError, limitReached };
}

async function runTransfer(items, locale, channel, auth) {
  if (transferInProgress) return { ok: false, error: "transfer already in progress" };
  transferInProgress = true;

  showOverlay("Connecting to LEGO cart…", 0, items.length);

  // auth is provided by the background (read via chrome.cookies); fall back to
  // document.cookie for the on-load path where background may not have passed it.
  if (!auth) auth = await waitForAuth();
  if (!auth) {
    showOverlay("Not signed in to LEGO.com — please log in and try again.", 0, 0, true);
    transferInProgress = false;
    return { ok: false, error: "not signed in" };
  }

  // Cart API requires "en-US" format, not "en-us"
  locale = cartLocale(locale);

  if (channel === "both") {
    const pabItems = items.filter(i => i.channel === "pab");
    const bapItems = items.filter(i => i.channel === "bap");
    const total = items.length;
    let added = 0, skipped = 0, failed = 0, lastError = null;

    for (const [channelItems, cartType, label, offset] of [
      [pabItems, "pab", "Bestseller", 0],
      [bapItems, "bap", "Standard",   pabItems.length],
    ]) {
      if (!channelItems.length) continue;
      let existing = new Set();
      try {
        const cart = await readCart(auth, locale, cartType);
        existing = new Set(cart.map(i => String(i.designId ?? i.sku)));
      } catch (e) { console.warn("MOC Source: cart read skipped:", e.message); }
      const toAdd = channelItems.filter(i => !existing.has(String(i.elementId)))
        .map(i => ({ sku: String(i.elementId), quantity: i.qty }));
      skipped += channelItems.length - toAdd.length;
      if (toAdd.length) {
        showOverlay(`Adding ${label} parts…`, offset, total);
        const r = await pushToCart(auth, locale, toAdd, cartType, label, offset, total);
        added += r.added; failed += r.failed;
        if (r.lastError) lastError = r.lastError;
      }
    }

    const parts = [];
    if (added > 0) parts.push(`${added} lot${added !== 1 ? "s" : ""} added`);
    if (skipped > 0) parts.push(`${skipped} already in cart`);
    if (failed > 0) parts.push(`${failed} failed`);
    const msg = failed > 0 ? `${parts.join(", ")}.\n${lastError ?? ""}` : `Done! ${parts.join(", ")}.`;
    showOverlay(msg, items.length, items.length, failed > 0, true);
    transferInProgress = false;
    return { ok: failed === 0, added, skipped, failed };
  }

  const cartType = channel === "bap" ? "bap" : "pab";
  const label = cartType === "pab" ? "Bestseller" : "Standard";
  const total = items.length;

  let existingSkus = new Set();
  try {
    const cart = await readCart(auth, locale, cartType);
    existingSkus = new Set(cart.map(i => String(i.designId ?? i.sku)));
  } catch (e) {
    console.warn("MOC Source: cart read skipped:", e.message);
  }

  const toAdd = items
    .filter(i => !existingSkus.has(String(i.elementId)))
    .map(i => ({ sku: String(i.elementId), quantity: i.qty }));

  const skipped = items.length - toAdd.length;

  if (toAdd.length === 0) {
    const msg = skipped > 0
      ? `All ${skipped} lot${skipped !== 1 ? "s" : ""} already in your LEGO cart.`
      : "Nothing to transfer.";
    showOverlay(msg, total, total, false, true);
    transferInProgress = false;
    return { ok: true, added: 0, skipped };
  }

  showOverlay(`Adding ${label} parts…`, 0, toAdd.length);
  const { added, failed, lastError } = await pushToCart(auth, locale, toAdd, cartType, label, 0, toAdd.length);

  const parts = [];
  if (added > 0) parts.push(`${added} lot${added !== 1 ? "s" : ""} added`);
  if (skipped > 0) parts.push(`${skipped} already in cart`);
  if (failed > 0) parts.push(`${failed} failed`);
  const msg = failed > 0
    ? `${parts.join(", ")}.\n${lastError ?? ""}`
    : `Done! ${parts.join(", ")}.`;

  showOverlay(msg, toAdd.length, toAdd.length, failed > 0, true);
  transferInProgress = false;
  return { ok: failed === 0, added, skipped, failed };
}

// ─── Overlay UI ──────────────────────────────────────────────────────────────

function showOverlay(msg, done, total, isError, done_) {
  let el = document.getElementById("moc-source-overlay");
  if (!el) {
    el = document.createElement("div");
    el.id = "moc-source-overlay";
    Object.assign(el.style, {
      position: "fixed",
      top: "50%", left: "50%",
      transform: "translate(-50%, -50%)",
      zIndex: "999999",
      background: "#1e2330", color: "#fff",
      borderRadius: "20px",
      padding: "40px 48px",
      width: "min(1000px, 90vw)",
      boxShadow: "0 16px 80px rgba(0,0,0,.7)",
      fontFamily: "sans-serif",
      fontSize: "36px", lineHeight: "1.5",
    });
    document.body.appendChild(el);
  }
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const isFinished = done_ === true;
  el.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <span style="font-weight:700;font-size:42px;color:${isError ? "#f87171" : "#fff"}">MOC Source</span>
      <button id="moc-source-close" style="background:none;border:none;color:#8b9ab0;font-size:36px;cursor:pointer;line-height:1;padding:0 0 0 20px" title="Close">✕</button>
    </div>
    <div style="margin-bottom:${total > 0 ? "24px" : "0"};white-space:pre-wrap;word-break:break-all;user-select:text">${msg}</div>
    ${total > 0 ? `
      <div style="background:#2d3547;border-radius:8px;height:20px;overflow:hidden">
        <div style="background:${isError ? "#f87171" : "#22c55e"};height:100%;width:${pct}%;transition:width .3s"></div>
      </div>
      <div style="font-size:27px;color:#8b9ab0;margin-top:12px">${done} / ${total}</div>` : ""}
    ${isFinished ? `
      <div style="margin-top:28px;font-size:27px;color:#8b9ab0">Refresh the page to see your updated LEGO cart.</div>
      <div style="margin-top:20px;display:flex;gap:16px">
        <button id="moc-source-refresh" style="background:#2563eb;border:none;color:#fff;font-size:27px;font-weight:600;border-radius:10px;padding:12px 28px;cursor:pointer">Refresh Page</button>
        <button id="moc-source-close2" style="background:#2d3547;border:none;color:#8b9ab0;font-size:27px;border-radius:10px;padding:12px 28px;cursor:pointer">Dismiss</button>
      </div>` : ""}
  `;
  document.getElementById("moc-source-close")?.addEventListener("click", () => location.reload());
  document.getElementById("moc-source-close2")?.addEventListener("click", () => location.reload());
  document.getElementById("moc-source-refresh")?.addEventListener("click", () => location.reload());
}

function removeOverlay() {
  document.getElementById("moc-source-overlay")?.remove();
}

// ─── Save Cart button ────────────────────────────────────────────────────────

async function doSaveCart(btn, originalText) {
  btn.disabled = true;
  btn.textContent = "Reading…";
  try {
    const auth = getGqAuth() || await waitForAuth(5000);
    if (!auth) throw new Error("Not signed in");

    const lang   = location.pathname.split("/")[1] || "en-us";
    const locale = cartLocale(lang);
    const parts  = [];

    console.log("[MOC] auth present:", !!auth, "locale:", locale);
    for (const cartType of ["pab", "bap"]) {
      let items = [];
      try {
        items = await readCart(auth, locale, cartType);
        console.log(`[MOC] readCart(${cartType}):`, JSON.stringify(items?.slice(0,2)));
      } catch(e) {
        console.log(`[MOC] readCart(${cartType}) error:`, e.message);
      }
      for (const item of items ?? []) {
        if ((item.quantity ?? 0) > 0) {
          parts.push({
            elementId: item.sku,
            designId:  String(item.designId ?? ""),
            name:      item.name ?? "",
            qty:       item.quantity,
            channel:   cartType,
          });
        }
      }
    }

    if (!parts.length) {
      btn.textContent = "Cart empty";
      setTimeout(() => { btn.disabled = false; btn.textContent = originalText; }, 2500);
      return;
    }

    const now  = new Date();
    const name = now.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })
      + " " + now.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

    await chrome.runtime.sendMessage({
      type: "SAVE_LEGO_CART",
      cart: { id: String(Date.now()), name, importedAt: Date.now(),
              locale: lang.toLowerCase(), partsCount: parts.length, parts },
    });

    btn.textContent = `✓ ${parts.length} lots saved`;
    setTimeout(() => { btn.disabled = false; btn.textContent = originalText; }, 3000);
  } catch (e) {
    btn.textContent = `Error: ${e.message}`;
    setTimeout(() => { btn.disabled = false; btn.textContent = originalText; }, 3000);
  }
}

function tryInjectSaveCartBtn() {
  if (!location.pathname.includes("/pick-and-build/pick-a-brick")) return;
  if (document.getElementById("moc-save-cart-btn")) return;

  // Use the data-test attribute for reliable targeting
  const allTabs = [...document.querySelectorAll('button[data-test="element-cart-tabs-child"]')];
  const orderInfoTab = allTabs.find(el => el.textContent.trim() === "Order Info");
  if (!orderInfoTab) return;

  const btn = document.createElement("button");
  btn.id = "moc-save-cart-btn";
  btn.textContent = "Save to MOC Source";
  btn.type = "button";
  btn.setAttribute("role", "tab");
  btn.setAttribute("data-test", "element-cart-tabs-child");
  btn.setAttribute("aria-selected", "false");
  btn.setAttribute("tabindex", "-1");
  // Use identical classes to sibling tabs (minus active) so LEGO CSS handles sizing
  btn.className = orderInfoTab.className.replace(/\bV5AtfW_active\b/g, "").trim();
  // Override just the color to distinguish as an action button
  btn.style.color = "#006db7";

  btn.addEventListener("click", () => doSaveCart(btn, "Save to MOC Source"));

  const tabParent = orderInfoTab.parentElement;
  tabParent.insertBefore(btn, orderInfoTab.nextSibling);
}

// Watch for the cart modal to open (React renders it dynamically)
const _legoObs = new MutationObserver(tryInjectSaveCartBtn);
_legoObs.observe(document.body, { childList: true, subtree: true });
tryInjectSaveCartBtn();

// ─── Message listener (foreground transfer) ───────────────────────────────────

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "TRANSFER_TO_PAB") {
    runTransfer(msg.items, msg.locale, msg.channel, msg.auth).then(sendResponse);
    return true;
  }
});

// ─── On-load: check for pending transfer queued from extension SPA ────────────

(async () => {
  const { pendingLegoTransfer } = await chrome.storage.local.get("pendingLegoTransfer");
  if (!pendingLegoTransfer) return;
  await chrome.storage.local.remove("pendingLegoTransfer");
  const { items, locale, channel, auth } = pendingLegoTransfer;
  runTransfer(items, locale, channel, auth);
})();
