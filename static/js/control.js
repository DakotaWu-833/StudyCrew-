const liveRegion = document.querySelector("[data-control-live]");

function csrfToken(form) {
  return form.querySelector("[name=csrfmiddlewaretoken]")?.value ?? "";
}

function announce(message, isError = false) {
  if (!liveRegion) return;
  liveRegion.textContent = message;
  liveRegion.hidden = false;
  liveRegion.classList.toggle("control-live--error", isError);
  liveRegion.setAttribute("role", isError ? "alert" : "status");
}

function addAuditEvent(event) {
  if (!event) return;
  const list = document.querySelector("[data-control-audit]");
  if (!list || list.querySelector(`[data-audit-id="${event.id}"]`)) return;
  list.querySelector("[data-audit-empty]")?.remove();
  const item = document.createElement("li");
  item.dataset.auditId = event.id;
  const action = document.createElement("span");
  action.textContent = event.action;
  const detail = document.createElement("small");
  const occurredAt = new Date(event.occurred_at);
  const readableTime = Number.isNaN(occurredAt.getTime())
    ? event.occurred_at
    : occurredAt.toLocaleString("en-AU", { dateStyle: "medium", timeStyle: "short" });
  detail.textContent = `${event.actor} · ${readableTime}`;
  item.append(action, detail);
  list.prepend(item);
  [...list.children].slice(20).forEach((row) => row.remove());
}

function updateReportQueue(payload) {
  if (!payload.report_id) return;
  document.querySelector(`[data-report-id="${payload.report_id}"]`)?.remove();
  const count = document.querySelector("[data-pending-report-count]");
  if (count && Number.isInteger(payload.pending_reports)) count.textContent = String(payload.pending_reports);
  const list = document.querySelector("[data-report-list]");
  if (list && !list.querySelector("[data-report-id]") && !list.querySelector(".empty-state")) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    const heading = document.createElement("h3");
    heading.textContent = "No pending reports";
    const message = document.createElement("p");
    message.textContent = "The moderation queue is clear.";
    empty.append(heading, message);
    list.append(empty);
  }
}

function updateControlActionCount(payload) {
  const count = document.querySelector("[data-control-action-count]");
  if (count && Number.isInteger(payload.control_actions)) count.textContent = String(payload.control_actions);
}

function requestConfirmation(form, submitter) {
  form.querySelector(".control-confirm")?.remove();
  const confirmation = document.createElement("div");
  confirmation.className = "control-confirm";
  confirmation.setAttribute("role", "group");
  confirmation.setAttribute("aria-label", submitter.dataset.confirm);
  const message = document.createElement("p");
  message.textContent = submitter.dataset.confirm;
  const proceed = document.createElement("button");
  proceed.type = "button";
  proceed.className = "button button--small button--danger";
  proceed.textContent = "Confirm";
  const back = document.createElement("button");
  back.type = "button";
  back.className = "button button--small button--quiet";
  back.textContent = "Go back";
  proceed.addEventListener("click", () => {
    confirmation.remove();
    void submitControlForm(form, submitter);
  });
  back.addEventListener("click", () => confirmation.remove());
  confirmation.append(message, proceed, back);
  form.append(confirmation);
  proceed.focus();
}

async function submitControlForm(form, submitter) {
    const body = new FormData(form);
    if (submitter?.name) body.set(submitter.name, submitter.value);
    if (submitter?.dataset.extraName) body.set(submitter.dataset.extraName, submitter.dataset.extraValue);
    const buttons = form.querySelectorAll("button");
    buttons.forEach((button) => { button.disabled = true; });
    announce("Working…");
    try {
      const response = await fetch(form.action, {
        method: "POST",
        headers: { Accept: "application/json", "X-CSRFToken": csrfToken(form) },
        body,
        credentials: "same-origin",
      });
      let payload;
      try {
        payload = await response.json();
      } catch {
        throw new Error("The server returned an unexpected response. Refresh the page before trying again.");
      }
      if (!response.ok) throw new Error(payload.error?.message ?? "The action could not be completed.");
      updateReportQueue(payload);
      updateControlActionCount(payload);
      if (payload.user_id) {
        const row = form.closest("[data-user-id]");
        const state = row?.querySelector("[data-user-state]");
        if (state) {
          state.textContent = payload.is_active ? "Active" : "Suspended";
          state.classList.toggle("status-pill--active", payload.is_active);
        }
        const activeInput = form.querySelector("[name=active]");
        if (activeInput) activeInput.value = payload.is_active ? "false" : "true";
        if (submitter) {
          submitter.textContent = payload.is_active ? "Suspend" : "Restore";
          submitter.classList.toggle("button--danger", payload.is_active);
          submitter.classList.toggle("button--quiet", !payload.is_active);
          const name = row?.dataset.userName || "this user";
          if (payload.is_active) submitter.dataset.confirm = `Suspend ${name}? Their current sessions will be ended.`;
          else delete submitter.dataset.confirm;
        }
      }
      addAuditEvent(payload.audit_event);
      announce(payload.message);
    } catch (error) {
      announce(error instanceof Error ? error.message : "The action could not be completed.", true);
    } finally {
      buttons.forEach((button) => { button.disabled = false; });
    }
}

document.querySelectorAll("[data-ajax-control]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const submitter = event.submitter;
    if (!submitter) return;
    if (submitter.dataset.confirm) {
      requestConfirmation(form, submitter);
      return;
    }
    void submitControlForm(form, submitter);
  });
});
