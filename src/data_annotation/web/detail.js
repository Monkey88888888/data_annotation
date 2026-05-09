// Shared document-detail modal. Used by both text.js and visual.js.
//
// API:
//   window.DocDetail.open(documentId)
//
// Modal pulls /api/document/{id}, renders content + editable facets, and
// supports re-annotate (calls /api/document/{id}/reannotate) and save-edits
// (calls /api/document/{id}/edit). No persistent state -- closes clean.

(function () {
  "use strict";

  const CONTINUOUS = [
    "auth_domain", "auth_author", "auth_institution",
    "strict_regulatory", "strict_technicality",
    "tone_formality", "tone_aggressiveness", "tone_creativity",
  ];
  const BOOLEAN = [
    "type_text", "type_image", "type_timeseries",
    "modality_b2b_email", "modality_landing_page",
    "modality_fmri_t1", "modality_fmri_bold",
  ];

  let currentDoc = null;
  let dirtyEdits = {};

  document.addEventListener("DOMContentLoaded", function () {
    const close = document.getElementById("docModalClose");
    const reannotate = document.getElementById("docReannotateBtn");
    const saveEdits = document.getElementById("docSaveEditsBtn");
    if (close) close.addEventListener("click", closeModal);
    if (reannotate) reannotate.addEventListener("click", runReannotate);
    if (saveEdits) saveEdits.addEventListener("click", runSaveEdits);

    const overlay = document.getElementById("docDetailModal");
    if (overlay) {
      overlay.addEventListener("click", function (event) {
        if (event.target === overlay) closeModal();
      });
    }
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeModal();
    });
  });

  async function open(documentId) {
    if (!documentId) return;
    showModal();
    setStatus("Loading...");
    try {
      const data = await fetchJson("/api/document/" + encodeURIComponent(documentId));
      currentDoc = data.document;
      dirtyEdits = {};
      render(currentDoc);
      setStatus("");
    } catch (err) {
      setStatus(err.message);
    }
  }

  function showModal() {
    document.getElementById("docDetailModal").classList.remove("hidden");
  }

  function closeModal() {
    document.getElementById("docDetailModal").classList.add("hidden");
    currentDoc = null;
    dirtyEdits = {};
    setStatus("");
    setSaveDisabled(true);
  }

  function render(doc) {
    document.getElementById("docModalArchetype").textContent = doc.archetype_id || "document";
    document.getElementById("docModalTitle").textContent =
      doc.source_name || ("Document " + (doc.id || "").slice(0, 8));

    renderPayload(doc);
    renderMeta(doc);
    renderFacets(doc);
    setSaveDisabled(true);
  }

  function renderPayload(doc) {
    const el = document.getElementById("docModalPayload");
    const payload = doc.content_payload || "";
    if (doc.archetype_id === "image_asset" && payload.startsWith("data:image/")) {
      el.innerHTML = '<img class="doc-modal-image" alt="annotated image" src="' + escapeAttribute(payload) + '" />';
    } else if (doc.archetype_id === "image_asset") {
      el.innerHTML = '<div class="empty">No image bytes stored. Re-upload to render the preview.</div>';
    } else {
      el.innerHTML = '<pre class="doc-modal-text">' + escapeHtml(payload) + '</pre>';
    }
  }

  function renderMeta(doc) {
    const el = document.getElementById("docModalMeta");
    el.innerHTML =
      '<div class="detail"><span>id</span><strong>' + escapeHtml(doc.id || "") + '</strong></div>' +
      '<div class="detail"><span>created</span><strong>' + escapeHtml(doc.created_at || "") + '</strong></div>' +
      '<div class="detail"><span>processed</span><strong>' + (doc.is_processed ? "yes" : "no") + '</strong></div>' +
      '<div class="detail"><span>indexed</span><strong>' + (doc.is_indexed ? "yes" : "no") + '</strong></div>';
  }

  function renderFacets(doc) {
    const facetEl = document.getElementById("docModalFacets");
    const continuousRows = CONTINUOUS.map(function (name) {
      const value = clamp01Number(doc[name]);
      return '<label class="facet-edit-row" data-facet="' + name + '">' +
        '<span>' + name + '</span>' +
        '<input type="number" min="0" max="1" step="0.05" value="' + value + '" data-edit-key="' + name + '" />' +
        '</label>';
    }).join("");
    const booleanRows = BOOLEAN.map(function (name) {
      const checked = doc[name] ? "checked" : "";
      return '<label class="facet-edit-row" data-facet="' + name + '">' +
        '<span>' + name + '</span>' +
        '<input type="checkbox" ' + checked + ' data-edit-key="' + name + '" />' +
        '</label>';
    }).join("");
    facetEl.innerHTML =
      '<div class="facet-edit-section"><h3>Continuous (0..1)</h3><div class="facet-edit-grid">' + continuousRows + '</div></div>' +
      '<div class="facet-edit-section"><h3>Boolean</h3><div class="facet-edit-grid">' + booleanRows + '</div></div>';

    facetEl.querySelectorAll("[data-edit-key]").forEach(function (input) {
      input.addEventListener("change", function () {
        const key = input.dataset.editKey;
        const newValue = input.type === "checkbox" ? input.checked : Number(input.value);
        dirtyEdits[key] = newValue;
        setSaveDisabled(false);
      });
    });
  }

  async function runReannotate() {
    if (!currentDoc) return;
    const button = document.getElementById("docReannotateBtn");
    button.disabled = true;
    button.textContent = "Re-annotating";
    setStatus("Calling annotator...");
    try {
      const data = await postJson("/api/document/" + encodeURIComponent(currentDoc.id) + "/reannotate", {});
      currentDoc = data.document;
      dirtyEdits = {};
      render(currentDoc);
      setStatus("Re-annotated.");
    } catch (err) {
      setStatus(err.message);
    } finally {
      button.disabled = false;
      button.textContent = "Re-annotate";
    }
  }

  async function runSaveEdits() {
    if (!currentDoc) return;
    if (Object.keys(dirtyEdits).length === 0) return;
    const button = document.getElementById("docSaveEditsBtn");
    button.disabled = true;
    button.textContent = "Saving";
    setStatus("Saving edits...");
    try {
      const data = await postJson("/api/document/" + encodeURIComponent(currentDoc.id) + "/edit", { facets: dirtyEdits });
      currentDoc = data.document;
      dirtyEdits = {};
      render(currentDoc);
      setStatus("Saved.");
    } catch (err) {
      setStatus(err.message);
    } finally {
      button.disabled = false;
      button.textContent = "Save edits";
    }
  }

  function setStatus(message) {
    const el = document.getElementById("docModalStatus");
    if (el) el.textContent = message || "";
  }

  function setSaveDisabled(disabled) {
    const btn = document.getElementById("docSaveEditsBtn");
    if (btn) btn.disabled = disabled;
  }

  function clamp01Number(value) {
    if (typeof value !== "number") value = Number(value || 0);
    if (Number.isNaN(value)) value = 0;
    return Math.max(0, Math.min(1, value));
  }

  async function fetchJson(path) {
    const response = await fetch(path);
    const payload = await response.json();
    if (!response.ok || payload.error) throw new Error(payload.error || "Request failed: " + response.status);
    return payload;
  }

  async function postJson(path, body) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok || payload.error) throw new Error(payload.error || "Request failed: " + response.status);
    return payload;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function escapeAttribute(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // Public API
  window.DocDetail = { open: open, close: closeModal };
})();
