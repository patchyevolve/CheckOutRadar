"""Pydantic Models for Checkout Radar.

All money is represented as integer minor units (e.g., paise, cents).
Findings are strictly labelled 'potential indicators', never legal verdicts.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, model_validator


class RequestedCondition(BaseModel):
    pincode: Optional[str] = None
    session: str = Field(default="fresh", description="fresh or returning")
    cart_tier: str = Field(default="above_threshold", description="above_threshold or below_threshold")


class ObservedCondition(BaseModel):
    pincode: Optional[str] = None
    subtotal_minor: int
    currency: str = "INR"


class CartRecipeItem(BaseModel):
    product_id: str
    product_name: str
    variant: str = "default"
    quantity: int = 1
    unit_price_minor: int


class CartRecipe(BaseModel):
    recipe_family_id: str
    target_tier: str  # above_threshold or below_threshold
    threshold_minor: int = 50000  # e.g., ₹500.00
    items: List[CartRecipeItem]
    target_subtotal_minor: int
    mechanism: str = "quantity_increment"  # e.g. adding 2nd unit of item


class StageCapture(BaseModel):
    step_name: str  # product, cart, checkout_summary, other
    step_index: int
    provider_step_id: Optional[str] = None
    capture_status: str  # verified, failed, incomplete
    inspection_status: str  # inspected, uninspected
    screenshot_ref: Optional[str] = None


class ChargeObservation(BaseModel):
    label: str
    amount_minor: int
    currency: str = "INR"
    step: str  # stage where charge is observed
    mandatory: str = "yes"  # yes, no, unknown
    canonical_label: Optional[str] = None


class DisclosureObservation(BaseModel):
    charge_label: str
    step: str
    state: str  # observed, not_observed_verified, unknown
    visible_text: Optional[str] = None
    amount_minor: Optional[int] = None
    condition_text: Optional[str] = None


class PreselectedAddon(BaseModel):
    label: str
    amount_minor: int
    default_selected: bool
    user_modified: bool = False
    in_total: bool = True
    step: str = "cart"


class UrgencyIndicator(BaseModel):
    text: str
    type: str  # countdown, scarcity, social_proof, other
    claimed_deadline: Optional[str] = None
    observed_seconds_remaining: Optional[int] = None
    step: str = "product"


class MonetaryTotals(BaseModel):
    subtotal_minor: int
    charges_minor: int
    taxes_minor: int = 0
    discounts_minor: int = 0
    final_payable_minor: int
    currency: str = "INR"

    def is_reconciled(self) -> bool:
        """Check Subtotal + Charges + Taxes - Discounts == Final payable."""
        expected = self.subtotal_minor + self.charges_minor + self.taxes_minor - self.discounts_minor
        return expected == self.final_payable_minor


class AgentRunOutput(BaseModel):
    status: str  # ok, blocked_by_login, blocked_by_bot, condition_not_applied, extraction_inconsistent, unsupported, failed
    requested: RequestedCondition
    observed: ObservedCondition
    stage_captures: List[StageCapture] = Field(default_factory=list)
    charges: List[ChargeObservation] = Field(default_factory=list)
    disclosures: List[DisclosureObservation] = Field(default_factory=list)
    preselected_addons: List[PreselectedAddon] = Field(default_factory=list)
    urgency_indicators: List[UrgencyIndicator] = Field(default_factory=list)
    totals: MonetaryTotals
    policy_links: Optional[Dict[str, Optional[str]]] = None


class CreateAuditRequest(BaseModel):
    input_url: str
    merchant: Optional[str] = None
    preset: str = Field(default="quick", description="quick (4 runs) or full (12 runs)")
    cart_recipe: Optional[CartRecipe] = None
    schedule_interval: Optional[int] = None  # seconds, for temporal re-observation


class AuditResponse(BaseModel):
    id: str
    input_url: str
    merchant: str
    preset: str
    status: str
    created_at: str
    total_conditions: int
    completed_runs: int
    findings_count: int


class FindingResponse(BaseModel):
    id: str
    audit_id: str
    diff_id: Optional[str]
    category: str
    severity: str  # low, medium, high
    confidence: float
    explanation: str
    evidence_ids: List[str]
    source: str  # rule or llm
    dedup_key: str
    heuristic_note: Optional[str] = None


class DiffResponse(BaseModel):
    id: str
    audit_id: str
    type: str  # PRICE_VARIANCE, LATE_DISCLOSURE, UNDISCLOSED_AT_STAGE, SMALL_CART_RULE, TEMPORAL_DRIFT
    run_a_id: str
    run_b_id: Optional[str]
    matching_key: str
    detail: Dict[str, Any]
    dedup_key: str


class ProviderCallLog(BaseModel):
    id: Optional[str] = None
    audit_id: str
    run_id: Optional[str] = None
    operation: str  # search, fetch, agent_submit, agent_poll, screenshot
    requested_at: str
    completed_at: Optional[str] = None
    provider_request_id: Optional[str] = None
    response_status: Optional[int] = None
    error_class: Optional[str] = None
    result_usable: bool = True
