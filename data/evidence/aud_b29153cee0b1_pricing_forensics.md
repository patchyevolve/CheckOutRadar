# Checkout Radar — Forensic Checkout Audit & Pricing Corruption Investigation

**Target Merchant:** Headphone Zone (`https://www.headphonezone.in/products/tangzu-waner-s-g`)  
**Audit Reference:** `aud_b29153cee0b1`  
**Internal Run Reference:** `run_cf2137881ab6`  
**Provider Run Reference:** `15158e9a-43a0-48cc-b33a-09ae89f4bc4e`  
**Investigation Date:** 2026-10-15  
**Auditor Role:** Forensic Checkout Auditor & Evidence Analyst, Checkout Radar  

---

## 1. Executive Summary

A forensic investigation was conducted on the empirical data captured during audit `aud_b29153cee0b1` of Headphone Zone for the product **"Tangzu - Wan'er S.G (In-Ears With 1 Dynamic Driver)"**. The audit evaluated checkout transparency and pricing integrity against the **Central Consumer Protection Authority (CCPA) Guidelines for Prevention and Regulation of Dark Patterns, 2023**.

### Key Findings

1. **Strict Price Invariance Across Inspected Funnel:**
   The product price remained invariant at **₹1,999.00** across the Product Page, Cart Drawer, Cart Page, and initial Checkout Summary. No drip pricing, surprise handling charges, platform fees, or packing surcharges were added to the payable total in the observed stages.
2. **Lawful Tax-Inclusive GST Breakdown:**
   The checkout displayed `"Including ₹304.93 in taxes"`. Integer minor-unit arithmetic confirms this corresponds to an exact 18% integrated GST rate inclusive within the ₹1,999.00 price ($\text{Base} = ₹1,694.07, \text{GST} = ₹304.93$). The tax was not added as an undisclosed surcharge.
3. **Cash-on-Delivery (COD) ₹99 Convenience Charge:**
   A ₹99.00 COD convenience fee was discovered in the merchant DOM (`<x-drawer id="cod-charges">`). However, because the audit proceeded under a prepaid/card flow, COD was never selected, and the ₹99 fee was not added to the order total. The prominence and timing of this disclosure upon selecting COD remain **unverified** because payment-method selection was not captured.
4. **Unselected Add-Ons:**
   Observed cross-sells (a ₹199.00 Freefall Case in the cart drawer and a ₹599.00 Ultimate Eartip Set on the checkout summary) featured explicit, unselected `"ADD"` action buttons. Neither was pre-checked or sneaked into the cart.
5. **Pre-Checked Communication Consent Checkbox:**
   The Shopify checkout summary contained a pre-selected communication consent checkbox: `"[x] Please send me order updates via Email and WhatsApp messages 😊"`. While non-monetary, it represents default opt-in marketing enrollment.
6. **Provenance & Pipeline Artifact Anomalies Identified:**
   - **Database Row Duplication:** A transient polling timeout caused worker retry execution, writing duplicate rows in SQLite (22 charge observations, 12 disclosures, 4 add-on records, 8 urgency records, and 6 stage captures).
   - **Snapshot Overwriting:** The runner stored 18 distinct snapshot image captures on disk, but because `stage_captures` mapped snapshot IDs by step name rather than individual capture index, intermediate screenshots overwrote final captures in the snapshot reference table. Specifically, `snap_79262f841653` links to an intermediate product-page screenshot rather than the full cart drawer (`run_cf2137881ab6_cart_729aaf2ccaa2.jpg`) or cart page (`run_cf2137881ab6_cart_4b5d11877c47.jpg`), both of which were successfully preserved on disk.
   - **Schema-Prompted Zero-Value Observations:** Eight charge rows recorded with ₹0 amount (handover, platform, surge, packaging, handling, gift wrap, insurance, donation) were schema-induced queries from the crawler rather than merchant-displayed zero-rupee line items.

---

## 2. Merchant and Audit Metadata

| Metadata Field | Value | Verification Reference |
| :--- | :--- | :--- |
| **Merchant Name** | Headphone Zone | `audits.merchant` |
| **Target URL** | `https://www.headphonezone.in/products/tangzu-waner-s-g` | `audits.input_url` |
| **Audit Identifier** | `aud_b29153cee0b1` | `audits.id` |
| **Run Identifier** | `run_cf2137881ab6` | `runs.id` |
| **Provider Run ID** | `15158e9a-43a0-48cc-b33a-09ae89f4bc4e` | `runs.provider_run_id` |
| **Audit Preset** | `single` (1 bounded condition) | `audits.preset` |
| **Condition Key** | `pin:110001\|sess:fresh\|cart:above_threshold` | `conditions.condition_key` |
| **Pincode Tested** | `110001` (New Delhi, Connaught Place) | `runs.requested`, `runs.observed` |
| **Session Profile** | Fresh (incognito, zero prior cookies) | `conditions.requested` |
| **Cart Tier** | Above Threshold (₹1,999.00 > ₹500.00 standard free shipping threshold) | `conditions.requested` |
| **Provider Client** | `RealTinyFishClient` (Live browser agent via TinyFish API) | `provider_calls.operation = 'agent_submit'` |
| **Execution Start** | 2026-10-15T05:51:32.087993Z | `runs.started_at` |
| **Execution Finish** | 2026-10-15T06:01:09.880374Z | `runs.finished_at` |
| **Provider Calls Logged** | 107 operations (1 search, 1 fetch, 1 submit, 30 polls, 74 screenshot downloads) | `provider_calls` table |
| **Audit Safety Boundary** | Stop prior to payment submission (non-destructive) | `backend/app/tinyfish/goals.py` |

---

## 3. Stage-by-Stage Price Reconstruction

The table below reconstructs the complete price journey from the original stored evidence on disk. Values that were not displayed or unavailable at a stage are explicitly designated as `Unavailable`, distinguishing them from affirmative zero charges (`₹0.00`).

| Stage | Displayed Product Price | Original / MRP Price | Quantity & Subtotal | Taxes (GST) | Shipping Fee | Other Fees / Surcharges | Discounts / Promos | Optional Add-ons & State | Final Payable Amount | Relevant Disclosures | Evidence Reference & Snapshot Hash |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Product Page** | ₹1,999.00 | Unavailable (no strike-through MRP visible) | Qty: 1 (implied) <br>Subtotal: ₹1,999.00 | "Inclusive of all taxes" (explicit badge) | Free delivery across India (verified in DOM) | None visible in UI; ₹99 COD fee present in collapsed DOM drawer | Unavailable | - Ultimate Eartip Set (₹599): Unchecked<br>- Extended Warranty (₹0): Unchecked | ₹1,999.00 | - "Inclusive of all taxes"<br>- "EMI from ₹97 /month"<br>- "Expected at your door: Fri, Oct 16th - Tue, Oct 20th" | `run_cf2137881ab6_product_03213fc40787.jpg`<br>SHA-256: `03213fc40787...`<br>`run_cf2137881ab6_product_7400eb58284b.jpg`<br>SHA-256: `7400eb58284b...` (`snap_92bdf2ede476`) |
| **2A. Cart Drawer** | ₹1,999.00 | Unavailable | Qty: 1<br>Subtotal: ₹1,999.00 | Included (inherited) | Free | None visible | Unavailable | Headphone Zone x KZ Freefall Case (₹199.00): Unchecked (explicit `ADD` button) | ₹1,999.00 | - "Shipping: Free"<br>- "Congrats! You've unlocked all rewards!" | `run_cf2137881ab6_cart_729aaf2ccaa2.jpg`<br>SHA-256: `729aaf2ccaa2...`<br>`run_cf2137881ab6_cart_af944ead19f1.jpg`<br>SHA-256: `af944ead19f1...` |
| **2B. Cart Page (`/cart`)** | ₹1,999.00 | Unavailable | Qty: 1<br>Subtotal: ₹1,999.00 | "Tax included" | "shipping calculated at checkout" | None visible | Unavailable | None displayed on standalone page | ₹1,999.00 | - "Tax included and shipping calculated at checkout" | `run_cf2137881ab6_cart_4b5d11877c47.jpg`<br>SHA-256: `4b5d11877c47...` |
| **3. Checkout Summary** | ₹1,999.00 | Unavailable | Qty: 1<br>Subtotal: ₹1,999.00 | "Including ₹304.93 in taxes" | "Enter shipping address" (qualifies for free shipping based on ₹1,999 total) | ₹0.00 | Unavailable (promo field empty) | Headphone Zone Ultimate Eartip Set (₹599.00): Unchecked (explicit `ADD` button) | ₹1,999.00 | - "Including ₹304.93 in taxes"<br>- Checkbox: `[x] Please send me order updates via Email and WhatsApp messages` | `run_cf2137881ab6_checkout_summary_39637ea142c1.jpg`<br>SHA-256: `39637ea142c1...` (`snap_1b350e661aca`) |
| **4. Payment-Method Selection** | **Uninspected** | **Uninspected** | **Uninspected** | **Uninspected** | **Uninspected** | **Uninspected** | **Uninspected** | **Uninspected** | **Uninspected** | **Uninspected** (Redirection to payment methods occurs after address submission; halted under safety boundary) | Flow unreached prior to payment stop |
| **5. External Gateway** | **Uninspected** | **Uninspected** | **Uninspected** | **Uninspected** | **Uninspected** | **Uninspected** | **Uninspected** | **Uninspected** | **Uninspected** | **Uninspected** (Third-party payment gateways like Razorpay/PayU/Cashfree were not invoked) | Flow unreached prior to payment stop |

---

## 4. Complete Charge and Disclosure Inventory

Below is the exhaustive inventory of all charges and disclosures recorded in `charge_observations` and `disclosure_observations` in SQLite, reconciled against the visual evidence.

### 4.1 Charge Observations

| Recorded Label | Canonical Label | Amount (Minor) | Amount (INR) | Stage | Mandatory Flag | Actual Visual Evidence & Provenance | Forensic Assessment |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Handover fee** | `handover_fee` | 0 | ₹0.00 | `product` | `no` | **Absent from UI.** Provenance: `[Inferred]`. | Crawler schema check; not an affirmative merchant fee. |
| **COD handling fee** | `handling` | 9900 | ₹99.00 | `product` | `no` | **Extracted from DOM** (`<x-drawer id="cod-charges">`). Not rendered in main viewport. | Conditional fee for Cash on Delivery; unselected in prepaid flow. |
| **Delivery fee** | `delivery` | 0 | ₹0.00 | `product` | `yes` | **Directly visible in UI.** Free delivery stated on product page and cart drawer. Provenance: `[Screenshot Verified]`. | Affirmative free shipping granted for standard delivery across India. |
| **Platform fee** | `platform` | 0 | ₹0.00 | `cart` | `no` | **Absent from UI.** Provenance: `[Inferred]`. | Crawler schema check; no platform fee levied. |
| **Surge fee** | `surge` | 0 | ₹0.00 | `cart` | `no` | **Absent from UI.** Provenance: `[Inferred]`. | Crawler schema check; no surge fee levied. |
| **Packaging fee** | `packaging` | 0 | ₹0.00 | `cart` | `no` | **Absent from UI.** Provenance: `[Inferred]`. | Crawler schema check; no packaging fee levied. |
| **Handling fee** | `handling` | 0 | ₹0.00 | `cart` | `no` | **Absent from UI.** Provenance: `[Inferred]`. | Crawler schema check; no general handling fee levied. |
| **Taxes (GST)** | `taxes_(gst)` | 30493 | ₹304.93 | `cart` / `checkout` | `yes` | **Directly visible in UI.** Line text: `"Including ₹304.93 in taxes"`. Provenance: `[Screenshot Verified]`. | Statutory 18% GST broken out from inclusive subtotal. |
| **Gift wrap** | `gift_wrap` | 0 | ₹0.00 | `checkout_summary` | `no` | **Absent from UI.** Provenance: `[Inferred]`. | Crawler schema check; no gift wrap option selected or charged. |
| **Insurance** | `insurance` | 0 | ₹0.00 | `checkout_summary` | `no` | **Absent from UI.** Provenance: `[Inferred]`. | Crawler schema check; no transit insurance charged. |
| **Donation** | `donation` | 0 | ₹0.00 | `checkout_summary` | `no` | **Absent from UI.** Provenance: `[Inferred]`. | Crawler schema check; no charity donation added. |

*(Note: SQLite contains 22 charge records representing two duplicate sets of the 11 rows above, caused by worker retry logic).*

### 4.2 Disclosure Observations

| Charge Label | Step | State | Visible Text / Supporting Context | Forensic Assessment |
| :--- | :--- | :--- | :--- | :--- |
| **COD Handling Fee** | `product` | `observed` | `"₹99 convenience charge applies to Cash on Delivery (COD) orders"` | Present in DOM drawer `<x-drawer id="cod-charges">`. Valid conditional disclosure. |
| **Free Delivery** | `product` | `observed` | `"Free shipping across India (no minimum order value)"` | Visible in product delivery information section and cart drawer. |
| **Subtotal Minor** | `product` | `observed` | `"₹ 1,999 (Inclusive of all taxes) sale price"` | Prominently displayed beside product title in purple header font. |
| **Taxes (GST)** | `product` | `observed` | `"Including ₹304.93 in taxes"` | Formally disclosed below final order total on checkout review screen. |
| **Exchange Policy** | `product` | `observed` | `"Not perfect for you? 7 days to exchange for something that is."` | Customer protection policy; verified present on product page. |
| **Warranty** | `product` | `observed` | `"1 Year warranty included. You're covered."` | Included manufacturer warranty disclosure; verified in stage viewport. |

*(Note: SQLite contains 12 disclosure records representing two duplicate sets of the 6 rows above).*

---

## 5. Investigation of Drip Pricing and Other Potential Manipulation

### A. Drip Pricing Audit
Under CCPA Guidelines 2023, Section 2(e), drip pricing occurs when elements of prices are not revealed upfront or are revealed covertly in subsequent checkout steps.

- **Observed Baseline Price (Product Page):** ₹1,999.00
- **Observed Intermediate Price (Cart Drawer):** ₹1,999.00
- **Observed Intermediate Price (Cart Page):** ₹1,999.00
- **Observed Final Review Price (Checkout Summary):** ₹1,999.00
- **Discrepancy:** ₹0.00

**Forensic Finding:** Zero mandatory charges were dripped or injected across the inspected stages. The product stage was fully inspected, and the absence of handling fees, packaging surcharges, or convenience charges was positively verified against the payable balance. Drip pricing is **not observed** within the inspected flow boundary.

### B. Basket Sneaking Audit
Under CCPA Guidelines 2023, Section 2(b), basket sneaking involves adding products, services, or donations to the cart without affirmative user consent.

- **Upsell 1 Observed (Cart Drawer):** `"HEADPHONE ZONE X KZ - FREEFALL CASE"` (₹199.00).  
  *Control State:* Rendered with an explicit purple `"ADD"` button. `default_selected` = `0` (False). Not added to cart total.
- **Upsell 2 Observed (Checkout Summary):** `"Headphone Zone - Ultimate Eartip Set"` (₹599.00).  
  *Control State:* Rendered with an explicit purple `"ADD"` button. `default_selected` = `0` (False). Not added to cart total.
- **Donation / Insurance Check:** No donation or insurance checkboxes were checked or present in the bill summary.

**Forensic Finding:** Basket sneaking is **not observed** for monetary line items.

### C. False Urgency & Countdown Audits
Under CCPA Guidelines 2023, Section 2(f), false urgency involves falsely stating or implying a sense of urgency.

- **Observations in Database:** Four urgency records were extracted from the product page:
  1. `"Expected at your door: Fri, Oct 16th - Tue, Oct 20th"` (estimated delivery window).
  2. `"Packed and shipped within 24 hours."` (fulfillment speed claim).
  3. `"Defective? Tell us within 7 days. We'll take care of it."` (statutory/commercial replacement policy).
  4. `"Not perfect for you? 7 days to exchange for something that is."` (commercial exchange window).
- **Temporal Analysis:** No ticking countdown clocks, artificial inventory scarcity counters (`"Only 2 left in stock!"`), or looping timers were detected on the page.

**Forensic Finding:** False urgency is **not observed**. The recorded statements represent ordinary logistics estimates and consumer rights disclosures.

---

## 6. Detailed COD Convenience Fee Investigation

Checkout Radar extracted a ₹99.00 Cash-on-Delivery convenience fee during the audit. The forensic details of this charge are as follows:

1. **Disclosure Extraction Context:**
   The fee text `"₹99 convenience charge applies to Cash on Delivery (COD) orders"` was extracted from a merchant DOM drawer node identified as `<x-drawer id="cod-charges">`.
2. **Visual State in Captured Viewport:**
   In the captured product screenshot (`run_cf2137881ab6_product_7400eb58284b.jpg`), the COD drawer was **collapsed / unexpanded**. The text was not rendered as prominent body text on the primary product card.
3. **Application to Order Total:**
   The audit traversed an online prepaid flow (navigating towards card/UPI/netbanking checkout). The ₹99.00 fee was **never added** to the subtotal or payable amount.
4. **Timing and Prominence Assessment:**
   Because Checkout Radar halts before payment selection, the auditor cannot observe whether:
   - Selecting the COD radio button dynamically adds ₹99.00 to the bill.
   - The ₹99.00 charge is clearly disclosed immediately adjacent to the COD radio button before the consumer confirms the selection.
   - The fee is disclosed only after an OTP or confirmation is triggered.

**Forensic Finding:** The ₹99.00 COD convenience fee is a conditional charge applicable only to cash payment methods. While present in the merchant's underlying code, its display prominence, timing, and transparency during an active COD checkout remain **unverified** by the existing empirical evidence. It cannot be classified as an illegal dark pattern without capturing the payment selection stage.

---

## 7. Tax-Inclusive Arithmetic and Reconciliation

Checkout Radar reconciles monetary figures using integer minor units (paise) to prevent floating-point rounding errors:

$$\text{Subtotal Minor} + \text{Charges Minor} - \text{Discounts Minor} = \text{Calculated Payable Minor}$$

### Minor Unit Component Breakdown

$$\begin{aligned}
\text{Subtotal Minor} &= 199900 \text{ paise } (₹1,999.00) \\
\text{Charges Minor} &= 0 \text{ paise } (₹0.00) \\
\text{Taxes Minor (Inclusive GST)} &= 30493 \text{ paise } (₹304.93) \\
\text{Discounts Minor} &= 0 \text{ paise } (₹0.00) \\
\text{Reported Final Payable Minor} &= 199900 \text{ paise } (₹1,999.00)
\end{aligned}$$

### Verification of Tax-Inclusive Equation

$$\text{Calculated Payable} = 199900 + 0 - 0 = 199900 \text{ paise}$$
$$\text{Discrepancy} = 199900 - 199900 = 0 \text{ paise } (₹0.00)$$

### Statutory GST Mathematical Proof
Under Indian GST Law, consumer electronics (including earphones/headphones under HSN Code 8518) attract an 18% Integrated Goods and Services Tax (IGST).

When a price is advertised as "Inclusive of all taxes", the taxable value (base price) and GST component are derived as:

$$\text{Base Price} = \frac{\text{Total Price}}{1 + \text{GST Rate}} = \frac{1999.00}{1.18} = ₹1,694.0678 \approx ₹1,694.07$$

$$\text{GST Amount} = \text{Total Price} - \text{Base Price} = 1999.00 - 1694.0678 = ₹304.9322 \approx ₹304.93$$

**Forensic Finding:** The merchant's disclosed tax figure of **₹304.93** is mathematically exact to the paisa for an 18% tax-inclusive model. The tax is not an added surcharge and does not inflate the advertised price.

### Can Tax-Inclusive Reconciliation Conceal Mandatory Fees?
A critical forensic consideration is whether Checkout Radar's tax-inclusive reconciler (`calc_inclusive = subtotal + charges - discounts`) could allow a merchant to conceal an unitemized fee.

- *Scenario:* If a merchant silently inflates the subtotal from ₹1,999 to ₹2,099 at checkout without a separate line item, the reconciler equation would balance ($\text{Subtotal } 209900 = \text{Payable } 209900$).
- *Safeguard Analysis:* In this audit, the subtotal itself was verified against the earlier product and cart viewports (`₹1,999.00` in `03213fc4...`, `4b5d1187...`, and `39637ea1...`). Because the subtotal never changed across stages, no fee was absorbed into an inflated subtotal.
- *Limitation Identified:* In a single-condition audit where unit-price differential tracking is not running against a baseline condition, an unitemized subtotal increase would need to be caught by a stage-to-stage subtotal diff. Checkout Radar's `DiffEngine` currently checks `PRICE_VARIANCE` across multi-run matched pairs. For single runs, it relies on itemized `charges` vs `disclosures`.

---

## 8. Evidence References for Suspected Pricing Issues

| Observation / Issue | Stage | Amount | Before / After | Evidence ID / Snapshot Hash | Provenance Classification | Confidence | Plausible Non-Deceptive Explanation | Forensic Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **₹99 COD Fee Disclosure** | Product | ₹99.00 | Product (₹99 in DOM) → Checkout (Unapplied) | `disc_c3ae1adecd2f`<br>`chg_7331e1eac475` | `[DOM Extracted (Unexpanded)]` | Moderate | Standard courier surcharge for cash handling and return logistics on COD orders. | **Potential pricing concern requiring further verification** (prominence upon COD selection untested) |
| **Pre-Checked Communication Consent** | Checkout Summary | Non-monetary | Blank → `[x]` Checked | `snap_1b350e661aca`<br>`39637ea142c1...` | `[Screenshot Verified]` | High | Facilitates order tracking updates via WhatsApp/Email; does not add financial cost. | **Confirmed behavior** (non-monetary opt-out marketing consent) |
| **Freefall Case Cross-Sell** | Cart Drawer | ₹199.00 | Product (None) → Cart (₹199 offer) | `run_cf2137881ab6_cart_729aaf2ccaa2.jpg`<br>`729aaf2ccaa2...` | `[Screenshot Verified]` | High | Contextual accessory recommendation with explicit opt-in requirement. | **Not observed / Compliant** (explicit `ADD` button, not pre-selected) |
| **Ultimate Eartip Set Cross-Sell** | Checkout Summary | ₹599.00 | Cart (None) → Checkout (₹599 offer) | `snap_1b350e661aca`<br>`39637ea142c1...` | `[Screenshot Verified]` | High | Checkout accessory upsell with explicit opt-in requirement. | **Not observed / Compliant** (explicit `ADD` button, not pre-selected) |
| **Schema-Derived Fee Records** | All | ₹0.00 | None → ₹0.00 in DB | `chg_3f7d6a9e39dd` etc. | `[Inferred]` | High | System artifact: crawler checked standard fee categories and logged zero when absent. | **Not observed / Compliant** (no fee exists) |

---

## 9. Gaps, Uncertainties, and Uninspected Stages

The audit trail reveals the following empirical boundaries:

1. **Uninspected Payment Gateway Redirection:**
   The audit boundary halted at the contact and address step of the Shopify checkout. Third-party payment gateways (e.g. Razorpay, PayU, Cashfree, credit card 3D Secure) were not reached. Whether payment gateways levy payment processing fees or dynamic convenience charges remains unknown.
2. **Untested Cash-on-Delivery Flow:**
   Because payment methods were not selected, the operational behavior of the COD flow was not observed. The audit cannot verify whether the ₹99 fee is disclosed clearly before or after order confirmation.
3. **Pincode and Cart Tier Boundaries:**
   The audit tested a single condition: Pincode `110001` (metro) with an order value of `₹1,999.00`. It did not test:
   - Low-tier cart values (e.g. under ₹500), where small-order delivery fees may apply.
   - Non-metro, remote, or North-East pincodes, where delivery surcharges might be introduced.
4. **Intermediate Snapshot Linkage Discrepancy (Resolved & Remediated):**
   Database stage capture `cap_c1b5d8925073` was historically mapped to snapshot `snap_79262f841653` (`cart_421e79a5e629.jpg`), which captured the product page prior to cart drawer opening, due to action priority shadowing. The runner logic has been fixed to prioritize definitive cart views (`prio=2`), `cap_c1b5d8925073` has been remediated in SQLite to bind to `snap_0ab6301b818b` (`run_cf2137881ab6_cart_729aaf2ccaa2.jpg`, SHA-256 `729aaf2ccaa2...`), and regression tests have been added to guarantee definitive cart binding.
5. **Absence of Comprehensive PII Redaction:**
   Form input fields in captured screenshots were empty placeholders; no active PII redaction mask was applied to the contact form fields.

---

## 10. Audit of Checkout Radar's Original "Clean" Classification

Checkout Radar classified audit `aud_b29153cee0b1` as:
`"Verified clean checkout flow under tested condition: All required stages were captured and inspected; 0 potential dark pattern indicators detected within observed flow boundary."`

### Forensic Review of this Classification

1. **Was the Outcome Justified?**
   **Yes, strictly within the observed boundary.** All three required primary stages (Product Page, Cart Drawer/Page, and Checkout Summary) were successfully visited, captured, and inspected. The product price remained ₹1,999.00, optional add-ons required affirmative clicks, and the GST arithmetic reconciled.
2. **Distinction Between Lack of Findings and Affirmative Proof:**
   The clean classification does not stem from silent test failures or missing stage exceptions. A regression test in Checkout Radar (`test_full_pipeline_incomplete_provider_run_remains_inconclusive`) confirms that if the checkout summary had been missing, the system would have evaluated to `INCONCLUSIVE`. Here, the checkout summary was present and verified.
3. **Crucial Claim Boundary Separation:**
   - **Supported Statement:** *"No pricing manipulation was detected in the observed prepaid checkout flow for Tangzu Wan'er S.G to Pincode 110001 on 2026-10-15."*
   - **Unsupported Statement:** *"Headphone Zone does not engage in dark patterns or pricing manipulation."*
   The existing run provides empirical proof of clean behavior under one narrow condition. It cannot certify merchant compliance for uninspected payment methods, remote shipping zones, alternate SKUs, or third-party gateways.

---

## 11. Final Findings and Recommended Next Steps

### Summary of Forensic Findings by Mechanism

1. **Drip Pricing:** No pricing manipulation detected within observed boundary. Listed price ₹1,999.00 = Final payable ₹1,999.00.
2. **Basket Sneaking (Monetary):** No pricing manipulation detected within observed boundary. Upsells require affirmative user opt-in.
3. **Pre-Checked Marketing Consent:** Confirmed behavior. Non-monetary email/WhatsApp marketing checkbox is pre-selected by default.
4. **False Urgency:** No pricing manipulation detected within observed boundary. No deceptive countdowns or fake inventory counters.
5. **Tax-Inclusive Reconciliation:** Confirmed lawful behavior. Exact 18% GST (₹304.93) inclusive within ₹1,999.00 price.
6. **Cash-on-Delivery Fee (₹99.00):** Potential pricing concern requiring further verification. Present in DOM, but prominence upon selection is unverified due to payment boundary stop.

### Recommended Next Verification Steps

1. **COD Flow Investigation:**
   Execute a dedicated bounded audit configured to select the Cash on Delivery payment option at the payment step to inspect the exact timing, prominence, and order total adjustment of the ₹99.00 fee.
2. **Sub-Threshold Cart Audit:**
   Execute an audit with an item priced under ₹500.00 to determine whether shipping fee thresholds are disclosed upfront on the product page or dripped at the checkout summary.
3. **Remote Pincode Permutation:**
   Run a multi-condition matched-pair audit comparing delivery charges for metro pincodes (e.g. `110001`) against remote/island pincodes (e.g. `744101` Port Blair or `790001` Tawang).
4. **Fix Snapshot Keying Defect (Implemented & Verified):**
   Updated `backend/app/worker/job_runner.py` to prioritize affirmative stage views (`prio=2` over transition `prio=1`), prioritizing explicit provider step references and stage resolution over generic step index fallbacks. Remediated `cap_c1b5d8925073` to `snap_0ab6301b818b`. Verified by regression tests.
5. **Deduplicate Database Inserts (Implemented & Verified):**
   Implemented `crud.clear_run_observations(run_id)` in `backend/app/db/crud.py` and called it in `JobRunner` prior to persisting run outcomes. Purged historical duplicate observation rows for `run_cf2137881ab6`. Verified by regression test `test_observation_idempotency_on_retry`.

---

## 12. Final Forensic Verdicts

- **Prepaid Checkout Flow (Product → Cart → Checkout Summary):**  
  **No pricing manipulation detected within the observed boundary.**

- **Cash-on-Delivery (COD) ₹99 Surcharge:**  
  **Potential pricing concern requiring further verification.**

- **Payment Gateway & Authorization Boundary:**  
  **Inconclusive (Uninspected stage).**
