const picker = document.querySelector("[data-timezone-picker]");

if (picker) {
  const select = picker.querySelector("select");
  const options = select ? [...select.options].filter((option) => option.value) : [];
  const fieldLabel = picker.closest(".form-field")?.querySelector("label");
  if (select && options.length) {
    const menuId = `${select.id}-menu`;
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "timezone-picker__trigger";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-controls", menuId);
    trigger.setAttribute("aria-expanded", "false");
    trigger.setAttribute("aria-label", "Choose time zone");

    const menu = document.createElement("div");
    menu.className = "timezone-picker__menu";
    menu.hidden = true;
    const search = document.createElement("input");
    search.type = "search";
    search.className = "timezone-picker__search";
    search.placeholder = "Search city or GMT offset";
    search.setAttribute("aria-label", "Search time zones");
    search.setAttribute("autocomplete", "off");
    const list = document.createElement("div");
    list.id = menuId;
    list.className = "timezone-picker__options";
    list.setAttribute("role", "listbox");
    list.setAttribute("aria-label", "Time zones");
    menu.append(search, list);
    picker.append(trigger, menu);
    fieldLabel?.addEventListener("click", (event) => {
      event.preventDefault();
      trigger.focus();
    });

    let matches = options;
    let activeIndex = 0;
    const selectedLabel = () => select.selectedOptions[0]?.textContent || "Choose a time zone";
    const updateTrigger = () => { trigger.textContent = selectedLabel(); };
    const render = () => {
      const term = search.value.trim().toLocaleLowerCase();
      matches = options.filter((option) => option.textContent.toLocaleLowerCase().includes(term));
      activeIndex = Math.max(0, Math.min(activeIndex, matches.length - 1));
      list.replaceChildren();
      if (!matches.length) {
        const empty = document.createElement("p");
        empty.className = "timezone-picker__empty";
        empty.textContent = "No matching time zones";
        list.append(empty);
        return;
      }
      matches.forEach((option, index) => {
        const item = document.createElement("button");
        item.type = "button";
        item.className = "timezone-picker__option";
        item.textContent = option.textContent;
        item.dataset.value = option.value;
        item.setAttribute("role", "option");
        item.setAttribute("aria-selected", String(option.value === select.value));
        item.tabIndex = -1;
        if (index === activeIndex) item.classList.add("is-active");
        item.addEventListener("click", () => choose(option.value));
        list.append(item);
      });
    };
    const close = () => {
      menu.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
    };
    const open = () => {
      menu.hidden = false;
      trigger.setAttribute("aria-expanded", "true");
      search.value = "";
      activeIndex = Math.max(0, options.findIndex((option) => option.value === select.value));
      render();
      search.focus();
      list.querySelector(".is-active")?.scrollIntoView({ block: "nearest" });
    };
    const choose = (value) => {
      select.value = value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      updateTrigger();
      close();
      trigger.focus();
    };
    const move = (direction) => {
      if (!matches.length) return;
      activeIndex = (activeIndex + direction + matches.length) % matches.length;
      render();
      list.querySelector(".is-active")?.scrollIntoView({ block: "nearest" });
    };

    trigger.addEventListener("click", () => menu.hidden ? open() : close());
    trigger.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (menu.hidden) open();
        else move(event.key === "ArrowDown" ? 1 : -1);
      }
    });
    search.addEventListener("input", () => { activeIndex = 0; render(); });
    search.addEventListener("keydown", (event) => {
      if (event.key === "Escape") { close(); trigger.focus(); }
      else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        move(event.key === "ArrowDown" ? 1 : -1);
      } else if (event.key === "Enter" && matches.length) {
        event.preventDefault();
        choose(matches[activeIndex].value);
      }
    });
    document.addEventListener("pointerdown", (event) => {
      if (!picker.contains(event.target)) close();
    });
    picker.addEventListener("focusout", () => {
      window.setTimeout(() => { if (!picker.contains(document.activeElement)) close(); }, 0);
    });
    updateTrigger();
    picker.classList.add("timezone-picker--ready");
  }
}
