document.querySelectorAll("[data-dismiss-flash]").forEach((button) => {
  button.addEventListener("click", () => button.closest(".flash")?.remove());
});

const showcase = document.querySelector("[data-feature-showcase]");

if (showcase) {
  const tabs = [...showcase.querySelectorAll("[data-feature-tab]")];
  const views = [...showcase.querySelectorAll("[data-feature-view]")];
  const pauseButton = showcase.querySelector("[data-showcase-toggle]");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let activeIndex = Math.max(0, tabs.findIndex((tab) => tab.getAttribute("aria-selected") === "true"));
  let timer = 0;
  let pointerInside = false;
  let focusInside = false;
  let manuallyPaused = false;

  const stopTimer = () => {
    window.clearTimeout(timer);
    timer = 0;
  };

  const canAutoAdvance = () => !reducedMotion.matches
    && !manuallyPaused
    && !pointerInside
    && !focusInside
    && !document.hidden;

  const scheduleAdvance = () => {
    stopTimer();
    if (!canAutoAdvance() || tabs.length < 2) return;
    timer = window.setTimeout(() => {
      selectTab((activeIndex + 1) % tabs.length);
      scheduleAdvance();
    }, 6500);
  };

  const selectTab = (nextIndex) => {
    activeIndex = (nextIndex + tabs.length) % tabs.length;
    tabs.forEach((tab, index) => {
      const selected = index === activeIndex;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      views[index].hidden = !selected;
    });

    const selectedTab = tabs[activeIndex];
    showcase.querySelectorAll("[data-showcase-callout]").forEach((element) => {
      const key = element.dataset.showcaseCallout;
      element.textContent = selectedTab.getAttribute(`data-${key}`) || "";
    });
    const summary = showcase.querySelector("[data-showcase-summary]");
    if (summary) summary.textContent = selectedTab.dataset.featureSummary || "";
    scheduleAdvance();
  };

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectTab(index));
    tab.addEventListener("keydown", (event) => {
      let nextIndex = index;
      if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
      else if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === "Home") nextIndex = 0;
      else if (event.key === "End") nextIndex = tabs.length - 1;
      else return;
      event.preventDefault();
      tabs[nextIndex].focus();
      selectTab(nextIndex);
    });
  });

  showcase.addEventListener("pointerenter", () => {
    pointerInside = true;
    stopTimer();
  });
  showcase.addEventListener("pointerleave", () => {
    pointerInside = false;
    scheduleAdvance();
  });
  showcase.addEventListener("focusin", () => {
    focusInside = true;
    stopTimer();
  });
  showcase.addEventListener("focusout", (event) => {
    if (event.relatedTarget && showcase.contains(event.relatedTarget)) return;
    focusInside = false;
    scheduleAdvance();
  });
  document.addEventListener("visibilitychange", scheduleAdvance);

  if (pauseButton) {
    pauseButton.hidden = reducedMotion.matches;
    pauseButton.addEventListener("click", () => {
      manuallyPaused = !manuallyPaused;
      pauseButton.setAttribute("aria-pressed", String(manuallyPaused));
      pauseButton.setAttribute("aria-label", manuallyPaused ? "Resume automatic feature preview" : "Pause automatic feature preview");
      pauseButton.querySelector("span").textContent = manuallyPaused ? "▶" : "Ⅱ";
      scheduleAdvance();
    });
  }

  reducedMotion.addEventListener?.("change", (event) => {
    if (pauseButton) pauseButton.hidden = event.matches;
    scheduleAdvance();
  });
  selectTab(activeIndex);
}

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
