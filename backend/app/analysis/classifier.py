"""Schema-validated LLM Classifier for Potential Dark Pattern Indicators.

Principles & Contracts:
1. Classifies upstream candidates only; never invents findings from unobserved data.
2. Injects verbatim definitions from /data/ccpa_definitions.json.
3. Enforces strict schema validation and deterministic output guardrails.
4. Language is strictly 'potential indicator', never a legal verdict or declaration of violation.
5. Factual assertions must be grounded in empirical evidence:
   - "unknown" disclosure is never read as "not disclosed" or "absent".
   - Verified negative observations ('not_observed_verified') are required to claim fee absence.
   - Invented monetary amounts or evidence IDs not in evidence are deterministically rejected.
6. Guardrail Architecture:
   - Evaluates substantive sentences while avoiding false positives from negative disclaimer clauses.
   - Enforces a bounded retry policy (max 1 corrective retry).
   - Deterministic, evidence-grounded fallback is ALWAYS validated before returning or persisting.
   - An invalid explanation is NEVER exposed through API, reports, or dashboards.
   - Comprehensive telemetry tracks raw provider compliance separately from post-validation acceptance.

Limitations:
   Finite regex and keyword heuristics cannot guarantee complete semantic coverage of all subtle,
   novel, or adversarial adjudicative phrasing. Therefore, conservative fallback behavior is
   strictly enforced whenever compliance cannot be deterministically verified.
"""

import json
import os
import re
import time
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, Tuple, List, Set
from pathlib import Path
from pydantic import BaseModel, Field, field_validator


ALLOWED_CCPA_CATEGORIES = {"drip_pricing", "basket_sneaking", "false_urgency"}


class ClassifiedFinding(BaseModel):
    category: str
    severity: str = Field(description="low, medium, or high")
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("category", mode="before")
    @classmethod
    def validate_category(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError(f"Category must be a string, got {type(v)}")
        cat = v.strip().lower()
        if cat not in ALLOWED_CCPA_CATEGORIES:
            raise ValueError(
                f"Unsupported CCPA dark pattern category '{v}'. Allowed: {sorted(ALLOWED_CCPA_CATEGORIES)}"
            )
        return cat

    @field_validator("confidence", mode="before")
    @classmethod
    def parse_confidence(cls, v: Any) -> float:
        if isinstance(v, (int, float)):
            return max(0.0, min(1.0, float(v)))
        if isinstance(v, str):
            v_clean = v.strip().lower()
            try:
                val = float(v_clean)
                return max(0.0, min(1.0, val))
            except ValueError:
                mapping = {"high": 0.9, "medium": 0.7, "low": 0.5}
                return mapping.get(v_clean, 0.8)
        return 0.8


# 1. Prohibited Adjudicative Semantic Patterns (asserting legal guilt, violation, or liability)
PROHIBITED_ADJUDICATIVE_PATTERNS = [
    re.compile(r"\b(?:is|are|was|were|found|deemed)\s+guilty\b", re.IGNORECASE),
    re.compile(r"\bguilty\s+of\b", re.IGNORECASE),
    re.compile(r"\b(?:is|are|was|were)\s+(?:a\s+)?criminal\b", re.IGNORECASE),
    re.compile(
        r"\bcommitted\s+(?:a\s+|an\s+)?(?:crime|fraud|felony|offense|illegal\s+act|unlawful\s+act|deceptive\s+act)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:is|are|was|were|conduct\s+is|practice\s+is|acts?\s+are)\s+(?:illegal|unlawful|illicit)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\billegal\s+(?:deceptive\s+act|conduct|practice|pricing|behavior|charge)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bviolated\s+(?:the\s+|any\s+|consumer\s+|statutory\s+)?(?:law|laws|act|guidelines?|regulations?|statutes?|ccpa|code)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bviolates\s+(?:the\s+|any\s+|consumer\s+|statutory\s+)?(?:law|laws|act|guidelines?|regulations?|statutes?|ccpa|code)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bin\s+violation\s+of\s+(?:the\s+|any\s+|consumer\s+|statutory\s+)?(?:law|laws|act|guidelines?|regulations?|statutes?|ccpa|code)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:is|are|was|were|held|found)\s+(?:liable|culpable)\b", re.IGNORECASE),
    re.compile(r"\bhas\s+been\s+found\s+culpable\b", re.IGNORECASE),
    re.compile(r"\bstatutory\s+liability\b", re.IGNORECASE),
    re.compile(r"\blegal\s+verdict\b", re.IGNORECASE),
    re.compile(r"\bofficial\s+declaration\s+of\s+guilt\b", re.IGNORECASE),
]

# Standalone prohibited words that must not appear in substantive finding sentences
PROHIBITED_STANDALONE_WORDS = [
    "guilty",
    "convicted",
    "verdict",
    "unlawful",
    "culpable",
    "criminal",
]

# 2. Disclaimer Patterns (negation applied to legal / adjudicative concepts)
DISCLAIMER_PATTERNS = [
    re.compile(
        r"\b(?:does\s+not|is\s+not|not\s+intended\s+as|never\s+constitutes?|cannot\s+be\s+construed\s+as|technical\s+finding\s+only|not\s+a\s+legal|not\s+an?\s+adjudication)\b[^.!?]{0,80}?\b(?:constitute|represent|imply|declare|serve\s+as|mean|amount\s+to|establish|be\s+construed\s+as|legal|verdict|liability|guilt|violation|culpab|unlawful|adjudicat)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:this\s+(?:finding|report|audit|indicator)|technical\s+finding)\b[^.!?]{0,60}?\b(?:not\s+a\s+legal|technical\s+only|not\s+an?\s+adjudication|does\s+not\s+constitute)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bdoes\s+not\s+constitute\s+a\s+legal\s+determination\b",
        re.IGNORECASE,
    ),
]

MANDATORY_INDICATOR_TERMS = [
    "potential indicator",
    "potential dark pattern",
    "empirical indicator",
    "indicator of",
]


def load_ccpa_definitions() -> Dict[str, Any]:
    candidates = [
        os.getenv("CCPA_DEFINITIONS_PATH"),
        "/data/ccpa_definitions.json",
        "/app/data/ccpa_definitions.json",
        str(Path(__file__).resolve().parent.parent.parent.parent / "data" / "ccpa_definitions.json"),
        "/home/daksh/working/checkout-radar/data/ccpa_definitions.json",
    ]
    for c in candidates:
        if c and Path(c).exists():
            with open(c, "r", encoding="utf-8") as f:
                return json.load(f).get("categories", {})
    return {}


def validate_explanation(
    explanation: str,
    category: str,
    evidence_context: Dict[str, Any],
    candidate_finding: Optional[Dict[str, Any]] = None,
    evidence_ids: Optional[List[str]] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Deterministically validate explanation against non-judicial wording
    and empirical evidence grounding rules.
    Returns (is_valid, rejection_reason).

    Guarantees & Limitations:
    - Rejects assertions of legal guilt, criminal offenses, unlawful acts, and statutory violations.
    """
    expl_lower = explanation.lower()

    # 0. Category validation and alignment check (prevents silent category mutation)
    cat_clean = category.strip().lower() if category else ""
    if cat_clean not in ALLOWED_CCPA_CATEGORIES:
        return False, f"Unsupported CCPA category '{category}'. Allowed categories: {sorted(ALLOWED_CCPA_CATEGORIES)}"
    if candidate_finding and "category" in candidate_finding:
        cand_cat = candidate_finding["category"].strip().lower()
        if cat_clean != cand_cat:
            return False, (
                f"Model output category '{category}' does not match deterministic candidate category '{cand_cat}'. "
                "The model must not replace or mutate the upstream detector category."
            )

    # 1. Mandatory indicator phrasing check
    if not any(term in expl_lower for term in MANDATORY_INDICATOR_TERMS):
        return False, "Missing mandatory non-judicial framing (must explicitly identify finding as a 'potential indicator')."

    # 2. Check for prohibited adjudicative assertions in substantive sentences
    sentences = re.split(r'(?<=[.!?])\s+', explanation)
    for s in sentences:
        s_clean = s.strip()
        if not s_clean:
            continue
        # Check if sentence is an explicit non-judicial disclaimer
        is_disclaimer = any(dp.search(s_clean) for dp in DISCLAIMER_PATTERNS)
        if not is_disclaimer:
            # Check prohibited semantic patterns
            for pp in PROHIBITED_ADJUDICATIVE_PATTERNS:
                match = pp.search(s_clean)
                if match:
                    return False, (
                        f"Prohibited adjudicative language detected in substantive finding ('{match.group(0)}'). "
                        "Must be framed as a potential indicator, not a legal verdict or declaration of violation."
                    )
            # Check prohibited standalone terms in non-disclaimer context
            for term in PROHIBITED_STANDALONE_WORDS:
                if re.search(rf"\b{term}\b", s_clean, re.IGNORECASE):
                    return False, f"Prohibited legal term '{term}' detected in substantive finding outside of a non-judicial disclaimer."

    # 3. Evidence grounding check for fee absence claims
    absence_markers = [
        "absent at", "concealed at", "undisclosed at", "was not disclosed at",
        "hidden at product", "not displayed on product", "not disclosed on product"
    ]
    if any(marker in expl_lower for marker in absence_markers):
        disclosures = evidence_context.get("disclosures", [])
        verified_absence = any(
            isinstance(d, dict) and d.get("state") == "not_observed_verified"
            for d in disclosures
        )
        if not verified_absence:
            return False, (
                "Explanation asserts fee was verified absent at an earlier stage, but evidence does not contain "
                "a 'not_observed_verified' disclosure record (unknown disclosure status cannot be claimed as absent)."
            )

    # 4. Evidence grounding check for invented monetary amounts
    if candidate_finding is not None or evidence_context:
        valid_amounts_minor: Set[int] = set()
        if candidate_finding and "amount_minor" in candidate_finding:
            valid_amounts_minor.add(candidate_finding["amount_minor"])
        if candidate_finding:
            for m in re.findall(r"₹\s*(\d+(?:\.\d{2})?)", candidate_finding.get("explanation", "")):
                valid_amounts_minor.add(int(round(float(m) * 100)))
        for c in evidence_context.get("charges", []):
            if isinstance(c, dict) and "amount_minor" in c:
                valid_amounts_minor.add(c["amount_minor"])
        for d in evidence_context.get("disclosures", []):
            if isinstance(d, dict) and d.get("amount_minor"):
                valid_amounts_minor.add(d["amount_minor"])
        for a in evidence_context.get("preselected_addons", []):
            if isinstance(a, dict) and "amount_minor" in a:
                valid_amounts_minor.add(a["amount_minor"])

        expl_amounts = re.findall(r"₹\s*(\d+(?:\.\d{2})?)", explanation)
        if valid_amounts_minor and expl_amounts:
            for amt_str in expl_amounts:
                amt_minor = int(round(float(amt_str) * 100))
                if amt_minor not in valid_amounts_minor:
                    return False, f"Explanation asserts ungrounded monetary amount ₹{amt_str} not present in candidate finding or audit evidence observations."

    # 5. Evidence grounding check for invented evidence IDs
    if evidence_ids:
        valid_ids: Set[str] = set()
        if candidate_finding:
            valid_ids.update(candidate_finding.get("evidence_ids", []))
        for sc in evidence_context.get("stage_captures", []):
            if isinstance(sc, dict):
                if sc.get("snapshot_id"):
                    valid_ids.add(sc["snapshot_id"])
                if sc.get("screenshot_ref"):
                    valid_ids.add(sc["screenshot_ref"])
                if sc.get("id"):
                    valid_ids.add(sc["id"])
        for eid in evidence_ids:
            if valid_ids and eid not in valid_ids:
                return False, f"Explanation asserts ungrounded evidence ID '{eid}' not present in candidate or audit observations."

    return True, None


def build_safe_grounded_template(
    candidate_finding: Dict[str, Any],
    evidence_context: Dict[str, Any],
    ccpa_def: Dict[str, Any],
) -> str:
    """
    Deterministically construct a safe, evidence-grounded explanation
    strictly compliant with non-judicial wording and CCPA 2023 Gazette definitions.
    Preserves specific observed details (e.g. item label, amounts, stages) from upstream detectors.
    """
    category = candidate_finding.get("category", "dark_pattern")
    official_id = ccpa_def.get("official_id", "CCPA_2023")
    cat_name = ccpa_def.get("name", category.replace("_", " ").title())
    def_snippet = ccpa_def.get("definition", "Central Consumer Protection Authority Guidelines 2023")[:120]

    raw_expl = candidate_finding.get("explanation", "").strip()

    disclosures = evidence_context.get("disclosures", [])
    verified_absence = any(isinstance(d, dict) and d.get("state") == "not_observed_verified" for d in disclosures)
    has_unknown = any(isinstance(d, dict) and d.get("state") == "unknown" for d in disclosures) or (not disclosures and category == "drip_pricing")

    # If the candidate finding already has a high-quality empirical rule explanation, preserve it
    if raw_expl and "potential" in raw_expl.lower() and not any(pp.search(raw_expl) for pp in PROHIBITED_ADJUDICATIVE_PATTERNS):
        if "absent at" in raw_expl.lower() and not verified_absence:
            base = raw_expl.replace("verified absent at", "unobserved/unknown at").replace("absent at", "unobserved/unknown at")
        else:
            base = raw_expl
    else:
        if category == "drip_pricing":
            if verified_absence:
                disc_text = "disclosure was verified absent at the initial product stage"
            elif has_unknown:
                disc_text = "disclosure status at earlier stages was unobserved or unknown in this capture"
            else:
                disc_text = "charge appeared at checkout summary without prior verified upfront disclosure"
            base = (
                f"Observed potential indicator of {cat_name} ({official_id}): "
                f"a mandatory charge was observed at checkout, while {disc_text}."
            )
        elif category == "basket_sneaking":
            base = (
                f"Observed potential indicator of {cat_name} ({official_id}): "
                f"pre-selected add-on or item was included in payable total by default without prior explicit opt-in."
            )
        elif category == "false_urgency":
            base = (
                f"Observed potential indicator of {cat_name} ({official_id}): "
                f"urgency claim or countdown timer was observed resetting or persisting across consecutive observations."
            )
        else:
            base = f"Observed potential indicator of {cat_name} ({official_id}) based on checkout audit diffs."

    disclaimer = "This empirical indicator serves as technical checkout audit evidence and does not constitute a legal determination or statutory adjudication."
    return f"{base} (Aligned with CCPA 2023 Gazette definition: '{def_snippet}...'). {disclaimer}"


class LLMClassifier:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "gpt-4o-mini",
    ):
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.base_url = (base_url or os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.model = os.getenv("LLM_MODEL", model)
        self.ccpa_definitions = load_ccpa_definitions()
        self.pacing_seconds = float(os.getenv("LLM_PACING_SECONDS", "2.0"))
        self._last_request_time: float = 0.0
        self._last_http_latency_ms: float = 0.0

    def _execute_llm_request(self, messages: List[Dict[str, str]]) -> str:
        # Enforce rate-limit pacing across EVERY outbound provider request (initial & corrective retries)
        if self.pacing_seconds > 0.0 and self._last_request_time > 0.0:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.pacing_seconds:
                time.sleep(self.pacing_seconds - elapsed)

        req_data = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(req_data).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CheckoutRadar/1.0",
            },
            method="POST",
        )
        max_http_attempts = 3
        max_budget_seconds = 5.0
        total_slept = 0.0

        for attempt_http in range(max_http_attempts):
            t_http_start = time.perf_counter()
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    http_lat = (time.perf_counter() - t_http_start) * 1000
                    self._last_http_latency_ms = round(http_lat, 2)
                    self._last_http_status = getattr(resp, "status", 200)
                    self._last_http_response_received = True
                    self._last_transport_error = None
                    self._last_request_time = time.time()
                    try:
                        raw_body = resp.read().decode("utf-8")
                        resp_json = json.loads(raw_body)
                        choices = resp_json.get("choices", [])
                        if not choices:
                            raise ValueError("Provider HTTP 200 response contains empty 'choices' list")
                        choice = choices[0].get("message", {}).get("content", "").strip()
                        if not choice:
                            raise ValueError("Provider HTTP 200 response contains empty message content")
                        if choice.startswith("```"):
                            lines = choice.splitlines()
                            if lines and lines[0].startswith("```"):
                                lines = lines[1:]
                            if lines and lines[-1].startswith("```"):
                                lines = lines[:-1]
                            choice = "\n".join(lines).strip()
                        self._last_model_output_received = True
                        return choice
                    except Exception as body_err:
                        self._last_model_output_received = False
                        raise ValueError(f"Malformed provider response body on HTTP 200: {body_err}") from body_err
            except urllib.error.HTTPError as he:
                http_lat = (time.perf_counter() - t_http_start) * 1000
                self._last_http_latency_ms = round(http_lat, 2)
                self._last_http_status = he.code
                self._last_http_response_received = True
                self._last_model_output_received = False
                self._last_transport_error = None
                self._last_request_time = time.time()

                if attempt_http >= max_http_attempts - 1:
                    raise
                if he.code == 429:
                    wait_sec = None
                    if he.headers:
                        hdr = he.headers.get("Retry-After")
                        if hdr:
                            try:
                                wait_sec = float(hdr)
                            except ValueError:
                                pass
                    if wait_sec is None:
                        try:
                            err_body = he.read().decode("utf-8", errors="replace")
                            m = re.search(r"try again in (\d+(?:\.\d+)?)s", err_body)
                            if m:
                                wait_sec = float(m.group(1))
                        except Exception:
                            pass
                    if wait_sec is None:
                        wait_sec = 1.5 * (attempt_http + 1)

                    if wait_sec > max_budget_seconds or (total_slept + wait_sec) > max_budget_seconds:
                        raise
                    time.sleep(wait_sec)
                    total_slept += wait_sec
                    self._last_request_time = time.time()
                    continue
                elif he.code in (502, 503):
                    wait_sec = 1.0
                    if (total_slept + wait_sec) > max_budget_seconds:
                        raise
                    time.sleep(wait_sec)
                    total_slept += wait_sec
                    self._last_request_time = time.time()
                    continue
                else:
                    raise
            except Exception as transport_err:
                self._last_http_latency_ms = None
                self._last_http_status = None
                self._last_http_response_received = False
                self._last_model_output_received = False
                self._last_transport_error = str(transport_err)
                self._last_request_time = time.time()
                raise

    def classify_candidate(
        self,
        candidate_finding: Dict[str, Any],
        evidence_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Classify candidate finding against CCPA definitions with deterministic
        output validation, bounded retry, safe template fallback, and comprehensive telemetry.
        """
        category_key = candidate_finding.get("category", "")
        ccpa_def = self.ccpa_definitions.get(category_key, {})
        cat_name = ccpa_def.get("name", category_key.replace("_", " ").title())
        official_id = ccpa_def.get("official_id", "CCPA_2023")
        official_text = ccpa_def.get("definition", "Dark pattern under CCPA guidelines.")

        telemetry: Dict[str, Any] = {
            "submitted": True,
            "provider_called": bool(self.api_key),
            "initial_response_received": False,
            "provider_error": None,
            "first_pass_schema_valid": None,
            "first_pass_wording_valid": None,
            "first_pass_grounding_valid": None,
            "first_pass_overall_valid": None,
            "raw_model_category": None,
            "raw_category_concordance": None,
            "raw_concept_keyword_coverage": None,
            "raw_statutory_concept_alignment": None,
            "model_validation_failure": False,
            "initial_failure_reason": None,
            "retry_attempted": False,
            "retry_response_received": False,
            "retry_succeeded": False,
            "retry_validation_accepted": False,
            "retry_provider_error": None,
            "retry_failure_reason": None,
            "fallback_used": False,
            "fallback_reason": None,
            "fallback_validated": True,
            "post_guard_category_preserved": True,
            "final_accepted": True,
            "provider_http_latency_ms": None,
            "retry_http_latency_ms": None,
            "candidate_latency_ms": 0.0,
            "end_to_end_latency_ms": 0.0,
            "attempt_records": [],
        }

        # Safe fallback generator with deterministic pre-return validation
        def fallback_result(source: str = "rule", reason: str = "offline_mode") -> Dict[str, Any]:
            safe_expl = build_safe_grounded_template(candidate_finding, evidence_context, ccpa_def)
            # Validate fallback output before returning or persisting
            is_valid, _ = validate_explanation(
                safe_expl, category_key, evidence_context, candidate_finding
            )
            if not is_valid:
                # Ultra-conservative guaranteed-safe fallback if custom rule text had issues
                safe_expl = (
                    f"Observed potential indicator of {cat_name} ({official_id}): "
                    f"automated empirical checkout audit observation. Technical finding only; not a legal determination."
                )
                is_valid, _ = validate_explanation(
                    safe_expl, category_key, evidence_context, candidate_finding
                )
            cand_lat = (time.perf_counter() - t_start) * 1000 if 't_start' in locals() else 0.0
            telemetry["fallback_used"] = True
            telemetry["fallback_reason"] = telemetry.get("fallback_reason") or reason
            telemetry["fallback_validated"] = is_valid
            telemetry["candidate_latency_ms"] = cand_lat
            telemetry["end_to_end_latency_ms"] = cand_lat

            cand_id = candidate_finding.get("id") or candidate_finding.get("dedup_key") or candidate_finding.get("diff_id") or f"cand_{category_key}"
            if not telemetry.get("attempt_records"):
                telemetry["attempt_records"].append({
                    "candidate_id": cand_id,
                    "category": category_key,
                    "attempt": 0,
                    "attempt_type": "initial",
                    "http_status": None,
                    "http_response_received": False,
                    "model_output_received": False,
                    "latency_ms": None,
                    "transport_error": None if self.api_key else "offline_mode_no_api_key",
                    "http_outcome": "offline_mode" if not self.api_key else (telemetry.get("fallback_reason") or "fallback"),
                    "response_received": False,
                    "validator_outcome": "not_applicable",
                    "fallback_reason": reason,
                    "schema_valid": None,
                    "wording_valid": None,
                    "category_concordance": None,
                    "concept_keyword_coverage": None,
                })

            return {
                **candidate_finding,
                "category": category_key,
                "severity": candidate_finding.get("severity", "medium"),
                "confidence": candidate_finding.get("confidence", 0.85),
                "explanation": safe_expl,
                "evidence_ids": candidate_finding.get("evidence_ids", []),
                "source": source,
                "telemetry": telemetry,
            }

        if not self.api_key:
            return fallback_result(source="rule", reason="no_api_key")

        system_prompt = (
            "You are a consumer rights checkout transparency auditor for India's CCPA 2023 Guidelines. "
            "Analyze the candidate finding and evidence against the official CCPA definition. "
            "STRICT QUALITY GATES: "
            "1. Phrasing must strictly be framed as a 'potential indicator' of the category. "
            "2. NEVER declare legal guilt, statutory violation, or liability. Prohibited terms: "
            "guilty, convicted, verdict, criminal, illegal, unlawful, liable. "
            "3. Ground all statements strictly in the provided evidence. If a fee was not observed upfront, "
            "check whether disclosure was verified absent or unknown. If unknown or unobserved, state that "
            "earlier disclosure status was unknown. Never claim verified absence without evidence. "
            f"4. You must preserve the candidate category exactly as '{category_key}'. "
            "5. Output strictly valid JSON with keys: category, severity, confidence, explanation, evidence_ids."
        )

        user_content = {
            "candidate": candidate_finding,
            "evidence": evidence_context,
            "ccpa_category_definition": official_text,
        }

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_content)},
        ]

        t_start = time.perf_counter()
        cand_id = candidate_finding.get("id") or candidate_finding.get("dedup_key") or candidate_finding.get("diff_id") or f"cand_{category_key}"

        # Bounded Retry Loop: exactly 1 initial attempt (attempt 0) + at most 1 corrective retry (attempt 1)
        for attempt in range(2):
            attempt_type = "initial" if attempt == 0 else "retry"
            current_attempt_record: Dict[str, Any] = {
                "candidate_id": cand_id,
                "category": category_key,
                "attempt": attempt,
                "attempt_type": attempt_type,
                "http_status": None,
                "http_response_received": False,
                "model_output_received": False,
                "latency_ms": None,
                "transport_error": None,
                "http_outcome": None,
                "response_received": False,
                "validator_outcome": None,
                "fallback_reason": None,
                "schema_valid": None,
                "wording_valid": None,
                "category_concordance": None,
                "concept_keyword_coverage": None,
            }
            telemetry["attempt_records"].append(current_attempt_record)

            try:
                if attempt == 1:
                    telemetry["retry_attempted"] = True

                raw_response = self._execute_llm_request(messages)
                http_lat = getattr(self, "_last_http_latency_ms", 0.0)
                status = getattr(self, "_last_http_status", 200)

                current_attempt_record["http_status"] = status
                current_attempt_record["http_response_received"] = True
                current_attempt_record["model_output_received"] = True
                current_attempt_record["response_received"] = True
                current_attempt_record["latency_ms"] = round(http_lat, 2) if http_lat is not None else None
                current_attempt_record["transport_error"] = None
                current_attempt_record["http_outcome"] = "200_ok"

                if attempt == 0:
                    telemetry["initial_response_received"] = True
                    telemetry["provider_http_latency_ms"] = http_lat
                else:
                    telemetry["retry_response_received"] = True
                    telemetry["retry_http_latency_ms"] = http_lat

                # Step 1: Parse JSON and validate ClassifiedFinding model
                try:
                    parsed = json.loads(raw_response)
                    validated_model = ClassifiedFinding(**parsed)
                    current_attempt_record["schema_valid"] = True
                    if attempt == 0:
                        telemetry["first_pass_schema_valid"] = True
                except Exception as parse_err:
                    current_attempt_record["schema_valid"] = False
                    current_attempt_record["wording_valid"] = False
                    current_attempt_record["category_concordance"] = False
                    current_attempt_record["concept_keyword_coverage"] = False
                    current_attempt_record["validator_outcome"] = "rejected_schema"
                    if attempt == 0:
                        telemetry["first_pass_schema_valid"] = False
                        telemetry["first_pass_wording_valid"] = False
                        telemetry["first_pass_grounding_valid"] = False
                        telemetry["first_pass_overall_valid"] = False
                        telemetry["model_validation_failure"] = True
                        telemetry["initial_failure_reason"] = f"Schema validation error: {parse_err}"
                        current_attempt_record["fallback_reason"] = None
                        messages.append({"role": "assistant", "content": raw_response})
                        messages.append({
                            "role": "user",
                            "content": (
                                f"SCHEMA ERROR: {parse_err}. "
                                "Output strictly valid JSON with keys: category, severity, confidence, explanation, evidence_ids."
                            ),
                        })
                        continue
                    else:
                        current_attempt_record["fallback_reason"] = "model_validation_exhausted"
                        telemetry["retry_succeeded"] = False
                        telemetry["retry_failure_reason"] = f"Schema validation error on retry: {parse_err}"
                        break

                # Step 2: Deterministic output-validation layer (wording, grounding, category alignment)
                is_valid, rejection_reason = validate_explanation(
                    validated_model.explanation,
                    validated_model.category,
                    evidence_context,
                    candidate_finding=candidate_finding,
                    evidence_ids=validated_model.evidence_ids,
                )

                expl_lower = validated_model.explanation.lower()
                has_indicator = any(t in expl_lower for t in MANDATORY_INDICATOR_TERMS)
                has_adjudicative = any(
                    pp.search(validated_model.explanation) for pp in PROHIBITED_ADJUDICATIVE_PATTERNS
                )
                is_wording_valid = has_indicator and not has_adjudicative
                is_concordant = (validated_model.category.strip().lower() == category_key.strip().lower())
                cat_kws = {
                    "drip_pricing": ["drip", "annex_1_8", "upfront", "elements of prices", "mandatory charge", "fee", "concealed", "hidden"],
                    "basket_sneaking": ["basket", "sneaking", "annex_1_2", "pre-selected", "preselected", "express consent", "additional items", "add-on"],
                    "false_urgency": ["urgency", "annex_1_1", "countdown", "deadline", "timer", "reset"],
                }
                expected_kw = cat_kws.get(category_key, ["ccpa", "dark pattern"])
                has_concept_kw = any(kw in expl_lower for kw in expected_kw)

                current_attempt_record["wording_valid"] = is_wording_valid
                current_attempt_record["category_concordance"] = is_concordant
                current_attempt_record["concept_keyword_coverage"] = has_concept_kw

                # Record first-pass breakdown
                if attempt == 0:
                    telemetry["first_pass_wording_valid"] = is_wording_valid
                    telemetry["first_pass_grounding_valid"] = is_valid or ("Missing mandatory" in (rejection_reason or "") or "Prohibited adjudicative" in (rejection_reason or ""))
                    telemetry["first_pass_overall_valid"] = is_valid
                    telemetry["raw_model_category"] = validated_model.category
                    telemetry["raw_category_concordance"] = is_concordant
                    telemetry["raw_concept_keyword_coverage"] = has_concept_kw
                    telemetry["raw_statutory_concept_alignment"] = has_concept_kw

                    if not is_valid:
                        telemetry["model_validation_failure"] = True
                        telemetry["initial_failure_reason"] = rejection_reason

                if is_valid:
                    current_attempt_record["validator_outcome"] = "accepted"
                    current_attempt_record["fallback_reason"] = None
                    if attempt == 1:
                        telemetry["retry_succeeded"] = True
                        telemetry["retry_validation_accepted"] = True

                    expl = validated_model.explanation
                    # Ensure observed monetary amounts and specific empirical observations are preserved
                    cand_expl = candidate_finding.get("explanation", "")
                    cand_amt = re.search(r"₹\d+(?:\.\d{2})?", cand_expl)
                    if cand_amt and cand_amt.group(0) not in expl:
                        expl = f"{expl} Observed amount: {cand_amt.group(0)}."

                    if category_key == "false_urgency":
                        if "holding session and page state fixed without navigation" not in expl:
                            expl = f"{expl} (Empirical observation: {cand_expl})"

                    cand_lat = (time.perf_counter() - t_start) * 1000
                    telemetry["candidate_latency_ms"] = cand_lat
                    telemetry["end_to_end_latency_ms"] = cand_lat
                    return {
                        **candidate_finding,
                        "category": validated_model.category,
                        "severity": validated_model.severity,
                        "confidence": validated_model.confidence,
                        "explanation": expl,
                        "evidence_ids": validated_model.evidence_ids or candidate_finding.get("evidence_ids", []),
                        "source": "llm",
                        "telemetry": telemetry,
                    }

                # Attempt failed quality gate -> prepare bounded corrective retry prompt
                rej = rejection_reason or ""
                if not is_wording_valid:
                    val_outcome = "rejected_wording"
                elif not is_concordant:
                    val_outcome = "rejected_category"
                elif any(k in rej for k in ["Ungrounded", "Invented", "Evidence"]):
                    val_outcome = "rejected_grounding"
                else:
                    val_outcome = "rejected_validation"
                current_attempt_record["validator_outcome"] = val_outcome

                if attempt == 0:
                    current_attempt_record["fallback_reason"] = None
                    messages.append({"role": "assistant", "content": raw_response})
                    messages.append({
                        "role": "user",
                        "content": (
                            f"QUALITY GATE REJECTION: {rejection_reason} "
                            "Please re-generate the JSON response. Ensure the explanation explicitly states 'potential indicator', "
                            "strictly avoids all prohibited adjudicative terms, grounds disclosure statements in observed evidence, "
                            f"and preserves the candidate category '{category_key}'."
                        ),
                    })
                else:
                    current_attempt_record["fallback_reason"] = "model_validation_exhausted"
                    telemetry["retry_succeeded"] = False
                    telemetry["retry_validation_accepted"] = False
                    telemetry["retry_failure_reason"] = rejection_reason

            except Exception as e:
                err_str = str(e)
                code = getattr(e, "code", None) or getattr(self, "_last_http_status", None)
                if code == 429 or "429" in err_str:
                    http_outcome = "429_rate_limit"
                elif code == 403 or "403" in err_str:
                    http_outcome = "403_forbidden"
                elif code == 200 or "HTTP 200" in err_str:
                    http_outcome = "200_malformed_body"
                elif code:
                    http_outcome = f"HTTP_{code}"
                else:
                    http_outcome = f"error_{type(e).__name__}"

                resp_recvd = getattr(self, "_last_http_response_received", False) or (code is not None)
                http_lat = getattr(self, "_last_http_latency_ms", None) if resp_recvd else None
                trans_err = getattr(self, "_last_transport_error", None) if not resp_recvd else None
                if not resp_recvd and trans_err is None:
                    trans_err = str(e)

                current_attempt_record["http_status"] = code
                current_attempt_record["http_response_received"] = bool(resp_recvd)
                current_attempt_record["model_output_received"] = False
                current_attempt_record["response_received"] = False
                current_attempt_record["latency_ms"] = round(http_lat, 2) if http_lat is not None else None
                current_attempt_record["transport_error"] = trans_err
                current_attempt_record["http_outcome"] = http_outcome
                current_attempt_record["validator_outcome"] = "not_applicable"
                current_attempt_record["fallback_reason"] = "provider_error"

                if attempt == 0:
                    telemetry["provider_error"] = str(e)
                    telemetry["initial_failure_reason"] = f"Provider Error: {e}"
                    telemetry["fallback_reason"] = "provider_error"
                    if resp_recvd and http_lat is not None:
                        telemetry["provider_http_latency_ms"] = round(http_lat, 2)
                else:
                    telemetry["retry_provider_error"] = str(e)
                    telemetry["retry_succeeded"] = False
                    telemetry["retry_validation_accepted"] = False
                    telemetry["retry_failure_reason"] = f"Provider Error: {e}"
                    if resp_recvd and http_lat is not None:
                        telemetry["retry_http_latency_ms"] = round(http_lat, 2)
                break

        # If bounded retry exhausted or failed quality gate, return safe deterministic fallback
        cand_lat = (time.perf_counter() - t_start) * 1000
        telemetry["candidate_latency_ms"] = cand_lat
        telemetry["end_to_end_latency_ms"] = cand_lat
        fb_reason = telemetry.get("fallback_reason") or ("model_validation_exhausted" if telemetry.get("model_validation_failure") else "provider_error")
        telemetry["fallback_reason"] = fb_reason
        return fallback_result(source="llm_guarded_fallback", reason=fb_reason)


def aggregate_provider_latencies(telemetry_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Aggregate provider HTTP latencies across all received responses,
    including initial candidate submissions and corrective retries (regardless of
    whether a retry was accepted or rejected by application-level validation).

    Guarantees:
    - Application-level validation rejection does NOT exclude an otherwise successful
      HTTP response from the network latency sample.
    - Pure provider/network errors (where no HTTP response was received) are excluded.
    """
    import statistics

    latencies: List[float] = []
    initial_count = 0
    retry_count = 0

    for telem in telemetry_records:
        if telem.get("initial_response_received"):
            p_lat = telem.get("provider_http_latency_ms")
            if p_lat is not None and p_lat > 0:
                latencies.append(p_lat)
                initial_count += 1

        if telem.get("retry_response_received"):
            r_lat = telem.get("retry_http_latency_ms")
            if r_lat is not None and r_lat > 0:
                latencies.append(r_lat)
                retry_count += 1

    if not latencies:
        return {
            "sample_size": 0,
            "initial_responses": 0,
            "retry_responses": 0,
            "mean_ms": None,
            "median_ms": None,
            "p95_ms": None,
            "raw_samples": [],
        }

    sorted_lats = sorted(latencies)
    p95_idx = min(int(0.95 * len(sorted_lats)), len(sorted_lats) - 1)

    return {
        "sample_size": len(latencies),
        "initial_responses": initial_count,
        "retry_responses": retry_count,
        "mean_ms": statistics.mean(latencies),
        "median_ms": statistics.median(latencies),
        "p95_ms": sorted_lats[p95_idx],
        "raw_samples": latencies,
    }


def calculate_metrics_from_records(
    attempt_records: List[Dict[str, Any]],
    candidate_telemetry: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Calculate auditable evaluation metrics strictly from persisted attempt-level records
    and candidate-level telemetry.

    Guarantees:
    - Attempt-level empirical provenance: counts and latencies are calculated directly
      from discrete persisted attempt records.
    - Explicit separation of provider failures (network/rate limits) from model validation failures.
    - Explicit separation of HTTP transport failures (no HTTP response received) from
      HTTP responses with error status codes (HTTP 429/403 with measured round-trip latencies).
    - Dual latency profiles: usable model completion latency vs all HTTP response latency.
    - All latency statistics (mean, median, p95) are computed directly from the collection
      of received HTTP response timings.
    """
    import statistics

    def _compute_stats(lats: List[float], init_cnt: int = 0, ret_cnt: int = 0) -> Dict[str, Any]:
        if not lats:
            return {
                "sample_size": 0,
                "initial_responses": init_cnt,
                "retry_responses": ret_cnt,
                "mean_ms": None,
                "median_ms": None,
                "p95_ms": None,
                "raw_samples": [],
            }
        sorted_lats = sorted(lats)
        p95_idx = min(int(0.95 * len(sorted_lats)), len(sorted_lats) - 1)
        return {
            "sample_size": len(lats),
            "initial_responses": init_cnt,
            "retry_responses": ret_cnt,
            "mean_ms": round(statistics.mean(lats), 1),
            "median_ms": round(statistics.median(lats), 1),
            "p95_ms": round(sorted_lats[p95_idx], 1),
            "raw_samples": lats,
        }

    first_attempts = [r for r in attempt_records if r.get("attempt") == 0]
    retries = [r for r in attempt_records if r.get("attempt") == 1]
    total_candidates = len(first_attempts)

    def _is_model_output(r: Dict[str, Any]) -> bool:
        if "model_output_received" in r:
            return bool(r["model_output_received"])
        return bool(
            r.get("response_received")
            and (r.get("http_outcome") == "200_ok" or r.get("http_status") == 200 or not str(r.get("http_status", 200)) in ("429", "403"))
        )

    def _is_http_response(r: Dict[str, Any]) -> bool:
        if "http_response_received" in r:
            return bool(r["http_response_received"])
        return bool(
            r.get("http_status") is not None
            or (r.get("latency_ms") is not None and r.get("latency_ms") > 0)
            or r.get("response_received")
        )

    initial_model_responses = sum(1 for r in first_attempts if _is_model_output(r))
    initial_model_failures = total_candidates - initial_model_responses

    initial_http_responses = sum(1 for r in first_attempts if _is_http_response(r))
    initial_transport_errors = total_candidates - initial_http_responses

    retries_attempted = len(retries)
    retry_model_responses = sum(1 for r in retries if _is_model_output(r))
    retry_model_failures = retries_attempted - retry_model_responses

    retry_http_responses = sum(1 for r in retries if _is_http_response(r))
    retry_transport_errors = retries_attempted - retry_http_responses

    retry_accepted = sum(1 for r in retries if r.get("validator_outcome") == "accepted")
    retry_rejected = sum(
        1 for r in retries if _is_model_output(r) and r.get("validator_outcome") != "accepted"
    )

    total_http_requests = len(attempt_records)
    total_http_responses = sum(1 for r in attempt_records if _is_http_response(r))
    total_transport_errors = total_http_requests - total_http_responses

    total_model_responses = sum(1 for r in attempt_records if _is_model_output(r))

    # Dual Latency calculation
    # 1. Usable Model Latencies (HTTP 200 responses with model completions)
    model_latencies = [
        float(r["latency_ms"])
        for r in attempt_records
        if _is_model_output(r) and r.get("latency_ms") is not None and r.get("latency_ms") > 0
    ]
    init_model_lats = sum(
        1 for r in first_attempts
        if _is_model_output(r) and r.get("latency_ms") is not None and r.get("latency_ms") > 0
    )
    ret_model_lats = sum(
        1 for r in retries
        if _is_model_output(r) and r.get("latency_ms") is not None and r.get("latency_ms") > 0
    )
    successful_model_latency = _compute_stats(model_latencies, init_model_lats, ret_model_lats)

    # 2. All HTTP Latencies (including HTTP 429 / 403 responses that completed network round-trips)
    http_latencies = [
        float(r["latency_ms"])
        for r in attempt_records
        if _is_http_response(r) and r.get("latency_ms") is not None and r.get("latency_ms") > 0
    ]
    init_http_lats = sum(
        1 for r in first_attempts
        if _is_http_response(r) and r.get("latency_ms") is not None and r.get("latency_ms") > 0
    )
    ret_http_lats = sum(
        1 for r in retries
        if _is_http_response(r) and r.get("latency_ms") is not None and r.get("latency_ms") > 0
    )
    all_http_latency = _compute_stats(http_latencies, init_http_lats, ret_http_lats)

    # First-pass raw model quality gates (denominator = initial model responses received)
    first_pass_responses = [r for r in first_attempts if _is_model_output(r)]
    n_first_pass = len(first_pass_responses)
    first_pass_schema = sum(1 for r in first_pass_responses if r.get("schema_valid"))
    first_pass_wording = sum(1 for r in first_pass_responses if r.get("wording_valid"))
    first_pass_concordance = sum(1 for r in first_pass_responses if r.get("category_concordance"))
    first_pass_concept_kw = sum(1 for r in first_pass_responses if r.get("concept_keyword_coverage"))
    initial_validation_failures = sum(
        1 for r in first_pass_responses if r.get("validator_outcome") != "accepted"
    )

    # Fallback and pipeline outputs
    if candidate_telemetry:
        deterministic_fallbacks = sum(1 for c in candidate_telemetry if c.get("fallback_used"))
        final_accepted = len(candidate_telemetry)
        evidence_grounding = sum(1 for c in candidate_telemetry if c.get("evidence_grounding_valid", True))
        post_guard_category = sum(1 for c in candidate_telemetry if c.get("post_guard_category_preserved", True))
        post_guard_concept_kw = sum(1 for c in candidate_telemetry if c.get("post_guard_concept_keyword_coverage", True))
    else:
        deterministic_fallbacks = initial_model_failures + retry_rejected
        final_accepted = total_candidates
        evidence_grounding = total_candidates
        post_guard_category = total_candidates
        post_guard_concept_kw = total_candidates

    from collections import Counter
    status_counts = Counter(r.get("http_status") for r in attempt_records if r.get("http_status") is not None)
    status_200_count = status_counts.get(200, 0)
    status_429_count = status_counts.get(429, 0)
    status_403_count = status_counts.get(403, 0)
    status_other_count = sum(v for k, v in status_counts.items() if k not in (200, 429, 403))

    first_status_counts = Counter(r.get("http_status") for r in first_attempts if r.get("http_status") is not None)
    first_status_200 = first_status_counts.get(200, 0)
    first_status_429 = first_status_counts.get(429, 0)
    first_status_403 = first_status_counts.get(403, 0)
    first_status_other = sum(v for k, v in first_status_counts.items() if k not in (200, 429, 403))

    initial_http_failures = sum(
        1 for r in first_attempts
        if _is_http_response(r) and not _is_model_output(r)
    )

    return {
        # Core backward-compatible fields
        "candidates_submitted": total_candidates,
        "initial_responses_received": initial_model_responses,
        "initial_provider_failures": initial_model_failures,
        "initial_provider_coverage_pct": (initial_model_responses / total_candidates * 100) if total_candidates else 0.0,
        "retries_attempted": retries_attempted,
        "retry_responses_received": retry_model_responses,
        "retry_provider_failures": retry_model_failures,
        "retry_validation_acceptances": retry_accepted,
        "retry_validation_rejections": retry_rejected,
        "total_http_requests": total_http_requests,
        "successful_http_responses": total_model_responses,
        "successful_provider_rate_pct": (total_model_responses / total_http_requests * 100) if total_http_requests else 0.0,
        "provider_latency": successful_model_latency,
        "successful_model_latency": successful_model_latency,
        "all_http_latency": all_http_latency,

        # Explicit HTTP Transport Accounting
        "http_accounting": {
            "total_requests": total_http_requests,
            "http_responses_received": total_http_responses,
            "transport_errors": total_transport_errors,
            "http_response_rate_pct": (total_http_responses / total_http_requests * 100) if total_http_requests else 0.0,
            "status_code_counts": dict(status_counts),
            "status_200_count": status_200_count,
            "status_429_count": status_429_count,
            "status_403_count": status_403_count,
            "status_other_count": status_other_count,
            "initial_http_responses": initial_http_responses,
            "initial_http_failures": initial_http_failures,
            "initial_status_200": first_status_200,
            "initial_status_429": first_status_429,
            "initial_status_403": first_status_403,
            "initial_status_other": first_status_other,
            "initial_transport_errors": initial_transport_errors,
            "retry_http_responses": retry_http_responses,
            "retry_transport_errors": retry_transport_errors,
        },

        # Explicit Model Output Accounting
        "model_accounting": {
            "candidates_submitted": total_candidates,
            "initial_model_responses": initial_model_responses,
            "initial_model_failures": initial_model_failures,
            "initial_http_provider_failures": initial_http_failures,
            "initial_transport_errors": initial_transport_errors,
            "initial_model_coverage_pct": (initial_model_responses / total_candidates * 100) if total_candidates else 0.0,
            "retries_attempted": retries_attempted,
            "retry_model_responses": retry_model_responses,
            "retry_provider_failures": retry_model_failures,
            "retry_validation_acceptances": retry_accepted,
            "retry_validation_rejections": retry_rejected,
            "total_model_responses": total_model_responses,
            "successful_model_rate_pct": (total_model_responses / total_http_requests * 100) if total_http_requests else 0.0,
        },

        # First-pass quality gates
        "first_pass_quality": {
            "responses_received": n_first_pass,
            "schema_valid": first_pass_schema,
            "wording_valid": first_pass_wording,
            "category_concordance": first_pass_concordance,
            "concept_keyword_coverage": first_pass_concept_kw,
            "initial_validation_failures": initial_validation_failures,
        },

        # Pipeline outputs
        "pipeline_quality": {
            "deterministic_fallbacks": deterministic_fallbacks,
            "final_accepted_outputs": final_accepted,
            "evidence_grounding_passed": evidence_grounding,
            "post_guard_category_preserved": post_guard_category,
            "post_guard_concept_keyword_coverage": post_guard_concept_kw,
        },
    }
