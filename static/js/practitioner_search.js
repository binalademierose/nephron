/*
  practitioner_search.js - upgrades the "Find a professional" search box into a live, debounced search.

  The form works with no JavaScript at all (a plain GET, server-rendered results - see
  routes/authorization_routes.py and templates/authorizations/share.html). This file only replaces that round
  trip with a faster one once it can.
*/
(function () {
  "use strict";
  const form = document.querySelector("[data-practitioner-search]");
  if (!form) { return; }

  const resultsBox = document.querySelector("[data-practitioner-results]");
  const searchInput = form.querySelector("[data-practitioner-search-input]");
  const searchUrl = form.getAttribute("action") + "/search";
  const requestUrl = form.dataset.requestUrl;
  const csrfToken = form.querySelector("[name=csrf_token]").value;
  let requestToken = 0;

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text || "";
    return div.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");      // safe inside an attribute too
  }

  function renderResults(data, term) {
    if (!data.results.length) {
      resultsBox.innerHTML = term
        ? '<p class="empty-inline">No professional account matches "' + escapeHtml(term) + '".</p>'
        : "";
      return;
    }
    // The administrator's licence check, so a person can see whether a professional has been verified.
    function verifyBadge(status) {
      const text = status === "verified" ? "Licence verified" : status === "rejected" ? "Licence not verified" : "Licence not yet verified";
      return '<span class="badge verify-badge ' + (status === "verified" ? "risk-badge-low" : "badge-neutral") + '">' + text + "</span>";
    }
    const items = data.results.map(function (professional) {
      const sub = [professional.profession_title, professional.institution].filter(Boolean).join(" &middot; ");
      return '<li class="search-result"><div><strong>' + escapeHtml(professional.full_name) + "</strong>" +
        '<p class="text-muted">' + sub + "</p>" + verifyBadge(professional.verification_status) + "</div>" +
        '<form method="post" action="' + requestUrl + '" data-confirm="consent" data-confirm-template="share-consent-template"' +
        ' data-confirm-name="' + escapeHtml(professional.full_name) + '" data-confirm-title="Share your health information?"' +
        ' data-confirm-message="You are about to send {name} a request to view your assessment history."' +
        ' data-confirm-check="I understand what I am sharing with {name}, and I agree to share it."' +
        ' data-confirm-accept="Agree and send request">' +
        '<input type="hidden" name="csrf_token" value="' + escapeHtml(csrfToken) + '">' +
        '<input type="hidden" name="professional_user_id" value="' + professional.user_id + '">' +
        '<input type="hidden" name="consent" value="">' +
        '<button class="button button-secondary" type="submit">Request</button></form></li>';
    });
    resultsBox.innerHTML = '<ul class="search-results" role="list">' + items.join("") + "</ul>";
  }

  function search() {
    const term = searchInput.value.trim();
    const token = ++requestToken;
    if (!term) { resultsBox.innerHTML = ""; return; }
    resultsBox.setAttribute("aria-busy", "true");
    fetch(searchUrl + "?q=" + encodeURIComponent(term), { credentials: "same-origin" })
      .then(function (response) {
        if (token !== requestToken) { return null; }
        if (!response.ok) { throw new Error("search failed"); }
        return response.json();
      })
      .then(function (data) {
        if (!data || token !== requestToken) { return; }
        renderResults(data, term);
        resultsBox.removeAttribute("aria-busy");
        history.replaceState(null, "", form.getAttribute("action") + "?q=" + encodeURIComponent(term));
      })
      .catch(function () {
        if (token !== requestToken) { return; }
        resultsBox.innerHTML = '<p class="empty-inline">Search is temporarily unavailable. Please try again shortly.</p>';
        resultsBox.removeAttribute("aria-busy");
      });
  }

  let debounceTimer = null;
  form.addEventListener("submit", function (event) { event.preventDefault(); search(); });
  searchInput.addEventListener("input", function () {
    if (debounceTimer) { clearTimeout(debounceTimer); }
    debounceTimer = setTimeout(search, 400);
  });

  // A "Request" button rendered by search() is a brand-new form the page did not have at load time, so its
  // click has to be caught here (event delegation), not on the form itself.
  resultsBox.addEventListener("submit", function (event) {
    const submitForm = event.target;
    if (submitForm.tagName !== "FORM") { return; }
    // A brand-new form the page did not have at load time - the browser's own plain submit works perfectly well
    // here (a real navigation, the server's own success message included), so this is left alone rather than
    // reimplemented over fetch: the only thing this file needs to own is the search box itself.
  });
})();
