const API_BASE = "https://api.moc-source.com";

// Cache PAB prices for the session to avoid redundant requests
const priceCache = new Map();

async function fetchPabPrice(partNo, colorId) {
  const key = `${partNo}:${colorId}`;
  if (priceCache.has(key)) return priceCache.get(key);

  try {
    const res = await fetch(`${API_BASE}/api/v1/parts/pab/price/${partNo}/${colorId}`);
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
