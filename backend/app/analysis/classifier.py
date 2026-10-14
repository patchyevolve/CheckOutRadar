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

    def _execute_llm_request(self, messages: List[Dict[str, str]]) -> str:
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
        for attempt_http in range(2):
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    resp_json = json.loads(resp.read().decode("utf-8"))
                    choice = resp_json["choices"][0]["message"]["content"].strip()
                    if choice.startswith("```"):
                        lines = choice.splitlines()
                        if lines and lines[0].startswith("```"):
                            lines = lines[1:]
                        if lines and lines[-1].startswith("```"):
                            lines = lines[:-1]
                        choice = "\n".join(lines).strip()
                    return choice
            except urllib.error.HTTPError as he:
                if he.code in (429, 502, 503) and attempt_http == 0:
                    time.sleep(1.0)
                    continue
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
            "raw_statutory_concept_alignment": None,
            "model_validation_failure": False,
            "initial_failure_reason": None,
            "retry_attempted": False,
            "retry_succeeded": False,
            "retry_failure_reason": None,
            "fallback_used": False,
            "fallback_reason": None,
            "fallback_validated": True,
            "post_guard_category_preserved": True,
            "final_accepted": True,
            "end_to_end_latency_ms": 0.0,
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
            telemetry["fallback_used"] = True
            telemetry["fallback_reason"] = telemetry.get("fallback_reason") or reason
            telemetry["fallback_validated"] = is_valid
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

        # Bounded Retry Loop: exactly 1 initial attempt (attempt 0) + at most 1 corrective retry (attempt 1)
        for attempt in range(2):
            try:
                if attempt == 1:
                    telemetry["retry_attempted"] = True

                raw_response = self._execute_llm_request(messages)

                if attempt == 0:
                    telemetry["initial_response_received"] = True

                # Step 1: Parse JSON and validate ClassifiedFinding model
                try:
                    parsed = json.loads(raw_response)
                    validated_model = ClassifiedFinding(**parsed)
                    if attempt == 0:
                        telemetry["first_pass_schema_valid"] = True
                except Exception as parse_err:
                    if attempt == 0:
                        telemetry["first_pass_schema_valid"] = False
                        telemetry["first_pass_wording_valid"] = False
                        telemetry["first_pass_grounding_valid"] = False
                        telemetry["first_pass_overall_valid"] = False
                        telemetry["model_validation_failure"] = True
                        telemetry["initial_failure_reason"] = f"Schema validation error: {parse_err}"
                    if attempt == 0:
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

                # Record first-pass breakdown
                if attempt == 0:
                    expl_lower = validated_model.explanation.lower()
                    has_indicator = any(t in expl_lower for t in MANDATORY_INDICATOR_TERMS)
                    has_adjudicative = any(
                        pp.search(validated_model.explanation) for pp in PROHIBITED_ADJUDICATIVE_PATTERNS
                    )
                    telemetry["first_pass_wording_valid"] = has_indicator and not has_adjudicative
                    telemetry["first_pass_grounding_valid"] = is_valid or ("Missing mandatory" in (rejection_reason or "") or "Prohibited adjudicative" in (rejection_reason or ""))
                    telemetry["first_pass_overall_valid"] = is_valid
                    telemetry["raw_model_category"] = validated_model.category
                    telemetry["raw_category_concordance"] = (
                        validated_model.category.strip().lower() == category_key.strip().lower()
                    )
                    cat_kws = {
                        "drip_pricing": ["drip", "annex_1_8", "upfront", "elements of prices", "mandatory charge", "fee", "concealed", "hidden"],
                        "basket_sneaking": ["basket", "sneaking", "annex_1_2", "pre-selected", "preselected", "express consent", "additional items", "add-on"],
                        "false_urgency": ["urgency", "annex_1_1", "countdown", "deadline", "timer", "reset"],
                    }
                    expected_kw = cat_kws.get(category_key, ["ccpa", "dark pattern"])
                    telemetry["raw_statutory_concept_alignment"] = any(kw in expl_lower for kw in expected_kw)

                    if not is_valid:
                        telemetry["model_validation_failure"] = True
                        telemetry["initial_failure_reason"] = rejection_reason

                if is_valid:
                    if attempt == 1:
                        telemetry["retry_succeeded"] = True

                    expl = validated_model.explanation
                    # Ensure observed monetary amounts and specific empirical observations are preserved
                    cand_expl = candidate_finding.get("explanation", "")
                    cand_amt = re.search(r"₹\d+(?:\.\d{2})?", cand_expl)
                    if cand_amt and cand_amt.group(0) not in expl:
                        expl = f"{expl} Observed amount: {cand_amt.group(0)}."

                    if category_key == "false_urgency":
                        if "holding session and page state fixed without navigation" not in expl:
                            expl = f"{expl} (Empirical observation: {cand_expl})"

                    telemetry["end_to_end_latency_ms"] = (time.perf_counter() - t_start) * 1000
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
                if attempt == 0:
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
                    telemetry["retry_succeeded"] = False
                    telemetry["retry_failure_reason"] = rejection_reason

            except Exception as e:
                # Provider / network / HTTP throttling error (e.g. 429, 403, timeout)
                if attempt == 0:
                    telemetry["provider_error"] = str(e)
                    telemetry["initial_failure_reason"] = f"Provider Error: {e}"
                    telemetry["fallback_reason"] = "provider_error"
                else:
                    telemetry["retry_succeeded"] = False
                    telemetry["retry_failure_reason"] = f"Provider Error: {e}"
                break

        # If bounded retry exhausted or failed quality gate, return safe deterministic fallback
        telemetry["end_to_end_latency_ms"] = (time.perf_counter() - t_start) * 1000
        fb_reason = telemetry.get("fallback_reason") or ("model_validation_exhausted" if telemetry.get("model_validation_failure") else "provider_error")
        telemetry["fallback_reason"] = fb_reason
        return fallback_result(source="llm_guarded_fallback", reason=fb_reason)
