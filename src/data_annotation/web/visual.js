// Visual workspace UI. Self-contained so app.js does not need to know about
// visual mode -- this script attaches its own listeners that toggle
// visualApp visibility on top of whatever app.js does.

(function () {
  "use strict";

  let currentImageBytes = null;
  let currentImageMediaType = null;

  document.addEventListener("DOMContentLoaded", function () {
    bindModeSwitching();
    bindUploadHandlers();
    bindSearchHandler();
    bindBriefHandler();
  });

  // ---- mode toggle ------------------------------------------------------

  function bindModeSwitching() {
    document.querySelectorAll("[data-mode]").forEach(function (button) {
      button.addEventListener("click", function () {
        const mode = button.dataset.mode;
        const visualApp = document.getElementById("visualApp");
        const landing = document.getElementById("modeLanding");
        const fmriApp = document.getElementById("fmriApp");
        const textApp = document.getElementById("textApp");
        if (mode === "visual") {
          visualApp.classList.remove("hidden");
          if (landing) landing.classList.add("hidden");
          if (fmriApp) fmriApp.classList.add("hidden");
          if (textApp) textApp.classList.add("hidden");
        } else {
          visualApp.classList.add("hidden");
        }
      });
    });
  }

  // ---- file picker + drag-and-drop --------------------------------------

  function bindUploadHandlers() {
    const fileInput = document.getElementById("visualFileInput");
    const dropzone = document.getElementById("visualDropzone");
    const annotateBtn = document.getElementById("runVisualAnnotator");
    const clearBtn = document.getElementById("clearVisualImage");

    fileInput.addEventListener("change", function (event) {
      const file = event.target.files && event.target.files[0];
      if (file) handleFile(file);
    });

    ["dragenter", "dragover"].forEach(function (evt) {
      dropzone.addEventListener(evt, function (event) {
        event.preventDefault();
        dropzone.classList.add("is-dragover");
      });
    });
    ["dragleave", "drop"].forEach(function (evt) {
      dropzone.addEventListener(evt, function (event) {
        event.preventDefault();
        dropzone.classList.remove("is-dragover");
      });
    });
    dropzone.addEventListener("drop", function (event) {
      const file = event.dataTransfer && event.dataTransfer.files[0];
      if (file) handleFile(file);
    });

    annotateBtn.addEventListener("click", runImageAnnotator);
    clearBtn.addEventListener("click", resetImageState);
  }

  function handleFile(file) {
    const reader = new FileReader();
    reader.onload = function () {
      currentImageBytes = reader.result; // ArrayBuffer
      currentImageMediaType = file.type || "image/png";
      const previewUrl = URL.createObjectURL(file);
      const preview = document.getElementById("visualPreview");
      preview.src = previewUrl;
      preview.classList.remove("hidden");
      document.getElementById("visualDropzonePrompt").classList.add("hidden");
      document.getElementById("runVisualAnnotator").disabled = false;
      document.getElementById("clearVisualImage").disabled = false;
      document.getElementById("visualHashBadge").textContent = file.name + " (" + Math.round(file.size / 1024) + " KB)";
    };
    reader.readAsArrayBuffer(file);
  }

  function resetImageState() {
    currentImageBytes = null;
    currentImageMediaType = null;
    document.getElementById("visualFileInput").value = "";
    const preview = document.getElementById("visualPreview");
    preview.removeAttribute("src");
    preview.classList.add("hidden");
    document.getElementById("visualDropzonePrompt").classList.remove("hidden");
    document.getElementById("runVisualAnnotator").disabled = true;
    document.getElementById("clearVisualImage").disabled = true;
    document.getElementById("visualHashBadge").textContent = "no file";
    document.getElementById("visualFacetResults").innerHTML =
      '<div class="empty">Annotate an image to see vision-model facets.</div>';
  }

  // ---- annotate ---------------------------------------------------------

  async function runImageAnnotator() {
    if (!currentImageBytes) return;
    const button = document.getElementById("runVisualAnnotator");
    const results = document.getElementById("visualFacetResults");
    button.disabled = true;
    button.textContent = "Annotating";
    results.innerHTML = '<div class="empty">Calling vision model...</div>';
    try {
      const base64 = arrayBufferToBase64(currentImageBytes);
      const data = await postJson("/api/image/annotate", {
        image_base64: base64,
        media_type: currentImageMediaType,
      });
      renderImageAnnotation(data.annotation, data.byte_count);
    } catch (err) {
      results.innerHTML = '<div class="empty error">' + escapeHtml(err.message) + "</div>";
    } finally {
      button.disabled = false;
      button.textContent = "Annotate image";
    }
  }

  function renderImageAnnotation(row, byteCount) {
    const facets = row.facets || {};
    document.getElementById("visualHashBadge").textContent = row.asset_hash.slice(0, 8) + "...";
    document.getElementById("visualFacetResults").innerHTML =
      '<div class="visual-summary-grid">' +
        detail("Archetype", row.archetype_id) +
        detail("Kind", row.annotator_kind) +
        detail("Model", row.model) +
        detail("Bytes", byteCount) +
      "</div>" +
      '<div class="facet-section"><h3>Modality</h3><div class="facet-chips">' +
        facetChip("Image", facets.type_image) +
        facetChip("B2B email", facets.modality_b2b_email) +
        facetChip("Landing page", facets.modality_landing_page) +
      "</div></div>" +
      '<div class="facet-section"><h3>Strictness</h3>' +
        facetBar("Regulatory", facets.strict_regulatory) +
        facetBar("Technicality", facets.strict_technicality) +
      "</div>" +
      '<div class="facet-section"><h3>Tone</h3>' +
        facetBar("Formality", facets.tone_formality) +
        facetBar("Aggressiveness", facets.tone_aggressiveness) +
        facetBar("Creativity", facets.tone_creativity) +
      "</div>";
  }

  // ---- search -----------------------------------------------------------

  function bindSearchHandler() {
    document.getElementById("runVisualSearch").addEventListener("click", runImageSearch);
  }

  async function runImageSearch() {
    const button = document.getElementById("runVisualSearch");
    const promptEl = document.getElementById("visualSearchPrompt");
    const planEl = document.getElementById("visualSearchPlan");
    const out = document.getElementById("visualSearchResults");
    const prompt = promptEl.value.trim();
    if (!prompt) return;
    button.disabled = true;
    button.textContent = "Searching";
    out.innerHTML = '<div class="empty">Querying Pinecone...</div>';
    try {
      const data = await postJson("/api/image/search", {
        prompt: prompt,
        plan: planEl.checked,
        top_k: 5,
      });
      renderSearchResults(data.matches || []);
    } catch (err) {
      out.innerHTML = '<div class="empty error">' + escapeHtml(err.message) + "</div>";
    } finally {
      button.disabled = false;
      button.textContent = "Search";
    }
  }

  function renderSearchResults(matches) {
    const out = document.getElementById("visualSearchResults");
    if (!matches.length) {
      out.innerHTML = '<div class="empty">No matches in the corpus yet -- annotate and index some images first.</div>';
      return;
    }
    out.innerHTML = matches.map(function (m, i) {
      const doc = m.document || {};
      const meta = m.metadata || {};
      return '<div class="visual-match-row">' +
        '<div class="visual-match-rank">' + (i + 1) + "</div>" +
        '<div class="visual-match-body">' +
          '<div class="visual-match-head">' +
            '<strong>' + escapeHtml(doc.source_name || meta.source_name || m.document_id) + '</strong>' +
            '<span class="visual-score">' + m.score.toFixed(4) + '</span>' +
          '</div>' +
          '<div class="visual-match-meta">' + escapeHtml(m.document_id) + '</div>' +
        '</div>' +
      '</div>';
    }).join("");
  }

  // ---- creative brief ---------------------------------------------------

  function bindBriefHandler() {
    document.getElementById("runVisualBrief").addEventListener("click", runImageBrief);
  }

  async function runImageBrief() {
    const button = document.getElementById("runVisualBrief");
    const promptEl = document.getElementById("visualBriefPrompt");
    const planEl = document.getElementById("visualBriefPlan");
    const out = document.getElementById("visualBriefOutput");
    const prompt = promptEl.value.trim();
    if (!prompt) return;
    button.disabled = true;
    button.textContent = "Generating";
    out.innerHTML = '<div class="empty">Retrieving and briefing...</div>';
    try {
      const data = await postJson("/api/image/generate", {
        prompt: prompt,
        plan: planEl.checked,
        top_k: 3,
      });
      renderBrief(data);
    } catch (err) {
      out.innerHTML = '<div class="empty error">' + escapeHtml(err.message) + "</div>";
    } finally {
      button.disabled = false;
      button.textContent = "Generate brief";
    }
  }

  function renderBrief(data) {
    const out = document.getElementById("visualBriefOutput");
    const sources = (data.sources || []).map(function (s) {
      return '<li>' + escapeHtml(s.source_name || s.document_id) + '</li>';
    }).join("");
    out.innerHTML =
      '<div class="visual-brief-text">' + escapeHtml(data.brief_text || "") + '</div>' +
      '<div class="visual-brief-sources">' +
        '<span class="eyebrow">Drawn from ' + (data.retrieved_count || 0) + ' source(s)</span>' +
        '<ul>' + sources + '</ul>' +
      '</div>';
  }

  // ---- helpers ----------------------------------------------------------

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

  function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    const chunkSize = 8192;
    let binary = "";
    for (let i = 0; i < bytes.length; i += chunkSize) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
    }
    return btoa(binary);
  }

  function detail(label, value) {
    return '<div class="detail"><span>' + escapeHtml(label) + '</span><strong>' + escapeHtml(String(value == null ? "-" : value)) + '</strong></div>';
  }

  function facetChip(label, active) {
    return '<span class="facet-chip ' + (active ? "active" : "") + '">' + escapeHtml(label) + ': ' + (active ? "true" : "false") + '</span>';
  }

  function facetBar(label, value) {
    const numeric = typeof value === "number" ? value : 0;
    const pct = Math.round(Math.max(0, Math.min(1, numeric)) * 100);
    return '<div class="facet-bar"><span>' + escapeHtml(label) + '</span>' +
      '<div class="facet-bar-track"><div class="facet-bar-fill" style="width:' + pct + '%"></div></div>' +
      '<strong>' + numeric.toFixed(2) + '</strong></div>';
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
})();
