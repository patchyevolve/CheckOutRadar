"""Schema-validated LLM Classifier for Potential Dark Pattern Indicators.

Principles:
1. Classifies upstream candidates only; never invents findings from unobserved data.
2. Injects verbatim definitions from /data/ccpa_definitions.json.
3. Enforces strict schema validation and deterministic output guardrails.
4. Language is strictly 'potential indicator', never a legal verdict.
5. Factual assertions must be grounded in empirical evidence:
   - "unknown" disclosure is never read as "not disclosed" or "absent".
   - Prohibited adjudicative terms are deterministically rejected with bounded retry & safe template fallback.
"""

import json
import os
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, Tuple, List
from pathlib import Path
from pydantic import BaseModel, Field


class ClassifiedFinding(BaseModel):
    category: str
    severity: str = Field(description="low, medium, or high")
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    evidence_ids: list[str] = Field(default_factory=list)


PROHIBITED_LEGAL_TERMS = [
    "guilty",
    "convicted",
    "verdict",
    "criminal",
    "illegal",
    "illegality",
    "violates the law",
    "violated the law",
    "violation of law",
    "unlawful",
    "culpable",
    "infraction of the law",
    "breach of law",
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
) -> Tuple[bool, Optional[str]]:
    """
    Deterministically validate explanation against non-judicial wording
    and empirical evidence grounding rules.
    Returns (is_valid, rejection_reason).
    """
    expl_lower = explanation.lower()

    # 1. Prohibited legal verdict / adjudicative terms check
    for term in PROHIBITED_LEGAL_TERMS:
        if term in expl_lower:
            return False, f"Prohibited adjudicative term '{term}' detected. Must be framed as a potential indicator, not a legal verdict."

    # 2. Mandatory indicator phrasing check
    if not any(term in expl_lower for term in MANDATORY_INDICATOR_TERMS):
        return False, "Missing mandatory non-judicial framing (must explicitly identify finding as a 'potential indicator')."

    # 3. Evidence grounding check for fee absence claims
    absence_markers = ["absent at", "concealed at", "undisclosed at", "was not disclosed at", "hidden at product"]
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
    if raw_expl and "potential" in raw_expl.lower() and not any(t in raw_expl.lower() for t in PROHIBITED_LEGAL_TERMS):
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

    def classify_candidate(
        self,
        candidate_finding: Dict[str, Any],
        evidence_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Classify candidate finding against CCPA definitions with deterministic
        output validation, bounded retry, and safe template fallback.
        """
        category_key = candidate_finding.get("category", "")
        ccpa_def = self.ccpa_definitions.get(category_key, {})
        official_text = ccpa_def.get("definition", "Dark pattern under CCPA guidelines.")

        # Fallback template generator helper
        def fallback_result(source: str = "rule") -> Dict[str, Any]:
            safe_expl = build_safe_grounded_template(candidate_finding, evidence_context, ccpa_def)
            return {
                **candidate_finding,
                "category": category_key,
                "severity": candidate_finding.get("severity", "medium"),
                "confidence": candidate_finding.get("confidence", 0.85),
                "explanation": safe_expl,
                "evidence_ids": candidate_finding.get("evidence_ids", []),
                "source": source,
            }

        if not self.api_key:
            return fallback_result(source="rule")

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
            "4. Output strictly valid JSON with keys: category, severity, confidence, explanation, evidence_ids."
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

        # Bounded Retry Loop (max 2 attempts)
        for attempt in range(2):
            try:
                raw_response = self._execute_llm_request(messages)
                parsed = json.loads(raw_response)
                validated_model = ClassifiedFinding(**parsed)

                # Deterministic output-validation layer
                is_valid, rejection_reason = validate_explanation(
                    validated_model.explanation,
                    validated_model.category,
                    evidence_context,
                )

                if is_valid:
                    expl = validated_model.explanation
                    # Ensure observed monetary amounts and specific empirical observations are preserved
                    import re
                    cand_expl = candidate_finding.get("explanation", "")
                    cand_amt = re.search(r"₹\d+(?:\.\d{2})?", cand_expl)
                    if cand_amt and cand_amt.group(0) not in expl:
                        expl = f"{expl} Observed amount: {cand_amt.group(0)}."

                    if category_key == "false_urgency":
                        if "holding session and page state fixed without navigation" not in expl:
                            expl = f"{expl} (Empirical observation: {cand_expl})"

                    return {
                        **candidate_finding,
                        "category": validated_model.category,
                        "severity": validated_model.severity,
                        "confidence": validated_model.confidence,
                        "explanation": expl,
                        "evidence_ids": validated_model.evidence_ids or candidate_finding.get("evidence_ids", []),
                        "source": "llm",
                    }

                # Attempt failed quality gate -> prepare bounded retry prompt
                if attempt == 0:
                    messages.append({"role": "assistant", "content": raw_response})
                    messages.append({
                        "role": "user",
                        "content": (
                            f"QUALITY GATE REJECTION: {rejection_reason} "
                            "Please re-generate the JSON response. Ensure the explanation explicitly states 'potential indicator', "
                            "strictly avoids all prohibited adjudicative terms, and grounds disclosure statements in observed evidence."
                        ),
                    })

            except Exception:
                # Break on transport/API exception to proceed to safe deterministic fallback
                break

        # If bounded retry exhausted or failed quality gate, return safe deterministic fallback
        return fallback_result(source="llm_guarded_fallback")
