/*
  motion.js - Nephron's animation system (the JavaScript half; static/css/motion.css has the rules and the
  reasoning). Small on purpose: it only ever ADDS a class (is-in) or moves a number, so a page is finished and
  readable even if this file never loads.

    [data-animate]      reveal once when scrolled into view (an element already scrolled past is shown at once)
    [data-stagger]      children get --d = 0,1,2...
    [data-walk]         the scroll-driven "How it works" walkthrough (sticky scene follows the active step)
    [data-parallax]     tiny pointer-driven depth on the home hero (mouse only)

  People who ask for less motion get finished states straight away and no parallax.
*/
(function () {
  "use strict";
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const hasObserver = "IntersectionObserver" in window;

  // ----- reveal on scroll -----
  document.querySelectorAll("[data-stagger]").forEach(function (parent) {
    Array.prototype.forEach.call(parent.children, function (child, index) { child.style.setProperty("--d", index); });
  });
  const reveal = document.querySelectorAll("[data-animate]");
  function show(el) { el.classList.add("is-in"); }
  if (reduce || !hasObserver) {
    reveal.forEach(show);
  } else {
    const seen = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) { show(entry.target); seen.unobserve(entry.target); }
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -6% 0px" });
    reveal.forEach(function (el) {
      if (el.getBoundingClientRect().bottom < 0) { show(el); } else { seen.observe(el); }   // already scrolled past
    });
  }

  // ----- the walkthrough on How it works -----
  const walk = document.querySelector("[data-walk]");
  if (walk) {
    const steps = Array.prototype.slice.call(walk.querySelectorAll("[data-walk-step]"));
    const scenes = Array.prototype.slice.call(walk.querySelectorAll("[data-walk-scene]"));
    const dots = Array.prototype.slice.call(walk.querySelectorAll("[data-walk-dot]"));
    const counter = walk.querySelector("[data-walk-counter]");
    const title = walk.querySelector("[data-walk-title]");
    let active = -1;

    function setActive(index) {
      if (index === active) { return; }
      active = index;
      steps.forEach(function (step, i) {
        step.classList.toggle("is-active", i === index);
        step.classList.toggle("is-done", i < index);
        if (i === index) { step.setAttribute("aria-current", "step"); } else { step.removeAttribute("aria-current"); }
      });
      scenes.forEach(function (scene, i) {
        const on = i === index;
        scene.classList.toggle("is-active", on);
        scene.classList.toggle("is-in", on);         // replays that scene's own animation each time it returns
      });
      dots.forEach(function (dot, i) { dot.classList.toggle("is-active", i === index); });
      if (counter) { counter.textContent = "Step " + (index + 1) + " of " + steps.length; }
      if (title) { title.textContent = steps[index].dataset.stepTitle || ""; }
    }

    let ticking = false;
    function update() {
      ticking = false;
      const middle = window.innerHeight * 0.45;
      let best = 0;
      let bestDistance = Infinity;
      steps.forEach(function (step, i) {
        const box = step.getBoundingClientRect();
        const distance = Math.abs(box.top + box.height / 2 - middle);
        if (distance < bestDistance) { bestDistance = distance; best = i; }
      });
      setActive(best);
      const area = walk.getBoundingClientRect();
      walk.style.setProperty("--walk-progress", Math.max(0, Math.min(1, (middle - area.top) / area.height)).toFixed(3));
    }
    function request() { if (!ticking) { ticking = true; window.requestAnimationFrame(update); } }
    window.addEventListener("scroll", request, { passive: true });
    window.addEventListener("resize", request);
    update();
  }

  // ----- a little depth on the home hero (mouse only, never for people who want less motion) -----
  const parallax = document.querySelector("[data-parallax]");
  if (parallax && !reduce && window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
    let frame = null;
    parallax.addEventListener("pointermove", function (event) {
      const box = parallax.getBoundingClientRect();
      const x = ((event.clientX - box.left) / box.width - 0.5) * 2;
      const y = ((event.clientY - box.top) / box.height - 0.5) * 2;
      if (frame) { window.cancelAnimationFrame(frame); }
      frame = window.requestAnimationFrame(function () { parallax.style.setProperty("--px", x.toFixed(3)); parallax.style.setProperty("--py", y.toFixed(3)); });
    });
    parallax.addEventListener("pointerleave", function () { parallax.style.setProperty("--px", 0); parallax.style.setProperty("--py", 0); });
  }

  window.Nephron = window.Nephron || {};
  window.Nephron.motion = { reveal: show };
})();
