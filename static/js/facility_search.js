/*
  facility_search.js - upgrades the PhilHealth centers search form into a live, debounced search.

  The form works with no JavaScript at all (a plain GET, server-rendered results - see routes/resource_routes.py
  and templates/resources/philhealth_centers.html). This file only replaces that round trip with a faster one
  once it can: the server is asked again, the same way, just without a full page reload.
*/
(function () {
  "use strict";
  const form = document.querySelector("[data-facility-search]");
  if (!form) { return; }

  const resultsBox = document.querySelector("[data-facility-results]");
  const countBox = document.querySelector("[data-facility-count]");
  const searchInput = form.querySelector("[data-facility-search-input]");
  const searchUrl = form.getAttribute("action") + "/search";
  let requestToken = 0;

  function titleCase(text) {
    return (text || "").toLowerCase().replace(/\b\w/g, function (ch) { return ch.toUpperCase(); });
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text || "";
    return div.innerHTML;
  }

  function renderResults(data) {
    if (!data.results.length) {
      const hasFilter = new FormData(form).get("q") || new FormData(form).get("region") || new FormData(form).get("sector");
      resultsBox.innerHTML = '<p class="empty-inline">' + (hasFilter
        ? "No accredited centers match your search."
        : "No accredited centers to show.") + "</p>";
      return;
    }
    const items = data.results.map(function (center) {
      const sectorClass = center.sector === "Private" ? "badge-info" : "risk-badge-low";
      const tel = center.tel ? '<span class="facility-tel">' + escapeHtml(center.tel) + "</span>" : "";
      const email = center.email ? '<a href="mailto:' + escapeHtml(center.email) + '">' + escapeHtml(center.email) + "</a>" : "";
      return '<li class="facility-item">' +
        '<div class="facility-item-header"><h3 class="facility-name">' + escapeHtml(titleCase(center.name)) + '</h3>' +
        '<span class="badge ' + sectorClass + '">' + escapeHtml(center.sector) + "</span></div>" +
        '<p class="facility-address">' + escapeHtml(titleCase(center.street)) + (center.street ? ", " : "") +
        escapeHtml(titleCase(center.municipality)) + ", " + escapeHtml(titleCase(center.province_or_city)) + "</p>" +
        '<p class="facility-region text-muted">' + escapeHtml(titleCase(center.region)) + "</p>" +
        '<div class="facility-contact">' + tel + email + "</div></li>";
    });
    resultsBox.innerHTML = '<ul class="facility-list" role="list">' + items.join("") + "</ul>";
  }

  function search() {
    const token = ++requestToken;
    const params = new URLSearchParams(new FormData(form));
    resultsBox.setAttribute("aria-busy", "true");
    if (countBox) { countBox.textContent = "Searching..."; }
    fetch(searchUrl + "?" + params.toString(), { credentials: "same-origin" })
      .then(function (response) {
        if (token !== requestToken) { return null; }         // a newer search already started; drop this answer
        if (!response.ok) { throw new Error("search failed"); }
        return response.json();
      })
      .then(function (data) {
        if (!data || token !== requestToken) { return; }
        renderResults(data);
        if (countBox) { countBox.textContent = data.total ? "Showing " + data.shown + " of " + data.total : ""; }
        resultsBox.removeAttribute("aria-busy");
        history.replaceState(null, "", form.getAttribute("action") + "?" + params.toString());
      })
      .catch(function () {
        if (token !== requestToken) { return; }
        resultsBox.innerHTML = '<p class="empty-inline">Search is temporarily unavailable. Please try again shortly.</p>';
        if (countBox) { countBox.textContent = ""; }
        resultsBox.removeAttribute("aria-busy");
      });
  }

  let debounceTimer = null;
  form.addEventListener("submit", function (event) { event.preventDefault(); search(); });
  if (searchInput) {
    searchInput.addEventListener("input", function () {
      if (debounceTimer) { clearTimeout(debounceTimer); }
      debounceTimer = setTimeout(search, 400);
    });
  }
  form.querySelectorAll("select[data-facility-search-input]").forEach(function (select) {
    select.addEventListener("change", search);
  });
})();
