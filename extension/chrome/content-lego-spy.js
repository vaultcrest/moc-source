// Runs in MAIN world at document_start — intercepts LEGO's GraphQL fetch calls
// before React hydrates, so we capture cart data the page loads itself.
(function () {
  const _fetch = window.fetch;
  window.__mocCartData = window.__mocCartData || {};

  window.fetch = function (input, init) {
    const url = (typeof input === "string" ? input : input?.url) || "";
    const p = _fetch.apply(this, arguments);

    if (url.includes("/api/graphql/")) {
      p.then(r => r.clone().json().then(body => {
        window.postMessage({ type: "__MOC_GQL__", url, body }, "*");
      }).catch(() => {})).catch(() => {});
    }

    return p;
  };
})();
