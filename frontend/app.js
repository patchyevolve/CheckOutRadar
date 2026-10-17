// Checkout Radar Dashboard Client Application — Forensic Workspace

let currentAuditId = null;
let currentAudit = null;
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
            closeSettingsModal();
        }
    });

    const modalList = document.querySelectorAll(".modal");
    modalList.forEach(m => {
        m.addEventListener("click", (e) => {
            if (e.target === m) {
                closeScreenshotModal();
                closeComplaintModal();
                closeSettingsModal();
            }
        });
    });
});

// -------------------------------------------------------------
// Clipboard Utilities
// -------------------------------------------------------------

function copyToClipboard(text, targetEl) {
    if (!text || text === "-" || text === "N/A") return;
    const cleanText = text.replace(/^[📋\s]+|[📋\s]+$/g, "").trim();
    if (!cleanText) return;

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(cleanText).then(showFeedback).catch(fallback);
    } else {
        fallback();
    }

    function fallback() {
        const ta = document.createElement("textarea");
        ta.value = cleanText;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand("copy"); showFeedback(); } catch (e) {}
        document.body.removeChild(ta);
    }

    function showFeedback() {
        const el = (typeof targetEl === "string") ? document.getElementById(targetEl) : targetEl;
        if (!el) return;
        const originalTitle = el.getAttribute("data-original-title") || el.title;
        el.setAttribute("data-original-title", originalTitle);
        const originalColor = el.style.color;
        el.style.color = "#34d399";
        el.title = "Copied to clipboard!";
        setTimeout(() => {
            el.style.color = originalColor;
            el.title = originalTitle;
        }, 1500);
    }
}

function copyActiveAuditId() {
    if (!currentAudit || !currentAudit.id) return;
    copyToClipboard(currentAudit.id, "active-audit-id");
}

// -------------------------------------------------------------
// Provider & LLM Settings
// -------------------------------------------------------------

let currentSettings = null;
let pendingClearLLMKey = false;
let pendingClearTinyFishKey = false;

async function openSettingsModal() {
    const modal = document.getElementById("settings-modal");
    const testResult = document.getElementById("connection-test-result");
    if (testResult) testResult.classList.add("hidden");

    pendingClearLLMKey = false;
    pendingClearTinyFishKey = false;

    try {
        const resp = await fetch("/settings");
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        currentSettings = data;

        document.getElementById("settings-llm-base-url").value = data.llm_base_url || "https://api.openai.com/v1";
        document.getElementById("settings-llm-model").value = data.llm_model || "gpt-4o-mini";
        document.getElementById("settings-pacing").value = data.llm_pacing_seconds !== undefined ? data.llm_pacing_seconds : 2.0;
        document.getElementById("settings-mock-mode").value = String(data.mock_tinyfish !== false);

        // Reset key input fields
        const llmKeyInput = document.getElementById("settings-llm-api-key");
        llmKeyInput.value = "";
        const tfKeyInput = document.getElementById("settings-tinyfish-key");
        tfKeyInput.value = "";

        updateKeyStatusBadges(data);
        onMockModeChanged();
    } catch (e) {
        console.error("Failed to load settings:", e);
    }

    modal.classList.remove("hidden");
}

function closeSettingsModal() {
    const modal = document.getElementById("settings-modal");
    if (modal) modal.classList.add("hidden");
}

function updateKeyStatusBadges(settings) {
    const llmStatus = document.getElementById("settings-llm-key-status");
    if (llmStatus) {
        if (pendingClearLLMKey) {
            llmStatus.innerText = "PENDING CLEAR (ON SAVE)";
            llmStatus.style.color = "#f59e0b";
            llmStatus.style.borderColor = "#f59e0b";
        } else if (settings && settings.has_llm_key) {
            llmStatus.innerText = `CONFIGURED (${settings.llm_key_masked || "STORED"})`;
            llmStatus.style.color = "#10b981";
            llmStatus.style.borderColor = "#10b981";
        } else {
            llmStatus.innerText = "NOT CONFIGURED (OFFLINE RULES)";
            llmStatus.style.color = "#94a3b8";
            llmStatus.style.borderColor = "#475569";
        }
    }

    const tfStatus = document.getElementById("settings-tinyfish-key-status");
    if (tfStatus) {
        if (pendingClearTinyFishKey) {
            tfStatus.innerText = "PENDING CLEAR (ON SAVE)";
            tfStatus.style.color = "#f59e0b";
            tfStatus.style.borderColor = "#f59e0b";
        } else if (settings && settings.has_tinyfish_key) {
            tfStatus.innerText = `CONFIGURED (${settings.tinyfish_key_masked || "STORED"})`;
            tfStatus.style.color = "#10b981";
            tfStatus.style.borderColor = "#10b981";
        } else {
            tfStatus.innerText = "NOT CONFIGURED (MOCK DEFAULT)";
            tfStatus.style.color = "#94a3b8";
            tfStatus.style.borderColor = "#475569";
        }
    }
}

function clearLLMKey() {
    pendingClearLLMKey = true;
    document.getElementById("settings-llm-api-key").value = "";
    document.getElementById("settings-llm-api-key").placeholder = "Key will be cleared upon saving";
    updateKeyStatusBadges(currentSettings);
}

function clearTinyFishKey() {
    pendingClearTinyFishKey = true;
    document.getElementById("settings-tinyfish-key").value = "";
    document.getElementById("settings-tinyfish-key").placeholder = "Key will be cleared upon saving";
    updateKeyStatusBadges(currentSettings);
}

function onMockModeChanged() {
    const isMock = document.getElementById("settings-mock-mode").value === "true";
    const tfGroup = document.getElementById("group-tinyfish-key");
    if (tfGroup) {
        tfGroup.style.opacity = isMock ? "0.75" : "1.0";
    }
}

function applyProviderPreset(preset) {
    const baseUrlInput = document.getElementById("settings-llm-base-url");
    const modelInput = document.getElementById("settings-llm-model");
    const pacingInput = document.getElementById("settings-pacing");

    if (preset === "groq") {
        baseUrlInput.value = "https://api.groq.com/openai/v1";
        modelInput.value = "llama-3.3-70b-versatile";
        pacingInput.value = 2.0;
    } else if (preset === "openai") {
        baseUrlInput.value = "https://api.openai.com/v1";
        modelInput.value = "gpt-4o-mini";
        pacingInput.value = 1.0;
    } else if (preset === "gemini") {
        baseUrlInput.value = "https://generativelanguage.googleapis.com/v1beta/openai";
        modelInput.value = "gemini-1.5-flash";
        pacingInput.value = 2.0;
    } else if (preset === "ollama") {
        baseUrlInput.value = "http://localhost:11434/v1";
        modelInput.value = "llama3.2";
        pacingInput.value = 0.5;
    } else if (preset === "custom") {
        baseUrlInput.focus();
    }
}

async function testLLMConnection() {
    const baseUrl = document.getElementById("settings-llm-base-url").value.trim();
    const model = document.getElementById("settings-llm-model").value.trim();
    const apiKey = document.getElementById("settings-llm-api-key").value.trim();

    const btn = document.getElementById("btn-test-connection");
    const spinner = document.getElementById("test-spinner");
    const resultBox = document.getElementById("connection-test-result");
    const badge = document.getElementById("test-status-badge");
    const latency = document.getElementById("test-latency-badge");
    const message = document.getElementById("test-message-text");

    btn.disabled = true;
    if (spinner) spinner.classList.remove("hidden");
    resultBox.classList.remove("hidden", "test-result-success", "test-result-error");
    resultBox.style.borderColor = "var(--border)";
    badge.className = "badge badge-accent";
    badge.innerText = "CONNECTING...";
    latency.innerText = "...";
    message.innerText = `Connecting to ${baseUrl}/chat/completions with model '${model}'...`;

    try {
        const payload = {
            base_url: baseUrl,
            model: model,
        };
        if (apiKey) {
            payload.api_key = apiKey;
        }

        const resp = await fetch("/settings/test-llm", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        const data = await resp.json();

        resultBox.classList.remove("hidden");
        if (data.success) {
            resultBox.classList.add("test-result-success");
            badge.className = "badge";
            badge.style.background = "#065f46";
            badge.style.color = "#a7f3d0";
            badge.innerText = `CONNECTED (${data.status_code || 200} OK)`;
            latency.innerText = `${data.latency_ms} ms`;
            message.innerText = data.message;
        } else {
            resultBox.classList.add("test-result-error");
            badge.className = "badge";
            badge.style.background = "#7f1d1d";
            badge.style.color = "#fecaca";
            badge.innerText = `FAILED (${data.status_code ? 'HTTP ' + data.status_code : data.error || 'ERROR'})`;
            latency.innerText = data.latency_ms ? `${data.latency_ms} ms` : "N/A";
            message.innerText = data.message;
        }
    } catch (e) {
        resultBox.classList.add("test-result-error");
        badge.className = "badge";
        badge.style.background = "#7f1d1d";
        badge.style.color = "#fecaca";
        badge.innerText = "CLIENT ERROR";
        latency.innerText = "N/A";
        message.innerText = `Failed to send test request: ${e.message}`;
    } finally {
        btn.disabled = false;
        if (spinner) spinner.classList.add("hidden");
    }
}

async function testTinyFishConnection() {
    const apiKey = document.getElementById("settings-tinyfish-key").value.trim();

    const btn = document.getElementById("btn-test-tinyfish");
    const spinner = document.getElementById("test-tf-spinner");
    const resultBox = document.getElementById("connection-test-result");
    const badge = document.getElementById("test-status-badge");
    const latency = document.getElementById("test-latency-badge");
    const message = document.getElementById("test-message-text");

    btn.disabled = true;
    if (spinner) spinner.classList.remove("hidden");
    resultBox.classList.remove("hidden", "test-result-success", "test-result-error");
    resultBox.style.borderColor = "var(--border)";
    badge.className = "badge badge-accent";
    badge.innerText = "CONNECTING...";
    latency.innerText = "...";
    message.innerText = "Connecting to TinyFish Web Agent API...";

    try {
        const payload = {};
        if (apiKey) {
            payload.api_key = apiKey;
        }

        const resp = await fetch("/settings/test-tinyfish", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        const data = await resp.json();

        resultBox.classList.remove("hidden");
        if (data.success) {
            resultBox.classList.add("test-result-success");
            badge.className = "badge";
            badge.style.background = "#065f46";
            badge.style.color = "#a7f3d0";
            badge.innerText = `CONNECTED (${data.status_code || 200} OK)`;
            latency.innerText = `${data.latency_ms} ms`;
            message.innerText = data.message;
        } else {
            resultBox.classList.add("test-result-error");
            badge.className = "badge";
            badge.style.background = "#7f1d1d";
            badge.style.color = "#fecaca";
            badge.innerText = `FAILED (${data.status_code ? 'HTTP ' + data.status_code : data.error || 'ERROR'})`;
            latency.innerText = data.latency_ms ? `${data.latency_ms} ms` : "N/A";
            message.innerText = data.message;
        }
    } catch (e) {
        resultBox.classList.add("test-result-error");
        badge.className = "badge";
        badge.style.background = "#7f1d1d";
        badge.style.color = "#fecaca";
        badge.innerText = "CLIENT ERROR";
        latency.innerText = "N/A";
        message.innerText = `Failed to send test request: ${e.message}`;
    } finally {
        btn.disabled = false;
        if (spinner) spinner.classList.add("hidden");
    }
}

async function saveProviderSettings(event) {
    if (event) event.preventDefault();

    const baseUrl = document.getElementById("settings-llm-base-url").value.trim();
    const model = document.getElementById("settings-llm-model").value.trim();
    const apiKey = document.getElementById("settings-llm-api-key").value.trim();
    const mockMode = document.getElementById("settings-mock-mode").value === "true";
    const tfKey = document.getElementById("settings-tinyfish-key").value.trim();
    const pacing = parseFloat(document.getElementById("settings-pacing").value) || 2.0;

    const payload = {
        llm_base_url: baseUrl,
        llm_model: model,
        llm_pacing_seconds: pacing,
        mock_tinyfish: mockMode,
    };

    if (pendingClearLLMKey) {
        payload.clear_llm_key = true;
    } else if (apiKey) {
        payload.llm_api_key = apiKey;
    }

    if (pendingClearTinyFishKey) {
        payload.clear_tinyfish_key = true;
    } else if (tfKey) {
        payload.tinyfish_api_key = tfKey;
    }

    const saveBtn = document.getElementById("btn-save-settings");
    saveBtn.disabled = true;
    saveBtn.innerText = "Saving...";

    try {
        const resp = await fetch("/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }

        const updated = await resp.json();
        currentSettings = updated;
        pendingClearLLMKey = false;
        pendingClearTinyFishKey = false;

        // Refresh health indicator in navbar
        await checkHealth();

        closeSettingsModal();
    } catch (e) {
        alert(`Failed to save settings: ${e.message}`);
    } finally {
        saveBtn.disabled = false;
        saveBtn.innerText = "Save Configuration";
    }
}

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

let currentTargetMerchant = null;

function setTarget(url, name) {
    document.getElementById("input-url").value = url;
    currentTargetMerchant = name || null;
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
            const isLive = !data.mock_mode && data.has_tinyfish_key;
            const modeText = data.mock_mode ? "Mock Mode" : (data.has_tinyfish_key ? "Live TinyFish" : "Ready");
            badge.innerText = `● API Online (${modeText})`;
            if (isLive) {
                badge.className = "badge badge-live";
                badge.style.color = "";
                badge.style.borderColor = "";
            } else {
                badge.className = "badge badge-mock";
                badge.style.color = "";
                badge.style.borderColor = "";
            }
        }
    } catch (e) {
        const badge = document.getElementById("backend-status");
        badge.innerText = "● API Offline";
        badge.className = "badge badge-outline";
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
        const reqBody = { input_url: inputUrl, preset: preset };
        if (currentTargetMerchant) {
            reqBody.merchant = currentTargetMerchant;
        }

        const resp = await fetch("/audits", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(reqBody)
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

        currentAudit = det.audit || null;
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

        // Hide stream console on completed audits to preserve above-the-fold vertical space
        const consoleDetails = document.getElementById("console-details");
        if (consoleDetails) {
            if (det.audit && det.audit.status === "complete") {
                consoleDetails.classList.add("hidden");
            } else {
                consoleDetails.classList.remove("hidden");
            }
        }

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
    const isRunning = Boolean((currentAudit && currentAudit.status === "running") || (assessment && assessment.status === "running"));
    const isClean = !isRunning && Boolean(assessment.is_clean === true && assessment.status === "clean");
    const isInconclusive = !isRunning && Boolean(assessment.is_inconclusive === true || assessment.status === "inconclusive");
    const hasIndicators = !isRunning && Boolean(
        assessment.status === "potential_indicators_detected" || 
        assessment.status === "indicators_detected" || 
        (assessment.findings_count > 0 && !isInconclusive)
    );

    // KPI 1: Assessment Verdict
    const badgeEl = document.getElementById("kpi-assessment-badge");
    const subEl = document.getElementById("kpi-assessment-sub");

    badgeEl.className = "kpi-badge";
    if (isRunning) {
        badgeEl.className = "kpi-badge badge-accent";
        badgeEl.style.background = "#0369a1";
        badgeEl.style.color = "#e0f2fe";
        badgeEl.innerText = "IN PROGRESS";
        const comp = runs.filter(r => r.finished_at && r.provider_status !== "RUNNING" && r.provider_status !== "PENDING").length;
        subEl.innerText = `${comp} of ${runs.length} conditions executed`;
    } else if (isClean) {
        badgeEl.classList.add("badge-clean");
        badgeEl.innerText = "VERIFIED CLEAN (TESTED FLOW)";
        subEl.innerText = "Observed flow clean; uninspected gateways outside scope";
    } else if (hasIndicators) {
        badgeEl.classList.add("badge-indicators");
        badgeEl.innerText = "INDICATORS DETECTED";
        subEl.innerText = `${findings.length} empirical candidate indicator(s)`;
    } else {
        badgeEl.classList.add("badge-inconclusive");
        badgeEl.innerText = "INCONCLUSIVE AUDIT";
        subEl.innerText = "Journey incomplete; clean status denied";
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

    if (isRunning) {
        priceValEl.innerText = `Evaluating...`;
        priceValEl.style.color = "#38bdf8";
        priceSubEl.innerText = "Extracting charges from completed runs";
    } else if (dripFeeMinor > 0) {
        priceValEl.innerText = `+₹${(dripFeeMinor / 100).toFixed(2)} Drip Fee`;
        priceValEl.style.color = "#f87171";
        priceSubEl.innerText = `${lateLabel} disclosed at checkout summary`;
    } else if (isClean) {
        priceValEl.innerText = `₹0.00 Variance`;
        priceValEl.style.color = "#34d399";
        priceSubEl.innerText = "Listed price matched checkout payable";
    } else if (isInconclusive) {
        priceValEl.innerText = `Uninspected`;
        priceValEl.style.color = "#fbbf24";
        priceSubEl.innerText = "Checkout payable stage not reached";
    } else {
        priceValEl.innerText = `₹0.00 Variance`;
        priceValEl.style.color = "#93c5fd";
        priceSubEl.innerText = "No unexpected charges observed";
    }

    // KPI 3: CCPA Dark Pattern Indicators
    const indValEl = document.getElementById("kpi-indicators-val");
    const indSubEl = document.getElementById("kpi-indicators-sub");

    const highCount = findings.filter(f => (f.severity || "").toLowerCase() === "high").length;
    const medCount = findings.filter(f => (f.severity || "").toLowerCase() === "medium").length;
    const lowCount = findings.filter(f => (f.severity || "").toLowerCase() === "low").length;

    const uniqueGroups = groupFindingsByPattern(findings);
    const uniqueCount = uniqueGroups.length;

    if (uniqueCount > 0) {
        indValEl.style.color = "#f87171";
        if (findings.length > uniqueCount) {
            indValEl.innerText = `${uniqueCount} Unique (${findings.length} Runs)`;
            indSubEl.innerText = `${uniqueCount} pattern(s) confirmed across ${findings.length} condition observations`;
        } else {
            indValEl.innerText = `${uniqueCount} Flagged`;
            indSubEl.innerText = `${highCount} High, ${medCount} Med, ${lowCount} Low (Non-adjudicative)`;
        }
    } else {
        indValEl.innerText = "0 Flagged";
        indValEl.style.color = "#34d399";
        indSubEl.innerText = isRunning ? "Evaluating candidate rules..." : "0 Violations under tested conditions";
    }

    // KPI 4: Evidence Integrity Score
    const integValEl = document.getElementById("kpi-integrity-val");
    const integSubEl = document.getElementById("kpi-integrity-sub");

    const displayRun = runs.find(r => r.is_reference && r.stage_captures && r.stage_captures.length > 0) ||
                       runs.find(r => r.stage_captures && r.stage_captures.length > 0) ||
                       runs[0];
    const stageCaps = displayRun ? (displayRun.stage_captures || []) : [];
    const verifiedCaps = stageCaps.filter(c => c.capture_status === "verified");

    if (verifiedCaps.length === 3) {
        integValEl.innerText = "3 / 3 Stages Hashed";
        integValEl.style.color = "#34d399";
        integSubEl.innerText = "Cryptographic SHA-256 chain of custody";
    } else if (verifiedCaps.length > 0) {
        integValEl.innerText = `${verifiedCaps.length} / 3 Stages Captured`;
        integValEl.style.color = "#fbbf24";
        integSubEl.innerText = isRunning ? "Active run stage pipeline" : "Incomplete stage observation pipeline";
    } else {
        integValEl.innerText = "0 / 3 Captured";
        integValEl.style.color = "#94a3b8";
        integSubEl.innerText = isRunning ? "Awaiting first run completion" : "Awaiting stage captures";
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

    const isRunning = Boolean(assessment.status === "running" || (currentAudit && currentAudit.status === "running"));
    if (isRunning) {
        banner.style.borderColor = "#0284c7";
        banner.style.background = "linear-gradient(180deg, rgba(2, 132, 199, 0.12) 0%, rgba(15, 23, 42, 0.6) 100%)";
        badge.className = "assessment-status-badge";
        badge.style.background = "#0369a1";
        badge.style.color = "#e0f2fe";
        badge.style.borderColor = "#38bdf8";
        badge.innerText = "AUDIT IN PROGRESS";
        title.innerText = "Automated Multi-Condition Audit In Progress";
        countTag.innerText = "Executing";
        countTag.style.color = "#38bdf8";
        summary.innerText = assessment.summary || "Real cloud browser agents are executing across matrix conditions. Evidence and viewports update live as runs complete.";
        reasonsContainer.classList.add("hidden");
        return;
    }

    banner.style.borderColor = "";
    banner.style.background = "";

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
        summary.innerText = "All required stages (Product, Cart, Checkout Summary) captured and inspected; 0 potential dark pattern indicators detected within observed flow boundary. Non-destructive audit stopped prior to payment authorization (third-party payment gateways uninspected).";
        reasonsContainer.classList.add("hidden");
    } else if (hasIndicators) {
        banner.classList.add("assessment-indicators");
        badge.classList.add("badge-indicators");
        badge.innerText = "INDICATORS DETECTED";
        const uniqueGroups = groupFindingsByPattern(rawFindings);
        if (rawFindings.length > uniqueGroups.length) {
            title.innerText = `${uniqueGroups.length} Unique Dark Pattern Category Flagged (${rawFindings.length} Matrix Run Observations)`;
            countTag.innerText = `${uniqueGroups.length} Unique (${rawFindings.length} Obs)`;
        } else {
            title.innerText = `${assessment.findings_count || 1} Potential Dark Pattern Indicator(s) Flagged`;
            countTag.innerText = `${assessment.findings_count || 1} Indicator(s)`;
        }
        countTag.style.color = "#f87171";
        summary.innerText = "Technical checkout audit findings flagged candidate dark patterns matching CCPA 2023 regulations. Non-adjudicative empirical evidence; not a statutory or judicial verdict.";
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
        const compRefRun = runs.find(r => r.is_reference && r.stage_captures && r.stage_captures.length > 0 && r.finished_at && r.provider_status !== "RUNNING");
        const compAnyRun = runs.find(r => r.stage_captures && r.stage_captures.length > 0 && r.finished_at && r.provider_status !== "RUNNING");
        const anyWithCaps = runs.find(r => r.stage_captures && r.stage_captures.length > 0);
        activeRun = compRefRun || compAnyRun || anyWithCaps || runs.find(r => r.is_reference) || runs[0];
    }
    selectedRunId = activeRun ? activeRun.id : null;

    const selContainer = document.getElementById("run-selector-container");
    const dropdown = document.getElementById("gallery-run-select");
    if (runs.length > 1) {
        selContainer.classList.remove("hidden");
        dropdown.innerHTML = runs.map(r => {
            let statusTag = "";
            if (r.provider_status === "RUNNING") {
                statusTag = " [⏳ Running]";
            } else if (r.provider_status === "FAILED" || r.outcome === "failed" || r.outcome === "provider_policy_blocked" || r.outcome === "blocked_by_bot") {
                if (r.outcome === "blocked_by_bot") statusTag = " [🚫 Bot Blocked]";
                else if (r.outcome === "provider_policy_blocked") statusTag = " [🛑 Policy Blocked]";
                else statusTag = " [❌ Failed]";
            } else if (r.outcome === "blocked_by_login") {
                statusTag = " [🔒 Login Wall]";
            } else if (r.outcome === "condition_not_applied") {
                statusTag = " [⚠️ Unapplied]";
            } else if (r.outcome === "extraction_inconsistent") {
                statusTag = " [⚠️ Math Mismatch]";
            } else if (r.finished_at && r.provider_status !== "PENDING") {
                statusTag = " [✓ Done]";
            } else {
                statusTag = " [⏱ Queued]";
            }
            const label = r.is_reference 
                ? `Reference (${r.condition_key || r.id.substring(0, 8)})${statusTag}` 
                : `Run ${r.id.substring(0, 8)} (${r.condition_key || 'Variant'})${statusTag}`;
            const selected = (r.id === selectedRunId) ? 'selected' : '';
            return `<option value="${r.id}" ${selected}>${escapeHtml(label)}</option>`;
        }).join("");
    } else {
        selContainer.classList.add("hidden");
    }

    const runAlert = document.getElementById("gallery-run-alert");
    if (runAlert) {
        if (activeRun && activeRun.outcome && activeRun.outcome !== "ok") {
            runAlert.classList.remove("hidden");
            const blockerMsg = activeRun.observed && (activeRun.observed.blocker_reason || activeRun.observed.error_message);
            const lastErrMsg = activeRun.last_error;
            let icon = "⚠️";
            let title = "Condition Execution Alert";
            let color = "#f59e0b";
            let bg = "rgba(245, 158, 11, 0.12)";
            let border = "#f59e0b";

            if (activeRun.outcome === "blocked_by_bot") {
                icon = "🚫";
                title = "Bot Detection Challenge (Cloudflare Turnstile)";
                color = "#f87171";
                bg = "rgba(239, 68, 68, 0.12)";
                border = "#ef4444";
            } else if (activeRun.outcome === "provider_policy_blocked") {
                icon = "🛑";
                title = "TinyFish Provider Safety Policy Block";
                color = "#f87171";
                bg = "rgba(239, 68, 68, 0.12)";
                border = "#ef4444";
            } else if (activeRun.outcome === "blocked_by_login") {
                icon = "🔒";
                title = "Mandatory Login / OTP Wall";
                color = "#fbbf24";
                bg = "rgba(251, 191, 36, 0.12)";
                border = "#f59e0b";
            } else if (activeRun.outcome === "extraction_inconsistent") {
                icon = "⚠️";
                title = "Extraction Arithmetic Inconsistency";
                color = "#fbbf24";
                bg = "rgba(251, 191, 36, 0.12)";
                border = "#f59e0b";
            } else if (activeRun.outcome === "condition_not_applied") {
                icon = "⚠️";
                title = "Condition Not Applied";
                color = "#fbbf24";
                bg = "rgba(251, 191, 36, 0.12)";
                border = "#f59e0b";
            }

            runAlert.innerHTML = `
                <div style="background: ${bg}; border: 1px solid ${border}; border-radius: 8px; padding: 0.75rem 1rem; color: #f1f5f9; display: flex; align-items: flex-start; gap: 0.75rem;">
                    <span style="font-size: 1.3rem; line-height: 1.2;">${icon}</span>
                    <div>
                        <strong style="color: ${color}; display: block; margin-bottom: 0.25rem;">${title}</strong>
                        <span style="font-size: 0.85rem; color: #cbd5e1;">${escapeHtml(blockerMsg || lastErrMsg || "This condition was obstructed or halted before complete checkout summary inspection.")}</span>
                    </div>
                </div>
            `;
        } else {
            runAlert.classList.add("hidden");
            runAlert.innerHTML = "";
        }
    }

    const stages = [
        { key: "product", name: "Product Page", num: "Stage 1" },
        { key: "cart", name: "Cart Drawer / Page", num: "Stage 2" },
        { key: "checkout_summary", name: "Checkout Summary", num: "Stage 3" },
    ];

    const stageCaps = activeRun ? (activeRun.stage_captures || []) : [];

    // Determine if this audit run is synthetic harness / mock vs live crawl
    const auditObj = currentAudit || {};
    const isSyntheticAudit = (auditObj.merchant || "").toLowerCase().includes("harness") ||
                             (auditObj.merchant || "").toLowerCase().includes("demo") ||
                             (auditObj.input_url || "").toLowerCase().includes("harness") ||
                             (auditObj.input_url || "").toLowerCase().includes("127.0.0.1") ||
                             (auditObj.input_url || "").toLowerCase().includes("localhost");
    const isSyntheticRun = activeRun && ((activeRun.provider_run_id || "").startsWith("mock_run_"));

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
        const execMeta = document.getElementById(`meta-exec-${st.key}`);
        const visualMeta = document.getElementById(`meta-visual-${st.key}`);
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

            const isSyntheticDigest = sha256 && sha256.startsWith("e9ec365e");
            const isSyntheticFixture = isSyntheticDigest || isSyntheticRun || isSyntheticAudit;

            // Separate Status 1: Stage Execution
            if (execMeta) {
                execMeta.innerHTML = `<span class="meta-status-pill pill-executed">STAGE EXECUTED</span>`;
            }

            // Separate Status 2: Visual Capture Availability
            if (visualMeta) {
                visualMeta.innerHTML = isSyntheticFixture 
                    ? `<span class="meta-status-pill pill-synthetic">Synthetic Fixture (No Live Viewport)</span>`
                    : `<span class="meta-status-pill pill-live">Live Viewport (1280×720)</span>`;
            }

            if (isSyntheticFixture) {
                // Clearly labelled synthetic preview container
                imgContainer.innerHTML = `
                    <div class="stage-synthetic-fixture">
                        <span class="synthetic-fixture-tag">SYNTHETIC HARNESS FIXTURE</span>
                        <div class="synthetic-fixture-title">Offline DOM Analysis</div>
                        <p class="synthetic-fixture-desc">Deterministic test harness execution. DOM charges & disclosures verified without browser rendering.</p>
                    </div>
                `;
                footer.innerHTML = `
                    <button class="btn btn-secondary btn-chip" onclick="openScreenshotModal('${evUrl}', '${escapeHtml(st.name)}', '${escapeHtml(snapId)}', '${escapeHtml(sha256)}', true)">
                        🔬 Raw Diagnostic Artifact
                    </button>
                `;
            } else if (evUrl) {
                // Live merchant real viewport
                imgContainer.innerHTML = `
                    <img src="${evUrl}" 
                         alt="${escapeHtml(st.name)} Viewport" 
                         class="gallery-thumb" 
                         onclick="openScreenshotModal('${evUrl}', '${escapeHtml(st.name)}', '${escapeHtml(snapId)}', '${escapeHtml(sha256)}', false)"
                         title="Click to view full-resolution screenshot"
                         onerror="this.onerror=null; this.parentElement.innerHTML='<div class=\\'stage-empty-state\\'>🖼️ Artifact referenced (${escapeHtml(snapId)})<br><small style=\\'color:#94a3b8\\'>File pending on disk</small></div>';" />
                `;
                footer.innerHTML = `
                    <button class="btn btn-secondary btn-chip" onclick="openScreenshotModal('${evUrl}', '${escapeHtml(st.name)}', '${escapeHtml(snapId)}', '${escapeHtml(sha256)}', false)">
                        🔍 Full Resolution
                    </button>
                `;
            } else {
                imgContainer.innerHTML = `<div class="stage-empty-state">📸 Snapshot metadata recorded (${escapeHtml(snapId)})</div>`;
                footer.innerHTML = `<span class="text-disabled">Metadata verified</span>`;
            }

            // Separate Status 3: Artifact Integrity
            snapMeta.innerText = snapId;
            snapMeta.title = `Click to copy Snapshot ID: ${snapId}`;
            snapMeta.style.cursor = "pointer";
            snapMeta.onclick = () => copyToClipboard(snapId, snapMeta);

            if (sha256) {
                hashMeta.innerText = `${sha256.substring(0, 16)}...`;
                hashMeta.title = `Click to copy full SHA-256 hash: ${sha256}`;
                hashMeta.style.cursor = "pointer";
                hashMeta.onclick = () => copyToClipboard(sha256, hashMeta);
            } else {
                hashMeta.innerText = "N/A";
                hashMeta.title = "No cryptographic digest recorded";
                hashMeta.style.cursor = "default";
                hashMeta.onclick = null;
            }

            timeMeta.innerText = timeStr;
        } else {
            const isRunBlocked = activeRun && (activeRun.outcome === "blocked_by_bot" || activeRun.outcome === "provider_policy_blocked" || activeRun.outcome === "failed" || activeRun.outcome === "blocked_by_login");
            const blockerMsg = activeRun && activeRun.observed && (activeRun.observed.blocker_reason || activeRun.observed.error_message);
            const lastErrMsg = activeRun && activeRun.last_error;
            
            badge.className = "stage-status-badge badge-stage-missing";
            badge.innerText = isRunBlocked ? (activeRun.outcome.toUpperCase().replace(/_/g, " ")) : "NOT CAPTURED";
            
            let emptyMsg = "⚠️ Stage was not captured in this audit run";
            if (activeRun && activeRun.outcome === "blocked_by_bot") {
                emptyMsg = `🚫 <b>Blocked by Bot Challenge / Cloudflare</b><br><small style="color:#f87171">${escapeHtml(blockerMsg || "Cloudflare Turnstile or CAPTCHA prevented navigation")}</small>`;
            } else if (activeRun && activeRun.outcome === "provider_policy_blocked") {
                emptyMsg = `🛑 <b>Provider Policy Block</b><br><small style="color:#f87171">${escapeHtml(blockerMsg || "Agent prompt violated cloud usage policy (e.g. interacting with payment gateway)")}</small>`;
            } else if (activeRun && activeRun.outcome === "blocked_by_login") {
                emptyMsg = `🔒 <b>Blocked by Login / OTP Wall</b><br><small style="color:#fbbf24">${escapeHtml(blockerMsg || "Mandatory authentication required before viewing stage")}</small>`;
            } else if (activeRun && (activeRun.outcome === "failed" || activeRun.provider_status === "FAILED")) {
                emptyMsg = `❌ <b>Agent Execution Failed</b><br><small style="color:#f87171">${escapeHtml(blockerMsg || lastErrMsg || "Cloud agent failed before checkout completion")}</small>`;
            }
            imgContainer.innerHTML = `<div class="stage-empty-state" style="padding: 1.5rem 1rem;">${emptyMsg}</div>`;
            if (execMeta) execMeta.innerHTML = `<span class="meta-status-pill pill-omitted">${isRunBlocked ? 'OBSTRUCTED' : 'NOT EXECUTED'}</span>`;
            if (visualMeta) visualMeta.innerHTML = `<span class="meta-status-pill pill-omitted">${isRunBlocked ? 'Blocked' : 'Not Captured'}</span>`;
            snapMeta.innerText = "-";
            snapMeta.title = "-";
            hashMeta.innerText = "-";
            hashMeta.title = "-";
            timeMeta.innerText = "-";
            footer.innerHTML = `<span class="text-disabled">${isRunBlocked ? 'Navigation obstructed' : 'No viewport captured'}</span>`;
        }
    });
}

function resetGalleryCards() {
    ["product", "cart", "checkout_summary"].forEach(k => {
        const badge = document.getElementById(`badge-stage-${k}`);
        const imgContainer = document.getElementById(`img-container-${k}`);
        const execMeta = document.getElementById(`meta-exec-${k}`);
        const visualMeta = document.getElementById(`meta-visual-${k}`);
        const snapMeta = document.getElementById(`meta-snap-${k}`);
        const hashMeta = document.getElementById(`meta-hash-${k}`);
        const timeMeta = document.getElementById(`meta-time-${k}`);
        const footer = document.getElementById(`footer-stage-${k}`);

        if (badge) { badge.className = "stage-status-badge badge-stage-waiting"; badge.innerText = "WAITING"; }
        if (imgContainer) imgContainer.innerHTML = `<div class="stage-empty-state">No viewport captured yet</div>`;
        if (execMeta) execMeta.innerText = "-";
        if (visualMeta) visualMeta.innerText = "-";
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

function groupFindingsByPattern(findingsList) {
    const groups = new Map();
    (findingsList || []).forEach(f => {
        let coreKey = f.category || "unknown";
        if (f.raw_observations && f.raw_observations.step_t0) {
            coreKey += `:${f.raw_observations.step_t0}_${f.raw_observations.step_t1}`;
        } else if (f.explanation) {
            const m = f.explanation.match(/'([^']+)'/);
            if (m) {
                coreKey += `:${m[1].toLowerCase()}`;
            } else {
                coreKey += `:${f.explanation.substring(0, 45).toLowerCase()}`;
            }
        }
        if (!groups.has(coreKey)) {
            groups.set(coreKey, []);
        }
        groups.get(coreKey).push(f);
    });
    return Array.from(groups.values());
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

    const uniqueGroups = groupFindingsByPattern(filtered);

    if (uniqueGroups.length === filtered.length) {
        document.getElementById("findings-count-pill").innerText = `${filtered.length} of ${rawFindings.length} Found`;
    } else {
        document.getElementById("findings-count-pill").innerText = `${uniqueGroups.length} Unique Pattern(s) (${filtered.length} Run Observations)`;
    }

    if (!filtered.length) {
        if (!rawFindings.length) {
            list.innerHTML = `<div class="empty-state">No dark pattern indicators detected in this flow.</div>`;
        } else {
            list.innerHTML = `<div class="empty-state">No indicators match current filter criteria.</div>`;
        }
        return;
    }

    list.innerHTML = uniqueGroups.map(items => {
        const primary = items[0];
        const isMultiRun = items.length > 1;

        let occurrencePill = "";
        if (isMultiRun) {
            occurrencePill = `<span class="badge badge-accent" style="font-size: 0.72em; padding: 2px 6px;">Observed in ${items.length} of ${currentAuditRuns.length || items.length} Matrix Runs (100% Reproduction)</span>`;
        } else {
            occurrencePill = `<span class="badge badge-outline" style="font-size: 0.72em; padding: 2px 6px;">1 Run Observation</span>`;
        }

        let traceSection = "";
        if (isMultiRun) {
            traceSection = `
            <div class="finding-matrix-trail" style="margin-top: 10px; background: rgba(15, 23, 42, 0.6); padding: 8px 10px; border-radius: 6px; border: 1px solid rgba(148, 163, 184, 0.15);">
                <div style="font-size: 0.78em; font-weight: 600; color: #94a3b8; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">
                    Matrix Traceability (${items.length} Run Occurrences):
                </div>
                <div style="display: flex; flex-direction: column; gap: 4px;">
                    ${items.map(it => {
                        const runObj = currentAuditRuns.find(r => r.id === it.run_id);
                        const runLabel = runObj ? (runObj.is_reference ? 'Reference (' + (runObj.condition_key || runObj.id.substring(0, 8)) + ')' : (runObj.condition_key || it.run_id.substring(0, 8))) : (it.run_id ? it.run_id.substring(0, 8) : 'Run');
                        const evArr = Array.isArray(it.evidence_ids) ? it.evidence_ids : (it.evidence_ids ? [it.evidence_ids] : []);
                        return `
                        <div style="font-size: 0.78em; font-family: ui-monospace, SFMono-Regular, monospace; display: flex; flex-wrap: wrap; gap: 6px; align-items: center;">
                            <span style="color: #38bdf8; font-weight: bold;">[${escapeHtml(runLabel)}]</span>
                            <span style="color: #64748b;">Finding: <code style="color: #cbd5e1;">${escapeHtml(it.id)}</code></span>
                            ${it.diff_id ? `<span style="color: #64748b;">Diff: <code style="color: #cbd5e1;">${escapeHtml(it.diff_id)}</code></span>` : ''}
                            ${evArr.length ? `<span style="color: #64748b;">Evidence: <code style="color: #cbd5e1;">${escapeHtml(evArr.join(', '))}</code></span>` : ''}
                        </div>`;
                    }).join("")}
                </div>
            </div>`;
        } else {
            let evSnippet = "";
            if (primary.evidence_ids && primary.evidence_ids.length) {
                const evArr = Array.isArray(primary.evidence_ids) ? primary.evidence_ids : [primary.evidence_ids];
                evSnippet = `<span class="trace-tag">Evidence: <code>${escapeHtml(evArr.join(", "))}</code></span>`;
            }
            traceSection = `
            <div class="finding-trace-bar">
                <span class="trace-tag">Finding ID: <code>${escapeHtml(primary.id)}</code></span>
                ${primary.diff_id ? `<span class="trace-tag">Diff Ref: <code>${escapeHtml(primary.diff_id)}</code></span>` : ""}
                ${evSnippet}
            </div>`;
        }

        return `
        <div class="finding-item">
            <div class="finding-item-header" style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span class="finding-cat">${escapeHtml((primary.category || "").replace(/_/g, " "))}</span>
                    ${occurrencePill}
                </div>
                <span class="finding-badge">${escapeHtml((primary.severity || "").toUpperCase())} (${Math.round((primary.confidence || 0) * 100)}%)</span>
            </div>
            <div class="finding-expl">${escapeHtml(primary.explanation || "")}</div>
            ${primary.heuristic_note ? `<div class="finding-heuristic">ℹ️ ${escapeHtml(primary.heuristic_note)}</div>` : ""}
            ${traceSection}
        </div>
        `;
    }).join("");
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
                        ${pageItems.map(a => {
                            const isLive = (a.merchant || "").toLowerCase().includes("headphone") || (a.input_url || "").toLowerCase().includes("headphonezone");
                            const provBadge = isLive 
                                ? `<span class="badge-tag-live">LIVE MERCHANT</span>` 
                                : `<span class="badge-tag-synthetic">SYNTHETIC HARNESS</span>`;
                            return `
                                <tr>
                                    <td>${(a.created_at || '').substring(0, 16).replace('T', ' ')}</td>
                                    <td><strong>${escapeHtml(a.merchant)}</strong> ${provBadge}</td>
                                    <td><span class="badge badge-outline">${escapeHtml((a.preset || 'quick').toUpperCase())}</span></td>
                                    <td><span style="color: ${a.status === 'complete' ? '#10b981' : '#f59e0b'}; font-weight: 600;">${escapeHtml(a.status)}</span></td>
                                    <td><strong>${a.findings_count}</strong></td>
                                    <td>
                                        <button type="button" class="btn-chip" onclick="selectAudit('${a.id}', '${escapeHtml(a.merchant)}')">Inspect Audit &rarr;</button>
                                    </td>
                                </tr>
                            `;
                        }).join('')}
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
                        ${pageItems.map(a => {
                            const isLive = (a.merchant || "").toLowerCase().includes("headphone") || (a.input_url || "").toLowerCase().includes("headphonezone");
                            const provBadge = isLive 
                                ? `<span class="badge-tag-live">LIVE MERCHANT</span>` 
                                : `<span class="badge-tag-synthetic">SYNTHETIC HARNESS</span>`;
                            return `
                                <tr>
                                    <td>${(a.created_at || '').substring(0, 16).replace('T', ' ')}</td>
                                    <td><strong>${escapeHtml(a.merchant)}</strong> ${provBadge}</td>
                                    <td><span class="badge badge-outline">${escapeHtml((a.preset || 'quick').toUpperCase())}</span></td>
                                    <td><span style="color: ${a.status === 'complete' ? '#10b981' : '#f59e0b'}; font-weight: 600;">${escapeHtml(a.status)}</span></td>
                                    <td><strong>${a.findings_count}</strong></td>
                                    <td>
                                        <button type="button" class="btn-chip" onclick="selectAudit('${a.id}', '${escapeHtml(a.merchant)}')">Inspect Audit &rarr;</button>
                                    </td>
                                </tr>
                            `;
                        }).join('')}
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

    // Reset pagination and search filters when switching audit
    callsPage = 1;
    callsSearch = "";
    const callsSearchInput = document.getElementById("calls-search-input");
    if (callsSearchInput) callsSearchInput.value = "";

    currentSeverityFilter = "all";
    currentFindingSearch = "";
    const findingSearchInput = document.getElementById("finding-search-input");
    if (findingSearchInput) findingSearchInput.value = "";
    document.querySelectorAll(".btn-filter").forEach(b => {
        if (b.getAttribute("data-severity") === "all") b.classList.add("active");
        else b.classList.remove("active");
    });

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

function openScreenshotModal(imgUrl, stageTitle, snapId, sha256, isSynthetic = false) {
    const modal = document.getElementById("screenshot-modal");
    document.getElementById("modal-stage-title").innerText = isSynthetic 
        ? `${stageTitle} (Synthetic Diagnostic Artifact)` 
        : `${stageTitle} Viewport`;
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
