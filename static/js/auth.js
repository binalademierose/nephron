(function () {
  "use strict";
  const details = document.querySelector("[data-professional-fields]");
  const roles = document.querySelectorAll("input[name='role']");
  if (!details || roles.length === 0) { return; }

  function update() {
    const chosen = document.querySelector("input[name='role']:checked");
    details.hidden = !(chosen && chosen.value === "professional");
  }
  roles.forEach(function (radio) { radio.addEventListener("change", update); });
  update();
})();
