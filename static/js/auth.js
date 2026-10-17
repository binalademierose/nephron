/*
  auth.js - the register page: show the professional details only while "Healthcare professional" is chosen.
  Without JavaScript the details simply stay visible, so nothing is lost.
*/
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
