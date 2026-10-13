"""Agent Goal Prompt Templates with CCPA and Privacy Guardrails.

Hard constraints:
- STOP before payment.
- Never log in or enter personal data; never submit OTPs.
- If a login or OTP wall blocks the bill, return blocked_by_login; never guess.
- For every observation, return the step name and the verbatim visible text.
- Never assert legal conclusions.
"""

from typing import Dict, Any, Optional

GOAL_SYSTEM_GUARDRAILS = """
MANDATORY SAFETY & AUDIT GUARDRAILS:
1. STOP IMMEDIATELY BEFORE ANY FINAL PAYMENT OR ORDER CONFIRMATION STEP.
2. DO NOT enter personal credentials, passwords, real credit cards, or submit OTPs.
3. If an inescapable login or OTP wall blocks viewing the checkout summary or order bill, immediately set status to "blocked_by_login" and stop.
4. If a bot detection challenge (CAPTCHA, Cloudflare block) prevents navigation, set status to "blocked_by_bot" and stop.
5. Record verbatim visible text for all charges, disclosures, and urgency claims.
6. Extract all monetary amounts in integer minor units (e.g., INR 5.00 -> 500 paise, INR 799.00 -> 79900 paise).
7. Do not guess or assume values. If a field or disclosure cannot be determined, mark it as "unknown".
"""


def build_checkout_goal(
    start_url: str,
    requested_pincode: Optional[str] = None,
    cart_recipe: Optional[Dict[str, Any]] = None,
    is_returning: bool = False,
) -> str:
    """Build the natural-language goal for TinyFish agent execution."""
    pincode_instruction = ""
    if requested_pincode:
        pincode_instruction = (
            f"If there is a delivery pincode or location selector widget on the site, "
            f"set the delivery pincode to '{requested_pincode}'. "
            f"Record the actually observed pincode in the observed output."
        )

    cart_instruction = ""
    if cart_recipe:
        recipe_items = cart_recipe.get("items", [])
        items_desc = ", ".join(
            [f"{it.get('quantity', 1)}x {it.get('product_name', 'item')} (variant: {it.get('variant', 'default')})" for it in recipe_items]
        )
        cart_instruction = (
            f"Cart Construction Recipe: Add the following items to the cart: {items_desc}. "
            f"Target subtotal: {cart_recipe.get('target_subtotal_minor', 'standard')} minor units. "
            f"Ensure product page, cart page, and checkout summary are visited in sequence."
        )
    else:
        cart_instruction = "Navigate to the product page, add the product to the shopping cart, and proceed to the checkout / order summary stage."

    returning_instruction = ""
    if is_returning:
        returning_instruction = "This session uses a returning visitor profile. Observe any existing cart contents, saved preferences, or returning discounts."

    goal = f"""
Navigate to {start_url}.
Audit the checkout flow for price transparency, hidden charges, pre-selected options, and urgency indicators.

Execution Steps:
1. Product Stage:
   - Inspect the product details, listed price, and any visible disclosures regarding delivery, handling, or extra fees.
   - Look for any urgency indicators (countdowns, scarcity banners, limited-time claims) and record their verbatim text and timers.
   - Controlled Countdown Procedure: If a countdown timer is visible, observe the timer and timestamp at t0; wait 30 seconds while remaining on the same page without navigating or refreshing; observe the timer and timestamp at t1. Record both observations, the claimed deadline, and the measured elapsed seconds.
   {pincode_instruction}

2. Cart Stage:
   {cart_instruction}
   - Inspect the cart itemization.
   - Check if any add-ons, gift wrap, insurance, or donation options are checked or selected by default.
   - Observe visible fee disclosures or delivery threshold notices.

3. Checkout Summary Stage:
   - Proceed to the checkout summary or order review screen (STOP BEFORE CLICKING 'PAY NOW' OR PLACING ORDER).
   - Extract every itemized charge component: subtotal, handling fee, delivery fee, platform fee, surge fee, packaging fee, taxes, discounts, and final payable.
   - Reconcile the math: Subtotal + Charges + Taxes - Discounts = Final Payable.

{returning_instruction}

{GOAL_SYSTEM_GUARDRAILS}
"""
    return goal.strip()
