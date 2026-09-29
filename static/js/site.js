document.querySelectorAll("[data-dismiss-flash]").forEach((button) => {
  button.addEventListener("click", () => button.closest(".flash")?.remove());
});

const revealTargets = [...document.querySelectorAll("[data-reveal]")];
const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

if (revealTargets.length && !prefersReducedMotion) {
  document.documentElement.classList.add("has-scroll-reveal");

  if ("IntersectionObserver" in window) {
    const revealObserver = new IntersectionObserver((entries, observer) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.14, rootMargin: "0px 0px -5% 0px" });

    revealTargets.forEach((element) => revealObserver.observe(element));
  } else {
    const pendingTargets = new Set(revealTargets);
    let framePending = false;
    const revealInView = () => {
      framePending = false;
      const revealLine = window.innerHeight * 0.9;
      pendingTargets.forEach((element) => {
        if (element.getBoundingClientRect().top < revealLine) {
          element.classList.add("is-visible");
          pendingTargets.delete(element);
        }
      });
      if (!pendingTargets.size) {
        window.removeEventListener("scroll", scheduleRevealCheck);
        window.removeEventListener("resize", scheduleRevealCheck);
      }
    };
    const scheduleRevealCheck = () => {
      if (framePending) return;
      framePending = true;
      window.requestAnimationFrame(revealInView);
    };

    window.addEventListener("scroll", scheduleRevealCheck, { passive: true });
    window.addEventListener("resize", scheduleRevealCheck, { passive: true });
    scheduleRevealCheck();
  }
} else {
  revealTargets.forEach((element) => element.classList.add("is-visible"));
}
