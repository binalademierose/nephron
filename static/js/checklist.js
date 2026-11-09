(function () {
  "use strict";

  const card = document.querySelector("[data-checklist]");
  if (!card || !window.fetch || !window.FormData) { return; }

  function message(done, total) {
    if (!total) { return "Nothing to do today."; }
    if (done === 0) { return "A fresh list for today. Tick each one as you do it."; }
    if (done === total) { return "All done for today. Well done!"; }
    if (done * 2 < total) { return "Good start. Keep going."; }
    return "More than halfway there.";
  }

  function setText(selector, value, root) {
    (root || document).querySelectorAll(selector).forEach(function (element) { element.textContent = String(value); });
  }

  function applyTotals(done, total) {
    const pct = total ? Math.round((100 * done) / total) : 0;
    const ring = card.querySelector("[data-checklist-ring]");
    if (ring) {
      ring.style.setProperty("--pct", pct);
      ring.setAttribute("aria-label", done + " of " + total + " tasks done today");
    }
    setText("[data-checklist-percent]", pct, card);
    setText("[data-checklist-done]", done, card);
    setText("[data-checklist-total]", total, card);
    setText("[data-checklist-status]", message(done, total), card);
    card.classList.toggle("is-complete", total > 0 && done === total);

    setText("[data-today-done]", done);
    setText("[data-today-total]", total);
    document.querySelectorAll("[data-today-progress]").forEach(function (bar) {
      bar.setAttribute("aria-valuenow", String(done));
      bar.setAttribute("aria-valuemax", String(total));
      const fill = bar.querySelector(".progress-bar-fill");
      if (fill) { fill.style.setProperty("--progress", pct + "%"); }
    });
  }

  function applyGroup(group) {
    const total = Number(group.dataset.total) || 0;
    const done = group.querySelectorAll(".checklist-item.is-done").length;
    setText("[data-group-done]", done, group);
    const count = group.querySelector(".checklist-group-count");
    if (count) { count.setAttribute("aria-label", done + " of " + total + " done"); }
    const bar = group.querySelector("[data-group-bar]");
    if (bar) { bar.style.setProperty("--progress", (total ? Math.round((100 * done) / total) : 0) + "%"); }
    group.classList.toggle("is-complete", total > 0 && done === total);
  }

  card.addEventListener("submit", function (event) {
    const form = event.target.closest("[data-checklist-form]");
    if (!form || form.dataset.sending === "1") { return; }
    event.preventDefault();
    const button = form.querySelector(".checklist-item");
    const state = form.querySelector('input[name="is_complete"]');
    form.dataset.sending = "1";
    button.setAttribute("aria-busy", "true");

    fetch(form.action, {
      method: "POST", body: new FormData(form), credentials: "same-origin",
      headers: { "X-Requested-With": "fetch", "Accept": "application/json" },
    })
      .then(function (response) {
        if (!response.ok) { throw new Error("HTTP " + response.status); }
        return response.json();
      })
      .then(function (data) {
        const isDone = Boolean(data.is_complete);
        button.classList.toggle("is-done", isDone);
        button.setAttribute("aria-pressed", String(isDone));
        state.value = isDone ? "0" : "1";
        applyGroup(form.closest("[data-checklist-group]"));
        applyTotals(Number(data.done) || 0, Number(data.total) || 0);
      })
      .catch(function () {
        form.submit();
      })
      .finally(function () {
        delete form.dataset.sending;
        button.removeAttribute("aria-busy");
      });
  });
}());
