const API_BASE = "https://api.moc-source.com";
const BL_API_BASE = "https://api.bricklink.com/api/store/v1";

// ─── BrickLink OAuth 1.0a ────────────────────────────────────────────────────

const blPriceCache = new Map(); // key: `${partNo}:${colorId}`, session-scoped

function _pct(s) {
  return encodeURIComponent(String(s))
    .replace(/[!'()*]/g, c => "%" + c.charCodeAt(0).toString(16).toUpperCase());
}

async function blOAuthHeader(method, url, creds) {
  const { consumerKey, consumerSecret, token, tokenSecret } = creds;
  const nonce = [...crypto.getRandomValues(new Uint8Array(16))]
    .map(b => b.toString(16).padStart(2, "0")).join("");
  const timestamp = Math.floor(Date.now() / 1000).toString();

  const params = {
    oauth_consumer_key:     consumerKey,
    oauth_nonce:            nonce,
    oauth_signature_method: "HMAC-SHA1",
    oauth_timestamp:        timestamp,
    oauth_token:            token,
    oauth_version:          "1.0",
  };

  // Strip query string from URL for base string; include query params in params object
  const [baseUrl, qs] = url.split("?");
  const oauthParams = { ...params };
  if (qs) {
    for (const pair of qs.split("&")) {
      const [k, v] = pair.split("=");
      oauthParams[decodeURIComponent(k)] = decodeURIComponent(v ?? "");
    }
  }

  const sortedParams = Object.entries(oauthParams)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => `${_pct(k)}=${_pct(v)}`)
    .join("&");

  const baseString = [method.toUpperCase(), _pct(baseUrl), _pct(sortedParams)].join("&");
  const signingKey = `${_pct(consumerSecret)}&${_pct(tokenSecret)}`;

  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw", enc.encode(signingKey), { name: "HMAC", hash: "SHA-1" }, false, ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(baseString));
  params.oauth_signature = btoa(String.fromCharCode(...new Uint8Array(sig)));

  return "OAuth " + Object.entries(params)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => `${_pct(k)}="${_pct(v)}"`)
    .join(", ");
}

async function decryptBLCredentials() {
  const { blCredentials } = await chrome.storage.local.get("blCredentials");
  if (!blCredentials) return null;
  try {
    const enc = new TextEncoder();
    const raw = enc.encode(chrome.runtime.id);
    const base = await crypto.subtle.importKey("raw", raw, "PBKDF2", false, ["deriveKey"]);
    const key  = await crypto.subtle.deriveKey(
      { name: "PBKDF2", salt: enc.encode("moc-source-bl"), iterations: 100000, hash: "SHA-256" },
      base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]
    );
    const fromB64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
    const plain = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: fromB64(blCredentials.iv) }, key, fromB64(blCredentials.ciphertext)
    );
    return JSON.parse(new TextDecoder().decode(plain));
  } catch { return null; }
}

async function fetchBLPriceGuide(partNo, colorId, condition) {
  const cacheKey = `${partNo}:${colorId}:${condition}`;
  if (blPriceCache.has(cacheKey)) return blPriceCache.get(cacheKey);

  const creds = await decryptBLCredentials();
  if (!creds?.consumerKey) { blPriceCache.set(cacheKey, null); return null; }

  const url = `${BL_API_BASE}/items/part/${encodeURIComponent(partNo)}/price?guide_type=stock&new_or_used=${condition}&color_id=${encodeURIComponent(colorId)}`;
  try {
    const auth = await blOAuthHeader("GET", url, creds);
    const res  = await fetch(url, { headers: { Authorization: auth } });
    if (!res.ok) { blPriceCache.set(cacheKey, null); return null; }
    const body = await res.json();
    if (body.meta?.code !== 200) { blPriceCache.set(cacheKey, null); return null; }
    blPriceCache.set(cacheKey, body.data);
    return body.data;
  } catch { blPriceCache.set(cacheKey, null); return null; }
}

async function fetchBLMarketPrice(partNo, colorId, condition) {
  if (condition === "A") {
    // Return whichever condition has the lower min_price
    const [newData, usedData] = await Promise.all([
      fetchBLPriceGuide(partNo, colorId, "N"),
      fetchBLPriceGuide(partNo, colorId, "U"),
    ]);
    if (!newData && !usedData) return null;
    if (!newData) return { ...usedData, condition: "U" };
    if (!usedData) return { ...newData, condition: "N" };
    const newMin  = parseFloat(newData.min_price)  || Infinity;
    const usedMin = parseFloat(usedData.min_price) || Infinity;
    return usedMin < newMin
      ? { ...usedData, condition: "U" }
      : { ...newData,  condition: "N" };
  }
  const data = await fetchBLPriceGuide(partNo, colorId, condition);
  return data ? { ...data, condition } : null;
}

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

async function fetchPabPricesForPart(partNo) {
  const locale = await getLocale();
  const key = `prices:${locale}:${partNo}`;
  if (priceCache.has(key)) return priceCache.get(key);
  try {
    const res = await fetch(`${API_BASE}/api/v1/parts/pab/prices/${partNo}?locale=${locale}`);
    if (!res.ok) return [];
    const data = await res.json();
    priceCache.set(key, data);
    return data;
  } catch {
    return [];
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

// ─── LEGO cart API ────────────────────────────────────────────────────────────
// These fetches run in the service worker (origin = chrome-extension://...).
// That makes them cross-origin to lego.com, so the browser sends NO lego.com
// cookies — including Cloudflare's __cf_bm bot-management token. Running the
// same fetch from a content script on lego.com would send that token and
// trigger CF 1015 rate limiting.

const LEGO_GQL_BASE = "https://www.lego.com/api/graphql";

async function legoGql(auth, locale, urlPath, operationName, query, variables) {
  const res = await fetch(`${LEGO_GQL_BASE}/${urlPath}`, {
    method: "POST",
    cache: "no-cache",
    headers: {
      "Content-Type": "application/json",
      "x-locale": locale,
      authorization: auth,
    },
    body: JSON.stringify({ operationName, variables, query }),
  });
  const json = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = json?.errors?.[0]?.message ?? json?.message ?? JSON.stringify(json);
    throw new Error(`HTTP ${res.status} on ${urlPath}: ${detail}`);
  }
  if (json?.errors?.length) throw new Error(json.errors[0].message);
  return json.data;
}

async function legoReadCart(auth, locale, cartType) {
  const data = await legoGql(
    auth, locale,
    "ElementCartQuery", "ElementCartQuery",
    `query ElementCartQuery($cartTypes: [CartType!]!) {
  elementCarts(types: $cartTypes) {
    carts {
      brickLineItems {
        id sku designId maxOrderQuantity deliveryChannel quantity
      }
    }
  }
}`,
    { cartTypes: [cartType] }
  );
  return data?.elementCarts?.carts?.[0]?.brickLineItems ?? [];
}

async function legoAddToCart(auth, locale, items, cartType) {
  return legoGql(
    auth, locale,
    "AddToElementCart", "ElementCartsAddToCart",
    `mutation ElementCartsAddToCart($items: [ElementInput!]!, $cartType: CartType!, $returnCarts: [CartType!]!) {
  elementCartsAddToCart(input: {items: $items, cartType: $cartType, returnCarts: $returnCarts}) {
    carts { id }
  }
}`,
    { items, cartType, returnCarts: [] }
  );
}

async function legoChangeInCart(auth, locale, elements, cartType) {
  return legoGql(
    auth, locale,
    "ChangeElementLineItem", "ElementCartsChangeLineItemQuantity",
    `mutation ElementCartsChangeLineItemQuantity($cartType: CartType!, $elements: [ElementLineItemInput!]!, $returnCarts: [CartType!]!) {
  elementCartsChangeLineItemQuantity(input: {cartType: $cartType, elements: $elements, returnCarts: $returnCarts}) {
    carts { id }
  }
}`,
    { elements, cartType, returnCarts: [] }
  );
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
  if (msg.type === "GET_BL_MARKET_PRICE") {
    fetchBLMarketPrice(msg.partNo, msg.colorId, msg.condition || "N").then(sendResponse);
    return true;
  }
  if (msg.type === "GET_PAB_PRICE") {
    fetchPabPrice(msg.partNo, msg.colorId).then(sendResponse);
    return true;
  }
  if (msg.type === "GET_PAB_PRICE_BY_ELEMENT") {
    fetchPabPriceByElement(msg.elementId).then(sendResponse);
    return true;
  }
  if (msg.type === "GET_PAB_PRICES_FOR_PART") {
    fetchPabPricesForPart(msg.partNo).then(sendResponse);
    return true;
  }
  if (msg.type === "OPEN_MOC_SOURCE") {
    chrome.tabs.create({ url: chrome.runtime.getURL("index.html") });
    sendResponse(true);
    return true;
  }
  if (msg.type === "LEGO_CART_API") {
    (async () => {
      try {
        let data;
        switch (msg.action) {
          case "readCart":
            data = await legoReadCart(msg.auth, msg.locale, msg.cartType); break;
          case "addToCart":
            data = await legoAddToCart(msg.auth, msg.locale, msg.items, msg.cartType); break;
          case "changeInCart":
            data = await legoChangeInCart(msg.auth, msg.locale, msg.elements, msg.cartType); break;
          default:
            throw new Error(`Unknown LEGO_CART_API action: ${msg.action}`);
        }
        sendResponse({ ok: true, data });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
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
