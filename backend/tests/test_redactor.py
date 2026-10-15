"""Tests for screenshot redaction, empirical threat model audit, and integrity hashing."""

import io
import hashlib
from pathlib import Path
from PIL import Image, ImageDraw
import pytest

from app.worker.redactor import apply_redaction_masks, redact_and_store_screenshot


def create_synthetic_checkout_screenshot(width: int = 800, height: int = 1000) -> Image.Image:
    """Creates a synthetic checkout screenshot with sensitive text in multiple regions."""
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Upper region (y=150): Customer Identity
    draw.text((50, 150), "Name: Rajesh Kumar | Phone: +91 98765 43210", fill=(0, 0, 0))

    # Middle region (y=500): Payment Card Form
    draw.text((50, 500), "Card Number: 4532 0150 1234 5678", fill=(0, 0, 0))

    # Lower-middle region (y=750): CVV and Expiry
    draw.text((50, 750), "CVV: 888  Exp: 12/28", fill=(0, 0, 0))

    # Footer region (y=975): Session token / cookie consent bar
    draw.text((50, 975), "Session Token: sess_98723498234", fill=(0, 0, 0))

    return img


def test_bottom_masking_limitation_leaves_upper_and_middle_regions_unredacted():
    """
    Honest Redaction Audit:
    Empirically proves that fixed bottom-5% masking ONLY protects the bottom 5%
    of the viewport and leaves payment card inputs, CVVs, and customer identity
    in the upper 95% completely exposed.
    """
    img = create_synthetic_checkout_screenshot(800, 1000)

    # 1. Verify before redaction: all 4 regions contain dark text pixels
    upper_crop_before = img.crop((50, 145, 450, 165))
    middle_crop_before = img.crop((50, 495, 400, 515))
    cvv_crop_before = img.crop((50, 745, 250, 765))
    footer_crop_before = img.crop((50, 970, 400, 990))

    upper_dark_before = sum(cnt for cnt, rgb in upper_crop_before.getcolors(maxcolors=10000) if rgb[0] < 50)
    middle_dark_before = sum(cnt for cnt, rgb in middle_crop_before.getcolors(maxcolors=10000) if rgb[0] < 50)
    cvv_dark_before = sum(cnt for cnt, rgb in cvv_crop_before.getcolors(maxcolors=10000) if rgb[0] < 50)
    footer_dark_before = sum(cnt for cnt, rgb in footer_crop_before.getcolors(maxcolors=10000) if rgb[0] < 50)

    assert upper_dark_before > 0, "Upper region text must be present before masking"
    assert middle_dark_before > 0, "Middle card text must be present before masking"
    assert cvv_dark_before > 0, "CVV text must be present before masking"
    assert footer_dark_before > 0, "Footer text must be present before masking"

    # 2. Apply default bottom-5% redaction (sensitive_regions=None)
    redacted_img, applied_boxes = apply_redaction_masks(img, sensitive_regions=None, apply_footer_mask=True)

    # Assert exactly 1 mask was applied (the bottom 5%: y=950 to 1000)
    assert len(applied_boxes) == 1
    assert applied_boxes[0] == (0, 950, 800, 1000)

    # 3. Audit footer region: completely redacted with charcoal mask (30, 30, 30)
    footer_crop_after = redacted_img.crop((0, 950, 800, 1000))
    colors_footer = footer_crop_after.getcolors(maxcolors=256)
    assert colors_footer == [(800 * 50, (30, 30, 30))], "Footer area must be completely masked with (30, 30, 30)"

    # 4. CRITICAL AUDIT FINDING: Upper and Middle regions REMAIN COMPLETELY UNMASKED!
    upper_crop_after = redacted_img.crop((50, 145, 450, 165))
    middle_crop_after = redacted_img.crop((50, 495, 400, 515))
    cvv_crop_after = redacted_img.crop((50, 745, 250, 765))

    upper_dark_after = sum(cnt for cnt, rgb in upper_crop_after.getcolors(maxcolors=10000) if rgb[0] < 50)
    middle_dark_after = sum(cnt for cnt, rgb in middle_crop_after.getcolors(maxcolors=10000) if rgb[0] < 50)
    cvv_dark_after = sum(cnt for cnt, rgb in cvv_crop_after.getcolors(maxcolors=10000) if rgb[0] < 50)

    # The dark text pixels are completely unaltered by the bottom-5% mask
    assert upper_dark_after == upper_dark_before, "Customer identity was NOT redacted by bottom-5% mask"
    assert middle_dark_after == middle_dark_before, "Credit card number was NOT redacted by bottom-5% mask"
    assert cvv_dark_after == cvv_dark_before, "CVV was NOT redacted by bottom-5% mask"


def test_targeted_region_masking_redacts_specified_form_fields():
    """
    Verifies that supplying explicit coordinate bounding boxes successfully redacts
    the targeted payment and CVV form fields in the viewport body.
    """
    img = create_synthetic_checkout_screenshot(800, 1000)

    # Specify targeted bounding boxes for card number and CVV
    targeted_boxes = [
        (45, 490, 410, 520),  # Card number box
        (45, 740, 260, 770),  # CVV box
    ]

    redacted_img, applied_boxes = apply_redaction_masks(
        img,
        sensitive_regions=targeted_boxes,
        apply_footer_mask=True,
    )

    # 3 boxes applied: 2 targeted + 1 footer
    assert len(applied_boxes) == 3

    # Check card number box is completely masked
    card_crop = redacted_img.crop((45, 490, 410, 520))
    w_card = 410 - 45
    h_card = 520 - 490
    assert card_crop.getcolors(maxcolors=256) == [(w_card * h_card, (30, 30, 30))], "Targeted card number must be masked"

    # Check CVV box is completely masked
    cvv_crop = redacted_img.crop((45, 740, 260, 770))
    w_cvv = 260 - 45
    h_cvv = 770 - 740
    assert cvv_crop.getcolors(maxcolors=256) == [(w_cvv * h_cvv, (30, 30, 30))], "Targeted CVV must be masked"

    # Check un-targeted upper region remains unmasked with text intact
    upper_crop = redacted_img.crop((50, 145, 450, 165))
    upper_dark = sum(cnt for cnt, rgb in upper_crop.getcolors(maxcolors=10000) if rgb[0] < 50)
    assert upper_dark > 0, "Unspecified upper text remains unmasked"


def test_normalized_coordinates_scaling():
    """Verifies that normalized float bounding boxes [0.0, 1.0] scale properly to image pixels."""
    img = Image.new("RGB", (1000, 2000), color=(255, 255, 255))
    # Normalized box at [0.1, 0.2, 0.5, 0.3] -> pixels [100, 400, 500, 600]
    normalized_box = (0.1, 0.2, 0.5, 0.3)

    _, applied_boxes = apply_redaction_masks(
        img,
        sensitive_regions=[normalized_box],
        apply_footer_mask=False,
    )

    assert len(applied_boxes) == 1
    assert applied_boxes[0] == (100, 400, 500, 600)


def test_redact_and_store_screenshot_e2e_persistence(tmp_path, monkeypatch):
    """Verifies end-to-end screenshot saving, SHA-256 hashing, and file integrity."""
    test_ev = tmp_path / "evidence_test"
    monkeypatch.setenv("EVIDENCE_DIR", str(test_ev))

    img = create_synthetic_checkout_screenshot(400, 500)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    raw_bytes = buf.getvalue()

    snap_id, sha256_hash, target_path = redact_and_store_screenshot(
        raw_bytes=raw_bytes,
        run_id="run_test_audit",
        step_name="checkout_summary",
        record_in_db=False,
    )

    assert snap_id.startswith("snap_")
    assert Path(target_path).exists()

    # Verify SHA256 of the persisted file matches returned hash
    disk_bytes = Path(target_path).read_bytes()
    expected_sha = hashlib.sha256(disk_bytes).hexdigest()
    assert sha256_hash == expected_sha


def test_invalid_or_synthetic_bytes_handled_gracefully(tmp_path, monkeypatch):
    """Verifies that corrupt or non-image binary bytes fall back safely without crashing."""
    test_ev = tmp_path / "evidence_test"
    monkeypatch.setenv("EVIDENCE_DIR", str(test_ev))

    corrupt_bytes = b"not_a_valid_image_header_random_junk_123456"

    snap_id, sha256_hash, target_path = redact_and_store_screenshot(
        raw_bytes=corrupt_bytes,
        run_id="run_fallback_test",
        step_name="product",
        record_in_db=False,
    )

    assert snap_id.startswith("snap_")
    assert Path(target_path).exists()
    assert Path(target_path).stat().st_size > 0
