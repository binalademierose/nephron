/*
  history.js - the "Compare selected" form on the history page.
  It only makes the form easier to use: two boxes at most, and the button waits for exactly two.
  The SERVER checks the choice again (exactly two different assessments of this person), so nothing depends on this file.
*/
(function () {
  "use strict";
  const form = document.querySelector("[data-compare-form]");
  if (!form) { return; }
  const boxes = Array.from(form.querySelectorAll("[data-pick]"));
  const button = form.querySelector("[data-compare-button]");
  const status = form.querySelector("[data-pick-status]");

  function update() {
    const chosen = boxes.filter(function (box) { return box.checked; }).length;
    boxes.forEach(function (box) { box.disabled = chosen >= 2 && !box.checked; });
    button.disabled = chosen !== 2;
    status.textContent = chosen === 2 ? "Two selected. Ready to compare."
      : chosen === 1 ? "Select one more assessment."
      : "Select two assessments on this page to compare them.";
  }

  boxes.forEach(function (box) { box.addEventListener("change", update); });
  update();
})();
