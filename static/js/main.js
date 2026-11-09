(function () {
  "use strict";

  const ICON_FOR_TOAST = { success: "check-circle", error: "alert-circle", info: "info", warning: "alert-triangle" };

  function makeIcon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "icon");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", "#i-" + name);
    svg.appendChild(use);
    return svg;
  }

  document.addEventListener("click", function (event) {
    const dismissButton = event.target.closest("[data-dismiss-alert]");
    if (!dismissButton) { return; }
    const alertBox = dismissButton.closest(".alert");
    if (!alertBox) { return; }
    alertBox.classList.add("is-hiding");
    window.setTimeout(function () { alertBox.remove(); }, 280);
  });

  function startLoading(button) {
    if (button.classList.contains("is-loading")) { return; }
    button.dataset.originalText = button.textContent;
    button.textContent = button.dataset.loadingText || "Working...";
    button.classList.add("is-loading");
    button.setAttribute("aria-busy", "true");
    button.disabled = true;
  }

  function stopLoading(button) {
    if (!button.classList.contains("is-loading")) { return; }
    button.textContent = button.dataset.originalText || button.textContent;
    button.classList.remove("is-loading");
    button.removeAttribute("aria-busy");
    button.disabled = false;
  }

  function flashSuccess(button, label) {
    const originalText = button.textContent;
    button.classList.add("is-success");
    button.textContent = label || "Done";
    window.setTimeout(function () {
      button.classList.remove("is-success");
      button.textContent = originalText;
    }, 1600);
  }

  function resetForm(form) {
    delete form.dataset.submitting;
    form.removeAttribute("aria-busy");
    form.querySelectorAll("[data-loading-text]").forEach(stopLoading);
    hideBusy();
  }

  document.addEventListener("submit", function (event) {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || event.defaultPrevented) { return; }
    if (form.dataset.submitting === "true") { event.preventDefault(); return; }
    const button = form.querySelector("[data-loading-text]");
    const wantsBusyScreen = form.dataset.busyTitle;
    if (!button && !wantsBusyScreen) { return; }
    form.dataset.submitting = "true";
    form.setAttribute("aria-busy", "true");
    window.setTimeout(function () {
      if (button) { startLoading(button); }
      if (wantsBusyScreen) { showBusy(form.dataset.busyTitle, form.dataset.busyMessage); }
    }, 0);
  });

  window.addEventListener("pageshow", function (event) {
    if (event.persisted) {
      document.querySelectorAll("form[data-submitting='true']").forEach(resetForm);
    }
  });

  function showBusy(title, message) {
    const overlay = document.getElementById("busy-overlay");
    if (!overlay) { return; }
    overlay.querySelector(".busy-title").textContent = title || "Working...";
    overlay.querySelector(".busy-message").textContent = message || "";
    overlay.classList.add("is-visible");
    overlay.querySelector(".busy-card").focus();
  }

  function hideBusy() {
    const overlay = document.getElementById("busy-overlay");
    if (overlay) { overlay.classList.remove("is-visible"); }
  }

  const TOAST_DURATION = { success: 5000, info: 5000, warning: 7000, error: 9000 };

  function swal() { return window.Swal && typeof window.Swal.fire === "function" ? window.Swal : null; }
  if (window.console) { console.info(swal() ? "Nephron: SweetAlert2 is loaded - pop-ups use it." : "Nephron: SweetAlert2 is not loaded - pop-ups use the built-in dialog."); }
  const SWAL_BASE = {
    buttonsStyling: false, reverseButtons: true,
    customClass: { popup: "swal-nephron", confirmButton: "button button-primary", cancelButton: "button button-secondary",
                   denyButton: "button button-secondary", actions: "swal-nephron-actions", input: "swal-nephron-input" }
  };
  const SWAL_ICON = { success: "success", error: "error", warning: "warning", info: "info" };
  function swalToast(type, text) {
    swal().fire({ toast: true, position: "top-end", icon: SWAL_ICON[type] || "info", title: text, showConfirmButton: false,
                  timer: TOAST_DURATION[type] || 5000, timerProgressBar: true, customClass: { popup: "swal-nephron-toast" },
                  didOpen: function (popup) { popup.addEventListener("mouseenter", window.Swal.stopTimer); popup.addEventListener("mouseleave", window.Swal.resumeTimer); } });
  }
  function escapeHtml(text) { const d = document.createElement("div"); d.textContent = text || ""; return d.innerHTML; }

  function mountToast(item, duration) {
    const region = document.getElementById("toast-region");
    if (!region) { return; }
    item.classList.remove("toast-static");
    item.style.setProperty("--toast-duration", duration + "ms");
    let timer = null;
    let remaining = duration;
    let startedAt = 0;
    function remove() {
      window.clearTimeout(timer);
      item.classList.add("is-hiding");
      window.setTimeout(function () { item.remove(); }, 280);
    }
    function start() { window.clearTimeout(timer); startedAt = Date.now(); timer = window.setTimeout(remove, remaining); }
    function pause() { window.clearTimeout(timer); remaining -= Date.now() - startedAt; }
    item.addEventListener("mouseenter", pause);
    item.addEventListener("mouseleave", start);
    item.addEventListener("focusin", pause);
    item.addEventListener("focusout", start);
    const close = item.querySelector("[data-toast-close]");
    if (close) { close.addEventListener("click", remove); }
    if (item.parentElement !== region) { region.appendChild(item); }
    start();
  }

  function toast(options) {
    const type = ICON_FOR_TOAST[options.type] ? options.type : "info";
    if (swal()) {
      try { swalToast(type, options.message || options.text || ""); return; } catch (problem) {  }
    }
    const item = document.createElement("div");
    item.className = "toast toast-" + type;
    item.setAttribute("role", type === "error" ? "alert" : "status");

    const chip = document.createElement("span");
    chip.className = "toast-icon";
    chip.setAttribute("aria-hidden", "true");
    chip.appendChild(makeIcon(ICON_FOR_TOAST[type]));
    item.appendChild(chip);

    const body = document.createElement("div");
    body.className = "toast-body";
    if (options.title) {
      const title = document.createElement("strong");
      title.className = "toast-title";
      title.textContent = options.title;
      body.appendChild(title);
    }
    body.appendChild(document.createTextNode(options.message || ""));
    item.appendChild(body);

    const close = document.createElement("button");
    close.type = "button";
    close.className = "toast-close";
    close.setAttribute("data-toast-close", "");
    close.setAttribute("aria-label", "Dismiss notification");
    close.appendChild(makeIcon("x"));
    item.appendChild(close);

    mountToast(item, options.duration || TOAST_DURATION[type]);
  }

  document.querySelectorAll(".flash-toasts .toast").forEach(function (item) {
    const body = item.querySelector(".toast-body");
    const text = body ? body.textContent.trim() : item.textContent.trim();
    try {
      if (!swal()) { throw new Error("SweetAlert2 is not installed"); }
      swal().fire(Object.assign({}, SWAL_BASE, { icon: "success", title: "Done", text: text, confirmButtonText: "OK",
                                                 timer: 3000, timerProgressBar: true }));
      item.remove();
    } catch (problem) {
      mountToast(item, TOAST_DURATION.success);
    }
  });
  if (swal()) {
    const failed = document.querySelector(".flash-region .alert-error");
    if (failed) {
      const title = failed.querySelector(".alert-title");
      const text = failed.querySelector(".alert-text");
      swal().fire(Object.assign({}, SWAL_BASE, { icon: "error", title: title ? title.textContent.trim() : "Something needs your attention",
        text: text ? text.textContent.replace(title ? title.textContent : "", "").trim() : failed.textContent.trim(), confirmButtonText: "OK" }));
    }
  }

  function closeDialog(dialog) {
    if (!dialog || !dialog.open || dialog.classList.contains("is-closing")) { return; }
    dialog.classList.add("is-closing");
    function finish() {
      dialog.classList.remove("is-closing");
      if (dialog.open) { dialog.close(); }
    }
    dialog.addEventListener("animationend", finish, { once: true });
    window.setTimeout(finish, 300);
  }

  document.addEventListener("click", function (event) {
    const opener = event.target.closest("[data-dialog-open]");
    if (opener) {
      const dialog = document.getElementById(opener.dataset.dialogOpen);
      if (dialog && typeof dialog.showModal === "function") { dialog.showModal(); }
      return;
    }
    const closer = event.target.closest("[data-dialog-close]");
    if (closer) { closeDialog(closer.closest("dialog")); return; }
    if (event.target instanceof HTMLDialogElement && event.target.open) {
      const box = event.target.getBoundingClientRect();
      const outside = event.clientX < box.left || event.clientX > box.right ||
                      event.clientY < box.top || event.clientY > box.bottom;
      if (outside) { closeDialog(event.target); }
    }
  });

  document.addEventListener("cancel", function (event) {
    if (event.target instanceof HTMLDialogElement) {
      event.preventDefault();
      closeDialog(event.target);
    }
  }, true);

  const shell = document.querySelector(".app-shell");
  if (shell) {
    const sidebar = shell.querySelector(".rail");
    const content = shell.querySelector(".app-main");
    const toggles = shell.querySelectorAll("[data-drawer-toggle]");
    const desktop = window.matchMedia("(min-width: 64rem)");

    function setDrawer(open) {
      shell.classList.toggle("is-drawer-open", open);
      document.documentElement.classList.toggle("has-drawer-open", open);
      toggles.forEach(function (button) { button.setAttribute("aria-expanded", String(open)); });
      if (open) {
        content.setAttribute("inert", "");
        const firstControl = sidebar.querySelector("a, button");
        if (firstControl) { firstControl.focus(); }
      } else {
        content.removeAttribute("inert");
        if (toggles[0]) { toggles[0].focus(); }
      }
    }

    toggles.forEach(function (button) {
      button.addEventListener("click", function () { setDrawer(!shell.classList.contains("is-drawer-open")); });
    });
    shell.querySelectorAll("[data-drawer-close]").forEach(function (element) {
      element.addEventListener("click", function () { setDrawer(false); });
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && shell.classList.contains("is-drawer-open")) { setDrawer(false); }
    });
    desktop.addEventListener("change", function (event) {
      if (event.matches && shell.classList.contains("is-drawer-open")) {
        shell.classList.remove("is-drawer-open");
        document.documentElement.classList.remove("has-drawer-open");
        content.removeAttribute("inert");
      }
    });
  }

  document.addEventListener("click", function (event) {
    const button = event.target.closest("[data-toggle-password]");
    if (!button) { return; }
    const input = document.getElementById(button.getAttribute("aria-controls"));
    if (!input) { return; }
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    button.setAttribute("aria-pressed", String(show));
    button.setAttribute("aria-label", show ? "Hide password" : "Show password");
    button.querySelector("use").setAttribute("href", show ? "#i-eye-off" : "#i-eye");
  });

  document.querySelectorAll(".chart").forEach(function (chart) {
    const tip = document.createElement("div");
    tip.className = "tooltip";
    tip.setAttribute("role", "tooltip");
    chart.appendChild(tip);

    function show(point) {
      tip.textContent = "";
      const title = document.createElement("strong");
      title.textContent = point.dataset.tooltipTitle;
      tip.appendChild(title);
      tip.appendChild(document.createTextNode(point.dataset.tooltipValue));
      const chartBox = chart.getBoundingClientRect();
      const pointBox = point.getBoundingClientRect();
      tip.style.left = (pointBox.left - chartBox.left + pointBox.width / 2) + "px";
      tip.style.top = (pointBox.top - chartBox.top) + "px";
      tip.classList.add("is-visible");
    }
    function hide() { tip.classList.remove("is-visible"); }

    chart.querySelectorAll("[data-tooltip-title]").forEach(function (point) {
      point.addEventListener("mouseenter", function () { show(point); });
      point.addEventListener("focus", function () { show(point); });
      point.addEventListener("mouseleave", hide);
      point.addEventListener("blur", hide);
    });
    chart.addEventListener("keydown", function (event) { if (event.key === "Escape") { hide(); } });
  });

  document.querySelectorAll("[data-greeting]").forEach(function (element) {
    const hour = new Date().getHours();
    element.textContent = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  });

  const prefersLessMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  document.querySelectorAll("[data-count-to]").forEach(function (element) {
    const target = Number(element.dataset.countTo);
    if (!target || prefersLessMotion) { return; }
    const startTime = performance.now();
    function step(now) {
      const progress = Math.min(1, (now - startTime) / 800);
      element.textContent = String(Math.round(target * (1 - Math.pow(1 - progress, 3))));
      if (progress < 1) { window.requestAnimationFrame(step); }
    }
    element.textContent = "0";
    window.requestAnimationFrame(step);
  });

  document.querySelectorAll("[data-user-menu]").forEach(function (menu) {
    const button = menu.querySelector(".user-menu-button");
    const list = menu.querySelector(".user-menu-list");
    if (!button || !list) { return; }

    function setOpen(open, returnFocus) {
      list.hidden = !open;
      button.setAttribute("aria-expanded", String(open));
      if (!open && returnFocus) { button.focus(); }
    }
    button.addEventListener("click", function () { setOpen(list.hidden, false); });
    document.addEventListener("click", function (event) {
      if (!list.hidden && !menu.contains(event.target)) { setOpen(false, false); }
    });
    menu.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !list.hidden) { setOpen(false, true); }
    });
  });

  document.querySelectorAll("[data-notif-menu]").forEach(function (menu) {
    const button = menu.querySelector(".notif-menu-button");
    const panel = menu.querySelector(".notif-panel");
    if (!button || !panel) { return; }

    function setOpen(open, returnFocus) {
      panel.hidden = !open;
      button.setAttribute("aria-expanded", String(open));
      if (!open && returnFocus) { button.focus(); }
    }
    button.addEventListener("click", function () { setOpen(panel.hidden, false); });
    document.addEventListener("click", function (event) {
      if (!panel.hidden && !menu.contains(event.target)) { setOpen(false, false); }
    });
    menu.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !panel.hidden) { setOpen(false, true); }
    });
  });

  document.querySelectorAll("[data-field-help]").forEach(function (button, index) {
    const popover = document.createElement("div");
    popover.className = "field-help-popover";
    popover.setAttribute("role", "tooltip");
    popover.id = "field-help-" + index;
    popover.textContent = button.dataset.fieldHelp;
    document.body.appendChild(popover);
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-describedby", popover.id);

    function place() {
      const box = button.getBoundingClientRect();
      const margin = 12;
      popover.style.left = "0px";
      const popoverWidth = popover.getBoundingClientRect().width;
      const maxLeft = window.innerWidth - popoverWidth - margin;
      const left = Math.max(margin, Math.min(box.left, maxLeft));
      popover.style.left = (left + window.scrollX) + "px";
      popover.style.top = (box.bottom + window.scrollY + 8) + "px";
    }
    function open() { place(); popover.classList.add("is-visible"); button.setAttribute("aria-expanded", "true"); }
    function close() { popover.classList.remove("is-visible"); button.setAttribute("aria-expanded", "false"); }

    button.addEventListener("click", function (event) {
      event.stopPropagation();
      const isOpen = popover.classList.contains("is-visible");
      document.querySelectorAll(".field-help-popover.is-visible").forEach(function (p) { p.classList.remove("is-visible"); });
      if (!isOpen) { open(); } else { close(); }
    });
    document.addEventListener("click", function (event) {
      if (!popover.contains(event.target) && event.target !== button) { close(); }
    });
    document.addEventListener("keydown", function (event) { if (event.key === "Escape") { close(); } });
    window.addEventListener("resize", function () { if (popover.classList.contains("is-visible")) { place(); } });
    window.addEventListener("scroll", function () { if (popover.classList.contains("is-visible")) { place(); } }, true);
  });

  const confirmDialog = document.getElementById("nephron-confirm");
  if (confirmDialog && typeof confirmDialog.showModal === "function") {
    const parts = {
      title: confirmDialog.querySelector("[data-confirm-title]"),
      lead: confirmDialog.querySelector("[data-confirm-lead]"),
      details: confirmDialog.querySelector("[data-confirm-details]"),
      check: confirmDialog.querySelector("[data-confirm-check]"),
      checkbox: confirmDialog.querySelector("[data-confirm-checkbox]"),
      checkText: confirmDialog.querySelector("[data-confirm-check-text]"),
      cancel: confirmDialog.querySelector("[data-confirm-cancel]"),
      accept: confirmDialog.querySelector("[data-confirm-accept]"),
      icons: confirmDialog.querySelectorAll("[data-confirm-icon]")
    };
    let pending = null;

    function fill(text, name) { return (text || "").replace(/\{name\}/g, name); }

    function openConfirm(form, opener) {
      const tone = ["consent", "danger"].indexOf(form.dataset.confirm) >= 0 ? form.dataset.confirm : "default";
      const name = form.dataset.confirmName || "";
      pending = { form: form, opener: opener };
      confirmDialog.className = "dialog confirm-dialog confirm-" + tone;
      parts.title.textContent = fill(form.dataset.confirmTitle, name) || "Are you sure?";
      parts.lead.textContent = fill(form.dataset.confirmMessage, name);
      parts.lead.hidden = !parts.lead.textContent;
      parts.icons.forEach(function (icon) { icon.hidden = icon.dataset.confirmIcon !== tone; });

      parts.details.textContent = "";
      const template = form.dataset.confirmTemplate && document.getElementById(form.dataset.confirmTemplate);
      if (template) {
        parts.details.appendChild(template.content.cloneNode(true));
        parts.details.querySelectorAll("[data-slot='name']").forEach(function (slot) { slot.textContent = name; });
      }

      const needsCheck = !!form.dataset.confirmCheck;
      parts.check.hidden = !needsCheck;
      parts.checkbox.checked = false;
      parts.checkText.textContent = fill(form.dataset.confirmCheck, name);
      parts.accept.disabled = needsCheck;
      parts.accept.textContent = form.dataset.confirmAccept || "Confirm";
      parts.cancel.textContent = form.dataset.confirmDismiss || "Go back";

      confirmDialog.showModal();
      (needsCheck ? parts.checkbox : tone === "danger" ? parts.cancel : parts.accept).focus();
    }

    parts.checkbox.addEventListener("change", function () { parts.accept.disabled = !parts.checkbox.checked; });

    parts.accept.addEventListener("click", function () {
      if (!pending || parts.accept.disabled) { return; }
      const form = pending.form;
      const consent = form.querySelector('input[type="hidden"][name="consent"]');
      if (consent && !parts.check.hidden) { consent.value = "1"; }
      form.dataset.confirmed = "1";
      pending = null;
      closeDialog(confirmDialog);
      busyFor(form);
      form.submit();
    });

    confirmDialog.addEventListener("close", function () {
      if (pending && pending.opener && document.contains(pending.opener)) { pending.opener.focus(); }
      pending = null;
    });

    function swalConfirm(form) {
      const tone = ["consent", "danger"].indexOf(form.dataset.confirm) >= 0 ? form.dataset.confirm : "default";
      const name = form.dataset.confirmName || "";
      const template = form.dataset.confirmTemplate && document.getElementById(form.dataset.confirmTemplate);
      const details = template ? template.innerHTML : "";
      const needsCheck = !!form.dataset.confirmCheck;
      const options = Object.assign({}, SWAL_BASE, {
        icon: tone === "danger" ? "warning" : tone === "consent" ? "info" : "question",
        title: fill(form.dataset.confirmTitle, name) || "Are you sure?",
        html: (form.dataset.confirmMessage ? "<p>" + escapeHtml(fill(form.dataset.confirmMessage, name)) + "</p>" : "") + details,
        showCancelButton: true,
        confirmButtonText: form.dataset.confirmAccept || "Confirm",
        cancelButtonText: form.dataset.confirmDismiss || "Go back",
        focusCancel: tone === "danger",
        customClass: Object.assign({}, SWAL_BASE.customClass, { confirmButton: tone === "danger" ? "button button-danger" : "button button-primary" })
      });
      if (needsCheck) {
        options.input = "checkbox";
        options.inputValue = 0;
        options.inputPlaceholder = fill(form.dataset.confirmCheck, name);
        options.inputValidator = function (checked) { return checked ? undefined : "Please tick the box to agree before continuing."; };
      }
      return swal().fire(options).then(function (result) {
        if (!result.isConfirmed) { return; }
        const consent = form.querySelector('input[type="hidden"][name="consent"]');
        if (consent && needsCheck) { consent.value = "1"; }
        form.dataset.confirmed = "1";
        busyFor(form);
        form.submit();
      });
    }

    function busyFor(form) {
      if (form.dataset.busyText && window.Nephron && window.Nephron.showBusy) { window.Nephron.showBusy(form.dataset.busyText, "This usually takes a few seconds."); }
    }
    window.NephronConfirm = function (form) { if (swal()) { swalConfirm(form); } else { openConfirm(form, null); } };

    document.addEventListener("submit", function (event) {
      const form = event.target;
      if (!(form instanceof HTMLFormElement) || !form.dataset.confirm || form.dataset.confirmed === "1") { return; }
      if (form.hasAttribute("data-confirm-after-check")) { return; }
      event.preventDefault();
      const opener = event.submitter;
      if (!swal()) { openConfirm(form, opener); return; }
      try {
        swalConfirm(form).catch(function () { openConfirm(form, opener); });
      } catch (problem) {
        openConfirm(form, opener);
      }
    }, true);
  }

  document.querySelectorAll("[data-shown-when]").forEach(function (section) {
    const parts = section.dataset.shownWhen.split("=");
    const form = section.closest("form");
    if (!form || parts.length !== 2) { return; }
    const name = parts[0], wanted = parts[1];
    const radios = form.querySelectorAll('input[type="radio"][name="' + name + '"]');
    const label = form.querySelector("[data-mode-label]");
    function sync() {
      const chosen = form.querySelector('input[type="radio"][name="' + name + '"]:checked');
      const value = chosen ? chosen.value : "";
      const show = value === wanted;
      section.hidden = !show;
      section.querySelectorAll("input, select, textarea").forEach(function (field) { field.disabled = !show; });
      const words = label && label.getAttribute("data-label-" + value);
      const text = label && label.querySelector("span");
      if (words && text) { text.textContent = words; }
    }
    radios.forEach(function (radio) { radio.addEventListener("change", sync); });
    sync();
  });

  document.addEventListener("click", function (event) {
    const button = event.target.closest("[data-copy-target]");
    if (!button) { return; }
    const source = document.getElementById(button.dataset.copyTarget);
    if (!source || !navigator.clipboard) { return; }
    navigator.clipboard.writeText(source.textContent.trim()).then(function () {
      if (window.Nephron && window.Nephron.toast) { window.Nephron.toast({ type: "success", message: "Copied." }); }
    });
  });

  document.querySelectorAll("form[data-live-filter]").forEach(function (form) {
    const targetId = form.dataset.liveFilter;
    let timer = null;
    let controller = null;
    function refresh() {
      const target = document.getElementById(targetId);
      if (!target) { return; }
      const params = new URLSearchParams(new FormData(form));
      Array.from(params.keys()).forEach(function (key) { if (!params.get(key)) { params.delete(key); } });
      const url = (form.getAttribute("action") || window.location.pathname) + (params.toString() ? "?" + params.toString() : "");
      if (controller) { controller.abort(); }
      controller = new AbortController();
      target.setAttribute("aria-busy", "true");
      fetch(url, { headers: { "X-Requested-With": "fetch" }, signal: controller.signal, credentials: "same-origin" })
        .then(function (response) { return response.ok ? response.text() : Promise.reject(response.status); })
        .then(function (html) {
          const fresh = new DOMParser().parseFromString(html, "text/html").getElementById(targetId);
          if (fresh) { target.replaceWith(fresh); }
          window.history.replaceState(null, "", url);
        })
        .catch(function () {  })
        .finally(function () { const t = document.getElementById(targetId); if (t) { t.removeAttribute("aria-busy"); } });
    }
    form.addEventListener("input", function (event) {
      if (event.target.matches("input[type=text], input[type=search]")) { clearTimeout(timer); timer = setTimeout(refresh, 250); }
    });
    form.addEventListener("change", function (event) {
      if (event.target.matches("select")) { refresh(); }
    });
  });

  document.querySelectorAll("select[data-gender-select]").forEach(function (select) {
    const followUp = select.form && select.form.querySelector("[data-sex-follow-up]");
    if (!followUp) { return; }
    function sync(fromUser) {
      const option = select.options[select.selectedIndex];
      const implied = option ? option.dataset.sex : "";
      const wasHidden = followUp.hidden;
      followUp.hidden = !select.value || !!implied;
      followUp.querySelectorAll("input[type=radio]").forEach(function (radio) {
        if (implied) { radio.checked = radio.value === implied; }
        else if (fromUser && wasHidden) { radio.checked = false; }
      });
    }
    select.addEventListener("change", function () { sync(true); });
    sync(false);
  });

  document.querySelectorAll("[data-location]").forEach(function (box) {
    const countrySelect = box.dataset.countryField ? document.getElementById(box.dataset.countryField) : null;
    const province = box.querySelector("[name=province_code]");
    const town = box.querySelector("[name=municipality_code]");
    const barangay = box.querySelector("[name=barangay_code]");
    const townStep = box.querySelector("[data-location-step=municipality]");
    const barangayStep = box.querySelector("[data-location-step=barangay]");
    const roleInputs = box.form ? Array.from(box.form.querySelectorAll("input[name=role]")) : [];

    function country() { return countrySelect ? countrySelect.value : box.dataset.country; }
    function role() { const chosen = roleInputs.find(function (r) { return r.checked; }); return chosen ? chosen.value : "general"; }
    function syncCountry() { box.hidden = country() !== "Philippines" || role() !== "general"; }
    function syncProvince() {
      const pangasinan = province.value === box.dataset.pangasinan;
      townStep.hidden = !pangasinan;
      barangayStep.hidden = !pangasinan;
    }
    function loadBarangays() {
      barangay.innerHTML = "";
      const first = document.createElement("option");
      first.value = "";
      if (!town.value) { first.textContent = "Choose the municipality first"; barangay.appendChild(first); barangay.disabled = true; return; }
      first.textContent = "Loading...";
      barangay.appendChild(first);
      barangay.disabled = true;
      fetch(box.dataset.barangaysUrl.replace("CODE", encodeURIComponent(town.value)), { credentials: "same-origin" })
        .then(function (response) { return response.ok ? response.json() : Promise.reject(response.status); })
        .then(function (data) {
          first.textContent = "Choose one";
          data.barangays.forEach(function (b) {
            const option = document.createElement("option");
            option.value = b.code;
            option.textContent = b.name;
            barangay.appendChild(option);
          });
          barangay.disabled = false;
        })
        .catch(function () { first.textContent = "Could not load the barangays - please try again"; });
    }
    if (countrySelect) { countrySelect.addEventListener("change", syncCountry); }
    roleInputs.forEach(function (r) { r.addEventListener("change", syncCountry); });
    province.addEventListener("change", syncProvince);
    town.addEventListener("change", loadBarangays);
    syncCountry();
    syncProvince();
  });

  window.Nephron = {
    startLoading: startLoading,
    stopLoading: stopLoading,
    flashSuccess: flashSuccess,
    showBusy: showBusy,
    hideBusy: hideBusy,
    toast: toast,
    closeDialog: closeDialog
  };
})();
