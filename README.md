# 📡 Checkout Radar

> **Outside-In Checkout Flow Auditor & CCPA Dark Pattern Detector**  
> *AZINHACK 2026 Submission* · Team of 4

[![CI Tests](https://img.shields.io/badge/tests-40%20passed-brightgreen.svg)]()
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
4. **Append-Only Evidence Store:** Step screenshots are redacted for privacy (PII masking), saved to disk, and verified with an immutable SHA-256 hash.

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
The LLM does not alter detection boundaries; candidate indicators are strictly produced upstream by the deterministic diff engine. The LLM's downstream role is to map candidates to official CCPA Gazette definitions and draft consumer grievances in structured JSON.

- **Non-Judicial Semantic Output Guard:** Intercepts and rejects raw LLM outputs containing definitive adjudicative or legalistic declarations (e.g., "merchant is guilty of fraud", "committed an illegal deceptive act", "violated consumer law", "conduct is unlawful", "found culpable"), while shielding legitimate non-judicial disclaimers (e.g., "does not constitute a legal determination that merchant violated consumer law").
- **Evidence Grounding Validation:**
  - Fee absence assertions strictly require a `not_observed_verified` disclosure record from upfront stages; unverified or unknown disclosures preserve uncertainty without generating false claims.
  - Invented monetary amounts not present in candidate items or observations are rejected.
  - Invented evidence IDs not present in the audit's observation index are rejected.
- **Bounded Retry & Pre-Validated Deterministic Fallback:** Enforces a maximum of 1 corrective retry before reverting to a pre-validated deterministic fallback template conforming strictly to schema, statutory citations, and non-judicial wording. 100% of persisted findings are guaranteed valid.
- **Auditable Benchmark Telemetry & Failure Taxonomy:**
  The benchmark runner (`evaluation/run_evaluation.py`) reports metrics with explicit denominators, retry-aware rate limiting, and 3-tier latency tracking, rigorously separating provider-level throttling/errors from raw model quality gates:
  - *Retry-Aware Request Pacing & Queue Discipline:* Centralized rate-limiter in `LLMClassifier` enforces a minimum 2.0s spacing across **all** outbound provider requests (both initial candidate submissions and corrective retries), preventing retry bursts from exhausting rate limits. `Retry-After` response headers are parsed with a strict cumulative backoff budget capped at $\le 5.0\text{s}$.
  - *Remote Provider Coverage & Failure Taxonomy (Denominator = Submitted Candidates, N = 30):*
    1. *Initial Provider Responses:* Submissions successfully returning raw model responses on first attempt: **21 / 30 (70.0%)** (improved from 40.0% without pacing).
    2. *Initial Provider Failures / Throttling:* Submissions rate-limited or unavailable: **9 / 30 (30.0%)** (handled via safe deterministic fallback).
    3. *Corrective Retries Attempted:* Bounded retries triggered strictly by invalid model outputs: **3** (0 retries burned on provider throttling).
    4. *Retry HTTP Responses Received:* HTTP responses returned from provider on retry: **3 / 3 (100.0%)** (0 provider network/rate-limit failures on retry).
    5. *Retry Responses Accepted by Guard:* Retries passing validation gates: **1 / 3 (33.3%)**.
    6. *Retry Responses Rejected by Guard:* Unrecovered validation failures routed to fallback: **2 / 3 (66.7%)**.
    7. *Successful Provider Responses / Total Attempts:* **24 / 33 (72.7%)** across all initial calls and corrective retries (9 requests rate-limited on initial submission; 0 requests rate-limited on retry).
  - *First-Pass Raw Model Quality Gates (Denominator = Responses Received, N = 21):*
    8. *First-Pass Schema Validity:* Valid raw responses conforming to `ClassifiedFinding`: **21 / 21 (100.0%)**.
    9. *First-Pass Non-Judicial Wording:* Raw responses devoid of adjudicative terms: **18 / 21 (85.7%)** (3 caught and flagged for adjudicative wording or missing indicator framing).
    10. *Raw Model Category Concordance:* Model independently agreed with candidate category before guards: **21 / 21 (100.0%)**.
    11. *Raw Model Concept-Keyword Coverage:* Raw response cited CCPA statutory vocabulary before guards: **21 / 21 (100.0%)**.
    12. *Initial Model Validation Failures:* Model responses rejected by guardrails on first pass: **3 / 21 (14.3%)** (intercepted by runtime guardrails).
  - *Post-Validation Acceptance & Grounding (Denominator = Submitted Candidates, N = 30):*
    13. *Deterministic Fallbacks Emitted:* Pre-validated template fallbacks invoked: **11 / 30 (36.7%)** (9 provider rate limits, 2 unrecovered validation failures).
    14. *Final Accepted Outputs:* Total valid findings accepted into the audit store: **30 / 30 (100.0%)**.
    15. *Evidence Grounding Rate:* Zero ungrounded absence assertions or invented amounts/IDs: **30 / 30 (100.0%)**.
    16. *Post-Guard Category Preservation:* Accepted category strictly preserves candidate category as an enforced architectural invariant: **30 / 30 (100.0%)**.
    17. *Post-Guard Pipeline Concept-Keyword Coverage:* Full pipeline accepted outputs (including validated fallbacks) include statutory Gazette keywords: **30 / 30 (100.0%)**.
    18. *Verification Method:* Regex search against CCPA 2023 Gazette statutory definition terminology sets (Annex 1.8, 1.2, 1.1). Confirms lexical presence of statutory vocabulary, not judicial semantic correctness.
  - *Three-Dimensional Latency & Execution Profile:*
    - **Provider HTTP Latency (Individual Successful Network Calls, N = 24):** Sample size: **24 calls** (21 initial responses + 3 retries, including both retry responses rejected by application-level validation; 0 network failures on retry). Average latency: **$\approx 1,265\text{ ms}$ (estimated)** derived from the prior verified 22-response mean ($1,255.1\text{ ms}$) and typical provider retry durations. Median (p50) and 95th percentile (p95) are marked **Unavailable / Pending** fresh live execution with persisted raw observations (data provenance requirement: raw observations must not be reconstructed or fitted).
    - **Candidate Processing Latency (End-to-End per Candidate, N = 30):** Avg: **5,914.8 ms**, Median: **6,425.8 ms**, p95: **9,533.1 ms** (includes pacing delays, retry loops, validation, and fallback overhead).
    - **Batch Evaluation Elapsed Duration:** **177.45 s** (~2.95 min) to process all 30 candidate findings sequentially.
  - *Methodological Scope & Sample Size Disclosure:*
    - Provider response coverage (21/30) reflects rate-limiting on the tested endpoint during evaluation. This is an empirical constraint of the tested environment, not a theoretical projection.
    - Raw model quality metrics are calculated strictly over received responses ($N = 21$), representing an empirical sample under provider limits rather than a universal guarantee. Concordance on received responses does not prove universal 100% model accuracy across all possible prompts.
    - Concept-keyword coverage measures regex inclusion of Gazette statutory terms, not independent human or judicial assessment of legal correctness.
    - Post-guard category preservation (30/30) and pipeline concept-keyword coverage (30/30) are architectural invariants enforced by deterministic validators and safe template fallbacks.

### Tier 3: Independent Dual-Annotated Real-Site Dataset
- **Status:** **PENDING** — Scheduled for Day 4 (17 Oct 2026) per Section 13 milestone.
- **Protocol:** Two human annotators independently audit live Indian e-commerce checkout funnels. Inter-rater reliability (Cohen's Kappa) will be measured and reported prior to model scoring.

### Evidence & Countdown Timestamp Provenance
All audit runs preserve empirical, timestamped evidence:
- **Controlled Countdown Procedure:** Observes timer at $t_0$, holds session and page fixed for $\Delta t = 30\text{s}$, and re-observes timer at $t_1$.
- **Timestamp Provenance:** Generates timezone-aware UTC timestamps at runtime when observations are captured. The elapsed duration is computed directly from timestamps ($t_1 - t_0$).
- **Evidence Linking & Provenance Tags:** Each observation is linked to supporting screenshot artifacts (`snapshot_id`), tagged with execution provenance (`provenance: "synthetic_mock_fixture"` vs `"live_agent"`), and annotated with non-judicial disclaimers.


---

## 7. Quickstart Guide

### Option A: One-Command Docker Compose (Recommended)

1. Clone repository and set up environment:
   ```bash
   cp .env.example .env
   # .env comes preconfigured with TINYFISH_API_KEY
   ```

2. Start all services:
   ```bash
   docker compose up --build
   ```

3. Open your browser:
   - **Auditor Dashboard:** [http://localhost:8000](http://localhost:8000)
   - **Demo Merchant Harness:** [http://localhost:8001](http://localhost:8001)
   - **Interactive API Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)

### Option B: Local Python Execution

```bash
# Set up virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

# Run test suite (40 tests)
cd backend && pytest -v

# Run evaluation benchmark
cd .. && python3 evaluation/run_evaluation.py

# Run backend API
uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir backend
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
