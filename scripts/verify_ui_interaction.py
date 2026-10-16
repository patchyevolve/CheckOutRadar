#!/usr/bin/env python3
"""
Visual interaction verification script for Checkout Radar Phase 1 Evidence Dashboard.
Uses Chrome DevTools Protocol (CDP) to drive headless Chrome, perform user interactions,
assert DOM states, and capture screenshots.
"""

import asyncio
import base64
import json
import os
import subprocess
import time
import urllib.request
import websockets

def resolve_api_base_url():
    if "API_PORT" in os.environ:
        return f"http://127.0.0.1:{os.environ['API_PORT']}"
    try:
        res = subprocess.run(["docker", "compose", "port", "api", "8000"], capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            out = res.stdout.strip().split("\n")[0]
            parts = out.split(":")
            if len(parts) >= 2:
                host = parts[0] if parts[0] not in ("0.0.0.0", "") else "127.0.0.1"
                port = parts[-1]
                return f"http://{host}:{port}"
    except Exception:
        pass
    return "http://127.0.0.1:8000"

BASE_URL = resolve_api_base_url()
CDP_PORT = 9222


class ChromeSession:
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
            "--window-size=1400,1200",
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
        self.ws = await websockets.connect(ws_url, max_size=50_000_000)
        await self.send("Page.enable")
        await self.send("Runtime.enable")

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
                    raise RuntimeError(f"CDP error: {resp['error']}")
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

    async def capture_screenshot(self, filepath):
        res = await self.send("Page.captureScreenshot", {"format": "png"})
        img_bytes = base64.b64decode(res["data"])
        with open(filepath, "wb") as f:
            f.write(img_bytes)
        print(f"  [+] Screenshot saved to {filepath} ({len(img_bytes)} bytes)")


async def run_checks():
    chrome = ChromeSession()
    chrome.start()
    try:
        await chrome.connect()

        # =========================================================================
        # CHECK 2: All stage screenshots load and open at full resolution via modal
        # =========================================================================
        print("\n--- Verifying Check 2: Full-Resolution Lightbox Modal ---")
        target_url = f"{BASE_URL}/?audit_id=aud_b29153cee0b1"
        print(f"Navigating to {target_url}...")
        await chrome.send("Page.navigate", {"url": target_url})
        await asyncio.sleep(2.0)  # Wait for API fetch and DOM render

        # Check stage cards are populated
        card_title = await chrome.evaluate("document.querySelector('#card-stage-cart .stage-name').innerText")
        cart_badge = await chrome.evaluate("document.getElementById('badge-stage-cart').innerText")
        cart_snap = await chrome.evaluate("document.getElementById('meta-snap-cart').innerText")
        print(f"  Stage 2 Card: '{card_title}', Badge: '{cart_badge}', SnapID: '{cart_snap}'")
        assert cart_badge == "VERIFIED", f"Expected VERIFIED badge, got {cart_badge}"
        assert "snap_" in cart_snap, f"Expected snapshot id, got {cart_snap}"

        # Modal initially hidden
        modal_hidden = await chrome.evaluate("document.getElementById('screenshot-modal').classList.contains('hidden')")
        assert modal_hidden is True, "Modal should initially be hidden"

        # Click the Full Resolution button on Cart card
        print("  Clicking 'Full Resolution' button on Stage 2 (Cart)...")
        await chrome.evaluate("document.querySelector('#footer-stage-cart button').click()")
        await asyncio.sleep(0.5)

        # Verify modal opened and populated
        modal_hidden_after = await chrome.evaluate("document.getElementById('screenshot-modal').classList.contains('hidden')")
        assert modal_hidden_after is False, "Modal should now be visible"

        modal_title = await chrome.evaluate("document.getElementById('modal-stage-title').innerText")
        modal_snap = await chrome.evaluate("document.getElementById('modal-snap-id').innerText")
        modal_hash = await chrome.evaluate("document.getElementById('modal-hash-val').innerText")
        modal_src = await chrome.evaluate("document.getElementById('modal-img').src")
        modal_raw_link = await chrome.evaluate("document.getElementById('modal-raw-link').href")

        print(f"  Modal Title: '{modal_title}'")
        print(f"  Modal Snap ID: '{modal_snap}'")
        print(f"  Modal Hash: '{modal_hash}'")
        print(f"  Modal Img Src: '{modal_src}'")
        print(f"  Modal Raw Link: '{modal_raw_link}'")

        assert "Cart Drawer" in modal_title
        assert modal_snap == cart_snap
        assert len(modal_hash) >= 64, "Expected full SHA-256 digest in modal"
        assert "/evidence/" in modal_src
        assert "/evidence/" in modal_raw_link

        # Capture screenshot of the modal
        await chrome.capture_screenshot("/tmp/view_modal_cart_open.png")

        # Close the modal
        print("  Closing modal...")
        await chrome.evaluate("closeScreenshotModal()")
        await asyncio.sleep(0.3)
        modal_hidden_closed = await chrome.evaluate("document.getElementById('screenshot-modal').classList.contains('hidden')")
        assert modal_hidden_closed is True, "Modal should be hidden after closing"
        print("  [✓] Check 2 passed: Modal opens with full resolution image, cryptographic hash, and links.")

        # =========================================================================
        # CHECK 3: Multi-Run Condition Switching
        # =========================================================================
        print("\n--- Verifying Check 3: Multi-Run Condition Switching ---")
        target_multi_url = f"{BASE_URL}/?audit_id=aud_75f062a2b04d"
        print(f"Navigating to {target_multi_url}...")
        await chrome.send("Page.navigate", {"url": target_multi_url})
        await asyncio.sleep(2.0)

        # Check run selector
        sel_hidden = await chrome.evaluate("document.getElementById('run-selector-container').classList.contains('hidden')")
        assert sel_hidden is False, "Run selector should be visible for multi-run audit"

        options = await chrome.evaluate("""
            Array.from(document.getElementById('gallery-run-select').options).map(o => ({
                value: o.value,
                text: o.text,
                selected: o.selected
            }))
        """)
        print(f"  Available condition runs ({len(options)}):")
        for opt in options:
            print(f"    - [{opt['value']}] {opt['text']} (selected: {opt['selected']})")
        assert len(options) == 4, f"Expected 4 runs in selector, found {len(options)}"

        # Verify initial run is reference
        selected_opt = next(o for o in options if o["selected"])
        assert "Reference" in selected_opt["text"], f"Reference run should be selected initially: {selected_opt}"
        initial_run_id = selected_opt["value"]
        initial_snap_cart = await chrome.evaluate("document.getElementById('meta-snap-cart').innerText")
        initial_hash_cart = await chrome.evaluate("document.getElementById('meta-hash-cart').innerText")
        print(f"  Initial Selected Run: {initial_run_id}, Cart Snap ID: {initial_snap_cart}, Hash: {initial_hash_cart}")

        # Switch to an alternate condition
        other_opt = next(o for o in options if not o["selected"])
        other_run_id = other_opt["value"]
        print(f"  Switching condition dropdown to {other_run_id} ({other_opt['text']})...")
        await chrome.evaluate(f"""
            const sel = document.getElementById('gallery-run-select');
            sel.value = '{other_run_id}';
            sel.dispatchEvent(new Event('change'));
        """)
        await asyncio.sleep(0.5)

        # Verify stage captures updated
        switched_snap_cart = await chrome.evaluate("document.getElementById('meta-snap-cart').innerText")
        switched_hash_cart = await chrome.evaluate("document.getElementById('meta-hash-cart').innerText")
        print(f"  Switched Cart Snap ID: {switched_snap_cart}, Hash: {switched_hash_cart}")
        assert switched_snap_cart != initial_snap_cart, f"Snap ID did not update: {switched_snap_cart} == {initial_snap_cart}"

        # Capture screenshot showing switched run viewports
        await chrome.capture_screenshot("/tmp/view_condition_switched_run2.png")
        print("  [✓] Check 3 passed: Switching condition dropdown updates stage viewport evidence dynamically.")

        # =========================================================================
        # CHECK 4: HTML Report /evidence links
        # =========================================================================
        print("\n--- Verifying Check 4: HTML Report Evidence Links ---")
        report_url = f"{BASE_URL}/audits/aud_b29153cee0b1/report"
        print(f"Navigating to {report_url}...")
        await chrome.send("Page.navigate", {"url": report_url})
        await asyncio.sleep(1.0)

        report_links = await chrome.evaluate("""
            Array.from(document.querySelectorAll('a[href*="evidence"]')).map(a => a.getAttribute('href'))
        """)
        print(f"  Found {len(report_links)} evidence link(s) in HTML report:")
        for l in report_links:
            print(f"    - {l}")
            assert not l.startswith("./"), f"Relative path found: {l}"
            assert l.startswith("/evidence/"), f"Path must start with /evidence/: {l}"

        await chrome.capture_screenshot("/tmp/view_html_report.png")
        print("  [✓] Check 4 passed: All HTML report links use safe /evidence/{filename} URLs.")

        # =========================================================================
        # CHECK 5: Provider Settings Modal & Zero Exfiltration Verification
        # =========================================================================
        print("\n--- Verifying Check 5: Provider Settings Modal & Zero Exfiltration ---")
        auditor_url = f"{BASE_URL}/auditor"
        print(f"Navigating to {auditor_url}...")
        await chrome.send("Page.navigate", {"url": auditor_url})
        await asyncio.sleep(1.5)

        # Open Settings Modal
        print("  Clicking 'Provider Settings' button in navbar...")
        await chrome.evaluate("openSettingsModal()")
        await asyncio.sleep(0.5)

        modal_visible = await chrome.evaluate("!document.getElementById('settings-modal').classList.contains('hidden')")
        assert modal_visible is True, "Settings modal should be visible"

        # Verify default / active base URL and model fields are populated
        base_url_val = await chrome.evaluate("document.getElementById('settings-llm-base-url').value")
        model_val = await chrome.evaluate("document.getElementById('settings-llm-model').value")
        key_input_val = await chrome.evaluate("document.getElementById('settings-llm-api-key').value")
        print(f"  Base URL: '{base_url_val}', Model: '{model_val}', Key Input Length: {len(key_input_val)}")

        assert base_url_val.startswith("http"), f"Expected HTTP base URL, got {base_url_val}"
        assert len(model_val) > 0, "Expected non-empty model identifier"
        # STRICT PRIVACY INVARIANT: API key input must NOT contain any plaintext secret by default
        assert key_input_val == "", "API key input must never be pre-populated with plaintext secrets from backend"

        # Test preset click (Groq)
        print("  Testing Groq preset button...")
        await chrome.evaluate("applyProviderPreset('groq')")
        groq_url = await chrome.evaluate("document.getElementById('settings-llm-base-url').value")
        groq_model = await chrome.evaluate("document.getElementById('settings-llm-model').value")
        assert "groq.com" in groq_url
        assert "llama-3.3-70b" in groq_model
        print(f"  Preset applied: {groq_url} ({groq_model})")

        # Capture screenshot of settings modal
        await chrome.capture_screenshot("/tmp/view_provider_settings_modal.png")

        # Close settings modal
        await chrome.evaluate("closeSettingsModal()")
        await asyncio.sleep(0.3)
        modal_closed = await chrome.evaluate("document.getElementById('settings-modal').classList.contains('hidden')")
        assert modal_closed is True, "Settings modal should be hidden after closing"
        print("  [✓] Check 5 passed: Provider settings modal functions with zero credential exfiltration.")

    finally:
        await chrome.close()
        chrome.stop()


if __name__ == "__main__":
    asyncio.run(run_checks())
