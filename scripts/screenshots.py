"""Capture a screenshot of every dashboard tab (used for the README). Requires the stack running."""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "docs" / "img"
URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8501"
TABS = ["Live operations", "Fraud alerts", "Forecast", "Portfolio", "Models", "Score a claim"]

OUT.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
    page.goto(URL, wait_until="networkidle")
    page.wait_for_selector("text=ClaimStream", timeout=60000)
    page.wait_for_timeout(6000)
    for i, tab in enumerate(TABS):
        page.get_by_role("tab", name=tab).click()
        page.wait_for_timeout(5000)
        if tab == "Score a claim":
            page.get_by_role("button", name="Score claim").click()
            page.wait_for_timeout(3000)
        page.screenshot(path=str(OUT / f"{i + 1}_{tab.lower().replace(' ', '_')}.png"), full_page=True)
        print("captured", tab)
    b.close()
