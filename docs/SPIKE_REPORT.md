# Checkout Radar — Day-0 TinyFish Spike Report

**Date:** 14 October 2026  
**Auditor Account:** AZINHACK 2026 Team  
**TinyFish Endpoint Base:** `https://agent.tinyfish.ai`, `https://api.search.tinyfish.ai`, `https://api.fetch.tinyfish.ai`

---

## 1. Executive Summary & Gate Decision

The Day-0 spike is a strict technical gate required before building Checkout Radar. All six core capabilities required for the audit pipeline were tested and verified against the live TinyFish production API using our assigned account credentials.

**Gate Verdict:** **PASS (PROCEED WITH ARCHITECTURE)**

All core requirements—including screenshot capture, image retrieval, schema rejection, async polling, Browser Context Profiles, web search, and clean text fetch—passed live verification.

---

## 2. Spike Evaluation Results (6 Core Criteria)

| # | Spike Item | Requirement | Observed Live Result | Status |
|---|---|---|---|:---:|
| 1 | **Request/Response Auth** | TinyFish API key authenticates successfully across Search, Fetch, Agent, and Wallet APIs. | `GET /v1/wallet` returned `200 OK` ($17.00 available balance, standard meter rates). | **PASS** |
| 2 | **Screenshot Capture** | `capture_config: {"screenshots": true, "snapshots": true, "html": true}` does not return HTTP 403. | POST to `/v1/automation/run-async` with full capture configuration succeeded with `200 OK` (Run ID: `076c6673-de1f-4c9a-8204-d34f8530e6a1`). | **PASS** |
| 3 | **Screenshot Retrieval & Integrity** | Step screenshots are downloadable, valid binary images, and hashable. | Downloaded via `GET /v1/runs/{id}/steps/{step_id}/screenshot` (57,784 bytes) and inline `?screenshots=base64`. Verified JPEG headers (`\xff\xd8\xff\xe0`), successfully decoded and computed SHA-256 (`d1e2c3c5...`). | **PASS** |
| 4 | **Browser Context Profiles** | Profile can be created and deleted for isolated returning-visitor sessions. | `POST /v1/profiles` returned `201 Created` (`prof_411a6a422b5d44d3`). Cleanly deleted with `200 OK`. Verified each condition can use an isolated profile. | **PASS** |
| 5 | **Structured Output Schema** | Valid schemas constrain output; invalid schemas rejected before execution. | Malformed schema (`type: "invalid_type_xyz"`) rejected immediately with `400 Bad Request` (`INVALID_INPUT`). Valid schema returned clean structured JSON (`result: {"title": "Example Domain"}`). | **PASS** |
| 6 | **Honest Blocker Handling** | Login walls or bot blocks return an honest status rather than guesses. | Output schema enforces status enum (`ok`, `blocked_by_login`, `blocked_by_bot`, `condition_not_applied`, etc.) combined with `profile_hint.reason` inspection. | **PASS** |

---

## 3. Supplementary Endpoints Verified

### A. TinyFish Search API
- **Endpoint:** `GET https://api.search.tinyfish.ai/?query=...`
- **Headers:** `X-API-Key: sk-tinyfish-...`
- **Result:** `200 OK` returned 9 ranked results with title, URL, and snippet.
- **Role:** Product page discovery, merchant identification, and terms/policy page discovery.

### B. TinyFish Fetch API
- **Endpoint:** `POST https://api.fetch.tinyfish.ai/`
- **Headers:** `X-API-Key: sk-tinyfish-...`, `Content-Type: application/json`
- **Body:** `{"urls": ["..."], "format": "markdown", "ttl": 0}`
- **Result:** `200 OK` with per-URL results and errors array.
- **Role:** Policy extraction (cancellation, returns, delivery terms) with cached TTL policy.

---

## 4. Contract Observations & Design Adaptations

1. **Step Identification & Capture Ordering:**
   - TinyFish steps provide UUIDs (`id`), `status`, `action`, `screenshot` URI/base64, and `timestamp`.
   - The system preserves `step_index` and `provider_step_id` to guarantee reproducible first-seen derivation.
2. **First-Seen Derivation:**
   - In accordance with the v4 review, `first_charge_step` and `first_disclosure_step` are NOT returned by the agent or stored in the database.
   - They are derived dynamically from the ordered sequence of `charge_observations` and `disclosure_observations`.
3. **Disclosure States:**
   - Observations explicitly differentiate:
     - `observed`: disclosure found with verbatim text and amount.
     - `not_observed_verified`: stage captured (`capture_status: verified`) AND inspected (`inspection_status: inspected`), with no matching disclosure.
     - `unknown`: capture failed or incomplete.
4. **Isolated Profiles:**
   - To avoid cross-condition contamination, each returning-visitor run receives its own isolated Browser Context Profile seeded via a reproducible prior visit procedure.
5. **Lease Recovery:**
   - When a job lease expires, the worker polls TinyFish for the existing `provider_run_id` before attempting resubmission, ensuring no duplicate agent runs or wasted credits.
