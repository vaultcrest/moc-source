// Runs in MAIN world — can override page globals that CSP blocks from inline scripts.
// Signals arrive via CustomEvents dispatched from the isolated-world content.js.

window.addEventListener("moc:confirm-override", () => {
  window.__mocOrigConfirm = window.confirm;
  window.confirm = () => true;
});

window.addEventListener("moc:confirm-restore", () => {
  if (typeof window.__mocOrigConfirm === "function") {
    window.confirm = window.__mocOrigConfirm;
    delete window.__mocOrigConfirm;
  }
});
