// Text workspace page nav + Setup/Review handlers.
// Annotate-page (paste -> /api/text/annotate) is owned by app.js and left alone.

(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    bindPageNav();
    bindProposal();
    bindSearch();
    bindGenerate();
    refreshSnapshot();
  });

  // --- page nav ---------------------------------------------------------

  function bindPageNav() {
    document.querySelectorAll('[data-text-page]').forEach(function (button) {
      button.addEventListener("click", function () {
        const page = button.dataset.textPage;
        document.querySelectorAll('[data-text-page]').forEach(function (b) {
          b.classList.toggle("active", b.dataset.textPage === page);
        });
        document.querySelectorAll('[data-text-page-panel]').forEach(function (panel) {
          panel.classList.toggle("active", panel.dataset.textPagePanel === page);
        });
        if (page === "setup") refreshSnapshot();
      });
    });
  }

  // --- Setup: project intake + project list -----------------------------

  function bindProposal() {
    const form = document.getElementById("textProposalForm");
    if (!form) return;
    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      const input = document.getElementById("textRequestInput");
      const requestText = input.value.trim();
      if (!requestText) return;
      const submit = form.querySelector("button[type=submit]");
      submit.disabled = true;
      submit.textContent = "Creating";
      try {
        const data = await postJson("/api/text/projects/propose", { request_text: requestText });
        renderSnapshot(data.snapshot);
        input.select();
      } catch (err) {
        renderProposalError(err.message);
      } finally {
        submit.disabled = false;
        submit.textContent = "Create project";
      }
    });
  }

  async function refreshSnapshot() {
    try {
      const snap = await fetchJson("/api/text/snapshot");
      renderSnapshot(snap);
    } catch (err) {
      // non-fatal; setup still usable
      console.error("text snapshot failed", err);
    }
  }

  function renderSnapshot(snap) {
    if (!snap) return;
    renderProjects(snap.projects || [], snap.active_project_id);
    renderActivity(snap.activity || []);
  }

  function renderProjects(projects, activeId) {
    const container = document.getElementById("textProjectsList");
    if (!container) return;
    container.innerHTML = projects.map(function (project) {
      const cls = project.id === activeId ? "project-tab active" : "project-tab";
      return '<button type="button" class="' + cls + '">' +
        '<strong>' + escapeHtml(project.name) + '</strong>' +
        '<span>' + escapeHtml(project.objective || project.request_text || "") + '</span>' +
      '</button>';
    }).join("");
  }

  function renderActivity(activity) {
    const list = document.getElementById("textActivityList");
    if (!list) return;
    if (!activity.length) {
      list.innerHTML = '<div class="empty">No activity yet -- create a project to get started.</div>';
      return;
    }
    list.innerHTML = activity.map(function (entry) {
      return '<div class="activity-item">' +
        '<strong>' + escapeHtml(entry.title || "") + '</strong>' +
        '<span>' + escapeHtml(entry.detail || "") + '</span>' +
        '<time>' + escapeHtml(entry.created_at || "") + '</time>' +
      '</div>';
    }).join("");
  }

  function renderProposalError(message) {
    const list = document.getElementById("textActivityList");
    if (!list) return;
    list.innerHTML = '<div class="empty error">' + escapeHtml(message) + '</div>';
  }

  // --- Review: search ---------------------------------------------------

  function bindSearch() {
    const button = document.getElementById("runTextSearch");
    if (!button) return;
    button.addEventListener("click", runTextSearch);
  }

  async function runTextSearch() {
    const button = document.getElementById("runTextSearch");
    const promptEl = document.getElementById("textSearchPrompt");
    const planEl = document.getElementById("textSearchPlan");
    const out = document.getElementById("textSearchResults");
    const prompt = promptEl.value.trim();
    if (!prompt) return;
    button.disabled = true;
    button.textContent = "Searching";
    out.innerHTML = '<div class="empty">Querying Pinecone...</div>';
    try {
      const data = await postJson("/api/text/search", {
        prompt: prompt,
        plan: planEl.checked,
        top_k: 5,
      });
      renderSearchResults(data.matches || []);
    } catch (err) {
      out.innerHTML = '<div class="empty error">' + escapeHtml(err.message) + '</div>';
    } finally {
      button.disabled = false;
      button.textContent = "Search";
    }
  }

  function renderSearchResults(matches) {
    const out = document.getElementById("textSearchResults");
    if (!matches.length) {
      out.innerHTML = '<div class="empty">No matches -- annotate and index some text first.</div>';
      return;
    }
    out.innerHTML = matches.map(function (m, i) {
      const doc = m.document || {};
      const snippet = (doc.content_payload || "").slice(0, 220);
      return '<button type="button" class="visual-match-row clickable" data-document-id="' + escapeHtml(m.document_id) + '">' +
        '<div class="visual-match-rank">' + (i + 1) + '</div>' +
        '<div class="visual-match-body">' +
          '<div class="visual-match-head">' +
            '<strong>' + escapeHtml(doc.source_name || m.document_id) + '</strong>' +
            '<span class="visual-score">' + m.score.toFixed(4) + '</span>' +
          '</div>' +
          '<div class="visual-match-meta">' + escapeHtml(snippet) + '</div>' +
        '</div>' +
      '</button>';
    }).join("");
    out.querySelectorAll("[data-document-id]").forEach(function (el) {
      el.addEventListener("click", function () {
        if (window.DocDetail) window.DocDetail.open(el.dataset.documentId);
      });
    });
  }

  // --- Review: generate -------------------------------------------------

  function bindGenerate() {
    const button = document.getElementById("runTextGenerate");
    if (!button) return;
    button.addEventListener("click", runTextGenerate);
  }

  async function runTextGenerate() {
    const button = document.getElementById("runTextGenerate");
    const promptEl = document.getElementById("textGeneratePrompt");
    const planEl = document.getElementById("textGeneratePlan");
    const out = document.getElementById("textGenerateOutput");
    const prompt = promptEl.value.trim();
    if (!prompt) return;
    button.disabled = true;
    button.textContent = "Generating";
    out.innerHTML = '<div class="empty">Retrieving and writing...</div>';
    try {
      const data = await postJson("/api/text/generate", {
        prompt: prompt,
        plan: planEl.checked,
        top_k: 3,
      });
      renderGeneratedText(data);
    } catch (err) {
      out.innerHTML = '<div class="empty error">' + escapeHtml(err.message) + '</div>';
    } finally {
      button.disabled = false;
      button.textContent = "Generate text";
    }
  }

  function renderGeneratedText(data) {
    const out = document.getElementById("textGenerateOutput");
    const sources = (data.sources || []).map(function (s) {
      return '<li>' + escapeHtml(s.source_name || s.document_id) + '</li>';
    }).join("");
    out.innerHTML =
      '<div class="visual-brief-text">' + escapeHtml(data.generated_text || "") + '</div>' +
      '<div class="visual-brief-sources">' +
        '<span class="eyebrow">Drawn from ' + (data.retrieved_count || 0) + ' source(s)</span>' +
        '<ul>' + sources + '</ul>' +
      '</div>';
  }

  // --- helpers ----------------------------------------------------------

  async function postJson(path, body) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok || payload.error) {
      throw new Error(payload.error || "Request failed: " + response.status);
    }
    return payload;
  }

  async function fetchJson(path) {
    const response = await fetch(path);
    const payload = await response.json();
    if (!response.ok || payload.error) {
      throw new Error(payload.error || "Request failed: " + response.status);
    }
    return payload;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
})();
