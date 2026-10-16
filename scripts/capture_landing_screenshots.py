#!/usr/bin/env python3
"""
Screenshot Capture Tool for Checkout Radar Product Landing Page.
Drives headless Chrome via Chrome DevTools Protocol (CDP) across multiple viewports
(Desktop 1440x900, Tablet 768x1024, Mobile 375x812) to capture landing page evidence.
"""

import asyncio
import base64
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path
import websockets

API_PORT = 36063
BASE_URL = f"http://127.0.0.1:{API_PORT}"
CDP_PORT = 9222
OUT_DIR = Path("/home/daksh/working/checkout-radar/screenshots/landing")


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
            "width": width,
            "height": height,
            "scale": 1,
        }
        res = await self.send("Page.captureScreenshot", {
            "format": "png",
            "captureBeyondViewport": True,
            "clip": clip,
        })
        img_bytes = base64.b64decode(res["data"])
        with open(filepath, "wb") as f:
            f.write(img_bytes)
        print(f"  [+] Captured Full Page -> {filename} ({len(img_bytes):,} bytes)")
        return str(filepath)


async def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    chrome = ChromeAutomator()
    print("Starting headless Chrome instance...")
    chrome.start()

    try:
        await chrome.connect()
        print(f"Connected via CDP. Navigating to Landing Page: {BASE_URL}/")
        await chrome.send("Page.navigate", {"url": f"{BASE_URL}/"})
        await asyncio.sleep(1.5)

        # 1. Desktop Viewport (1440x900)
        print("\n--- Capturing Desktop Viewport (1440x900) ---")
        await chrome.set_viewport(1440, 900, mobile=False)
        await asyncio.sleep(0.5)
        await chrome.capture_viewport("01_landing_desktop_1440x900.png")
        await chrome.capture_full_page("01_landing_desktop_fullpage_1440.png")

        # 2. Tablet Viewport (768x1024)
        print("\n--- Capturing Tablet Viewport (768x1024) ---")
        await chrome.set_viewport(768, 1024, mobile=True)
        await asyncio.sleep(0.5)
        await chrome.capture_viewport("02_landing_tablet_768x1024.png")
        await chrome.capture_full_page("02_landing_tablet_fullpage_768.png")

        # 3. Mobile Viewport (375x812)
        print("\n--- Capturing Mobile Viewport (375x812) ---")
        await chrome.set_viewport(375, 812, mobile=True)
        await asyncio.sleep(0.5)
        await chrome.capture_viewport("03_landing_mobile_375x812.png")
        await chrome.capture_full_page("03_landing_mobile_fullpage_375.png")

        print("\nAll landing page screenshots successfully captured.")

    finally:
        await chrome.close()
        chrome.stop()
        print("Chrome stopped.")


if __name__ == "__main__":
    asyncio.run(main())
