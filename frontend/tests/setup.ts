// jsdom does not provide native dialog top-layer behaviour. Keep these shims
// in tests; the application uses the browser's real modal implementation.
if (typeof HTMLDialogElement !== "undefined" && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
    this.querySelector<HTMLElement>("[autofocus], button, input, textarea, select")?.focus();
  };
}
if (typeof HTMLDialogElement !== "undefined" && !HTMLDialogElement.prototype.close) {
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); this.dispatchEvent(new Event("close")); };
}
