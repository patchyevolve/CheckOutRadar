// Checkout Radar Dashboard Client Application — Forensic Workspace

let currentAuditId = null;
let eventSource = null;
let currentAuditRuns = [];
let selectedRunId = null;
let activeTab = "evidence";

// Filter & Search State
let currentSeverityFilter = "all";
let currentFindingSearch = "";
let rawFindings = [];
let rawDiffs = [];

// Provider Calls Pagination State
let rawCalls = [];
let callsPage = 1;
const callsPageSize = 10;
let callsSearch = "";

// History Pagination State
let rawAudits = [];
let historyPage = 1;
const historyPageSize = 10;
let historySearch = "";

let homeHistoryPage = 1;
const homeHistoryPageSize = 10;
let homeHistorySearch = "";

document.addEventListener("DOMContentLoaded", () => {
    checkHealth();
    loadPastAudits();

    const urlParams = new URLSearchParams(window.location.search);
    const qAuditId = urlParams.get("audit_id");
    if (qAuditId) {
        selectAudit(qAuditId, "Loading Audit...");
    } else {
        // Expand launcher on initial page load if no audit is active
        toggleLauncher(true);
    }

    document.getElementById("audit-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        await launchAudit();
    });

    // Close modals on Escape key or outside click
    window.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            closeScreenshotModal();
            closeComplaintModal();
        }
    });

    const modalList = document.querySelectorAll(".modal");
    modalList.forEach(m => {
        m.addEventListener("click", (e) => {
            if (e.target === m) {
                closeScreenshotModal();
                closeComplaintModal();
            }
        });
    });
});

// -------------------------------------------------------------
// Launcher Collapse & Expand
// -------------------------------------------------------------

function toggleLauncher(forceState) {
    const section = document.getElementById("launch-section");
    const summary = document.getElementById("launch-summary-text");
    const toggleBtn = document.getElementById("launch-toggle-btn");
    const btnNav = document.getElementById("btn-toggle-launcher");

    const isCollapsed = (forceState !== undefined) ? !forceState : !section.classList.contains("launch-collapsed");

    if (isCollapsed) {
        section.classList.add("launch-collapsed");
        if (summary) summary.innerText = "Click to expand configuration drawer and run new test matrix.";
        if (toggleBtn) toggleBtn.innerText = "▼";
        if (btnNav) btnNav.innerText = "+ New Audit";
    } else {
        section.classList.remove("launch-collapsed");
        if (summary) summary.innerText = "Run automated checkout flows across controlled condition matrices (Location, Session, Cart Tier, Time) using TinyFish web agents.";
        if (toggleBtn) toggleBtn.innerText = "▲";
        if (btnNav) btnNav.innerText = "▲ Collapse Form";
    }
}

function setTarget(url, name) {
    document.getElementById("input-url").value = url;
}

// -------------------------------------------------------------
// Tab Switching
// -------------------------------------------------------------

function switchTab(tabKey) {
    activeTab = tabKey;
    const tabButtons = document.querySelectorAll(".tab-btn");
    tabButtons.forEach(btn => {
        btn.classList.remove("active");
    });

    const tabPanes = document.querySelectorAll(".tab-pane");
    tabPanes.forEach(pane => {
        pane.classList.add("hidden");
    });

    const activeBtn = document.getElementById(`tab-btn-${tabKey}`);
    const activePane = document.getElementById(`pane-${tabKey}`);

    if (activeBtn) activeBtn.classList.add("active");
    if (activePane) activePane.classList.remove("hidden");
}

// -------------------------------------------------------------
// System Health
// -------------------------------------------------------------

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

// -------------------------------------------------------------
// Audit Launch
// -------------------------------------------------------------

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

        // Collapse launcher to give prime space to investigation
        toggleLauncher(false);

        // Switch view to active audit
        document.getElementById("active-audit-section").classList.remove("hidden");
        document.getElementById("home-history-section").classList.add("hidden");
        document.getElementById("active-merchant").innerText = data.merchant;
        document.getElementById("active-audit-id").innerText = data.id;
        document.getElementById("active-target-url").innerText = inputUrl;
        document.getElementById("active-preset-badge").innerText = `${preset.toUpperCase()} PRESET`;
        document.getElementById("progress-count").innerText = `0 / ${data.conditions_count} runs`;
        document.getElementById("progress-bar").style.width = "5%";
        document.getElementById("progress-label").innerText = "Executing automated agent runs...";

        // Open live console accordion
        const consoleDetails = document.getElementById("console-details");
        if (consoleDetails) consoleDetails.open = true;

        switchTab("evidence");
        connectEventStream(data.id);
        loadPastAudits();
    } catch (err) {
        alert("Failed to submit audit: " + err.message);
    } finally {
        btnSubmit.disabled = false;
        btnSubmit.innerText = "Start Multi-Condition Audit";
    }
}

// -------------------------------------------------------------
// Server-Sent Events (SSE) Streaming
// -------------------------------------------------------------

function connectEventStream(auditId) {
    if (eventSource) {
        eventSource.close();
    }

    const consoleBox = document.getElementById("console-box");
    consoleBox.innerHTML = "";
    appendConsole(`📡 Subscribing to live SSE stream for ${auditId}...`);
    document.getElementById("console-status-pill").innerText = "Streaming";
    document.getElementById("console-status-pill").style.color = "#38bdf8";

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
        document.getElementById("console-status-pill").innerText = "Complete";
        document.getElementById("console-status-pill").style.color = "#10b981";

        // Auto-collapse console once finished so evidence is clear
        setTimeout(() => {
            const consoleDetails = document.getElementById("console-details");
            if (consoleDetails && !consoleDetails.classList.contains("user-opened")) {
                consoleDetails.open = false;
            }
        }, 1500);

        refreshAuditData(auditId);
    });

    eventSource.addEventListener("complete", () => {
        eventSource.close();
        document.getElementById("console-status-pill").innerText = "Closed";
        document.getElementById("console-status-pill").style.color = "#94a3b8";
    });

    eventSource.onerror = () => {
        document.getElementById("console-status-pill").innerText = "Idle";
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

// -------------------------------------------------------------
// Audit Data Refresh & Rendering
// -------------------------------------------------------------

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
        rawFindings = findsData.findings || [];
        rawDiffs = diffsData.diffs || [];
        rawCalls = callsData.provider_calls || [];

        if (det.audit && det.audit.merchant) {
            document.getElementById("active-merchant").innerText = det.audit.merchant;
            if (det.audit.input_url) {
                document.getElementById("active-target-url").innerText = det.audit.input_url;
            }
            if (det.audit.preset) {
                document.getElementById("active-preset-badge").innerText = `${det.audit.preset.toUpperCase()} PRESET`;
            }
        }

        // Update progress
        const totalConds = det.conditions ? det.conditions.length : (currentAuditRuns.length || 1);
        const compRuns = currentAuditRuns.filter(r => r.finished_at).length;
        const pct = Math.min(100, Math.round((compRuns / totalConds) * 100));
        document.getElementById("progress-bar").style.width = `${pct}%`;
        document.getElementById("progress-count").innerText = `${compRuns} / ${totalConds} runs`;

        // Update Tab Badges
        document.getElementById("tab-pill-evidence").innerText = "3";
        document.getElementById("tab-pill-findings").innerText = String(rawFindings.length);
        document.getElementById("tab-pill-calls").innerText = String(rawCalls.length);

        // Render Core Components
        renderExecutiveScorecard(det, rawFindings, rawDiffs, currentAuditRuns);
        renderAssessmentBanner(det.assessment);
        renderEvidenceGallery(currentAuditRuns, selectedRunId);
        filterAndRenderFindings();
        renderDiffs(rawDiffs);
        renderCalls();
    } catch (e) {
        console.error("Refresh error:", e);
    }
}

// -------------------------------------------------------------
// Executive Scorecard Hero Rendering (4 KPIs)
// -------------------------------------------------------------

function renderExecutiveScorecard(det, findings, diffs, runs) {
    const assessment = det.assessment || {};
    const isClean = Boolean(assessment.is_clean === true && assessment.status === "clean");
    const isInconclusive = Boolean(assessment.is_inconclusive === true || assessment.status === "inconclusive");
    const hasIndicators = Boolean(
        assessment.status === "potential_indicators_detected" || 
        assessment.status === "indicators_detected" || 
        (assessment.findings_count > 0 && !isInconclusive)
    );

    // KPI 1: Assessment Verdict
    const badgeEl = document.getElementById("kpi-assessment-badge");
    const subEl = document.getElementById("kpi-assessment-sub");

    badgeEl.className = "kpi-badge";
    if (isClean) {
        badgeEl.classList.add("badge-clean");
        badgeEl.innerText = "VERIFIED CLEAN";
        subEl.innerText = "Fail-closed observed boundary";
    } else if (hasIndicators) {
        badgeEl.classList.add("badge-indicators");
        badgeEl.innerText = "INDICATORS DETECTED";
        subEl.innerText = `${findings.length} dark pattern indicators`;
    } else {
        badgeEl.classList.add("badge-inconclusive");
        badgeEl.innerText = "INCONCLUSIVE AUDIT";
        subEl.innerText = "Missing / obstructed flow";
    }

    // KPI 2: Pricing Disclosures & Drip Impact
    const priceValEl = document.getElementById("kpi-price-val");
    const priceSubEl = document.getElementById("kpi-price-sub");

    let dripFeeMinor = 0;
    let lateLabel = "";
    diffs.forEach(d => {
        if (d.type === "LATE_DISCLOSURE" && d.detail && d.detail.amount_minor) {
            dripFeeMinor = Math.max(dripFeeMinor, d.detail.amount_minor);
            lateLabel = d.detail.label || "Drip Fee";
        }
    });

    if (dripFeeMinor > 0) {
        priceValEl.innerText = `+₹${(dripFeeMinor / 100).toFixed(2)}`;
        priceValEl.style.color = "#f87171";
        priceSubEl.innerText = `${lateLabel} added at checkout`;
    } else if (isClean) {
        priceValEl.innerText = `₹0.00 Net Drip`;
        priceValEl.style.color = "#34d399";
        priceSubEl.innerText = "Upfront price matched across flow";
    } else if (isInconclusive) {
        priceValEl.innerText = `Unverified`;
        priceValEl.style.color = "#fbbf24";
        priceSubEl.innerText = "Checkout summary not inspected";
    } else {
        priceValEl.innerText = `₹0.00 Net Drip`;
        priceValEl.style.color = "#93c5fd";
        priceSubEl.innerText = "No unexpected fees disclosed";
    }

    // KPI 3: CCPA Dark Pattern Indicators
    const indValEl = document.getElementById("kpi-indicators-val");
    const indSubEl = document.getElementById("kpi-indicators-sub");

    const highCount = findings.filter(f => (f.severity || "").toLowerCase() === "high").length;
    const medCount = findings.filter(f => (f.severity || "").toLowerCase() === "medium").length;
    const lowCount = findings.filter(f => (f.severity || "").toLowerCase() === "low").length;

    indValEl.innerText = `${findings.length} Flagged`;
    if (findings.length > 0) {
        indValEl.style.color = "#f87171";
        indSubEl.innerText = `${highCount} High, ${medCount} Med, ${lowCount} Low`;
    } else {
        indValEl.style.color = "#34d399";
        indSubEl.innerText = "0 Violations under tested conditions";
    }

    // KPI 4: Evidence Integrity Score
    const integValEl = document.getElementById("kpi-integrity-val");
    const integSubEl = document.getElementById("kpi-integrity-sub");

    const refRun = runs.find(r => r.is_reference) || runs[0];
    const stageCaps = refRun ? (refRun.stage_captures || []) : [];
    const verifiedCaps = stageCaps.filter(c => c.capture_status === "verified");

    if (verifiedCaps.length === 3) {
        integValEl.innerText = "100% Verified";
        integValEl.style.color = "#34d399";
        integSubEl.innerText = "3 / 3 Stages SHA-256 Hashed";
    } else if (verifiedCaps.length > 0) {
        const pctInteg = Math.round((verifiedCaps.length / 3) * 100);
        integValEl.innerText = `${pctInteg}% Incomplete`;
        integValEl.style.color = "#fbbf24";
        integSubEl.innerText = `${verifiedCaps.length} of 3 Required Stages Verified`;
    } else {
        integValEl.innerText = "0% Captured";
        integValEl.style.color = "#94a3b8";
        integSubEl.innerText = "Awaiting stage captures";
    }
}

// -------------------------------------------------------------
// Assessment Status Banner
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
// Evidence Gallery (3-Stage Viewports)
// -------------------------------------------------------------

function renderEvidenceGallery(runs, targetRunId) {
    if (!runs || !runs.length) {
        resetGalleryCards();
        return;
    }

    let activeRun = null;
    if (targetRunId) {
        activeRun = runs.find(r => r.id === targetRunId);
    }
    if (!activeRun) {
        activeRun = runs.find(r => r.is_reference) || runs[0];
    }
    selectedRunId = activeRun ? activeRun.id : null;

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
// Interactive Findings Filtering & Rendering
// -------------------------------------------------------------

function setSeverityFilter(sev) {
    currentSeverityFilter = sev;
    document.querySelectorAll(".btn-filter").forEach(b => {
        if (b.getAttribute("data-severity") === sev) {
            b.classList.add("active");
        } else {
            b.classList.remove("active");
        }
    });
    filterAndRenderFindings();
}

function onSearchFindings() {
    currentFindingSearch = (document.getElementById("finding-search-input").value || "").toLowerCase().trim();
    filterAndRenderFindings();
}

function filterAndRenderFindings() {
    const list = document.getElementById("findings-list");
    let filtered = rawFindings;

    if (currentSeverityFilter !== "all") {
        filtered = filtered.filter(f => (f.severity || "").toLowerCase() === currentSeverityFilter);
    }

    if (currentFindingSearch) {
        filtered = filtered.filter(f => {
            const cat = (f.category || "").toLowerCase();
            const expl = (f.explanation || "").toLowerCase();
            const heu = (f.heuristic_note || "").toLowerCase();
            return cat.includes(currentFindingSearch) || expl.includes(currentFindingSearch) || heu.includes(currentFindingSearch);
        });
    }

    document.getElementById("findings-count-pill").innerText = `${filtered.length} of ${rawFindings.length} Found`;

    if (!filtered.length) {
        if (!rawFindings.length) {
            list.innerHTML = `<div class="empty-state">No dark pattern indicators detected in this flow.</div>`;
        } else {
            list.innerHTML = `<div class="empty-state">No indicators match current filter criteria.</div>`;
        }
        return;
    }

    list.innerHTML = filtered.map(f => `
        <div class="finding-item">
            <div class="finding-item-header">
                <span class="finding-cat">${escapeHtml((f.category || "").replace(/_/g, " "))}</span>
                <span class="finding-badge">${escapeHtml((f.severity || "").toUpperCase())} (${Math.round((f.confidence || 0) * 100)}%)</span>
            </div>
            <div class="finding-expl">${escapeHtml(f.explanation || "")}</div>
            ${f.heuristic_note ? `<div class="finding-heuristic">ℹ️ ${escapeHtml(f.heuristic_note)}</div>` : ""}
        </div>
    `).join("");
}

// -------------------------------------------------------------
// Matched-Pair Differential Matrix Rendering
// -------------------------------------------------------------

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
                <div class="diff-type">${escapeHtml(d.type)}</div>
                <div class="diff-desc">${escapeHtml(desc)}</div>
                <small style="color: #64748b; font-family: ui-monospace, SFMono-Regular, monospace;">Match: ${escapeHtml(d.matching_key || "-")}</small>
            </div>
        `;
    }).join("");
}

// -------------------------------------------------------------
// Provider Calls Pagination & Search
// -------------------------------------------------------------

function onSearchCalls() {
    callsSearch = (document.getElementById("calls-search-input").value || "").toLowerCase().trim();
    callsPage = 1;
    renderCalls();
}

function changeCallsPage(delta) {
    callsPage += delta;
    renderCalls();
}

function renderCalls() {
    const tbody = document.getElementById("calls-tbody");
    let filtered = rawCalls;

    if (callsSearch) {
        filtered = filtered.filter(c => {
            const op = (c.operation || "").toLowerCase();
            const stat = String(c.response_status || "");
            const reqId = (c.provider_request_id || "").toLowerCase();
            return op.includes(callsSearch) || stat.includes(callsSearch) || reqId.includes(callsSearch);
        });
    }

    const total = filtered.length;
    const maxPage = Math.max(1, Math.ceil(total / callsPageSize));
    if (callsPage > maxPage) callsPage = maxPage;
    if (callsPage < 1) callsPage = 1;

    const startIdx = (callsPage - 1) * callsPageSize;
    const pageItems = filtered.slice(startIdx, startIdx + callsPageSize);

    if (!pageItems.length) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: #94a3b8; padding: 20px;">No calls recorded.</td></tr>`;
    } else {
        tbody.innerHTML = pageItems.map(c => `
            <tr>
                <td>${(c.requested_at || "").substring(11, 19)}</td>
                <td style="font-weight: 600; color: #60a5fa;">${escapeHtml(c.operation)}</td>
                <td style="color: ${c.response_status === 200 || c.response_status === 201 ? '#10b981' : '#ef4444'}">${c.response_status || 'ERR'}</td>
                <td>${c.result_usable ? '✓ Yes' : '✗ No'}</td>
                <td style="font-family: ui-monospace, SFMono-Regular, monospace; font-size: 0.85em;">${escapeHtml(c.provider_request_id || '-')}</td>
            </tr>
        `).join("");
    }

    // Update pagination controls
    const prevBtn = document.getElementById("btn-calls-prev");
    const nextBtn = document.getElementById("btn-calls-next");
    const pageInfo = document.getElementById("calls-page-info");

    if (prevBtn) prevBtn.disabled = (callsPage <= 1);
    if (nextBtn) nextBtn.disabled = (callsPage >= maxPage);
    if (pageInfo) pageInfo.innerText = `Page ${callsPage} of ${maxPage} (${total} total calls)`;
}

// -------------------------------------------------------------
// Previous Audits History (Tab 4 & Home View)
// -------------------------------------------------------------

async function loadPastAudits() {
    try {
        const resp = await fetch("/audits");
        rawAudits = await resp.json();
        document.getElementById("tab-pill-history").innerText = String(rawAudits.length);

        renderHistoryTable();
        renderHomeHistoryTable();
    } catch (e) {
        console.error("Failed to load past audits:", e);
    }
}

function onSearchHistory() {
    historySearch = (document.getElementById("history-search-input").value || "").toLowerCase().trim();
    historyPage = 1;
    renderHistoryTable();
}

function changeHistoryPage(delta) {
    historyPage += delta;
    renderHistoryTable();
}

function renderHistoryTable() {
    const list = document.getElementById("audits-history-list");
    let filtered = rawAudits;

    if (historySearch) {
        filtered = filtered.filter(a => {
            const m = (a.merchant || "").toLowerCase();
            const id = (a.id || "").toLowerCase();
            return m.includes(historySearch) || id.includes(historySearch);
        });
    }

    const total = filtered.length;
    const maxPage = Math.max(1, Math.ceil(total / historyPageSize));
    if (historyPage > maxPage) historyPage = maxPage;
    if (historyPage < 1) historyPage = 1;

    const startIdx = (historyPage - 1) * historyPageSize;
    const pageItems = filtered.slice(startIdx, startIdx + historyPageSize);

    if (!pageItems.length) {
        list.innerHTML = `<div class="empty-state">No audits match search criteria.</div>`;
    } else {
        list.innerHTML = `
            <div class="table-responsive">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Date / Time</th>
                            <th>Merchant</th>
                            <th>Preset</th>
                            <th>Status</th>
                            <th>Findings</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${pageItems.map(a => `
                            <tr>
                                <td>${(a.created_at || '').substring(0, 16).replace('T', ' ')}</td>
                                <td><strong>${escapeHtml(a.merchant)}</strong></td>
                                <td><span class="badge badge-outline">${escapeHtml((a.preset || 'quick').toUpperCase())}</span></td>
                                <td><span style="color: ${a.status === 'complete' ? '#10b981' : '#f59e0b'}; font-weight: 600;">${escapeHtml(a.status)}</span></td>
                                <td><strong>${a.findings_count}</strong></td>
                                <td>
                                    <button type="button" class="btn-chip" onclick="selectAudit('${a.id}', '${escapeHtml(a.merchant)}')">Inspect Audit &rarr;</button>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;
    }

    const prevBtn = document.getElementById("btn-history-prev");
    const nextBtn = document.getElementById("btn-history-next");
    const pageInfo = document.getElementById("history-page-info");

    if (prevBtn) prevBtn.disabled = (historyPage <= 1);
    if (nextBtn) nextBtn.disabled = (historyPage >= maxPage);
    if (pageInfo) pageInfo.innerText = `Page ${historyPage} of ${maxPage} (${total} total audits)`;
}

function onSearchHomeHistory() {
    homeHistorySearch = (document.getElementById("home-history-search").value || "").toLowerCase().trim();
    homeHistoryPage = 1;
    renderHomeHistoryTable();
}

function changeHomeHistoryPage(delta) {
    homeHistoryPage += delta;
    renderHomeHistoryTable();
}

function renderHomeHistoryTable() {
    const list = document.getElementById("home-audits-list");
    let filtered = rawAudits;

    if (homeHistorySearch) {
        filtered = filtered.filter(a => {
            const m = (a.merchant || "").toLowerCase();
            const id = (a.id || "").toLowerCase();
            return m.includes(homeHistorySearch) || id.includes(homeHistorySearch);
        });
    }

    const total = filtered.length;
    const maxPage = Math.max(1, Math.ceil(total / homeHistoryPageSize));
    if (homeHistoryPage > maxPage) homeHistoryPage = maxPage;
    if (homeHistoryPage < 1) homeHistoryPage = 1;

    const startIdx = (homeHistoryPage - 1) * homeHistoryPageSize;
    const pageItems = filtered.slice(startIdx, startIdx + homeHistoryPageSize);

    if (!pageItems.length) {
        list.innerHTML = `<div class="empty-state">No audits recorded.</div>`;
    } else {
        list.innerHTML = `
            <div class="table-responsive">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Date / Time</th>
                            <th>Merchant</th>
                            <th>Preset</th>
                            <th>Status</th>
                            <th>Findings</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${pageItems.map(a => `
                            <tr>
                                <td>${(a.created_at || '').substring(0, 16).replace('T', ' ')}</td>
                                <td><strong>${escapeHtml(a.merchant)}</strong></td>
                                <td><span class="badge badge-outline">${escapeHtml((a.preset || 'quick').toUpperCase())}</span></td>
                                <td><span style="color: ${a.status === 'complete' ? '#10b981' : '#f59e0b'}; font-weight: 600;">${escapeHtml(a.status)}</span></td>
                                <td><strong>${a.findings_count}</strong></td>
                                <td>
                                    <button type="button" class="btn-chip" onclick="selectAudit('${a.id}', '${escapeHtml(a.merchant)}')">Inspect Audit &rarr;</button>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;
    }

    const prevBtn = document.getElementById("btn-home-history-prev");
    const nextBtn = document.getElementById("btn-home-history-next");
    const pageInfo = document.getElementById("home-history-page-info");

    if (prevBtn) prevBtn.disabled = (homeHistoryPage <= 1);
    if (nextBtn) nextBtn.disabled = (homeHistoryPage >= maxPage);
    if (pageInfo) pageInfo.innerText = `Page ${homeHistoryPage} of ${maxPage} (${total} total audits)`;
}

// -------------------------------------------------------------
// Audit Selection
// -------------------------------------------------------------

function selectAudit(auditId, merchant) {
    currentAuditId = auditId;
    selectedRunId = null;
    currentAuditRuns = [];

    // Collapse launcher when inspecting an audit
    toggleLauncher(false);

    document.getElementById("active-audit-section").classList.remove("hidden");
    document.getElementById("home-history-section").classList.add("hidden");

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
    switchTab("evidence");

    window.scrollTo({ top: 120, behavior: "smooth" });
}

// -------------------------------------------------------------
// Actions: Report, Complaint, Re-observe
// -------------------------------------------------------------

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
// Lightbox Modal
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

// -------------------------------------------------------------
// Utilities
// -------------------------------------------------------------

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
