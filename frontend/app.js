// Checkout Radar Dashboard Client Application

let currentAuditId = null;
let eventSource = null;
let currentAuditRuns = [];
let selectedRunId = null;

document.addEventListener("DOMContentLoaded", () => {
    checkHealth();
    loadPastAudits();

    const urlParams = new URLSearchParams(window.location.search);
    const qAuditId = urlParams.get("audit_id");
    if (qAuditId) {
        selectAudit(qAuditId, "Loading Audit...");
    }

    document.getElementById("audit-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        await launchAudit();
    });
});

function setTarget(url, name) {
    document.getElementById("input-url").value = url;
}

async function checkHealth() {
    try {
        const resp = await fetch("/health");
        const data = await resp.json();
        const badge = document.getElementById("backend-status");
        if (data.status === "healthy") {
            const modeText = data.mock_mode ? "Mock Mode" : (data.has_tinyfish_key ? "Live TinyFish" : "Ready");
            badge.innerText = `● API Online (${modeText})`;
            badge.style.color = "#10b981";
            badge.style.borderColor = "#10b981";
        }
    } catch (e) {
        const badge = document.getElementById("backend-status");
        badge.innerText = "● API Offline";
        badge.style.color = "#ef4444";
        badge.style.borderColor = "#ef4444";
    }
}

async function launchAudit() {
    const inputUrl = document.getElementById("input-url").value;
    const preset = document.getElementById("preset-select").value;
    const btnSubmit = document.getElementById("btn-submit");

    btnSubmit.disabled = true;
    btnSubmit.innerText = "Launching Matrix...";

    try {
        const resp = await fetch("/audits", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ input_url: inputUrl, preset: preset })
        });
        const data = await resp.json();
        currentAuditId = data.id;
        selectedRunId = null;
        currentAuditRuns = [];

        // Switch view to active audit
        document.getElementById("active-audit-section").classList.remove("hidden");
        document.getElementById("active-merchant").innerText = data.merchant;
        document.getElementById("active-audit-id").innerText = data.id;
        document.getElementById("progress-count").innerText = `0 / ${data.conditions_count}`;
        document.getElementById("progress-bar").style.width = "5%";

        connectEventStream(data.id);
        loadPastAudits();
    } catch (err) {
        alert("Failed to submit audit: " + err.message);
    } finally {
        btnSubmit.disabled = false;
        btnSubmit.innerText = "Start Multi-Condition Audit";
    }
}

function connectEventStream(auditId) {
    if (eventSource) {
        eventSource.close();
    }

    const consoleBox = document.getElementById("console-box");
    consoleBox.innerHTML = "";
    appendConsole(`📡 Subscribing to live SSE stream for ${auditId}...`);

    eventSource = new EventSource(`/audits/${auditId}/stream`);

    eventSource.addEventListener("audit_started", (e) => {
        const payload = JSON.parse(e.data);
        appendConsole(`🚀 Audit Started: Preset ${payload.preset.toUpperCase()} (${payload.conditions_count} conditions)`);
    });

    eventSource.addEventListener("run_started", (e) => {
        const payload = JSON.parse(e.data);
        appendConsole(`▶️ Run Started: Condition ${payload.condition_key} (ID: ${payload.run_id})`);
    });

    eventSource.addEventListener("run_completed", (e) => {
        const payload = JSON.parse(e.data);
        appendConsole(`✅ Run Completed: Outcome = ${payload.outcome} (${payload.condition_key})`);
        refreshAuditData(auditId);
    });

    eventSource.addEventListener("finding_flagged", (e) => {
        const payload = JSON.parse(e.data);
        appendConsole(`🚨 INDICATOR FLAGGED: ${payload.category.toUpperCase()} (${payload.severity})`);
        refreshAuditData(auditId);
    });

    eventSource.addEventListener("audit_completed", (e) => {
        appendConsole(`🏁 Audit Complete! All conditions executed, diffed, and evaluated.`);
        document.getElementById("progress-bar").style.width = "100%";
        document.getElementById("progress-label").innerText = "Audit Completed";
        refreshAuditData(auditId);
    });

    eventSource.addEventListener("complete", () => {
        eventSource.close();
    });

    eventSource.onerror = () => {
        // Fallback polling if SSE disconnects
        setTimeout(() => refreshAuditData(auditId), 3000);
    };
}

function appendConsole(text) {
    const box = document.getElementById("console-box");
    const line = document.createElement("div");
    line.className = "console-line";
    const time = new Date().toISOString().substring(11, 19);
    line.innerText = `[${time}] ${text}`;
    box.appendChild(line);
    box.scrollTop = box.scrollHeight;
}

async function refreshAuditData(auditId) {
    try {
        const [detResp, diffResp, findResp, callsResp] = await Promise.all([
            fetch(`/audits/${auditId}`),
            fetch(`/audits/${auditId}/diff`),
            fetch(`/audits/${auditId}/findings`),
            fetch(`/audits/${auditId}/provider-calls`)
        ]);

        const det = await detResp.json();
        const diffsData = await diffResp.json();
        const findsData = await findResp.json();
        const callsData = await callsResp.json();

        currentAuditRuns = det.runs || [];

        if (det.audit && det.audit.merchant) {
            document.getElementById("active-merchant").innerText = det.audit.merchant;
        }

        // Update progress
        const totalConds = det.conditions ? det.conditions.length : 1;
        const compRuns = currentAuditRuns.filter(r => r.finished_at).length;
        const pct = Math.min(100, Math.round((compRuns / totalConds) * 100));
        document.getElementById("progress-bar").style.width = `${pct}%`;
        document.getElementById("progress-count").innerText = `${compRuns} / ${totalConds} runs`;

        renderAssessmentBanner(det.assessment);
        renderEvidenceGallery(currentAuditRuns, selectedRunId);
        renderFindings(findsData.findings || []);
        renderDiffs(diffsData.diffs || []);
        renderCalls(callsData.provider_calls || []);
    } catch (e) {
        console.error("Refresh error:", e);
    }
}

function renderFindings(findings) {
    const list = document.getElementById("findings-list");
    document.getElementById("findings-count-pill").innerText = `${findings.length} Found`;

    if (!findings.length) {
        list.innerHTML = `<div class="empty-state">No dark pattern indicators detected in this flow.</div>`;
        return;
    }

    list.innerHTML = findings.map(f => `
        <div class="finding-item">
            <div class="finding-item-header">
                <span class="finding-cat">${f.category.replace('_', ' ')}</span>
                <span class="finding-badge">${f.severity.toUpperCase()} (${Math.round(f.confidence * 100)}%)</span>
            </div>
            <div class="finding-expl">${f.explanation}</div>
            ${f.heuristic_note ? `<div class="finding-heuristic">ℹ️ ${f.heuristic_note}</div>` : ''}
        </div>
    `).join("");
}

function renderDiffs(diffs) {
    const list = document.getElementById("diffs-list");
    document.getElementById("diffs-count-pill").innerText = `${diffs.length} Diffs`;

    if (!diffs.length) {
        list.innerHTML = `<div class="empty-state">No variances detected across tested pairs.</div>`;
        return;
    }

    list.innerHTML = diffs.map(d => {
        let desc = "";
        const det = d.detail || {};
        if (d.type === "PRICE_VARIANCE") {
            desc = `${det.canonical_label}: ₹${det.amount_a_minor / 100} vs ₹${det.amount_b_minor / 100} across ${det.dimension}`;
        } else if (d.type === "LATE_DISCLOSURE") {
            desc = `${det.label} (₹${det.amount_minor / 100}) first observed at ${det.observed_disclosure_stage}, absent on ${det.expected_stage}`;
        } else if (d.type === "SMALL_CART_RULE") {
            desc = `Cart Policy: ${det.label} (₹${det.amount_minor / 100}) applied only below threshold.`;
        } else if (d.type === "TEMPORAL_DRIFT") {
            desc = `${det.canonical_label} changed from ₹${det.amount_t0_minor / 100} to ₹${det.amount_t1_minor / 100} across observations`;
        } else {
            desc = JSON.stringify(det);
        }

        return `
            <div class="diff-item">
                <div class="diff-type">${d.type}</div>
                <div class="diff-desc">${desc}</div>
                <small style="color: #64748b; font-family: monospace;">Match: ${d.matching_key}</small>
            </div>
        `;
    }).join("");
}

function renderCalls(calls) {
    const tbody = document.getElementById("calls-tbody");
    if (!calls.length) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: #94a3b8;">No calls recorded.</td></tr>`;
        return;
    }

    tbody.innerHTML = calls.map(c => `
        <tr>
            <td>${(c.requested_at || "").substring(11, 19)}</td>
            <td style="font-weight: 600; color: #60a5fa;">${c.operation}</td>
            <td style="color: ${c.response_status === 200 || c.response_status === 201 ? '#10b981' : '#ef4444'}">${c.response_status || 'ERR'}</td>
            <td>${c.result_usable ? '✓ Yes' : '✗ No'}</td>
            <td style="font-family: monospace; font-size: 0.8em;">${c.provider_request_id || '-'}</td>
        </tr>
    `).join("");
}

async function loadPastAudits() {
    try {
        const resp = await fetch("/audits");
        const audits = await resp.json();
        const list = document.getElementById("audits-history-list");
        if (!audits.length) {
            list.innerHTML = `<div style="color: #94a3b8; font-size: 0.85em;">No previous audits recorded.</div>`;
            return;
        }

        list.innerHTML = `
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Merchant</th>
                        <th>Preset</th>
                        <th>Status</th>
                        <th>Findings</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${audits.map(a => `
                        <tr>
                            <td>${(a.created_at || '').substring(0, 16).replace('T', ' ')}</td>
                            <td><strong>${a.merchant}</strong></td>
                            <td>${(a.preset || 'quick').toUpperCase()}</td>
                            <td><span style="color: ${a.status === 'complete' ? '#10b981' : '#f59e0b'}">${a.status}</span></td>
                            <td><strong>${a.findings_count}</strong></td>
                            <td>
                                <button class="btn-chip" onclick="selectAudit('${a.id}', '${a.merchant}')">View Audit &rarr;</button>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    } catch (e) {
        console.error("Failed to load past audits:", e);
    }
}

function selectAudit(auditId, merchant) {
    currentAuditId = auditId;
    selectedRunId = null;
    currentAuditRuns = [];
    document.getElementById("active-audit-section").classList.remove("hidden");
    if (merchant) {
        document.getElementById("active-merchant").innerText = merchant;
    }
    document.getElementById("active-audit-id").innerText = auditId;
    try {
        const u = new URL(window.location);
        u.searchParams.set("audit_id", auditId);
        window.history.replaceState({}, "", u);
    } catch (e) {}
    connectEventStream(auditId);
    refreshAuditData(auditId);
    window.scrollTo({ top: 300, behavior: "smooth" });
}

function openReport() {
    if (!currentAuditId) return;
    window.open(`/audits/${currentAuditId}/report`, "_blank");
}

async function openComplaintModal() {
    if (!currentAuditId) return;
    try {
        const resp = await fetch(`/audits/${currentAuditId}/complaint-draft`, { method: "POST" });
        const data = await resp.json();
        document.getElementById("complaint-text").value = data.draft_text;
        document.getElementById("complaint-modal").classList.remove("hidden");
    } catch (e) {
        alert("Failed to generate draft: " + e.message);
    }
}

function closeComplaintModal() {
    document.getElementById("complaint-modal").classList.add("hidden");
}

function copyComplaintText() {
    const txt = document.getElementById("complaint-text");
    txt.select();
    document.execCommand("copy");
    alert("Complaint draft copied to clipboard!");
}

async function triggerReobserve() {
    if (!currentAuditId) return;
    try {
        appendConsole("⏱️ Spawning manual temporal re-observation...");
        const resp = await fetch(`/audits/${currentAuditId}/reobserve`, { method: "POST" });
        const data = await resp.json();
        appendConsole(`▶️ New observation attempt enqueued (ID: ${data.new_run_id}). Waiting for completion...`);
    } catch (e) {
        alert("Failed to trigger re-observation: " + e.message);
    }
}

// -------------------------------------------------------------
// Assessment Banner Rendering
// -------------------------------------------------------------

function renderAssessmentBanner(assessment) {
    const banner = document.getElementById("assessment-banner");
    if (!assessment) {
        banner.classList.add("hidden");
        return;
    }

    banner.classList.remove("hidden");
    banner.classList.remove("assessment-clean", "assessment-indicators", "assessment-inconclusive");

    const badge = document.getElementById("assessment-badge");
    const title = document.getElementById("assessment-title");
    const countTag = document.getElementById("assessment-count-tag");
    const summary = document.getElementById("assessment-summary");
    const reasonsContainer = document.getElementById("assessment-reasons-container");
    const reasonsList = document.getElementById("assessment-reasons-list");

    badge.className = "assessment-status-badge";

    // Strictly enforce backend assessment contract:
    // Never label VERIFIED CLEAN without explicit is_clean boolean flag and clean status.
    const isClean = Boolean(assessment.is_clean === true && assessment.status === "clean");
    const isInconclusive = Boolean(assessment.is_inconclusive === true || assessment.status === "inconclusive");
    const hasIndicators = Boolean(
        assessment.status === "potential_indicators_detected" || 
        assessment.status === "indicators_detected" || 
        (assessment.findings_count > 0 && !isInconclusive)
    );

    if (isClean) {
        banner.classList.add("assessment-clean");
        badge.classList.add("badge-clean");
        badge.innerText = "VERIFIED CLEAN (UNDER TESTED FLOW)";
        title.innerText = "Verified Clean Checkout Flow";
        countTag.innerText = "0 Indicators Detected";
        countTag.style.color = "#10b981";
        summary.innerText = assessment.summary || "All required stages were captured and inspected; 0 potential dark pattern indicators detected within observed flow boundary.";
        reasonsContainer.classList.add("hidden");
    } else if (hasIndicators) {
        banner.classList.add("assessment-indicators");
        badge.classList.add("badge-indicators");
        badge.innerText = "INDICATORS DETECTED";
        title.innerText = `${assessment.findings_count || 1} Potential Dark Pattern Indicator(s) Flagged`;
        countTag.innerText = `${assessment.findings_count || 1} Indicator(s)`;
        countTag.style.color = "#f87171";
        summary.innerText = assessment.summary || "Technical checkout audit findings flagged candidate dark patterns matching CCPA 2023 regulations.";
        reasonsContainer.classList.add("hidden");
    } else {
        // Conservative fail-closed default: missing findings alone NEVER equals clean
        banner.classList.add("assessment-inconclusive");
        badge.classList.add("badge-inconclusive");
        badge.innerText = "INCONCLUSIVE AUDIT";
        title.innerText = "Audit Inconclusive: Incomplete or Obstructed Journey";
        countTag.innerText = "Flow Incomplete";
        countTag.style.color = "#f59e0b";
        summary.innerText = assessment.summary || "Missing, uninspected, or obstructed stage observations cannot establish that the flow is clean.";

        const reasons = assessment.inconclusive_reasons || [];
        if (reasons.length > 0) {
            reasonsList.innerHTML = reasons.map(r => `<li>${escapeHtml(r)}</li>`).join("");
            reasonsContainer.classList.remove("hidden");
        } else {
            reasonsContainer.classList.add("hidden");
        }
    }
}

// -------------------------------------------------------------
// Evidence Gallery Rendering (3 Stages)
// -------------------------------------------------------------

function renderEvidenceGallery(runs, targetRunId) {
    if (!runs || !runs.length) {
        resetGalleryCards();
        return;
    }

    // Determine target run: if specified, use it; else prefer reference run, else first run
    let activeRun = null;
    if (targetRunId) {
        activeRun = runs.find(r => r.id === targetRunId);
    }
    if (!activeRun) {
        activeRun = runs.find(r => r.is_reference) || runs[0];
    }
    selectedRunId = activeRun ? activeRun.id : null;

    // Handle run selector dropdown if multiple runs
    const selContainer = document.getElementById("run-selector-container");
    const dropdown = document.getElementById("gallery-run-select");
    if (runs.length > 1) {
        selContainer.classList.remove("hidden");
        dropdown.innerHTML = runs.map(r => {
            const label = r.is_reference 
                ? `Reference (${r.condition_key || r.id.substring(0, 8)})` 
                : `Run ${r.id.substring(0, 8)} (${r.condition_key || 'Variant'})`;
            const selected = (r.id === selectedRunId) ? 'selected' : '';
            return `<option value="${r.id}" ${selected}>${escapeHtml(label)}</option>`;
        }).join("");
    } else {
        selContainer.classList.add("hidden");
    }

    const stages = [
        { key: "product", name: "Product Page", num: "Stage 1" },
        { key: "cart", name: "Cart Drawer / Page", num: "Stage 2" },
        { key: "checkout_summary", name: "Checkout Summary", num: "Stage 3" },
    ];

    const stageCaps = activeRun ? (activeRun.stage_captures || []) : [];

    stages.forEach(st => {
        // Resolve stage capture record
        const sc = stageCaps.find(c => {
            const sName = (c.step_name || "").toLowerCase();
            if (st.key === "product") return sName === "product" || sName.includes("prod");
            if (st.key === "cart") return sName === "cart" || sName.includes("cart");
            if (st.key === "checkout_summary") return sName === "checkout_summary" || sName === "checkout" || sName.includes("check");
            return false;
        });

        const badge = document.getElementById(`badge-stage-${st.key}`);
        const imgContainer = document.getElementById(`img-container-${st.key}`);
        const snapMeta = document.getElementById(`meta-snap-${st.key}`);
        const hashMeta = document.getElementById(`meta-hash-${st.key}`);
        const timeMeta = document.getElementById(`meta-time-${st.key}`);
        const footer = document.getElementById(`footer-stage-${st.key}`);

        if (sc && (sc.evidence_url || sc.snapshot_id || sc.provider_step_id)) {
            const isVerified = (sc.capture_status === "verified");
            badge.className = `stage-status-badge ${isVerified ? 'badge-stage-verified' : 'badge-stage-waiting'}`;
            badge.innerText = isVerified ? "VERIFIED" : (sc.capture_status || "CAPTURED").toUpperCase();

            const evUrl = sc.evidence_url || (sc.evidence_filename ? `/evidence/${sc.evidence_filename}` : "");
            const snapId = sc.snapshot_id || sc.provider_step_id || "snap_unknown";
            const sha256 = sc.snapshot_sha256 || "";
            const timeRaw = sc.snapshot_captured_at || sc.captured_at;
            const timeStr = timeRaw ? formatTimestamp(timeRaw) : "Timestamp recorded";

            if (evUrl) {
                imgContainer.innerHTML = `
                    <img src="${evUrl}" 
                         alt="${escapeHtml(st.name)} Viewport" 
                         class="gallery-thumb" 
                         onclick="openScreenshotModal('${evUrl}', '${escapeHtml(st.name)}', '${escapeHtml(snapId)}', '${escapeHtml(sha256)}')"
                         title="Click to view full-resolution screenshot"
                         onerror="this.onerror=null; this.parentElement.innerHTML='<div class=\\'stage-empty-state\\'>🖼️ Artifact referenced (${escapeHtml(snapId)})<br><small style=\\'color:#94a3b8\\'>File pending on disk</small></div>';" />
                `;
                footer.innerHTML = `
                    <button class="btn btn-secondary btn-chip" onclick="openScreenshotModal('${evUrl}', '${escapeHtml(st.name)}', '${escapeHtml(snapId)}', '${escapeHtml(sha256)}')">
                        🔍 Full Resolution
                    </button>
                `;
            } else {
                imgContainer.innerHTML = `<div class="stage-empty-state">📸 Snapshot metadata recorded (${escapeHtml(snapId)})</div>`;
                footer.innerHTML = `<span class="text-disabled">Metadata verified</span>`;
            }

            snapMeta.innerText = snapId;
            snapMeta.title = snapId;

            if (sha256) {
                hashMeta.innerText = `${sha256.substring(0, 16)}...`;
                hashMeta.title = sha256;
            } else {
                hashMeta.innerText = "N/A";
                hashMeta.title = "No cryptographic digest recorded";
            }

            timeMeta.innerText = timeStr;
        } else {
            // Stage was not captured in this run
            badge.className = "stage-status-badge badge-stage-missing";
            badge.innerText = "NOT CAPTURED";
            imgContainer.innerHTML = `<div class="stage-empty-state">⚠️ Stage was not captured in this audit run</div>`;
            snapMeta.innerText = "-";
            snapMeta.title = "-";
            hashMeta.innerText = "-";
            hashMeta.title = "-";
            timeMeta.innerText = "-";
            footer.innerHTML = `<span class="text-disabled">No viewport captured</span>`;
        }
    });
}

function resetGalleryCards() {
    ["product", "cart", "checkout_summary"].forEach(k => {
        const badge = document.getElementById(`badge-stage-${k}`);
        const imgContainer = document.getElementById(`img-container-${k}`);
        const snapMeta = document.getElementById(`meta-snap-${k}`);
        const hashMeta = document.getElementById(`meta-hash-${k}`);
        const timeMeta = document.getElementById(`meta-time-${k}`);
        const footer = document.getElementById(`footer-stage-${k}`);

        if (badge) { badge.className = "stage-status-badge badge-stage-waiting"; badge.innerText = "WAITING"; }
        if (imgContainer) imgContainer.innerHTML = `<div class="stage-empty-state">No viewport captured yet</div>`;
        if (snapMeta) { snapMeta.innerText = "-"; snapMeta.title = "-"; }
        if (hashMeta) { hashMeta.innerText = "-"; hashMeta.title = "-"; }
        if (timeMeta) timeMeta.innerText = "-";
        if (footer) footer.innerHTML = `<span class="text-disabled">Awaiting capture</span>`;
    });
}

function onGalleryRunChanged() {
    const dropdown = document.getElementById("gallery-run-select");
    if (!dropdown) return;
    const chosenRunId = dropdown.value;
    renderEvidenceGallery(currentAuditRuns, chosenRunId);
}

// -------------------------------------------------------------
// Full-Resolution Screenshot Lightbox
// -------------------------------------------------------------

function openScreenshotModal(imgUrl, stageTitle, snapId, sha256) {
    const modal = document.getElementById("screenshot-modal");
    document.getElementById("modal-stage-title").innerText = `${stageTitle} Viewport`;
    document.getElementById("modal-snap-id").innerText = snapId || "-";
    document.getElementById("modal-img").src = imgUrl;
    document.getElementById("modal-hash-val").innerText = sha256 || "N/A (digest not supplied)";
    document.getElementById("modal-raw-link").href = imgUrl;
    modal.classList.remove("hidden");
}

function closeScreenshotModal() {
    const modal = document.getElementById("screenshot-modal");
    modal.classList.add("hidden");
    document.getElementById("modal-img").src = "";
}

function formatTimestamp(isoStr) {
    if (!isoStr) return "-";
    try {
        const d = new Date(isoStr);
        if (isNaN(d.getTime())) return String(isoStr).substring(11, 19);
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) + ' UTC';
    } catch {
        return String(isoStr).substring(11, 19);
    }
}

function escapeHtml(str) {
    if (!str) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
