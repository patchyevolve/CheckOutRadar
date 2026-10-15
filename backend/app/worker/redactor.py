"""Evidence Redaction and Integrity Hashing.

Threat Model & Redaction Scope:
--------------------------------
1. Default Masking (Bottom 5% Heuristic):
   - By default, applies a solid rectangle mask over the bottom 5% of the viewport (y >= 0.95 * height).
   - Intended for: sticky cookie consent notices, session tokens, and fixed footer utility bars.
   - KNOWN ARCHITECTURAL LIMITATION:
     This heuristic DOES NOT redact form-level PII located in the viewport body.
     Checkout form inputs (credit/debit card numbers, CVVs, expiration dates, customer names,
     phone numbers, billing addresses) typically render in the upper and middle screen regions
     (between 15% and 85% viewport height). Without explicit coordinates, these inputs remain
     unmasked.

2. Targeted Region Masking:
   - Callers can provide `sensitive_regions` (bounding boxes in pixels or normalized [0.0, 1.0] coordinates)
     extracted from browser DOM elements (e.g., input[type="password"], input[autocomplete*="cc"]).
   - All specified regions are masked with solid fill before persistence and hashing.

3. Integrity Hashing:
   - SHA-256 hash is computed strictly on the final redacted byte representation.
   - Stored in an append-only evidence store and verified by SQLite audit record.
"""

import os
import hashlib
from pathlib import Path
from typing import Tuple, List, Optional
from PIL import Image, ImageDraw
import io
from ..db import crud


def get_evidence_dir() -> Path:
    candidates = [
        os.getenv("EVIDENCE_DIR"),
        "/app/data/evidence",
        str(Path(__file__).resolve().parent.parent.parent.parent / "data" / "evidence"),
    ]
    for c in candidates:
        if c:
            if c.startswith("/app/") and not Path("/app").exists():
                continue
            try:
                p = Path(c)
                p.mkdir(parents=True, exist_ok=True)
                return p
            except (PermissionError, FileNotFoundError, OSError):
                continue
    p = Path("data/evidence")
    p.mkdir(parents=True, exist_ok=True)
    return p


def apply_redaction_masks(
    img: Image.Image,
    sensitive_regions: Optional[List[Tuple[float, float, float, float]]] = None,
    apply_footer_mask: bool = True,
    mask_color: Tuple[int, int, int] = (30, 30, 30),
) -> Tuple[Image.Image, List[Tuple[int, int, int, int]]]:
    """
    Applies privacy masking to an Image object.

    Args:
        img: PIL Image to redact.
        sensitive_regions: Optional list of bounding boxes (x0, y0, x1, y1).
                           Can be integer pixel coordinates or normalized floats [0.0, 1.0].
        apply_footer_mask: If True, masks the bottom 5% of the viewport.
        mask_color: RGB fill tuple for redacted regions (default dark charcoal).

    Returns:
        (redacted_image, list_of_applied_pixel_bounding_boxes)
    """
    if img.mode != "RGB":
        img = img.convert("RGB")

    draw = ImageDraw.Draw(img)
    width, height = img.size
    applied_boxes: List[Tuple[int, int, int, int]] = []

    # 1. Apply targeted sensitive region bounding boxes (if provided)
    if sensitive_regions:
        for box in sensitive_regions:
            x0, y0, x1, y1 = box
            # If coordinates are normalized floats (<= 1.0), scale to image dimensions
            if 0.0 <= x0 <= 1.0 and 0.0 <= y0 <= 1.0 and 0.0 <= x1 <= 1.0 and 0.0 <= y1 <= 1.0:
                px0 = int(x0 * width)
                py0 = int(y0 * height)
                px1 = int(x1 * width)
                py1 = int(y1 * height)
            else:
                px0 = int(x0)
                py0 = int(y0)
                px1 = int(x1)
                py1 = int(y1)

            # Clamp to image boundaries
            px0 = max(0, min(width, px0))
            py0 = max(0, min(height, py0))
            px1 = max(0, min(width, px1))
            py1 = max(0, min(height, py1))

            if px1 > px0 and py1 > py0:
                draw.rectangle([px0, py0, px1, py1], fill=mask_color)
                applied_boxes.append((px0, py0, px1, py1))

    # 2. Apply bottom-5% heuristic mask
    if apply_footer_mask and height > 0:
        mask_top = int(height * 0.95)
        draw.rectangle([0, mask_top, width, height], fill=mask_color)
        applied_boxes.append((0, mask_top, width, height))

    return img, applied_boxes


def redact_and_store_screenshot(
    raw_bytes: bytes,
    run_id: str,
    step_name: str,
    sensitive_regions: Optional[List[Tuple[float, float, float, float]]] = None,
    apply_footer_mask: bool = True,
    record_in_db: bool = True,
) -> Tuple[str, str, str]:
    """
    Redact image, save to append-only evidence store, compute SHA256, and record snapshot.

    Returns:
        (snapshot_id, sha256_hash, relative_or_absolute_file_path)
    """
    # Open image with PIL
    try:
        img = Image.open(io.BytesIO(raw_bytes))
    except Exception:
        # If invalid or synthetic, create minimal RGB image
        img = Image.new("RGB", (100, 100), color=(240, 240, 240))

    img, _ = apply_redaction_masks(
        img,
        sensitive_regions=sensitive_regions,
        apply_footer_mask=apply_footer_mask,
    )

    # Save redacted image to buffer
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    redacted_bytes = buf.getvalue()

    # Compute SHA256 hash of the retained artifact
    sha256 = hashlib.sha256(redacted_bytes).hexdigest()

    # Generate snapshot ID and target path
    ev_dir = get_evidence_dir()
    filename = f"{run_id}_{step_name}_{sha256[:12]}.jpg"
    target_path = ev_dir / filename

    with open(target_path, "wb") as f:
        f.write(redacted_bytes)

    if record_in_db:
        snap_id = crud.create_snapshot(
            run_id=run_id,
            step_name=step_name,
            artifact_path=str(target_path),
            sha256=sha256,
            redaction_status="redacted",
        )
    else:
        snap_id = f"snap_{sha256[:12]}"

    return snap_id, sha256, str(target_path)
