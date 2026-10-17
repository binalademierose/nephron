/*
  preview.js - makes the design previews (and the style guide) interactive.
  Development only: this file is loaded by the preview pages, never by real pages.
*/
(function () {
  "use strict";

  // Buttons with data-toast-message show a toast.
  document.addEventListener("click", function (event) {
    const trigger = event.target.closest("[data-toast-message]");
    if (!trigger) { return; }
    window.Nephron.toast({
      type: trigger.dataset.toastType || "info",
      title: trigger.dataset.toastTitle,
      message: trigger.dataset.toastMessage
    });
  });

  // Links to pages that are built in later phases explain themselves instead of pretending.
  document.addEventListener("click", function (event) {
    const link = event.target.closest("[data-preview-link]");
    if (!link) { return; }
    event.preventDefault();
    window.Nephron.toast({ type: "info", title: "Preview only", message: "This page is built in a later phase." });
  });

  // Buttons with data-busy-demo show the busy screen for a moment.
  document.addEventListener("click", function (event) {
    const trigger = event.target.closest("[data-busy-demo]");
    if (!trigger) { return; }
    window.Nephron.showBusy(trigger.dataset.busyTitle, trigger.dataset.busyMessage);
    window.setTimeout(window.Nephron.hideBusy, 2400);
  });

  // Loading and success button demos in the style guide.
  document.querySelectorAll("[data-demo-loading]").forEach(function (button) {
    button.addEventListener("click", function () {
      window.Nephron.startLoading(button);
      window.setTimeout(function () { window.Nephron.stopLoading(button); }, 1800);
    });
  });
  document.querySelectorAll("[data-demo-success]").forEach(function (button) {
    button.addEventListener("click", function () { window.Nephron.flashSuccess(button, "Saved"); });
  });

  // ----- Sign-in preview: show the validation states without sending anything -----
  const loginForm = document.querySelector("[data-preview-form]");
  if (loginForm) {
    const email = loginForm.querySelector("#email");
    const password = loginForm.querySelector("#password");

    function setState(input, valid, message) {
      const error = document.getElementById(input.id + "-error");
      input.classList.toggle("is-invalid", !valid);
      input.classList.toggle("is-valid", valid);
      input.setAttribute("aria-invalid", String(!valid));
      if (error) { error.hidden = valid; }
      if (message && error) { error.querySelector("span").textContent = message; }
    }

    loginForm.addEventListener("submit", function (event) {
      event.preventDefault();
      const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value.trim());
      const passwordOk = password.value.length > 0;
      setState(email, emailOk);
      setState(password, passwordOk);
      const button = loginForm.querySelector("[data-loading-text]");
      if (!emailOk || !passwordOk) {
        (emailOk ? password : email).focus();
        return;
      }
      // Valid: show the loading state, as a real sign-in would while it waits for the server.
      loginForm.dataset.submitting = "true";
      window.Nephron.startLoading(button);
      window.setTimeout(function () {
        window.Nephron.stopLoading(button);
        delete loginForm.dataset.submitting;
        window.Nephron.toast({ type: "info", title: "Preview only", message: "This is a design preview. The real page is at /login. Nothing was sent." });
      }, 1200);
    });
  }

  // ----- Guided screening preview: steps, progress and the review list -----
  const assessment = document.querySelector("[data-assessment]");
  if (assessment) {
    const steps = Array.from(assessment.querySelectorAll(".stepper-step"));
    const panels = Array.from(assessment.querySelectorAll(".step-panel"));
    const summary = assessment.querySelector("[data-step-summary]");
    const backButton = assessment.querySelector("[data-step-back]");
    const nextButton = assessment.querySelector("[data-step-next]");
    const form = assessment.querySelector("[data-assessment-form]");
    const reviewList = assessment.querySelector("[data-review-list]");
    const progressBar = assessment.querySelector("[data-step-progress]");
    const progressText = assessment.querySelector("[data-step-progress-text]");
    let current = 0;

    function buildReview() {
      reviewList.textContent = "";
      const seen = {};
      form.querySelectorAll("[data-review-label]").forEach(function (field) {
        const label = field.dataset.reviewLabel;
        let value = "";
        if (field.type === "radio") {
          if (seen[label]) { return; }
          seen[label] = true;
          const chosen = form.querySelector("input[name='" + field.name + "']:checked");
          value = chosen ? chosen.value : "";
        } else if (field.tagName === "SELECT") {
          value = field.value;
        } else {
          value = field.value ? field.value + " " + (field.dataset.reviewSuffix || "") : "";
        }
        const row = document.createElement("div");
        row.className = "summary-row";
        const dt = document.createElement("dt");
        dt.textContent = label;
        const dd = document.createElement("dd");
        dd.textContent = value.trim() || "Not provided";
        row.appendChild(dt);
        row.appendChild(dd);
        reviewList.appendChild(row);
      });
    }

    function render(direction, moveFocus) {
      assessment.dataset.direction = direction;
      steps.forEach(function (step, index) {
        step.classList.toggle("is-complete", index < current);
        step.classList.toggle("is-current", index === current);
        if (index === current) { step.setAttribute("aria-current", "step"); } else { step.removeAttribute("aria-current"); }
      });
      panels.forEach(function (panel, index) { panel.classList.toggle("is-active", index === current); });
      const percent = Math.round((current / steps.length) * 100);
      progressBar.setAttribute("aria-valuenow", String(percent));
      progressBar.querySelector(".progress-bar-fill").style.setProperty("--progress", percent + "%");
      progressText.textContent = percent + "% complete";
      summary.textContent = "Step " + (current + 1) + " of " + steps.length + ": " + panels[current].dataset.stepTitle;
      backButton.disabled = current === 0;
      const last = current === steps.length - 1;
      nextButton.textContent = last ? "Analyze assessment" : "Continue";
      if (last) { buildReview(); }
      // Move focus to the new step's heading (but not when the page first opens).
      if (moveFocus) {
        const heading = panels[current].querySelector("h2");
        if (heading) { heading.focus({ preventScroll: true }); }
      }
    }

    backButton.addEventListener("click", function () {
      if (current > 0) { current -= 1; render("back", true); }
    });
    nextButton.addEventListener("click", function () {
      if (current < steps.length - 1) { current += 1; render("forward", true); return; }
      nextButton.disabled = true;
      window.Nephron.showBusy("Analyzing your information...", "This usually takes a few seconds.");
      window.setTimeout(function () { window.location.href = assessment.dataset.resultUrl; }, 2200);
    });
    render("forward", false);
  }
})();
