# Checkout Radar — Pitch & Presentation Deck (AZINHACK 2026)

**Team of 4** · Submission: 18 Oct 2026 · Finale: 21–22 Oct 2026

---

## Slide 1: Title & Positioning
- **Title:** Checkout Radar
- **Subtitle:** Outside-In Checkout Flow Auditor & CCPA Dark Pattern Detector
- **Tagline:** Turning subjective dark pattern claims into reproducible, screenshot-backed empirical evidence.
- **Track:** Innovation & Consumer Transparency
- **Core Technology:** TinyFish Web Agents + Deterministic Differential Engine + SQLite WAL + LLM Classifier

---

## Slide 2: The Problem
- **The Hidden Fee Trap:** Consumers in India face surge fees, platform charges, convenience levies, and handling fees that silently appear on the final bill.
- **The Regulatory Void:** The Central Consumer Protection Authority (CCPA) notified strict dark pattern guidelines on 30 Nov 2023, prohibiting *Drip Pricing* and *Basket Sneaking*.
- **The Core Bottleneck:** Existing auditing tools cater to platform compliance teams or regulators. Consumers, journalists, and consumer-rights groups lack any continuous, outside-in auditing mechanism to collect admissible, timestamped evidence.

---

## Slide 3: The Solution
- **Checkout Radar:** An automated, outside-in auditor that navigates checkout funnels under controlled experimental variations.
- **Matched-Pair Condition Matrix:**
  - Isolates **Delivery Pincode** (Location Effect)
  - Isolates **Session History** (Fresh vs Returning Visitor)
  - Isolates **Cart Value** (Above vs Below Threshold)
  - Isolates **Observation Time** (Temporal Drift)
- **Evidence-First Outputs:**
  1. Deterministic Matched-Pair Diffs (comparing runs that differ in exactly one dimension)
  2. Append-only, redacted, SHA-256 hashed screenshot artifacts
  3. Formal CCPA complaint draft ready for consumer grievance filing

---

## Slide 4: Target Users & Real-World Impact
- **Consumers & Advocacy Groups (e.g. National Consumer Helpline):** Instant empirical proof to dispute unexpected drip fees.
- **Journalists & Investigative Media:** Data-backed exposés on dynamic pricing and geographic fee discrimination.
- **Compliance & Product Teams:** Proactive outside-in regression testing to prevent regulatory penalties.
- **Impact Metric:** Reduces complaint drafting time from 45 minutes to 30 seconds with cryptographic artifact verification.

---

## Slide 5: Technical Innovation & Differential Auditing
- **Not a Scraper, A Controlled Experiment:**
  - Traditional scrapers extract static text and break on dynamic Single Page Apps (SPAs).
  - Checkout Radar drives active browser sessions through the entire funnel and isolates independent variables.
- **Cart Recipe Invariant:**
  - Distinguishes **Recipe Family** from **Cart Instance**.
  - A quantity increase (1 unit vs 2 units) moves the subtotal across free delivery thresholds without altering unit prices.
  - The diff engine guarantees quantity changes do NOT trigger false `PRICE_VARIANCE`. Standard delivery rules are reported as legitimate policy rules (`SMALL_CART_RULE`).

---

## Slide 6: Deep TinyFish Integration
- **Central in the Main Execution Path:**
  1. **TinyFish Search API:** Discovers merchant terms of service and pricing policies during audit initiation.
  2. **TinyFish Fetch API:** Extracts clean policy text with defined cache TTLs (`ttl: 0` for live checkout, `ttl: 3600` for policy text).
  3. **TinyFish Agent API:** Executes multi-step browser automations across product, cart, and summary states with CCPA safety guardrails (STOP before payment, no credentials).
  4. **TinyFish Profiles API:** Spawns isolated Browser Context Profiles for returning-visitor conditions, preventing cross-condition contamination.
- **Auditable Provider Log:** Every API call, status, latency, and usability flag is persisted in `provider_calls`.

---

## Slide 7: Reliability & Architecture
- **Durable Job Table with Lease Recovery:**
  - Prevents double submissions: on lease expiry or worker crash, the system polls the existing `provider_run_id` before retrying.
- **Deterministic First, LLM Last:**
  - Candidate indicators are flagged exclusively by deterministic rules.
  - The LLM only classifies and explains candidates against verbatim CCPA 2023 legal definitions.
- **Hardened Semantic Output Guard & Evidence Grounding:**
  - Semantic non-judicial filter intercepts adjudicative declarations ("guilty of fraud", "unlawful") while preserving valid legal disclaimers.
  - Absence claims require explicit `not_observed_verified` records; rejects hallucinated amounts and ungrounded evidence IDs.
  - Bounded retry (max 1) with pre-validated deterministic fallback ensures 100% compliant persisted findings.
- **Monetary Reconciliation:**
  - All currency stored as integer minor units.
  - Mandatory equation: $\text{Subtotal} + \text{Charges} + \text{Taxes} - \text{Discounts} = \text{Final Payable}$. Mismatches trigger `extraction_inconsistent` and are excluded from diffs.
- **Comprehensive Quality Gate:**
  - 40 container tests passing in CI/Docker across normalizers, reconcilers, detectors, diff engine, lease recovery, category mutation prevention, and classifier guards.

---

## Slide 8: Evaluation & Benchmark Framework
- **Three-Tier Evaluation Methodology:**
  1. **Tier 1 (Synthetic Acceptance Suite — 45 Bundles):** 100% Precision, 100% Recall, F1 = 1.000 across Clean, Drip, Basket Sneaking, and False Urgency. Zero false alarms on negative controls (unit regression on designed fixtures).
  2. **Tier 2 (Auditable Remote LLM Telemetry & Retry-Aware Rate Limiting):**
     - Centralized Request Pacing: Minimum 2.0s spacing across all outbound provider calls (submissions and corrective retries) + `Retry-After` bounded backoff ($\le 5.0\text{s}$ budget).
     - Provider Coverage: **21 / 30 (70.0%)** empirical coverage (improved from 40.0% without pacing; 9 rate-limited handled via safe fallback).
     - First-Pass Model Quality ($N = 21$ received responses; empirical sample under provider limits): 100.0% (21/21) schema validity, 85.7% (18/21) non-judicial wording, 14.3% (3/21) caught by guardrails, 100.0% (21/21) raw category concordance, 100.0% (21/21) raw concept-keyword coverage (regex search on CCPA Gazette keywords).
     - Corrective Retries (5-Level Taxonomy): 3 attempted (triggered strictly by model errors), 3/3 (100.0%) HTTP responses received (0 network errors), 1/3 (33.3%) accepted after retry, 2/3 (66.7%) unrecovered rejections routed to fallback; Successful Provider Responses / Total Attempts: **24 / 33 (72.7%)**.
     - Post-Guard Accepted Quality ($N = 30$): 100.0% (30/30) accepted outputs, 100.0% evidence grounding, 100.0% post-guard category preservation (enforced invariant), 100.0% post-guard pipeline concept-keyword coverage (including validated fallbacks).
     - Three-Dimensional Latency: Provider HTTP round-trip ($N = 24$ successful provider responses, including unrecovered retries): Avg **1,264.8 ms** (Median 1,150.9 ms, p95 1,963.9 ms); Candidate end-to-end ($N = 30$): Avg **5,914.8 ms** (Median 6,425.8 ms, p95 9,533.1 ms); Total batch duration: **177.45 s** (~2.95 min).
  3. **Tier 3 (Dual-Annotated Real Sites):** In-progress for Day 4 (17 Oct) per Section 13 milestone. Two labelers annotating live Indian e-commerce checkout funnels. Cohen's Kappa will be established before model evaluation.

---

## Slide 9: Live Demo & Merchant Harness
- **Controlled 5-Variant Demo Merchant Container:**
  1. *Clean Store:* Transparent upfront fees $\rightarrow$ 0 findings.
  2. *Late Handling Fee:* ₹5 fee hidden until checkout summary $\rightarrow$ Flagged Drip Pricing.
  3. *Add-on + Countdown:* Pre-selected insurance + resetting timer $\rightarrow$ Flagged Basket Sneaking & False Urgency.
  4. *Negative Control (Upfront Fee):* ₹20 fee disclosed on product page $\rightarrow$ 0 findings.
  5. *Negative Control (Threshold):* Free delivery above ₹500 $\rightarrow$ Reported as legitimate rule, not deceptive.
- **Real-Site Demonstration:**
  - Full TinyFish navigation path with local screenshot persistence and honest `blocked_by_login` boundary handling.

---

## Slide 10: Feasibility, Budget & Future Scope
- **Current Feasibility:**
  - Docker Compose one-command launch (`docker compose up`).
  - Credit-conscious budgeting: Quick matrix costs under $0.20 per audit.
- **Future Roadmap:**
  - Expand to global proxy auditing across 7 countries (US, GB, CA, DE, FR, JP, AU).
  - Browser Extension for real-time consumer warnings during live checkout.
  - Automated integration with National Consumer Helpline grievance APIs.
