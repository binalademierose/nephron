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
