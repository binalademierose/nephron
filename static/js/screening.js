/*
  screening.js - the guided screening form: steps, progress, friendly checks, the BMI readout and the review list.

  The SERVER checks every answer again (services/screening_contract.py), so this file only makes the form pleasant:
  it never decides anything. Without it the form could not be used, which the page says.
*/
(function () {
  "use strict";
  const root = document.querySelector("[data-assessment]");
  if (!root) { return; }

  const form = root.querySelector("[data-assessment-form]");
  const steps = Array.from(root.querySelectorAll(".stepper-step"));
  const panels = Array.from(root.querySelectorAll(".step-panel"));
  const summary = root.querySelector("[data-step-summary]");
  const back = root.querySelector("[data-step-back]");
  const next = root.querySelector("[data-step-next]");
  const submit = root.querySelector("[data-step-submit]");
  const reviewList = root.querySelector("[data-review-list]");
  const progressBar = root.querySelector("[data-step-progress]");
  const progressText = root.querySelector("[data-step-progress-text]");
  const draftStatus = root.querySelector("[data-draft-status]");
  const draftSaveUrl = root.dataset.draftSaveUrl;
  let current = 0;

  // ---------- small helpers ----------
  const WHOLE = /^\d{1,4}$/;
  const DECIMAL = /^\d{1,4}(\.\d{1,3})?$/;
  function fmt(number) { return String(Number(number)); }

  function showError(anchor, id, message) {
    let node = document.getElementById(id);
    if (!message) { if (node) { node.remove(); } return; }
    if (!node) {
      node = document.createElement("p");
      node.className = "form-error";
      node.id = id;
      anchor.appendChild(node);
    }
    node.textContent = message;
  }

  function markInvalid(controls, invalid) {
    controls.forEach(function (control) {
      if (invalid) { control.setAttribute("aria-invalid", "true"); control.classList.add("is-invalid"); }
      else { control.removeAttribute("aria-invalid"); control.classList.remove("is-invalid"); }
    });
  }

  function checkNumber(text, min, max, whole) {
    if (!text) { return "Enter a number."; }
    if (!(whole ? WHOLE : DECIMAL).test(text)) { return whole ? "Enter a whole number, for example 48." : "Use digits and a dot only, for example 1.8."; }
    const value = Number(text);
    if (value < min || value > max) { return "Enter a value from " + fmt(min) + " to " + fmt(max) + "."; }
    return "";
  }

  // ---------- one question ----------
  function checkQuestion(group) {
    const kind = group.dataset.kind;
    const name = group.dataset.name;
    let message = "";
    let controls = [];
    if (kind === "choice" || kind === "yesno") {
      const radios = Array.from(group.querySelectorAll("input[type=radio]"));
      if (radios.length) {
        controls = radios;
        if (!radios.some(function (r) { return r.checked; })) { message = kind === "yesno" ? "Choose Yes or No." : "Choose one answer."; }
      } else {
        const select = group.querySelector("select");
        controls = [select];
        if (!select.value) { message = "Choose one answer."; }
      }
      showError(group.querySelector("fieldset, .form-group"), name + "-error", message);
    } else if (kind === "number") {
      const input = group.querySelector("input[type=text]");
      controls = [input];
      message = checkNumber(input.value.trim(), Number(group.dataset.min), Number(group.dataset.max), group.dataset.integer === "true");
      showError(input.closest(".form-group"), name + "-error", message);
    } else if (kind === "bmi") {
      const block = group.querySelector("[data-bmi]");
      const inputs = Array.from(block.querySelectorAll("[data-bmi-input]"));
      controls = inputs;
      inputs.forEach(function (input) {
        const problem = checkNumber(input.value.trim(), Number(input.dataset.min), Number(input.dataset.max), false);
        showError(input.closest("div").parentElement, input.dataset.bmiInput + "-error", problem);
        markInvalid([input], !!problem);
        if (problem && !message) { message = problem; }
      });
      if (!message) {
        const bmi = currentBmi(block);
        if (bmi < Number(block.dataset.bmiMin) || bmi > Number(block.dataset.bmiMax)) { message = block.dataset.bmiNote; }
      }
      showError(block, name + "-error", message && !inputs.some(function (i) { return i.classList.contains("is-invalid"); }) ? message : "");
      return { ok: !message, first: inputs.find(function (i) { return i.classList.contains("is-invalid"); }) || inputs[0] };
    }
    markInvalid(controls, !!message);
    return { ok: !message, first: controls[0] };
  }

  function checkPanel(panel) {
    let firstBad = null;
    panel.querySelectorAll("[data-question]").forEach(function (group) {
      if (group.hidden) { return; }                 // e.g. "Sex assigned at birth" when the gender answer already tells
      const result = checkQuestion(group);
      if (!result.ok && !firstBad) { firstBad = result.first; }
    });
    return firstBad;
  }

  // ---------- Activity level, worked out from exercise hours ----------
  // The server works it out again from the hours (services/screening_contract.py); this only shows it as they type.
  root.querySelectorAll("[data-derived-from]").forEach(function (group) {
    const source = form.querySelector("[name='" + group.dataset.derivedFrom + "']");
    const readout = group.querySelector("[data-derived-readout]");
    const hidden = group.querySelector("[data-derived-value]");
    let bands = [];
    try { bands = JSON.parse(group.dataset.bands || "[]"); } catch (error) { bands = []; }
    if (!source) { return; }
    function update() {
      const text = source.value.trim();
      const hours = DECIMAL.test(text) ? Number(text) : NaN;
      let level = "";
      if (Number.isFinite(hours)) {
        const band = bands.find(function (b) { return b.below === null || hours < b.below; });
        level = band ? band.value : "";
      }
      hidden.value = level;
      readout.value = level;
    }
    source.addEventListener("input", update);
    update();
  });

  // ---------- Gender -> Sex assigned at birth ----------
  // A gender answer that tells the sex (Gay man -> Male) fills in the hidden "Sex assigned at birth" itself; one that
  // does not (Non-binary, Prefer not to say...) shows that question. The server works it out again regardless.
  root.querySelectorAll("[data-gender-question]").forEach(function (group) {
    const followUp = root.querySelector("[data-sex-follow-up]");
    if (!followUp) { return; }
    const sexRadios = Array.from(followUp.querySelectorAll("input[type=radio]"));
    function sync(fromUser) {
      const chosen = group.querySelector("input[type=radio]:checked");
      const implied = chosen ? chosen.dataset.sex : "";
      const wasHidden = followUp.hidden;
      followUp.hidden = !chosen || !!implied;
      sexRadios.forEach(function (radio) {
        if (implied) { radio.checked = radio.value === implied; }
        else if (fromUser && wasHidden) { radio.checked = false; }     // never keep a sex the page guessed
      });
      if (fromUser && chosen && !implied && wasHidden) { showError(followUp.querySelector("fieldset"), followUp.dataset.name + "-error", ""); }
    }
    group.querySelectorAll("input[type=radio]").forEach(function (radio) { radio.addEventListener("change", function () { sync(true); }); });
    sync(false);
  });

  // ---------- BMI ----------
  function currentBmi(block) {
    const height = Number((block.querySelector("[data-bmi-input=height_cm]").value || "").trim());
    const weight = Number((block.querySelector("[data-bmi-input=weight_kg]").value || "").trim());
    return height > 0 && weight > 0 ? Math.round((weight / Math.pow(height / 100, 2)) * 10) / 10 : NaN;
  }

  function updateBmi(block) {
    const readout = block.querySelector("[data-bmi-readout]");
    const bmi = currentBmi(block);
    readout.textContent = Number.isFinite(bmi) ? "Your body mass index (BMI) is " + bmi.toFixed(1) + "." : "";
  }

  root.querySelectorAll("[data-bmi]").forEach(function (block) {
    block.querySelectorAll("[data-bmi-input]").forEach(function (input) { input.addEventListener("input", function () { updateBmi(block); }); });
    updateBmi(block);
  });

  // ---------- review ----------
  function buildReview() {
    // One group per step (About you, Health history, ...), each with its own "Edit" button that jumps straight
    // back to that step - easier to check than one long list, and nothing has to be retyped to change an answer.
    reviewList.textContent = "";
    const seen = {};
    panels.forEach(function (panel, panelIndex) {
      if (panel.contains(reviewList)) { return; }
      const rows = [];
      panel.querySelectorAll("[data-review-label]").forEach(function (field) {
        const label = field.dataset.reviewLabel;
        if (field.closest("[data-question][hidden]")) { return; }
        if (seen[label]) { return; }
        seen[label] = true;
        let text = "";
        if (field.type === "radio") {
          const chosen = form.querySelector("input[name='" + field.name + "']:checked");
          text = chosen ? chosen.dataset.reviewText : "";
        } else if (field.tagName === "SELECT") {
          text = field.value ? field.options[field.selectedIndex].text : "";
        } else {
          text = field.value.trim() ? field.value.trim() + " " + (field.dataset.reviewSuffix || "") : "";
        }
        rows.push([label, text]);
      });
      panel.querySelectorAll("[data-bmi]").forEach(function (block) {
        const bmi = currentBmi(block);
        rows.push(["Body mass index", Number.isFinite(bmi) ? bmi.toFixed(1) + " (from your height and weight)" : ""]);
      });
      if (!rows.length) { return; }
      appendGroup(panel.dataset.stepTitle || "", panelIndex, rows);
    });
  }

  function appendGroup(title, panelIndex, rows) {
    const group = document.createElement("div");
    group.className = "review-group";
    const head = document.createElement("div");
    head.className = "review-group-head";
    const heading = document.createElement("h4");
    heading.textContent = title;
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "button button-secondary button-sm";
    edit.textContent = "Edit";
    edit.setAttribute("aria-label", "Edit " + title);
    edit.addEventListener("click", function () { current = panelIndex; render("back", true); saveDraft(); });
    head.appendChild(heading);
    head.appendChild(edit);
    group.appendChild(head);
    const list = document.createElement("div");
    list.className = "review-grid";
    rows.forEach(function (pair) {
      const row = document.createElement("div");
      row.className = "summary-row";
      const dt = document.createElement("dt");
      dt.textContent = pair[0];
      const dd = document.createElement("dd");
      dd.textContent = pair[1].trim() || "Not answered";
      if (!pair[1].trim()) { dd.classList.add("is-missing"); }
      row.appendChild(dt);
      row.appendChild(dd);
      list.appendChild(row);
    });
    group.appendChild(list);
    reviewList.appendChild(group);
  }

  // ---------- steps ----------
  function render(direction, moveFocus) {
    root.dataset.direction = direction;
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
    back.disabled = current === 0;
    const last = current === steps.length - 1;
    next.hidden = last;
    submit.hidden = !last;
    if (last) { buildReview(); }
    if (moveFocus) {
      const heading = panels[current].querySelector("h2");
      if (heading) { heading.focus({ preventScroll: false }); }
    }
  }

  back.addEventListener("click", function () {
    if (current > 0) { current -= 1; render("back", true); saveDraft(); }
  });

  next.addEventListener("click", function () {
    const bad = checkPanel(panels[current]);
    if (bad) { bad.focus(); return; }
    if (current < steps.length - 1) { current += 1; render("forward", true); saveDraft(); }
  });

  // ---------- autosave the draft, so a refresh or a closed tab never loses progress ----------
  // Never on every keystroke (see routes/screening_routes.py's own note on this): a short pause after the person
  // stops typing, or the moment they move to another step, whichever comes first.
  let saveTimer = null;
  function saveDraft() {
    if (!draftSaveUrl) { return; }
    if (draftStatus) { draftStatus.textContent = "Saving..."; }
    const data = new FormData(form);
    data.set("current_step", panels[current].dataset.stepKey);
    fetch(draftSaveUrl, { method: "POST", body: data, credentials: "same-origin" })
      .then(function (response) { if (draftStatus) { draftStatus.textContent = response.ok ? "Saved" : ""; } })
      .catch(function () { if (draftStatus) { draftStatus.textContent = ""; } });
  }
  function scheduleSaveDraft() {
    if (draftStatus) { draftStatus.textContent = ""; }
    if (saveTimer) { clearTimeout(saveTimer); }
    saveTimer = setTimeout(saveDraft, 1500);
  }
  if (draftSaveUrl) {
    form.addEventListener("input", scheduleSaveDraft);
    form.addEventListener("change", scheduleSaveDraft);
  }

  // Pressing Enter in a field goes to the next step; it must not send an unfinished form.
  form.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && event.target.tagName === "INPUT" && event.target.type !== "submit" && event.target.type !== "radio") {
      event.preventDefault();
      if (!next.hidden) { next.click(); }
    }
  });

  form.addEventListener("submit", function (event) {
    // Check every step once more. If something is wrong, go to that step instead of sending.
    for (let index = 0; index < panels.length - 1; index += 1) {
      const bad = checkPanel(panels[index]);
      if (bad) {
        event.preventDefault();
        current = index;
        render("back", false);
        bad.focus();
        return;
      }
    }
    // Every step passed: ask the calm "are your answers true?" confirmation before anything is analysed.
    if (form.dataset.confirm && form.dataset.confirmed !== "1" && window.NephronConfirm) {
      event.preventDefault();
      window.NephronConfirm(form);
      return;
    }
    if (window.Nephron && window.Nephron.showBusy) { window.Nephron.showBusy("Analysing your answers...", "This usually takes a few seconds."); }
  });

  // A page that came back from the server with errors opens on the first step that has one.
  const firstError = parseInt(root.dataset.firstErrorStep, 10);
  if (firstError >= 0) { current = firstError; }
  render("forward", false);
  if (firstError >= 0) {
    const bad = panels[current].querySelector("[aria-invalid=true]");
    if (bad) { bad.focus(); }
  }
})();
