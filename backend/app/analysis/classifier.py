"""Schema-validated LLM Classifier for Potential Dark Pattern Indicators.

Principles:
1. Classifies upstream candidates only; never invents findings from unobserved data.
2. Injects verbatim definitions from /data/ccpa_definitions.json.
3. Enforces strict schema validation with fallback to rule detector.
4. Language is strictly 'potential indicator', never a legal verdict.
"""

import json
import os
import urllib.request
import urllib.error
from typing import Dict, Any, Optional
from pathlib import Path
from pydantic import BaseModel, Field


class ClassifiedFinding(BaseModel):
    category: str
    severity: str = Field(description="low, medium, or high")
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    evidence_ids: list[str] = Field(default_factory=list)


def load_ccpa_definitions() -> Dict[str, Any]:
    def_path = Path("/home/daksh/working/checkout-radar/data/ccpa_definitions.json")
    if def_path.exists():
        with open(def_path, "r", encoding="utf-8") as f:
            return json.load(f).get("categories", {})
    return {}


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

    def classify_candidate(
        self,
        candidate_finding: Dict[str, Any],
        evidence_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Classify candidate finding against CCPA definitions.
        Falls back safely to the rule detector output if LLM is unavailable.
        """
        category_key = candidate_finding.get("category", "")
        ccpa_def = self.ccpa_definitions.get(category_key, {})
        official_text = ccpa_def.get("definition", "Dark pattern under CCPA guidelines.")

        # If no LLM API key is provided, return rule output with official definition context
        if not self.api_key:
            return {
                **candidate_finding,
                "source": "rule",
                "explanation": f"{candidate_finding.get('explanation', '')} (Aligned with CCPA 2023 definition: {official_text[:120]}...)",
            }

        # Prompt LLM with candidate, evidence, and official CCPA definition
        system_prompt = (
            "You are a consumer rights checkout transparency auditor. "
            "Analyze the candidate finding and evidence against the official CCPA 2023 dark patterns definition. "
            "Never declare legal guilt or statutory violations; always phrase findings as 'potential indicators'. "
            "Output strictly valid JSON with keys: category, severity, confidence, explanation, evidence_ids."
        )

        user_content = {
            "candidate": candidate_finding,
            "evidence": evidence_context,
            "ccpa_category_definition": official_text,
        }

        try:
            req_data = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_content)},
                ],
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
            }

            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=json.dumps(req_data).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=15) as resp:
                resp_json = json.loads(resp.read().decode("utf-8"))
                choice = resp_json["choices"][0]["message"]["content"]
                parsed = json.loads(choice)
                validated = ClassifiedFinding(**parsed)

                return {
                    **candidate_finding,
                    "category": validated.category,
                    "severity": validated.severity,
                    "confidence": validated.confidence,
                    "explanation": validated.explanation,
                    "evidence_ids": validated.evidence_ids or candidate_finding.get("evidence_ids", []),
                    "source": "llm",
                }
        except Exception:
            # Fallback cleanly to rule output
            return {
                **candidate_finding,
                "source": "rule",
            }
