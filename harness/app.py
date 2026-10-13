"""Demo Merchant Harness Container (5 Variants).

Variants:
1. Clean: All fees disclosed upfront. (Negative control -> No findings)
2. Late Disclosure: Handling fee appears only at checkout summary. (Adversarial -> Drip Pricing)
3. Addon & Resetting Countdown: Pre-selected add-on and resetting timer. (Adversarial -> Basket Sneaking & False Urgency)
4. Upfront Fee: Mandatory fee prominently disclosed on product page. (Negative control -> No findings)
5. Legitimate Threshold: Free delivery above ₹500, ₹40 below ₹500. (Negative control -> SMALL_CART_RULE, no findings)
"""

import time
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Checkout Radar Demo Merchant Harness")

# In-memory timer for variant 3 to demonstrate controlled countdown resets
TIMER_START = time.time()


@app.get("/", response_class=HTMLResponse)
def index():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Checkout Radar — Demo Merchant Harness</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 40px; }
            .card { background: #1e293b; border-radius: 8px; padding: 24px; max-width: 800px; margin: 0 auto; border: 1px solid #334155; }
            h1 { color: #38bdf8; margin-top: 0; }
            ul { list-style: none; padding: 0; }
            li { background: #0f172a; margin: 12px 0; padding: 16px; border-radius: 6px; border: 1px solid #334155; display: flex; justify-content: space-between; align-items: center; }
            a { color: #38bdf8; text-decoration: none; font-weight: bold; background: #1e293b; padding: 6px 14px; border-radius: 4px; border: 1px solid #38bdf8; }
            a:hover { background: #38bdf8; color: #0f172a; }
            .badge { font-size: 0.75em; padding: 2px 8px; border-radius: 4px; font-weight: bold; }
            .bg-green { background: #166534; color: #86efac; }
            .bg-red { background: #991b1b; color: #fca5a5; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🏪 Checkout Radar Demo Merchant Harness</h1>
            <p>Controlled test merchant providing 5 behavioral variants for differential checkout auditing:</p>
            <ul>
                <li>
                    <div>
                        <strong>1. Clean Merchant</strong> <span class="badge bg-green">Clean Baseline</span><br>
                        <small style="color: #94a3b8;">All fees disclosed upfront on product page. Expected: No findings.</small>
                    </div>
                    <a href="/variant/clean">Visit Store &rarr;</a>
                </li>
                <li>
                    <div>
                        <strong>2. Late Disclosure</strong> <span class="badge bg-red">Adversarial</span><br>
                        <small style="color: #94a3b8;">₹5 Handling fee appears only at final checkout summary. Expected: Drip pricing.</small>
                    </div>
                    <a href="/variant/late_disclosure">Visit Store &rarr;</a>
                </li>
                <li>
                    <div>
                        <strong>3. Addon & Resetting Countdown</strong> <span class="badge bg-red">Adversarial</span><br>
                        <small style="color: #94a3b8;">₹15 pre-selected insurance + timer resets every 30s. Expected: Basket sneaking & False urgency.</small>
                    </div>
                    <a href="/variant/addon_countdown">Visit Store &rarr;</a>
                </li>
                <li>
                    <div>
                        <strong>4. Upfront Convenience Fee</strong> <span class="badge bg-green">Negative Control</span><br>
                        <small style="color: #94a3b8;">₹20 fee disclosed upfront on product page. Expected: No findings.</small>
                    </div>
                    <a href="/variant/upfront_fee">Visit Store &rarr;</a>
                </li>
                <li>
                    <div>
                        <strong>5. Legitimate Cart Threshold</strong> <span class="badge bg-green">Negative Control</span><br>
                        <small style="color: #94a3b8;">Free delivery above ₹500; ₹40 below. Expected: SMALL_CART_RULE, no findings.</small>
                    </div>
                    <a href="/variant/legitimate_threshold">Visit Store &rarr;</a>
                </li>
            </ul>
        </div>
    </body>
    </html>
    """


@app.get("/variant/{variant}", response_class=HTMLResponse)
def product_page(variant: str, pincode: str = "110001", qty: int = 2):
    # Base item: ₹499.00
    price_minor = 49900
    subtotal_minor = price_minor * qty

    # Fee disclosures on product page:
    disclosures_html = ""
    urgency_html = ""

    if variant == "clean":
        disclosures_html = """
        <div style="background: #f0fdf4; border: 1px solid #86efac; padding: 12px; border-radius: 6px; margin: 16px 0; color: #166534;">
            <strong>✓ Transparent Pricing Disclosure:</strong> Standard Delivery: ₹40. No hidden handling charges.
        </div>
        """
    elif variant == "upfront_fee":
        disclosures_html = """
        <div style="background: #f0fdf4; border: 1px solid #86efac; padding: 12px; border-radius: 6px; margin: 16px 0; color: #166534;">
            <strong>✓ Disclosed Upfront:</strong> Convenience Fee of ₹20 applied to all orders at checkout.
        </div>
        """
    elif variant == "legitimate_threshold":
        disclosures_html = """
        <div style="background: #f8fafc; border: 1px solid #cbd5e1; padding: 12px; border-radius: 6px; margin: 16px 0; color: #334155;">
            <strong>ℹ️ Shipping Policy:</strong> FREE delivery on orders over ₹500! Standard ₹40 delivery fee for smaller orders.
        </div>
        """
    elif variant == "addon_countdown":
        # Resetting countdown: resets back to 09:59 periodically
        urgency_html = """
        <div style="background: #fef2f2; border: 1px solid #fca5a5; padding: 12px; border-radius: 6px; margin: 16px 0; color: #991b1b; font-weight: bold;">
            ⏳ FLASH SALE: Claim ends in <span id="timer">09:59</span> minutes! Hurry, limited stock!
        </div>
        <script>
            // Controlled resetting countdown timer
            let seconds = 599;
            setInterval(() => {
                seconds--;
                if (seconds <= 570) seconds = 599; // Deliberate reset for audit harness demonstration!
                let m = Math.floor(seconds / 60);
                let s = seconds % 60;
                document.getElementById('timer').innerText = (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
            }, 1000);
        </script>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Artisan Coffee Beans — Demo Store ({variant})</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f8fafc; color: #0f172a; margin: 0; padding: 32px; }}
            .container {{ max-width: 700px; margin: 0 auto; background: white; padding: 24px; border-radius: 8px; border: 1px solid #e2e8f0; }}
            .btn {{ background: #2563eb; color: white; border: none; padding: 12px 20px; font-size: 1em; font-weight: bold; border-radius: 6px; cursor: pointer; text-decoration: none; display: inline-block; }}
            .btn:hover {{ background: #1d4ed8; }}
        </style>
    </head>
    <body>
        <div class="container">
            <span style="font-size: 0.8em; text-transform: uppercase; background: #e2e8f0; padding: 4px 8px; border-radius: 4px; font-weight: bold;">Variant: {variant}</span>
            <h1 style="margin-top: 12px;">Artisan Whole Bean Coffee (500g)</h1>
            <p style="color: #64748b;">Single-origin medium roast Arabica coffee beans from Chikmagalur.</p>
            <div style="font-size: 1.6em; font-weight: bold; margin: 16px 0;">₹499.00 <span style="font-size: 0.6em; color: #64748b;">/ unit</span></div>

            <div style="margin: 16px 0; background: #f1f5f9; padding: 12px; border-radius: 6px;">
                <label><strong>Delivery Pincode:</strong> </label>
                <input type="text" id="pincode" value="{pincode}" style="padding: 6px; border: 1px solid #cbd5e1; border-radius: 4px;">
                <span style="color: #16a34a; font-weight: bold; margin-left: 8px;">✓ Available</span>
            </div>

            {urgency_html}
            {disclosures_html}

            <div style="margin: 24px 0;">
                <label><strong>Quantity:</strong> </label>
                <select id="qty" style="padding: 6px; border: 1px solid #cbd5e1; border-radius: 4px;">
                    <option value="1" {'selected' if qty == 1 else ''}>1 unit (₹499.00)</option>
                    <option value="2" {'selected' if qty == 2 else ''}>2 units (₹998.00)</option>
                </select>
            </div>

            <a class="btn" href="/variant/{variant}/cart?pincode={pincode}&qty={qty}">Add to Cart & Proceed &rarr;</a>
        </div>
    </body>
    </html>
    """


@app.get("/variant/{variant}/cart", response_class=HTMLResponse)
def cart_page(variant: str, pincode: str = "110001", qty: int = 2):
    price_minor = 49900
    subtotal_minor = price_minor * qty
    subtotal_inr = subtotal_minor / 100

    addon_html = ""
    if variant == "addon_countdown":
        addon_html = """
        <div style="background: #eff6ff; border: 1px solid #bfdbfe; padding: 12px; border-radius: 6px; margin: 16px 0;">
            <label style="display: flex; align-items: center; cursor: pointer;">
                <input type="checkbox" id="addon_insurance" checked style="width: 18px; height: 18px; margin-right: 10px;">
                <div>
                    <strong>Transit Protection Guarantee: ₹15.00</strong><br>
                    <small style="color: #64748b;">Protection against in-transit damage or loss (Pre-selected by default).</small>
                </div>
            </label>
        </div>
        """

    delivery_notice = ""
    if variant == "legitimate_threshold":
        if subtotal_minor >= 50000:
            delivery_notice = "<p style='color: #16a34a;'><strong>✓ Free Delivery Qualified!</strong> Your cart is above ₹500.</p>"
        else:
            delivery_notice = "<p style='color: #d97706;'><strong>Standard Delivery: ₹40.00</strong> (Add ₹1.00 more for Free Delivery)</p>"

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Your Shopping Cart — Demo Store ({variant})</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f8fafc; color: #0f172a; margin: 0; padding: 32px; }}
            .container {{ max-width: 700px; margin: 0 auto; background: white; padding: 24px; border-radius: 8px; border: 1px solid #e2e8f0; }}
            .btn {{ background: #2563eb; color: white; border: none; padding: 12px 20px; font-size: 1em; font-weight: bold; border-radius: 6px; cursor: pointer; text-decoration: none; display: inline-block; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Shopping Cart</h1>
            <table style="width: 100%; border-bottom: 1px solid #e2e8f0; padding-bottom: 12px; margin-bottom: 16px;">
                <tr>
                    <td><strong>Artisan Coffee Beans</strong> (Qty: {qty})</td>
                    <td style="text-align: right; font-weight: bold;">₹{subtotal_inr:.2f}</td>
                </tr>
            </table>

            {delivery_notice}
            {addon_html}

            <div style="font-size: 1.3em; font-weight: bold; margin: 20px 0; text-align: right;">
                Cart Subtotal: ₹{subtotal_inr:.2f}
            </div>

            <div style="text-align: right;">
                <a class="btn" href="/variant/{variant}/checkout?pincode={pincode}&qty={qty}">Proceed to Checkout Summary &rarr;</a>
            </div>
        </div>
    </body>
    </html>
    """


@app.get("/variant/{variant}/checkout", response_class=HTMLResponse)
def checkout_summary(variant: str, pincode: str = "110001", qty: int = 2):
    price_minor = 49900
    subtotal_minor = price_minor * qty

    # Calculate itemized fees according to variant
    handling_fee_minor = 0
    delivery_fee_minor = 0
    convenience_fee_minor = 0
    addon_fee_minor = 0

    if variant == "clean":
        delivery_fee_minor = 4000
    elif variant == "late_disclosure":
        handling_fee_minor = 500  # ₹5 hidden handling fee!
    elif variant == "addon_countdown":
        addon_fee_minor = 1500  # ₹15 pre-selected insurance
    elif variant == "upfront_fee":
        convenience_fee_minor = 2000  # ₹20 convenience fee
    elif variant == "legitimate_threshold":
        if subtotal_minor < 50000:
            delivery_fee_minor = 4000  # ₹40 below threshold

    total_minor = subtotal_minor + handling_fee_minor + delivery_fee_minor + convenience_fee_minor + addon_fee_minor

    fee_rows = ""
    if handling_fee_minor:
        fee_rows += f"""<tr><td>Handling fee</td><td style='text-align: right; color: #dc2626; font-weight: bold;'>₹{handling_fee_minor / 100:.2f}</td></tr>"""
    if delivery_fee_minor:
        fee_rows += f"""<tr><td>Delivery fee</td><td style='text-align: right;'>₹{delivery_fee_minor / 100:.2f}</td></tr>"""
    if convenience_fee_minor:
        fee_rows += f"""<tr><td>Convenience fee</td><td style='text-align: right;'>₹{convenience_fee_minor / 100:.2f}</td></tr>"""
    if addon_fee_minor:
        fee_rows += f"""<tr><td>Transit Protection Insurance</td><td style='text-align: right; color: #dc2626; font-weight: bold;'>₹{addon_fee_minor / 100:.2f}</td></tr>"""

    timer_box = ""
    if variant == "addon_countdown":
        timer_box = """
        <div style="background: #fef2f2; border: 1px solid #fca5a5; padding: 10px; border-radius: 6px; margin-bottom: 16px; color: #991b1b; font-weight: bold;">
            ⏳ Complete checkout within <span id="chk_timer">09:59</span> minutes to hold reserved inventory!
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Checkout Summary — Demo Store ({variant})</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f8fafc; color: #0f172a; margin: 0; padding: 32px; }}
            .container {{ max-width: 600px; margin: 0 auto; background: white; padding: 24px; border-radius: 8px; border: 1px solid #e2e8f0; }}
            table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
            td {{ padding: 8px 0; border-bottom: 1px solid #f1f5f9; }}
            .btn-pay {{ background: #16a34a; color: white; border: none; padding: 14px; font-size: 1.1em; font-weight: bold; border-radius: 6px; width: 100%; cursor: pointer; margin-top: 16px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Order & Checkout Summary</h2>
            <div style="background: #f1f5f9; padding: 8px 12px; border-radius: 4px; font-size: 0.9em; margin-bottom: 16px;">
                Shipping to Delivery Pincode: <strong>{pincode}</strong>
            </div>
            {timer_box}

            <table>
                <tr>
                    <td>Items Subtotal ({qty} units)</td>
                    <td style="text-align: right; font-weight: bold;">₹{subtotal_minor / 100:.2f}</td>
                </tr>
                {fee_rows}
                <tr style="border-top: 2px solid #0f172a; font-size: 1.25em; font-weight: bold;">
                    <td>Final Payable Amount</td>
                    <td style="text-align: right;">₹{total_minor / 100:.2f}</td>
                </tr>
            </table>

            <div style="background: #eff6ff; border: 1px solid #bfdbfe; padding: 8px 12px; border-radius: 4px; font-size: 0.8em; color: #1e40af; margin-top: 16px;">
                🛡️ Audit Boundary: The agent stops here before entering payment details.
            </div>

            <button class="btn-pay" onclick="alert('Audit Boundary: Payment step reached')">Proceed to Pay (STOP BEFORE CLICK)</button>
        </div>
    </body>
    </html>
    """


@app.get("/policy/refund", response_class=HTMLResponse)
def policy_refund():
    return """
    <html><body><h1>Refund Policy</h1><p>Orders may be cancelled within 1 hour. Full refund initiated within 5 business days.</p></body></html>
    """
