// Checkout Radar Dashboard Client Application

let currentAuditId = null;
let eventSource = null;

document.addEventListener("DOMContentLoaded", () => {
    checkHealth();
    loadPastAudits();

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

        // Update progress
        const totalConds = det.conditions ? det.conditions.length : 1;
        const compRuns = det.runs ? det.runs.filter(r => r.finished_at).length : 0;
        const pct = Math.min(100, Math.round((compRuns / totalConds) * 100));
        document.getElementById("progress-bar").style.width = `${pct}%`;
        document.getElementById("progress-count").innerText = `${compRuns} / ${totalConds} runs`;

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
    document.getElementById("active-audit-section").classList.remove("hidden");
    document.getElementById("active-merchant").innerText = merchant;
    document.getElementById("active-audit-id").innerText = auditId;
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
