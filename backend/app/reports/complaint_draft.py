"""Draft Consumer Complaint Generator.

Explicit constraint:
- DRAFT ONLY. Never automatically submitted anywhere.
- References the Central Consumer Protection Authority (CCPA) Dark Patterns Guidelines 2023.
- Itemizes timestamped evidence, observed fees, and diff results.
"""

from typing import Dict, Any, List


def generate_complaint_draft(
    audit: Dict[str, Any],
    findings: List[Dict[str, Any]],
    diffs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    merchant = audit.get("merchant", "E-Commerce Platform")
    audit_id = audit.get("id", "AUD-UNKNOWN")
    date_str = audit.get("created_at", "")[:10]

    findings_text = ""
    for idx, f in enumerate(findings, 1):
        findings_text += f"""
{idx}. Category: {f['category'].upper().replace('_', ' ')} (Potential Indicator)
   - Observed Practice: {f['explanation']}
   - Confidence: {int(f['confidence'] * 100)}% | Severity: {f['severity'].upper()}
   - Technical Rule Rationale: {f.get('heuristic_note', 'Observed in checkout flow')}
   - Evidence Identifiers: {', '.join(f.get('evidence_ids', [])) or 'Captured sequence'}
"""

    draft_text = f"""[DRAFT GRIEVANCE / INFORMATIONAL FILING - NOT AUTOMATICALLY SUBMITTED]

TO:
The Central Consumer Protection Authority (CCPA) /
National Consumer Helpline (NCH), Department of Consumer Affairs,
Government of India.

SUBJECT: Notice of Potential Dark Pattern Practices Observed on {merchant} (Audit Ref: {audit_id})

Respected Authority,

I am writing to submit empirical, timestamped evidence regarding checkout transparency practices observed during an audit of the online checkout process on {merchant} ({audit.get('input_url')}) on {date_str}.

In accordance with the Guidelines for Prevention and Regulation of Dark Patterns, 2023, notified by the CCPA under Section 18 of the Consumer Protection Act, 2019, the following potential indicators were identified:

SUMMARY OF EMPIRICAL FINDINGS:
{findings_text or 'No dark pattern indicators observed during audit.'}

AUDIT METHODOLOGY & CONTROLS:
- Automated multi-condition audit conducted under controlled parameters (Location / Pincode, Session History, and Cart Thresholds).
- Evidence captured via sequential screenshots of Product Page, Cart Page, and Checkout Summary.
- Monetary figures reconciled in minor units.
- Matched-pair differential auditing was utilized to isolate independent variables and rule differences from baseline charges.

DECLARATION:
This document is a technical audit summary prepared for consumer awareness and regulatory review. The submitter notes that these findings reflect potential indicators recorded at the time of observation and requests appropriate review under applicable CCPA guidelines.

Audit Reference: {audit_id}
Generated on: {audit.get('created_at')}
"""

    return {
        "audit_id": audit_id,
        "merchant": merchant,
        "is_draft": True,
        "auto_submitted": False,
        "subject": f"Notice of Potential Dark Pattern Practices on {merchant}",
        "draft_text": draft_text.strip(),
    }
