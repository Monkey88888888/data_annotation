let snapshot = null;
let lastExport = null;
let activePageName = "setup";
let activeMode = "landing";

document.addEventListener("DOMContentLoaded", async () => {
  bindStaticActions();
  await loadState();
});

function bindStaticActions() {
  document.querySelectorAll("[data-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      setActiveMode(button.dataset.mode);
    });
  });

  document.querySelectorAll("[data-sample]").forEach((button) => {
    button.addEventListener("click", () => {
      document.getElementById("textPayload").value = textSample(button.dataset.sample);
    });
  });

  document.getElementById("runTextAnnotator").addEventListener("click", annotateTextPayload);

  document.querySelectorAll("[data-page]").forEach((button) => {
    button.addEventListener("click", () => {
      setActivePage(button.dataset.page);
    });
  });

  document.getElementById("proposalForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = document.getElementById("requestInput");
    const requestText = input.value.trim();
    if (!requestText) return;
    const response = await api("/api/projects/propose", {
      method: "POST",
      body: { request_text: requestText },
    });
    snapshot = response.snapshot;
    render();
  });

  document.getElementById("resetBtn").addEventListener("click", async () => {
    snapshot = await api("/api/reset", { method: "POST", body: {} });
    lastExport = null;
    render();
  });
}

function setActiveMode(modeName) {
  activeMode = modeName;
  document.getElementById("modeLanding").classList.toggle("hidden", activeMode !== "landing");
  document.getElementById("fmriApp").classList.toggle("hidden", activeMode !== "fmri");
  document.getElementById("textApp").classList.toggle("hidden", activeMode !== "text");
  if (activeMode === "fmri") {
    drawScan(snapshot?.current_assignment || snapshot?.review_assignment);
    renderAssetPreview(snapshot?.current_assignment || snapshot?.review_assignment);
  }
}

function setActivePage(pageName) {
  activePageName = pageName;
  document.querySelectorAll("[data-page]").forEach((button) => {
    button.classList.toggle("active", button.dataset.page === activePageName);
  });
  document.querySelectorAll("[data-page-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.pagePanel === activePageName);
  });
  drawScan(snapshot?.current_assignment || snapshot?.review_assignment);
}

async function loadState() {
  snapshot = await api("/api/state");
  render();
  setActiveMode(activeMode);
}

async function api(path, options = {}) {
  const init = { method: options.method || "GET", headers: {} };
  if (options.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, init);
  const payload = await response.json();
  if (!response.ok || payload.error) {
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}

function render() {
  if (!snapshot) return;
  setActivePage(activePageName);
  renderProjectList();
  renderProjectPanel();
  renderSpecPanel();
  renderTaskPanel();
  renderQueuePanel();
  renderQualityPanel();
  renderRetrievalPanel();
  renderExportPanel();
  renderActivityPanel();
  drawScan(snapshot.current_assignment || snapshot.review_assignment);
  renderAssetPreview(snapshot.current_assignment || snapshot.review_assignment);
  bindDynamicActions();
}

async function annotateTextPayload() {
  const button = document.getElementById("runTextAnnotator");
  const text = document.getElementById("textPayload").value.trim();
  if (!text) return;
  button.disabled = true;
  button.textContent = "Annotating";
  try {
    const response = await api("/api/text/annotate", {
      method: "POST",
      body: { text },
    });
    renderTextAnnotation(response.annotation, response.text_length);
  } finally {
    button.disabled = false;
    button.textContent = "Annotate text";
  }
}

function renderTextAnnotation(row, textLength) {
  const facets = row.facets || {};
  document.getElementById("textHashBadge").textContent = `${row.asset_hash.slice(0, 8)}...`;
  document.getElementById("textFacetResults").innerHTML = `
    <div class="text-summary-grid">
      ${detail("Archetype", row.archetype_id)}
      ${detail("Kind", row.annotator_kind)}
      ${detail("Model", row.model)}
      ${detail("Characters", textLength)}
    </div>
    <div class="facet-section">
      <h3>Modality</h3>
      <div class="facet-chips">
        ${facetChip("Text", facets.type_text)}
        ${facetChip("B2B email", facets.modality_b2b_email)}
        ${facetChip("Landing page", facets.modality_landing_page)}
      </div>
    </div>
    <div class="facet-section">
      <h3>Strictness</h3>
      ${facetBar("Regulatory", facets.strict_regulatory)}
      ${facetBar("Technicality", facets.strict_technicality)}
    </div>
    <div class="facet-section">
      <h3>Tone</h3>
      ${facetBar("Formality", facets.tone_formality)}
      ${facetBar("Aggressiveness", facets.tone_aggressiveness)}
      ${facetBar("Creativity", facets.tone_creativity)}
    </div>
  `;
  document.getElementById("textJsonOutput").textContent = JSON.stringify(row, null, 2);
}

function facetChip(label, active) {
  return `<span class="facet-chip ${active ? "active" : ""}">${escapeHtml(label)}: ${active ? "true" : "false"}</span>`;
}

function facetBar(label, value) {
  const number = Number(value || 0);
  const width = Math.round(Math.max(0, Math.min(1, number)) * 100);
  return `<div class="facet-bar-row">
    <div class="facet-bar-label"><span>${escapeHtml(label)}</span><strong>${numberText(number)}</strong></div>
    <div class="bar"><span style="width:${width}%"></span></div>
  </div>`;
}

function textSample(name) {
  const samples = {
    email:
      "Hi Jordan, your analytics team can cut manual reporting time by connecting pipeline metrics, model evaluation, and compliance-ready exports in one workspace. Want to see a 15 minute demo this week?",
    landing:
      "Turn raw customer feedback into trusted product decisions. Start your workspace, route high-impact comments to reviewers, and export clean insights for every stakeholder. Sign up to explore features and pricing.",
    policy:
      "All model outputs must comply with privacy, retention, and audit requirements. Teams are required to document policy exceptions, regulatory risk, and review status before publishing external responses.",
  };
  return samples[name] || samples.email;
}

function activeView() {
  return snapshot.active_project || { project: {}, task_spec: {}, quality: {}, assignments: [] };
}

function renderProjectList() {
  const activeId = snapshot.active_project_id;
  document.getElementById("projectList").innerHTML = snapshot.projects
    .map(({ project, quality }) => {
      const cls = project.id === activeId ? "project-tab active" : "project-tab";
      return `<button class="${cls}" data-project-id="${escapeHtml(project.id)}" type="button">
        ${escapeHtml(project.name)}
        <span>${quality.total_assignments || 0} assignments, ${escapeHtml(project.status)}</span>
      </button>`;
    })
    .join("");
}

function renderProjectPanel() {
  const { project, quality } = activeView();
  document.getElementById("projectPanel").innerHTML = `
    <div class="panel-heading">
      <div>
        <span class="eyebrow">Project</span>
        <h2>${escapeHtml(project.name || "No project")}</h2>
      </div>
      <span class="status-pill ${escapeHtml(project.status || "")}">${escapeHtml(project.status || "")}</span>
    </div>
    <p class="muted">${escapeHtml(project.objective || "")}</p>
    <div class="metric-grid">
      ${metric("Items", quality.dataset_items || 0)}
      ${metric("Done", percent(quality.completion_rate))}
      ${metric("Agreement", percent(quality.ai_human_agreement))}
      ${metric("Review", quality.review_backlog || 0)}
    </div>
  `;
}

function renderSpecPanel() {
  const { task_spec: spec, project } = activeView();
  if (!spec || !spec.id) {
    document.getElementById("specPanel").innerHTML = `<div class="empty">No task spec drafted.</div>`;
    return;
  }
  document.getElementById("specPanel").innerHTML = `
    <div class="panel-heading">
      <div>
        <span class="eyebrow">Task Spec</span>
        <h2>${escapeHtml(spec.task_type)}</h2>
      </div>
      <span class="status-pill ${escapeHtml(spec.status)}">${escapeHtml(spec.status)}</span>
    </div>
    <label for="rubricEditor">Rubric</label>
    <textarea id="rubricEditor">${escapeHtml(spec.rubric_md || "")}</textarea>
    <div class="detail-grid">
      ${detail("Primary", spec.primary_field)}
      ${detail("Review role", spec.routing_policy_json?.reviewer_role)}
    </div>
    <div class="actions">
      <button id="approveSpecBtn" type="button" data-project-id="${escapeHtml(project.id)}">Save + approve</button>
      <button id="generateAssignmentsBtn" class="secondary" type="button" data-project-id="${escapeHtml(project.id)}">Generate assignments</button>
    </div>
  `;
}

function renderTaskPanel() {
  const detailView = snapshot.current_assignment;
  const reviewView = snapshot.review_assignment;
  const assignmentHtml = detailView ? annotationHtml(detailView) : `<div class="empty">Annotation queue is clear.</div>`;
  const reviewHtml = reviewView ? reviewHtmlFor(reviewView) : "";
  document.getElementById("taskPanel").innerHTML = assignmentHtml + reviewHtml;
}

function annotationHtml(view) {
  const { assignment, item, task_spec: spec } = view;
  const metadata = item.metadata_json || {};
  const asset = (item.payload_json || {}).asset || item.payload_json || {};
  return `
    <div class="panel-heading">
      <div>
        <span class="eyebrow">Annotator Task</span>
        <h2>${escapeHtml(metadata.subject || asset.dataset_id || item.id)}</h2>
      </div>
      <span class="status-pill ${escapeHtml(assignment.state)}">${escapeHtml(assignment.state)}</span>
    </div>
    <div class="detail-grid">
      ${detail("Dataset", asset.dataset_id || metadata.source)}
      ${detail("Task", metadata.task || "model-eval")}
      ${detail("Run", metadata.run || "n/a")}
      ${detail("Authority", numberText(metadata.authority_score))}
    </div>
    <div class="detail field-wide">
      <span>Source</span>
      <strong>${escapeHtml(item.source_uri || item.id)}</strong>
    </div>
    <div id="assetPreviewPanel" class="asset-preview-panel" data-item-id="${escapeHtml(item.id)}">
      <div class="asset-preview-header">
        <div>
          <span class="eyebrow">Source Asset</span>
          <strong>${escapeHtml(asset.path || item.source_uri || item.id)}</strong>
        </div>
        <a id="sourceDownloadLink" class="source-link" href="#" target="_blank" rel="noreferrer">Open source</a>
      </div>
      <div class="asset-preview-grid">
        <canvas id="niftiPreviewCanvas" width="256" height="256" aria-label="NIfTI slice preview"></canvas>
        <div id="assetPreviewMeta" class="asset-preview-meta">Loading preview...</div>
      </div>
    </div>
    ${checksHtml((item.payload_json || {}).authority_checks)}
    <div class="prelabel">
      <strong>AI pre-label</strong>
      <code>${escapeHtml(JSON.stringify(assignment.prelabel_json, null, 2))}</code>
      <p class="muted">${escapeHtml(assignment.prelabel_rationale || "")}</p>
    </div>
    <form id="annotationForm" data-assignment-id="${escapeHtml(assignment.id)}">
      <div class="form-grid">
        ${schemaFormHtml(spec, assignment.prelabel_json || {}, "ann")}
        <div class="field-wide">
          <label for="rationale">Rationale</label>
          <textarea id="rationale" name="rationale">Evidence matches the rubric and the authority checks shown above.</textarea>
        </div>
        <div class="field-wide">
          <label for="confidenceRange">Confidence</label>
          <div class="range-row">
            <input id="confidenceRange" type="range" min="0" max="1" step="0.01" value="${assignment.prelabel_confidence || 0.78}" />
            <strong id="confidenceValue">${Math.round((assignment.prelabel_confidence || 0.78) * 100)}%</strong>
          </div>
        </div>
      </div>
      <div class="actions">
        <button type="submit">Submit annotation</button>
      </div>
    </form>
  `;
}

function reviewHtmlFor(view) {
  const { assignment, annotation, item, task_spec: spec } = view;
  if (!annotation) return "";
  return `
    <hr />
    <div class="panel-heading">
      <div>
        <span class="eyebrow">Reviewer Adjudication</span>
        <h2>${escapeHtml(item.metadata_json?.subject || item.id)}</h2>
      </div>
      <span class="status-pill needs_review">needs review</span>
    </div>
    <div class="detail-grid">
      ${detail("Reasons", (assignment.review_reasons || []).join(", ") || "n/a")}
      ${detail("Human label", primaryLabel(annotation.label_json, spec))}
    </div>
    <div class="prelabel">
      <strong>Submitted label</strong>
      <code>${escapeHtml(JSON.stringify(annotation.label_json, null, 2))}</code>
      <p class="muted">${escapeHtml(annotation.rationale || "")}</p>
    </div>
    <label for="reviewNotes">Review notes</label>
    <textarea id="reviewNotes">Reviewed against source evidence and rubric.</textarea>
    <div class="actions">
      <button data-review-action="approve" data-annotation-id="${escapeHtml(annotation.id)}" type="button">Approve</button>
      <button class="secondary" data-review-action="correct" data-annotation-id="${escapeHtml(annotation.id)}" type="button">Use AI pre-label</button>
      <button class="warning" data-review-action="escalate" data-annotation-id="${escapeHtml(annotation.id)}" type="button">Escalate</button>
    </div>
  `;
}

function renderQueuePanel() {
  const assignments = activeView().assignments || [];
  document.getElementById("queuePanel").innerHTML = `
    <div class="panel-heading">
      <div>
        <span class="eyebrow">Queue</span>
        <h2>Assignments</h2>
      </div>
    </div>
    <div class="queue-list">
      ${assignments
        .map(({ assignment, item }) => {
          const metadata = item.metadata_json || {};
          return `<div class="queue-item">
            <div>
              <strong>${escapeHtml(metadata.subject || item.id)}</strong>
              <div class="muted">${escapeHtml(item.source_uri || "")}</div>
            </div>
            <span class="status-pill ${escapeHtml(assignment.state)}">${escapeHtml(assignment.state)}</span>
          </div>`;
        })
        .join("")}
    </div>
  `;
}

function renderQualityPanel() {
  const quality = activeView().quality || {};
  const distribution = quality.label_distribution || {};
  document.getElementById("qualityPanel").innerHTML = `
    <div class="panel-heading">
      <div>
        <span class="eyebrow">Quality</span>
        <h2>Live metrics</h2>
      </div>
    </div>
    ${barMetric("Completion", quality.completion_rate)}
    ${barMetric("AI agreement", quality.ai_human_agreement)}
    ${barMetric("Average confidence", quality.avg_confidence)}
    <div class="detail-grid">
      ${detail("Gold failures", quality.gold_failures || 0)}
      ${detail("Local payloads", quality.local_payloads || 0)}
      ${detail("Retrieval ready", quality.retrieval_ready || 0)}
      ${detail("Avg authority", numberText(quality.avg_authority_score))}
    </div>
    <div class="result-list">
      ${Object.keys(distribution).length ? Object.entries(distribution).map(([label, count]) => `<div class="result-item"><strong>${escapeHtml(label)}</strong><div class="muted">${count} labels</div></div>`).join("") : `<div class="empty">No human labels yet.</div>`}
    </div>
  `;
}

function renderRetrievalPanel() {
  const project = activeView().project || {};
  const latest = (snapshot.retrieval_runs || [])[0];
  document.getElementById("retrievalPanel").innerHTML = `
    <div class="panel-heading">
      <div>
        <span class="eyebrow">Step 5-6</span>
        <h2>Faceted retrieval</h2>
      </div>
    </div>
    <form id="retrievalForm" class="retrieval-form" data-project-id="${escapeHtml(project.id || "")}">
      <label for="retrievalPrompt">Prompt</label>
      <input id="retrievalPrompt" value="high authority fMRI balloon risk task" />
      <label for="terminalIntent">Terminal route</label>
      <select id="terminalIntent">
        <option value="pure_retrieval">Pure retrieval</option>
        <option value="clean_room_text">Clean-room text</option>
        <option value="image_context">Image context</option>
      </select>
      <div class="slider-grid">
        ${slider("authority", 1)}
        ${slider("type", 1)}
        ${slider("modality", 1)}
        ${slider("strictness", 1)}
        ${slider("tone", 0.2)}
      </div>
      <button type="submit">Run retrieval</button>
    </form>
    ${latest ? retrievalResultsHtml(latest) : `<div class="empty">No retrieval run yet.</div>`}
  `;
}

function retrievalResultsHtml(run) {
  return `
    <div class="result-list">
      ${(run.results || [])
        .map(
          (result) => `<div class="result-item">
            <strong>${escapeHtml(result.path)}</strong>
            <div class="muted">score ${numberText(result.score)} | authority ${numberText(result.authority_score)} | ${escapeHtml(result.terminal_route || "retrieval")}</div>
            ${openNeuroLink(result.dataset_id, result.path)}
          </div>`,
        )
        .join("")}
    </div>
    <div class="export-box"><code>${escapeHtml(JSON.stringify(run.terminal_output || {}, null, 2))}</code></div>
  `;
}

async function renderAssetPreview(view) {
  const panel = document.getElementById("assetPreviewPanel");
  if (!panel || !view?.item?.id) return;
  const meta = document.getElementById("assetPreviewMeta");
  const link = document.getElementById("sourceDownloadLink");
  const canvas = document.getElementById("niftiPreviewCanvas");
  try {
    const preview = await api(`/api/assets/${encodeURIComponent(view.item.id)}/preview`);
    if (link && preview.source_url) {
      link.href = preview.source_url;
      link.textContent = preview.local_payload_present ? "Open/download source" : "Download from OpenNeuro";
    }
    if (preview.renderable) {
      drawNiftiPreview(canvas, preview);
      meta.innerHTML = `
        <div class="detail-grid compact">
          ${detail("Preview", `slice ${preview.z_index + 1}/${preview.depth}`)}
          ${detail("Shape", `${preview.width} x ${preview.height}`)}
          ${detail("Payload", "local")}
          ${detail("Datatype", preview.datatype)}
        </div>
        <p class="muted">Rendered from the downloaded NIfTI payload. Browser preview is a normalized middle axial slice.</p>
      `;
    } else {
      clearPreviewCanvas(canvas, "Metadata only");
      meta.innerHTML = `
        <div class="detail-grid compact">
          ${detail("Payload", preview.local_payload_present ? "local" : "not downloaded")}
          ${detail("Preview", "unavailable")}
        </div>
        <p class="muted">Use the source link to download the NIfTI payload. Raw .nii.gz files are not browser images, so this panel renders only when a local payload is available.</p>
      `;
    }
  } catch (error) {
    clearPreviewCanvas(canvas, "Preview error");
    meta.textContent = error.message;
  }
}

function drawNiftiPreview(canvas, preview) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  canvas.width = preview.width;
  canvas.height = preview.height;
  const image = ctx.createImageData(preview.width, preview.height);
  preview.pixels.forEach((pixel, index) => {
    const value = Number(pixel);
    const offset = index * 4;
    image.data[offset] = value;
    image.data[offset + 1] = value;
    image.data[offset + 2] = value;
    image.data[offset + 3] = 255;
  });
  ctx.putImageData(image, 0, 0);
}

function clearPreviewCanvas(canvas, message) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  canvas.width = 256;
  canvas.height = 256;
  ctx.fillStyle = "#0b1118";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#8fa0b1";
  ctx.font = "700 16px system-ui";
  ctx.textAlign = "center";
  ctx.fillText(message, canvas.width / 2, canvas.height / 2);
}

function openNeuroLink(datasetId, path) {
  if (!datasetId || !path) return "";
  const url = `https://s3.amazonaws.com/openneuro.org/${encodeURIComponent(datasetId)}/${path.split("/").map(encodeURIComponent).join("/")}`;
  return `<a class="source-link inline" href="${escapeHtml(url)}" target="_blank" rel="noreferrer">Open source payload</a>`;
}

function renderExportPanel() {
  const project = activeView().project || {};
  const exports = snapshot.exports || [];
  const latest = lastExport || exports[0];
  document.getElementById("exportPanel").innerHTML = `
    <div class="panel-heading">
      <div>
        <span class="eyebrow">Export</span>
        <h2>Dataset artifact</h2>
      </div>
    </div>
    <div class="actions">
      <button data-export-format="jsonl" data-project-id="${escapeHtml(project.id || "")}" type="button">JSONL</button>
      <button class="secondary" data-export-format="csv" data-project-id="${escapeHtml(project.id || "")}" type="button">CSV</button>
    </div>
    ${
      latest
        ? `<div class="detail-grid">${detail("Rows", latest.row_count || 0)}${detail("Format", latest.format || "jsonl")}</div>
           <div class="export-box"><code>${escapeHtml((latest.content || latest.path || "").slice(0, 4000))}</code></div>`
        : `<div class="empty">No export created.</div>`
    }
  `;
}

function renderActivityPanel() {
  document.getElementById("activityPanel").innerHTML = `
    <div class="panel-heading">
      <div>
        <span class="eyebrow">Activity</span>
        <h2>Audit trail</h2>
      </div>
    </div>
    <div class="activity-list">
      ${(snapshot.activity || [])
        .map(
          (activity) => `<div class="activity-item">
            <strong>${escapeHtml(activity.title)}</strong>
            <div class="muted">${escapeHtml(activity.detail || "")}</div>
          </div>`,
        )
        .join("")}
    </div>
  `;
}

function bindDynamicActions() {
  document.querySelectorAll("[data-project-id].project-tab").forEach((button) => {
    button.addEventListener("click", async () => {
      snapshot = await api(`/api/projects/${button.dataset.projectId}/activate`, { method: "POST", body: {} });
      render();
    });
  });

  const approve = document.getElementById("approveSpecBtn");
  if (approve) {
    approve.addEventListener("click", async () => {
      const projectId = approve.dataset.projectId;
      const rubric = document.getElementById("rubricEditor").value;
      const response = await api(`/api/projects/${projectId}/approve`, {
        method: "POST",
        body: { patch: { rubric_md: rubric } },
      });
      snapshot = response.snapshot;
      render();
    });
  }

  const generate = document.getElementById("generateAssignmentsBtn");
  if (generate) {
    generate.addEventListener("click", async () => {
      const response = await api(`/api/projects/${generate.dataset.projectId}/assignments/generate`, {
        method: "POST",
        body: {},
      });
      snapshot = response.snapshot;
      render();
    });
  }

  const confidence = document.getElementById("confidenceRange");
  if (confidence) {
    confidence.addEventListener("input", () => {
      document.getElementById("confidenceValue").textContent = `${Math.round(Number(confidence.value) * 100)}%`;
    });
  }

  const annotationForm = document.getElementById("annotationForm");
  if (annotationForm) {
    annotationForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const view = snapshot.current_assignment;
      const label = collectSchemaValues(annotationForm, view.task_spec);
      const response = await api(`/api/assignments/${annotationForm.dataset.assignmentId}/annotations`, {
        method: "POST",
        body: {
          label_json: label,
          rationale: document.getElementById("rationale").value,
          confidence: Number(document.getElementById("confidenceRange").value),
          time_spent_sec: 48,
        },
      });
      snapshot = response.snapshot;
      render();
    });
  }

  document.querySelectorAll("[data-review-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const review = snapshot.review_assignment;
      const corrected =
        button.dataset.reviewAction === "correct" ? review.assignment.prelabel_json : undefined;
      const response = await api("/api/reviews", {
        method: "POST",
        body: {
          annotation_id: button.dataset.annotationId,
          decision: button.dataset.reviewAction,
          corrected_label_json: corrected,
          notes: document.getElementById("reviewNotes").value,
        },
      });
      snapshot = response.snapshot;
      render();
    });
  });

  const retrievalForm = document.getElementById("retrievalForm");
  if (retrievalForm) {
    retrievalForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const body = { prompt: document.getElementById("retrievalPrompt").value };
      ["authority", "type", "modality", "strictness", "tone"].forEach((facet) => {
        body[`${facet}_weight`] = Number(document.getElementById(`${facet}Weight`).value);
      });
      body.terminal_intent = document.getElementById("terminalIntent").value;
      body.top_k = 3;
      const response = await api(`/api/projects/${retrievalForm.dataset.projectId}/retrieval`, {
        method: "POST",
        body,
      });
      snapshot = response.snapshot;
      render();
    });
  }

  document.querySelectorAll("[data-export-format]").forEach((button) => {
    button.addEventListener("click", async () => {
      const response = await api(`/api/projects/${button.dataset.projectId}/export`, {
        method: "POST",
        body: { format: button.dataset.exportFormat },
      });
      lastExport = response.export;
      snapshot = response.snapshot;
      render();
    });
  });
}

function schemaFormHtml(spec, values, prefix) {
  const fields = spec.schema_json?.fields || [];
  return fields.map((field) => fieldHtml(field, values?.[field.name], prefix)).join("");
}

function fieldHtml(field, value, prefix) {
  const id = `${prefix}_${field.name}`;
  if (field.type === "select") {
    return `<div>
      <label for="${escapeHtml(id)}">${escapeHtml(field.label || field.name)}</label>
      <select id="${escapeHtml(id)}" data-field="${escapeHtml(field.name)}">
        ${(field.options || [])
          .map((option) => `<option value="${escapeHtml(option.value)}" ${option.value === value ? "selected" : ""}>${escapeHtml(option.label || option.value)}</option>`)
          .join("")}
      </select>
    </div>`;
  }
  if (field.type === "boolean") {
    return `<div class="checkbox-row">
      <input id="${escapeHtml(id)}" type="checkbox" data-field="${escapeHtml(field.name)}" ${value ? "checked" : ""} />
      <label for="${escapeHtml(id)}">${escapeHtml(field.label || field.name)}</label>
    </div>`;
  }
  if (field.type === "multi_select") {
    const selected = Array.isArray(value) ? value : [];
    return `<div class="field-wide">
      <label>${escapeHtml(field.label || field.name)}</label>
      <div class="multi-options">
        ${(field.options || [])
          .map((option) => {
            const optionId = `${id}_${option.value}`;
            return `<label for="${escapeHtml(optionId)}">
              <input id="${escapeHtml(optionId)}" type="checkbox" data-field="${escapeHtml(field.name)}" value="${escapeHtml(option.value)}" ${selected.includes(option.value) ? "checked" : ""} />
              ${escapeHtml(option.label || option.value)}
            </label>`;
          })
          .join("")}
      </div>
    </div>`;
  }
  return `<div>
    <label for="${escapeHtml(id)}">${escapeHtml(field.label || field.name)}</label>
    <input id="${escapeHtml(id)}" data-field="${escapeHtml(field.name)}" value="${escapeHtml(value || "")}" />
  </div>`;
}

function collectSchemaValues(form, spec) {
  const values = {};
  (spec.schema_json?.fields || []).forEach((field) => {
    const nodes = Array.from(form.querySelectorAll(`[data-field="${field.name}"]`));
    if (field.type === "boolean") {
      values[field.name] = Boolean(nodes[0]?.checked);
    } else if (field.type === "multi_select") {
      values[field.name] = nodes.filter((node) => node.checked).map((node) => node.value);
    } else {
      values[field.name] = nodes[0]?.value || "";
    }
  });
  return values;
}

function checksHtml(checks) {
  if (!checks || !Object.keys(checks).length) return "";
  return `<div class="check-grid">
    ${Object.entries(checks)
      .map(([key, value]) => `<div class="check ${value ? "pass" : "fail"}"><b>${escapeHtml(key)}</b></div>`)
      .join("")}
  </div>`;
}

function drawScan(view) {
  const canvas = document.getElementById("scanCanvas");
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#111611";
  ctx.fillRect(0, 0, width, height);

  const item = view?.item || {};
  const payload = item.payload_json || {};
  const raw = payload.raw_hypervector_preview || [1, -1, 1, 1, -1, -1, 1, -1];
  const auth = payload.authority_vector_preview || [-1, 1, -1, 1, 1, -1, 1, -1];
  const score = Number(item.metadata_json?.authority_score || 0.72);
  const cx = width * 0.5;
  const cy = height * 0.44;

  ctx.save();
  ctx.translate(cx, cy);
  for (let layer = 0; layer < 5; layer += 1) {
    const radiusX = 235 - layer * 34;
    const radiusY = 142 - layer * 22;
    ctx.beginPath();
    ctx.ellipse(0, 0, radiusX, radiusY, 0, 0, Math.PI * 2);
    ctx.strokeStyle = layer % 2 === 0 ? "rgba(174, 232, 216, 0.42)" : "rgba(241, 150, 84, 0.34)";
    ctx.lineWidth = 2;
    ctx.stroke();
  }

  for (let y = -130; y <= 130; y += 10) {
    for (let x = -220; x <= 220; x += 10) {
      const inside = (x * x) / (238 * 238) + (y * y) / (146 * 146) <= 1;
      if (!inside) continue;
      const idx = Math.abs((x * 7 + y * 13 + raw.length * 17) % raw.length);
      const jdx = Math.abs((x * 5 - y * 11 + auth.length * 19) % auth.length);
      const value = raw[idx] * auth[jdx] * score;
      ctx.fillStyle = value > 0 ? `rgba(32, 175, 151, ${0.18 + score * 0.36})` : `rgba(215, 100, 54, ${0.12 + score * 0.22})`;
      ctx.fillRect(x, y, 7, 7);
    }
  }
  ctx.restore();

  const checks = payload.authority_checks || {};
  const entries = Object.entries(checks).slice(0, 14);
  const barWidth = (width - 64) / Math.max(entries.length, 1);
  entries.forEach(([key, value], index) => {
    const x = 32 + index * barWidth;
    const h = value ? 54 : 22;
    ctx.fillStyle = value ? "#31a88f" : "#c15a1a";
    ctx.fillRect(x, height - 74, Math.max(4, barWidth - 5), h);
    ctx.save();
    ctx.translate(x + 3, height - 80);
    ctx.rotate(-Math.PI / 3);
    ctx.fillStyle = "#dce8df";
    ctx.font = "10px system-ui";
    ctx.fillText(key.replaceAll("_", " "), 0, 0);
    ctx.restore();
  });

  ctx.fillStyle = "#f8fff8";
  ctx.font = "700 18px system-ui";
  ctx.fillText(`Authority ${Math.round(score * 100)}%`, 24, 34);
  ctx.fillStyle = "#a9bbb0";
  ctx.font = "12px system-ui";
  ctx.fillText(item.source_uri || "No active scan", 24, 54);
}

function slider(name, value) {
  const label = name[0].toUpperCase() + name.slice(1);
  return `<label for="${name}Weight">${label}
    <input id="${name}Weight" type="range" min="0" max="2" step="0.1" value="${value}" />
  </label>`;
}

function metric(label, value) {
  return `<div class="metric"><strong>${escapeHtml(String(value))}</strong><span>${escapeHtml(label)}</span></div>`;
}

function detail(label, value) {
  return `<div class="detail"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value ?? "n/a")}</strong></div>`;
}

function barMetric(label, value) {
  const width = Math.max(0, Math.min(1, Number(value || 0))) * 100;
  return `<div class="detail">
    <span>${escapeHtml(label)}</span>
    <strong>${percent(value)}</strong>
    <div class="bar"><span style="width:${width}%"></span></div>
  </div>`;
}

function primaryLabel(label, spec) {
  const key = spec?.primary_field;
  if (key && label && label[key] !== undefined) return label[key];
  return label ? Object.values(label)[0] : "n/a";
}

function percent(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function numberText(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return "n/a";
  return Number(value).toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
