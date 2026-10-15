# 📡 Checkout Radar

> **Outside-In Checkout Flow Auditor & CCPA Dark Pattern Detector**  
> *AZINHACK 2026 Submission* · Team of 4

[![CI Tests](https://img.shields.io/badge/tests-76%20passed-brightgreen.svg)]()
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)]()
[![Docker Compose](https://img.shields.io/badge/docker--compose-ready-blue.svg)]()
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)]()

Checkout Radar audits e-commerce checkout funnels from the outside in. By executing identical checkout tasks across controlled variations (Delivery Pincode, Session History, Cart Value, and Observation Time) using **TinyFish** web agents, it extracts every itemized charge, deterministically diffs the flow, and produces timestamped, screenshot-backed evidence of potential dark pattern indicators mapped directly to the **CCPA 2023 Dark Pattern Guidelines**.

---

## 1. Problem & Positioning

Indian e-commerce and quick-commerce fees (handling, platform, convenience, surge, and small-cart fees) frequently appear late in the funnel or vary arbitrarily across sessions and locations. While the **Central Consumer Protection Authority (CCPA)** notified dark pattern guidelines in November 2023 prohibiting practices like *Drip Pricing* and *Basket Sneaking*, consumers, consumer-rights organizations, and journalists lack continuous, empirical auditing tools.

**Target Users:**
- **Consumers & Consumer Groups:** Continuous evidence gathering for grievance filings.
- **Journalists & Researchers:** Empirical data on fee inflation and deceptive flows.
- **Compliance Teams:** Outside-in auditing to ensure transparency standards before regulatory scrutiny.

*Hard Invariant:* Findings represent potential computational indicators, never judicial verdicts.

---

## 2. Core Method: The Condition Matrix

Checkout Radar uses **matched-pair differential auditing**—comparing runs that differ in *exactly one requested dimension*:

| Dimension | Reference Condition | Matched Comparison | Controls Kept Fixed |
|---|---|---|---|
| **Location Effect** | Pincode A (Tier-1) | Pincode B, C (Tier-2/3) | Session, Cart Tier, Recipe Family |
| **Session Effect** | Fresh Profile | Returning Profile | Pincode, Cart Tier, Recipe Family |
| **Cart Threshold** | Above Threshold (e.g. ₹998) | Below Threshold (e.g. ₹499) | Pincode, Session, Recipe Family |
| **Temporal Drift** | Time $t_0$ | Scheduled Re-observation $t_1$ | All Conditions & Cart Recipe |

### Cart Invariant & Separation of Recipe Family from Instantiated Cart
Changing cart quantity moves total value without altering unit prices. Checkout Radar separates:
- **Recipe Family:** Identical product IDs, variants, pricing context, and construction rules.
- **Cart Instance:** Quantity required to cross the threshold (e.g. 1 unit vs 2 units).
- **Rule Verification:** Quantity changes do **not** trigger `PRICE_VARIANCE`. A fee present only on the below-threshold side is reported as a legitimate `SMALL_CART_RULE`, not mistaken for a deceptive fee.

---

## 3. Architecture & Reliability

```
[ Dashboard (Web UI) ] ─── REST + SSE ───► [ FastAPI API ] ──► [ SQLite DB ]
                                                 │ enqueue         ▲
                                          [ Durable Jobs ] ────────┘
                                                 │
                  ┌──────────────────────────────┴──────────────────────────────┐
                  ▼                                                             ▼
         [ Matrix Orchestrator ]                                        [ Worker Daemon ]
                  │                                                             │
                  ├─► TinyFish Search (Merchant/Policy Discovery)               ├─► Diff Engine (5 Types)
                  ├─► TinyFish Fetch (Cached TTL Policy Extraction)             ├─► CCPA Rule Detectors
                  └─► TinyFish Agent (Async multi-condition runs)               ├─► Schema-validated LLM Classifier
                                                                                └─► Append-only Evidence Store
```

### Key Reliability Mechanisms
1. **Durable Job Table with Lease Recovery:** On worker startup or lease expiration, the system queries TinyFish for the existing `provider_run_id` before deciding to retry. Live runs are **never resubmitted**, avoiding duplicate credit usage.
2. **Deterministic First, LLM Last:** The deterministic diff engine and rule detectors produce candidate indicators; the LLM strictly classifies and contextualizes against CCPA legal text.
3. **Monetary Reconciliation in Integer Minor Units:** Every extraction is checked against:  
   $$\text{Subtotal} + \text{Charges} + \text{Taxes} - \text{Discounts} = \text{Final Payable}$$  
   If the equation fails, the run outcome is flagged `extraction_inconsistent` and excluded from diffs.
4. **Append-Only Evidence Store & Privacy Redaction:** Step screenshots are redacted for privacy (solid bottom-5% mask by default for sticky cookie/footer bars, with optional targeted bounding-box redaction for form fields), saved to disk, and verified with an immutable SHA-256 hash. *Architectural Audit Finding:* Fixed bottom-5% masking protects footers but leaves middle/upper form fields unmasked; targeted coordinate bounding boxes or full OCR pipelines are required for form-level PII.

---

## 4. TinyFish Integration Contract

TinyFish is central and in the main execution path:

| TinyFish API | Endpoint | Role in Checkout Radar |
|---|---|---|
| **Search API** | `GET https://api.search.tinyfish.ai` | Discovers merchant pricing policies, terms of service, and cancellation links in every demo audit. |
| **Fetch API** | `POST https://api.fetch.tinyfish.ai` | Extracts clean terms and conditions text with cached TTL freshness policy (`ttl: 0` for live pricing, `ttl: 3600` for policies). |
| **Agent API** | `POST https://agent.tinyfish.ai/v1/automation/run-async` | Runs multi-condition checkout automations with CCPA guardrails and output schema. |
| **Profiles API**| `POST/DELETE https://agent.tinyfish.ai/v1/profiles` | Creates isolated Browser Context Profiles per returning condition to prevent state leakage. |
| **Runs & Screenshots**| `GET /v1/runs/{id}`, `/runs/{id}/steps/{stepId}/screenshot` | Polls execution status and downloads step screenshot bytes. |

*Day-0 Spike Status:* **PASS** (All 6 core capabilities verified on live production account). See [docs/SPIKE_REPORT.md](docs/SPIKE_REPORT.md).

---

## 5. Five-Variant Demo Merchant Harness

The separate `harness` container provides 5 reproducible merchant checkout variants:

1. **Clean Merchant:** All delivery and handling charges disclosed upfront on the product page. *(Negative Control: Expected 0 findings)*
2. **Late Disclosure:** A ₹5.00 Handling Fee is concealed until the final checkout summary. *(Adversarial: Expected Drip Pricing indicator)*
3. **Add-on + Countdown:** A ₹15.00 Package Protection is checked by default and included in the total, alongside a timer that restarts every 30 seconds. *(Adversarial: Expected Basket Sneaking & False Urgency indicators)*
4. **Upfront Fee:** Mandatory convenience fee disclosed upfront on product page. *(Negative Control: Expected 0 findings)*
5. **Legitimate Threshold:** Free delivery above ₹500, flat ₹40 fee below ₹500. *(Negative Control: Reported as `SMALL_CART_RULE`, not deceptive)*

---

## 6. Evaluation & Benchmark Framework

Checkout Radar employs a three-tier evaluation methodology:

### Tier 1: Synthetic Scenario Benchmark — 45 Designed Fixtures (Rules-Only Unit Regression)
Deterministic acceptance suite verifying algorithm conformance against known dark pattern patterns:
- **15 Clean Bundles:** Negative controls across upfront fee, legitimate cart thresholds, and standard itemization.
- **12 Drip Pricing Bundles:** Mandatory fees disclosed late at checkout with verified absent upfront disclosures.
- **10 Basket Sneaking Bundles:** Pre-selected add-ons (insurance, donation, priority wrap) included in total payable.
- **8 False Urgency Bundles:** Controlled countdown resets (holding page and session fixed) and expiration anomalies.

```
Total Evaluated Fixtures: 45 synthetic bundles
Detection Performance: Precision 100%, Recall 100%, F1-Score 1.000 (0 false positives on negative controls)
Classification Conformance: 100% (30/30) on designed scenario fixtures
Note: Reflects deterministic regression conformance on designed test cases; does not represent uncurated production performance.
```

### Tier 2: Downstream LLM Verification, Semantic Guardrails & Statutory Explanation
The LLM does not alter detection boundaries; candidate indicators are strictly produced upstream by the deterministic diff engine. Only candidate findings from positive scenario bundles are queued for downstream classification ($N = 30$ candidates; the 15 clean bundles emit zero candidate indicators and zero outbound provider requests).

- **Execution Provenance:** Recorded live remote provider run (`openai/gpt-oss-20b` via Groq) against commit `0f2c227` with a clean working tree.
- **Persisted Telemetry Artifact:** Durably recorded in `evaluation/last_run_telemetry.json`. All reported metrics are calculated directly from this persisted record set via `calculate_metrics_from_records` and can be replayed anytime via `python3 evaluation/run_evaluation.py --from-telemetry evaluation/last_run_telemetry.json`.
- **HTTP Transport Round-Trips (Denominator = 30 Outbound Network Calls):**
  1. *Total Outbound Requests:* 30 calls (30 initial submissions; 0 corrective retries triggered).
  2. *HTTP Responses Received:* **30 / 30 (100.0%)** completed network round-trips returning an HTTP status code.
     - HTTP 200 OK: **2 / 30 (6.7%)**
     - HTTP 429 Rate Limit: **28 / 30 (93.3%)**
  3. *Network Transport Errors:* **0 / 30 (0.0%)** failed before HTTP negotiation (zero connection drops or DNS timeouts).
- **Model Output Coverage (Denominator = 30 Submitted Candidates):**
  4. *Initial Model Responses:* **2 / 30 (6.7%)** returned usable model completions on first attempt.
  5. *Initial HTTP Provider Errors:* **28 / 30 (93.3%)** HTTP 429 rate limit responses (safely routed directly to deterministic template fallbacks).
  6. *Corrective Retries Attempted:* **0** (max 1 retry; retries are triggered strictly by invalid model responses, not HTTP provider throttling).
  7. *Total Usable Model Outputs:* **2 / 30 (6.7%)** across all attempts.
- **First-Pass Raw Model Quality Gates (Denominator = 2 Received Responses):**
  8. *First-Pass Schema Validity:* **2 / 2 (100.0%)** raw JSON conformed to `ClassifiedFinding`.
  9. *First-Pass Non-Judicial Wording:* **2 / 2 (100.0%)** avoided adjudicative terminology.
  10. *Raw Model Category Concordance:* **2 / 2 (100.0%)** model independently agreed with candidate category before guards.
  11. *Raw Model Concept-Keyword Coverage:* **2 / 2 (100.0%)** cited CCPA statutory vocabulary before guards.
  12. *Initial Model Validation Failures:* **0 / 2 (0.0%)** rejected by runtime guardrails.
- **Post-Validation Acceptance & Pipeline Quality (Denominator = 30 Submitted Candidates):**
  13. *Deterministic Fallbacks Emitted:* **28 / 30 (93.3%)** safe pre-validated template fallbacks invoked (28 HTTP provider errors, 0 unrecovered validation failures).
  14. *Final Accepted Outputs:* **30 / 30 (100.0%)** verified compliant before persistence (2 model-derived + 28 fallbacks = 30 accepted).
  15. *Evidence Grounding Rate:* **30 / 30 (100.0%)** zero ungrounded absence claims or invented values.
  16. *Post-Guard Category Preservation:* **30 / 30 (100.0%)** enforced architectural invariant.
  17. *Post-Guard Pipeline Concept-Keyword Coverage:* **30 / 30 (100.0%)** full pipeline outputs include statutory Gazette terms.
- **Three-Dimensional Empirical Latency Profile:**
  - *Usable Model Response Latency (HTTP 200 completions, N = 2):* Mean: **1,508.1 ms**, Median: **1,508.1 ms**, p95: **1,977.7 ms** (raw samples: `[1977.7, 1038.5] ms`).
  - *All HTTP Round-Trip Latency (Includes HTTP 429 responses, N = 30):* Mean: **288.5 ms**, Median: **205.2 ms**, p95: **1,038.5 ms**.
  - *Candidate Processing Latency (End-to-End per Candidate, N = 30):* Mean: **2,395.2 ms**, Median: **2,205.0 ms**, p95: **3,039.1 ms** (includes inter-submission pacing, network calls, and fallback synthesis).
- **Methodological Scope & Disclosures:**
  - *Proven Resilience Under Rate-Limiting:* The 100% final output acceptance rate ($30/30$) reflects verified pipeline recovery via safe template fallbacks ($2\text{ model} + 28\text{ fallbacks}$), not 100% remote LLM availability.
  - *Descriptive Latency Sample:* With $N = 2$ successful model responses under severe upstream rate limits, reported model latency ($1,508.1\text{ ms}$) is a descriptive empirical measurement of this specific run, not an unconstrained baseline.
  - *Non-Conflation of Historical Runs:* Historical benchmark runs (e.g., 21/30 coverage or 19 model + 11 fallbacks) are distinct historical runs; the current benchmark artifact strictly reflects commit `0f2c227`.

### Tier 3: Independent Dual-Annotated Real-Site Dataset
- **Status:** **PENDING** — Scheduled for Day 4 (17 Oct 2026) per Section 13 milestone.
- **Protocol:** Two human annotators independently audit live Indian e-commerce checkout funnels. Inter-rater reliability (Cohen's Kappa) will be measured and reported prior to model scoring. See [docs/REAL_SITE_VALIDATION_PROTOCOL.md](docs/REAL_SITE_VALIDATION_PROTOCOL.md) for the complete non-destructive execution plan and safe stop-before-payment boundary.

### Evidence & Countdown Timestamp Provenance
All audit runs preserve empirical, timestamped evidence:
- **Controlled Countdown Procedure:** Observes timer at $t_0$, holds session and page fixed for $\Delta t = 30\text{s}$, and re-observes timer at $t_1$.
- **Timestamp Provenance:** Generates timezone-aware UTC timestamps at runtime when observations are captured. The elapsed duration is computed directly from timestamps ($t_1 - t_0$).
- **Evidence Linking & Provenance Tags:** Each observation is linked to supporting screenshot artifacts (`snapshot_id`), tagged with execution provenance (`provenance: "synthetic_mock_fixture"` vs `"live_agent"`), and annotated with non-judicial disclaimers.


---

## 7. Judge-Ready Quickstart Guide

Checkout Radar features a **one-command, cross-platform launcher** supporting Linux, macOS, and Windows. A fresh checkout runs the full audit pipeline in **deterministic offline mock mode by default**—requiring zero external API keys, zero LLM provider credits, and zero live merchant access.

### Prerequisites
- **Docker Engine & Docker Compose** (v2.20+ recommended or Docker Desktop).
- Git.

---

### 7.1 Single Launch Command

Clone the repository and run the launcher for your operating system:

```bash
# Clone the repository
git clone https://github.com/your-org/checkout-radar.git
cd checkout-radar
```

| Operating System | Command | Fallback / Direct CLI |
|---|---|---|
| **Linux & macOS** | `./start.sh` | `python3 scripts/launcher.py` |
| **Windows (CMD / PowerShell)** | `start.cmd` | `python scripts\launcher.py` |
| **Direct Docker Compose** | `docker compose up --build -d` | `docker compose up` |

#### What the Launcher Does Automatically
1. **Pre-Flight Diagnostics:** Verifies that Docker is installed, the daemon is active, and Compose is available.
2. **Zero-Configuration Environment:** If no `.env` file exists, automatically initializes one from `.env.example` with `MOCK_TINYFISH=true`.
3. **Container Build & Orchestration:** Builds and starts the 3 core services:
   - `harness`: 5-variant reproducible merchant server.
   - `api`: FastAPI backend, SSE stream engine, and static dashboard.
   - `worker`: Durable job daemon with monotonic lease fencing.
4. **Healthcheck Synchronization:** Polls service health endpoints until all containers report `healthy`.
5. **Dynamic Port Discovery:** Resolves mapped host ports automatically (handles custom or overridden ports without hardcoding).
6. **Automatic Browser Launch:** Opens the Auditor Dashboard in your default browser once the service is confirmed ready.

---

### 7.2 Service Endpoints

Once initialized, the services are available at:

| Component | Default URL | Description |
|---|---|---|
| **Auditor Dashboard** | [http://localhost:8000](http://localhost:8000) | Full visual auditing dashboard, 3-stage screenshot gallery, and diffs. |
| **Demo Merchant Harness** | [http://localhost:8001](http://localhost:8001) | Controlled e-commerce store exhibiting the 5 behavioral variants. |
| **Interactive API Docs** | [http://localhost:8000/docs](http://localhost:8000/docs) | Swagger/OpenAPI documentation for all REST endpoints. |
| **Health Check** | [http://localhost:8000/health](http://localhost:8000/health) | Real-time service status, mock mode indicator, and key detection. |

*(Note: If port 8000 or 8001 is already bound, set `API_PORT` or `HARNESS_PORT` in `.env` or use `./start.sh`, which automatically detects dynamic port bindings).*

---

### 7.3 How to Run a Demonstration Audit (Judge Walkthrough)

1. **Launch an Adversarial Audit (Drip Pricing Positive Control):**
   - In the **Launch Checkout Audit** card, click the **`2. Late Handling Fee`** preset button (sets URL to `http://harness:8001/variant/late_disclosure`).
   - Click **`Start Multi-Condition Audit`**.
   - Watch the real-time **SSE Audit Progress Console** as 4 controlled condition runs execute.
   - **Observe Outcome:** The **Assessment Banner** turns red (`INDICATORS DETECTED`), flagging a **Drip Pricing** indicator where a mandatory ₹5.00 Handling Fee was concealed until checkout.
   - **Inspect Evidence Gallery:** Review the 3-stage visual viewports (Product, Cart Drawer, Checkout Summary). Click **`🔍 Full Resolution`** on any card to inspect the lightbox modal showing the full capture and immutable SHA-256 cryptographic digest.
   - **Condition Run Selector:** Use the dropdown above the gallery to switch between the Reference run and alternate Pincode/Cart Tier variants.
   - **Inspect Diff Matrix:** Review the `LATE_DISCLOSURE` matched-pair differential evidence card.

2. **Launch a Clean Upfront Audit (Negative Control):**
   - Click the **`1. Clean Upfront`** preset button (sets URL to `http://harness:8001/variant/clean`).
   - Click **`Start Multi-Condition Audit`**.
   - **Observe Outcome:** The Assessment Banner turns green (`VERIFIED CLEAN (UNDER TESTED FLOW)`), confirming zero dark patterns detected under the tested boundary.

3. **Export Standalone Evidence Report:**
   - Click the **`📄 HTML Evidence Report`** button in the Active Audit card.
   - Inspect the standalone report featuring CCPA legal citations, SHA-256 cryptographic hashes, and clickable `/evidence/{filename}` screenshot artifacts.

4. **Generate CCPA Grievance Draft:**
   - Click **`⚖️ CCPA Complaint Draft`** to generate a formatted consumer grievance report ready for filing with consumer protection authorities (labeled Draft Only; never auto-submitted).

---

### 7.4 Stopping the Application

To cleanly tear down running containers:

```bash
# Linux & macOS
./stop.sh

# Windows
stop.cmd

# Or using Docker Compose directly
docker compose down
```

---

### 7.5 Troubleshooting & Common Scenarios

- **Docker daemon is not running:**
  - *Linux:* Run `sudo systemctl start docker` (and optionally `sudo usermod -aG docker $USER`).
  - *macOS / Windows:* Launch Docker Desktop and wait until the whale icon shows "Engine running".
- **Port Conflict (Port 8000 or 8001 in use):**
  - Run with custom ports via environment variables:
    ```bash
    API_PORT=8080 HARNESS_PORT=8081 ./start.sh
    ```
- **Headless / Remote Server (No GUI / SSH):**
  - Pass `--no-browser` to suppress automatic browser launching:
    ```bash
    ./start.sh --no-browser
    ```
- **Inspecting Container Logs:**
  - View live or tail logs directly:
    ```bash
    ./start.sh --logs
    # or
    docker compose logs -f api worker
    ```
- **Checking Service Status:**
  ```bash
  ./start.sh --status
  # or
  docker compose ps
  ```

---

### 7.6 Verification & Test Suites

Checkout Radar includes a comprehensive, 100% reproducible test and verification suite requiring **zero external API calls**:

```bash
# 1. Local Pytest Suite (76 tests across 13 modules)
pytest backend/tests/ -v

# 2. Docker Isolated Pytest Suite
docker compose run --rm api pytest tests/

# 3. Three-Flow Demonstration Verification (Synthetic Positive, Clean Negative, Inconclusive Fail-Closed)
python3 scripts/verify_demo_flows.py

# 4. Automated Browser Interaction & Lightbox CDP Verification
python3 scripts/verify_ui_interaction.py

# 5. Dedicated Security & Secret Scanner (59 files + full git history)
python3 scripts/scan_secrets.py
```

---

## 8. API Surface

| Endpoint | Method | Purpose |
|---|---|---|
| `/audits` | `POST` | Submit URL and matrix preset (`quick` or `full`). |
| `/audits` | `GET` | List past audits with run and finding counts. |
| `/audits/{id}` | `GET` | Detailed audit status, conditions, and runs. |
| `/audits/{id}/stream`| `GET` | Live Server-Sent Events (SSE) agent progress feed. |
| `/audits/{id}/diff` | `GET` | Deterministic matched-pair diff results. |
| `/audits/{id}/findings` | `GET` | CCPA-mapped dark pattern candidate indicators. |
| `/audits/{id}/report` | `GET` | Exportable standalone HTML evidence report with SHA-256 hashes. |
| `/audits/{id}/complaint-draft` | `POST` | Generates CCPA consumer grievance draft (Draft only; never auto-submitted). |
| `/audits/{id}/reobserve` | `POST` | Triggers manual temporal re-observation across time. |
| `/audits/{id}/provider-calls` | `GET` | Complete log of all Search, Fetch, Agent, and Screenshot calls. |

---

## 9. Declared Code Reuse & Dependencies

Checkout Radar was designed and developed originally for AZINHACK 2026. Standard open-source libraries used:
- `FastAPI`, `Starlette`, `Uvicorn` — Web framework and ASGI server
- `Pydantic` — Contract validation and schema generation
- `Pillow` — Image redaction and privacy masking
- `SQLite3` (Standard Library) — Append-only durable database with WAL mode
- `pytest`, `httpx` — Automated unit, diff, and evaluation testing

---

## 10. Legal & Ethical Disclaimer

Findings generated by Checkout Radar represent algorithmic candidate indicators of potential deceptive practices under the CCPA Guidelines for Prevention and Regulation of Dark Patterns, 2023. They do not constitute judicial rulings, formal legal determinations, or statutory liability.
