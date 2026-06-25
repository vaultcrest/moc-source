const API_BASE = "https://api.moc-source.com";

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
    // Prefer PAB (Pick a Brick) over BAP (Bricks and Pieces)
    const hit = data.find(e => e.channel === "pab") ?? data.find(e => e.channel === "bap") ?? null;
    priceCache.set(key, hit);
    return hit;
  } catch {
    return null;
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "GET_PAB_PRICE") {
    fetchPabPrice(msg.partNo, msg.colorId).then(sendResponse);
    return true; // keep channel open for async response
  }
});
