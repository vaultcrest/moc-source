const API_BASE = "https://api.moc-source.com";

chrome.action.onClicked.addListener(() => {
  chrome.tabs.create({ url: chrome.runtime.getURL("index.html") });
});

// Cache PAB prices per locale for the session
const priceCache = new Map(); // key: `${locale}:${partNo}:${colorId}`

// Cache the locale setting so we don't call storage on every request
let cachedLocale = null;

async function getLocale() {
  if (cachedLocale) return cachedLocale;
  const { pabRegion } = await chrome.storage.sync.get({ pabRegion: "en-us" });
  cachedLocale = pabRegion || "en-us";
  return cachedLocale;
}

// Invalidate locale cache when settings change
chrome.storage.onChanged.addListener((changes) => {
  if (changes.pabRegion) {
    cachedLocale = changes.pabRegion.newValue || "en-us";
    priceCache.clear(); // old locale prices are stale
  }
});

async function fetchPabPrice(partNo, colorId) {
  const locale = await getLocale();
  const key = `${locale}:${partNo}:${colorId}`;
  if (priceCache.has(key)) return priceCache.get(key);

  try {
    const res = await fetch(
      `${API_BASE}/api/v1/parts/pab/price/${partNo}/${colorId}?locale=${locale}`
    );
    if (!res.ok) return null;
    const data = await res.json();
    const hit = data.find(e => e.channel === "pab") ?? data.find(e => e.channel === "bap") ?? data[0] ?? null;
    priceCache.set(key, hit);
    return hit;
  } catch {
    return null;
  }
}

async function fetchPabPriceByElement(elementId) {
  const locale = await getLocale();
  const key = `element:${locale}:${elementId}`;
  if (priceCache.has(key)) return priceCache.get(key);

  try {
    const res = await fetch(
      `${API_BASE}/api/v1/parts/element/${elementId}/price?locale=${locale}`
    );
    if (!res.ok) return null;
    const data = await res.json();
    const hit = data.find(e => e.channel === "pab") ?? data.find(e => e.channel === "bap") ?? data[0] ?? null;
    priceCache.set(key, hit);
    return hit;
  } catch {
    return null;
  }
}

function jwtIat(token) {
  // Returns the iat (issued-at) claim from a JWT, or -1 if unparseable.
  try {
    const b64 = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = b64 + "=".repeat((4 - b64.length % 4) % 4);
    return JSON.parse(atob(padded))?.iat ?? -1;
  } catch {
    return -1;
  }
}

async function getLegoAuth() {
  // Lego.com can have multiple gqauth cookies (different paths/domains) with
  // different expiries. chrome.cookies.get returns only the most-specific match
  // which may be an expired one. getAll + pick the freshest by iat.
  const all = await chrome.cookies.getAll({ name: "gqauth" }).catch(() => []);
  const legoOnly = all.filter(c => c.domain.includes("lego.com") && c.value);
  if (!legoOnly.length) return null;
  legoOnly.sort((a, b) => jwtIat(b.value) - jwtIat(a.value));
  return legoOnly[0].value;
}

async function openBLUpload() {
  const url = "https://www.bricklink.com/v2/wanted/upload.page";
  const existing = await chrome.tabs.query({ url: "https://www.bricklink.com/*" });
  if (existing.length > 0) {
    chrome.tabs.update(existing[0].id, { url, active: true });
  } else {
    chrome.tabs.create({ url });
  }
}

async function openLegoTransfer(items, channel) {
  const locale = await getLocale();
  const auth = await getLegoAuth();

  const payload = { items, locale, channel, auth };
  await chrome.storage.local.set({ pendingLegoTransfer: payload });

  // Always navigate to the PAB page — ensures the content script is freshly
  // injected regardless of whether the tab was already open. Auth is already
  // captured above so navigating doesn't reset the JWT.
  const pabUrl = `https://www.lego.com/${locale}/pick-and-build/pick-a-brick`;
  const existing = await chrome.tabs.query({ url: "https://www.lego.com/*" });
  if (existing.length > 0) {
    chrome.tabs.update(existing[0].id, { url: pabUrl, active: true });
  } else {
    chrome.tabs.create({ url: pabUrl });
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "GET_PAB_PRICE") {
    fetchPabPrice(msg.partNo, msg.colorId).then(sendResponse);
    return true;
  }
  if (msg.type === "GET_PAB_PRICE_BY_ELEMENT") {
    fetchPabPriceByElement(msg.elementId).then(sendResponse);
    return true;
  }
  if (msg.type === "OPEN_MOC_SOURCE") {
    chrome.tabs.create({ url: chrome.runtime.getURL("index.html") });
    sendResponse(true);
    return true;
  }
  if (msg.type === "QUEUE_TRANSFER") {
    openLegoTransfer(msg.items, msg.channel).then(() => sendResponse(true));
    return true;
  }
  if (msg.type === "QUEUE_BL_UPLOAD") {
    openBLUpload().then(() => sendResponse(true));
    return true;
  }
  if (msg.type === "SAVE_LEGO_CART") {
    (async () => {
      const { legoCarts = [] } = await chrome.storage.local.get("legoCarts");
      legoCarts.unshift(msg.cart);
      await chrome.storage.local.set({ legoCarts });
      sendResponse(true);
    })();
    return true;
  }
});
