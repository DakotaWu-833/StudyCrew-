document.querySelectorAll("[data-dismiss-flash]").forEach((button) => {
  button.addEventListener("click", () => button.closest(".flash")?.remove());
});
