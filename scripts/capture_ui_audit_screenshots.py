#!/usr/bin/env python3
"""
Systematic UI & Visual Audit Screenshot Capture Tool.
Drives headless Chrome via Chrome DevTools Protocol (CDP) across multiple viewports,
data volumes, and interactive states to capture baseline screenshots for Phase 3A.
"""

import asyncio
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
import websockets

API_PORT = 36063
BASE_URL = f"http://127.0.0.1:{API_PORT}"
CDP_PORT = 9222
IS_AFTER = "--after" in sys.argv
OUT_DIR = Path("/home/daksh/working/checkout-radar/screenshots/ui-audit/after" if IS_AFTER else "/home/daksh/working/checkout-radar/screenshots/ui-audit")


class ChromeAutomator:
    def __init__(self, port=CDP_PORT):
        self.port = port
        self.proc = None
        self.ws = None
        self.msg_id = 0

    def start(self):
        cmd = [
            "/usr/bin/google-chrome",
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            f"--remote-debugging-port={self.port}",
            "--window-size=1440,900",
            "about:blank",
        ]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.5)

    def stop(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except Exception:
                self.proc.kill()

    async def connect(self):
        req = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json")
        targets = json.loads(req.read())
        page_target = next(t for t in targets if t.get("type") == "page")
        ws_url = page_target["webSocketDebuggerUrl"]
        self.ws = await websockets.connect(ws_url, max_size=100_000_000)
        await self.send("Page.enable")
        await self.send("Runtime.enable")
        await self.send("DOM.enable")

    async def close(self):
        if self.ws:
            await self.ws.close()

    async def send(self, method, params=None):
        self.msg_id += 1
        current_id = self.msg_id
        payload = {"id": current_id, "method": method, "params": params or {}}
        await self.ws.send(json.dumps(payload))
        while True:
            raw = await self.ws.recv()
            resp = json.loads(raw)
            if resp.get("id") == current_id:
                if "error" in resp:
                    raise RuntimeError(f"CDP error in {method}: {resp['error']}")
                return resp.get("result", {})

    async def evaluate(self, expr):
        res = await self.send("Runtime.evaluate", {
            "expression": expr,
            "returnByValue": True,
            "awaitPromise": True,
        })
        result = res.get("result", {})
        if "value" in result:
            return result["value"]
        return result

    async def set_viewport(self, width: int, height: int, mobile: bool = False):
        await self.send("Emulation.setDeviceMetricsOverride", {
            "width": width,
            "height": height,
            "deviceScaleFactor": 1,
            "mobile": mobile,
        })
        await asyncio.sleep(0.3)

    async def capture_viewport(self, filename: str):
        filepath = OUT_DIR / filename
        res = await self.send("Page.captureScreenshot", {"format": "png"})
        img_bytes = base64.b64decode(res["data"])
        with open(filepath, "wb") as f:
            f.write(img_bytes)
        print(f"  [+] Captured Viewport -> {filename} ({len(img_bytes):,} bytes)")
        return str(filepath)

    async def capture_full_page(self, filename: str):
        filepath = OUT_DIR / filename
        metrics = await self.send("Page.getLayoutMetrics")
        content_size = metrics["contentSize"]
        width = int(content_size["width"])
        height = int(content_size["height"])

        clip = {
            "x": 0,
            "y": 0,
            "width": max(width, 1200),
            "height": max(height, 800),
            "scale": 1,
        }
        res = await self.send("Page.captureScreenshot", {
            "format": "png",
            "clip": clip,
            "captureBeyondViewport": True,
        })
        img_bytes = base64.b64decode(res["data"])
        with open(filepath, "wb") as f:
            f.write(img_bytes)
        print(f"  [+] Captured Full Page -> {filename} ({width}x{height}, {len(img_bytes):,} bytes)")
        return str(filepath)


async def run_audit_capture():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    automator = ChromeAutomator()
    automator.start()

    try:
        await automator.connect()

        # =========================================================================
        # Scenario 1: Initial Dashboard (Empty / No Audit Selected)
        # =========================================================================
        print("\n[1/12] Capturing Scenario 1: Initial Dashboard (No Selected Audit)...")
        await automator.set_viewport(1440, 900)
        await automator.send("Page.navigate", {"url": f"{BASE_URL}/"})
        await asyncio.sleep(2.0)
        await automator.capture_viewport("01_initial_dashboard_viewport_1440x900.png")
        await automator.capture_full_page("01_initial_dashboard_fullpage_1440.png")

        # =========================================================================
        # Scenario 2: Clean Audit Completed (aud_2f7143ce0c5a or aud_75f062a2b04d)
        # =========================================================================
        print("\n[2/12] Capturing Scenario 2: Verified Clean Checkout Flow...")
        await automator.send("Page.navigate", {"url": f"{BASE_URL}/?audit_id=aud_2f7143ce0c5a"})
        await asyncio.sleep(2.0)
        await automator.capture_viewport("02_clean_audit_viewport_1440x900.png")
        await automator.capture_full_page("02_clean_audit_fullpage_1440.png")

        # =========================================================================
        # Scenario 3: Indicators Detected (Drip Pricing Positive Control)
        # =========================================================================
        print("\n[3/12] Capturing Scenario 3: Indicators Detected (Drip Pricing)...")
        await automator.send("Page.navigate", {"url": f"{BASE_URL}/?audit_id=aud_4d476bc71e63"})
        await asyncio.sleep(2.0)
        await automator.capture_viewport("03_indicators_detected_viewport_1440x900.png")
        await automator.capture_full_page("03_indicators_detected_fullpage_1440.png")

        if IS_AFTER:
            # Also capture the individual workspace tabs for this audit
            await automator.evaluate("switchTab('findings')")
            await asyncio.sleep(0.5)
            await automator.capture_viewport("03b_indicators_findings_tab_1440x900.png")

            await automator.evaluate("switchTab('integrity')")
            await asyncio.sleep(0.5)
            await automator.capture_viewport("03c_integrity_trail_tab_1440x900.png")

            await automator.evaluate("switchTab('history')")
            await asyncio.sleep(0.5)
            await automator.capture_viewport("03d_history_tab_1440x900.png")

            await automator.evaluate("switchTab('evidence')")
            await asyncio.sleep(0.3)

        # =========================================================================
        # Scenario 4: Inconclusive / Incomplete Audit Flow
        # =========================================================================
        print("\n[4/12] Capturing Scenario 4: Inconclusive Audit (Incomplete Journey)...")
        await automator.send("Page.navigate", {"url": f"{BASE_URL}/?audit_id=aud_f0946ab48e50"})
        await asyncio.sleep(2.0)
        await automator.capture_viewport("04_inconclusive_audit_viewport_1440x900.png")
        await automator.capture_full_page("04_inconclusive_audit_fullpage_1440.png")

        # =========================================================================
        # Scenario 5: High Volume / Dense Dataset (12 runs, 36 findings, 36 snapshots)
        # =========================================================================
        print("\n[5/12] Capturing Scenario 5: High Volume Matrix (12 Runs, 36 Findings)...")
        await automator.send("Page.navigate", {"url": f"{BASE_URL}/?audit_id=aud_3a4d4885de1f"})
        await asyncio.sleep(2.0)
        await automator.capture_viewport("05_high_volume_dense_viewport_1440x900.png")
        await automator.capture_full_page("05_high_volume_dense_fullpage_1440.png")

        if IS_AFTER:
            await automator.evaluate("switchTab('findings')")
            await asyncio.sleep(0.5)
            await automator.capture_viewport("05b_high_volume_findings_tab_1440x900.png")
            await automator.evaluate("switchTab('evidence')")
            await asyncio.sleep(0.3)

        # =========================================================================
        # Scenario 6: Evidence Gallery with Real Site Screenshots (aud_b29153cee0b1)
        # =========================================================================
        print("\n[6/12] Capturing Scenario 6: Real Merchant Evidence Gallery (Headphone Zone)...")
        await automator.send("Page.navigate", {"url": f"{BASE_URL}/?audit_id=aud_b29153cee0b1"})
        await asyncio.sleep(2.0)
        # Scroll down to center evidence gallery in viewport
        await automator.evaluate("document.getElementById('evidence-gallery-section').scrollIntoView({behavior: 'instant', block: 'start'})")
        await asyncio.sleep(0.5)
        await automator.capture_viewport("06_real_merchant_gallery_viewport_1440x900.png")

        # =========================================================================
        # Scenario 7: Full-Resolution Lightbox Modal Open
        # =========================================================================
        print("\n[7/12] Capturing Scenario 7: Full-Resolution Lightbox Modal...")
        await automator.evaluate("document.querySelector('#footer-stage-cart button').click()")
        await asyncio.sleep(0.6)
        await automator.capture_viewport("07_lightbox_modal_open_1440x900.png")
        await automator.evaluate("closeScreenshotModal()")
        await asyncio.sleep(0.3)

        # =========================================================================
        # Scenario 8: CCPA Consumer Grievance Draft Modal Open
        # =========================================================================
        print("\n[8/12] Capturing Scenario 8: CCPA Complaint Draft Modal...")
        # Open complaint modal on audit with findings
        await automator.send("Page.navigate", {"url": f"{BASE_URL}/?audit_id=aud_4d476bc71e63"})
        await asyncio.sleep(2.0)
        await automator.evaluate("openComplaintModal()")
        await asyncio.sleep(0.6)
        await automator.capture_viewport("08_complaint_draft_modal_1440x900.png")
        await automator.evaluate("closeComplaintModal()")
        await asyncio.sleep(0.3)

        # =========================================================================
        # Scenario 9: HTML Standalone Evidence Report in Browser
        # =========================================================================
        print("\n[9/12] Capturing Scenario 9: Standalone HTML Evidence Report...")
        await automator.send("Page.navigate", {"url": f"{BASE_URL}/audits/aud_b29153cee0b1/report"})
        await asyncio.sleep(1.5)
        await automator.capture_viewport("09_html_report_viewport_1440x900.png")
        await automator.capture_full_page("09_html_report_fullpage_1440.png")

        # =========================================================================
        # Scenario 10: In-Progress Audit Execution (Progress bar, SSE console)
        # =========================================================================
        print("\n[10/12] Capturing Scenario 10: Active Audit Execution & SSE Progress...")
        await automator.send("Page.navigate", {"url": f"{BASE_URL}/"})
        await asyncio.sleep(1.0)
        # Trigger quick audit submission
        await automator.evaluate("""
            document.getElementById('input-url').value = 'http://harness:8001/variant/late_disclosure';
            document.getElementById('audit-form').dispatchEvent(new Event('submit'));
        """)
        await asyncio.sleep(1.2)  # Capture while actively streaming
        await automator.capture_viewport("10_audit_execution_in_progress_1440x900.png")

        # =========================================================================
        # Scenario 11: Responsive Tablet Viewport (768 x 1024)
        # =========================================================================
        print("\n[11/12] Capturing Scenario 11: Responsive Tablet Layout (768x1024)...")
        await automator.set_viewport(768, 1024)
        await automator.send("Page.navigate", {"url": f"{BASE_URL}/?audit_id=aud_4d476bc71e63"})
        await asyncio.sleep(2.0)
        await automator.capture_viewport("11_tablet_viewport_768x1024.png")
        await automator.capture_full_page("11_tablet_fullpage_768.png")

        # =========================================================================
        # Scenario 12: Responsive Mobile Viewport (375 x 812)
        # =========================================================================
        print("\n[12/12] Capturing Scenario 12: Responsive Mobile Layout (375x812)...")
        await automator.set_viewport(375, 812, mobile=True)
        await automator.send("Page.navigate", {"url": f"{BASE_URL}/?audit_id=aud_4d476bc71e63"})
        await asyncio.sleep(2.0)
        await automator.capture_viewport("12_mobile_viewport_375x812.png")
        await automator.capture_full_page("12_mobile_fullpage_375.png")

        print("\n" + "=" * 70)
        print(" [SUCCESS] All 12 baseline audit scenarios captured successfully!")
        print(f" Images stored in: {OUT_DIR}")
        print("=" * 70)

    finally:
        await automator.close()
        automator.stop()


if __name__ == "__main__":
    asyncio.run(run_audit_capture())
