"""Layout checks for the static dashboard. These fail if a number wraps or a map label is cut off."""

import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"

pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def server():
    process = subprocess.Popen(
        ["python3", "-m", "http.server", "8765", "--bind", "127.0.0.1"],
        cwd=SITE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.4)
    yield "http://127.0.0.1:8765/index.html"
    process.terminate()
    process.wait(timeout=5)


def _check(page):
    overflow = page.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2")
    assert overflow, "page scrolls sideways"
    wrapped = page.evaluate(
        """() => [...document.querySelectorAll('.page:not([hidden]) .kpi .value')].filter(node => node.scrollWidth > node.clientWidth + 1).map(node => node.textContent)"""
    )
    assert wrapped == [], f"KPI values wrap: {wrapped}"
    labels = page.evaluate(
        """() => {
          const svg = document.querySelector('.map');
          if (!svg || svg.closest('.page').hidden) return [];
          const box = svg.viewBox.baseVal;
          return [...svg.querySelectorAll('.map-label')].filter(node => {
            const b = node.getBBox();
            return b.x < -1 || b.y < -1 || b.x + b.width > box.width + 1 || b.y + b.height > box.height + 1;
          }).map(node => node.textContent);
        }"""
    )
    assert labels == [], f"map labels clipped: {labels}"
    unsorted = page.evaluate(
        """() => [...document.querySelectorAll('.page:not([hidden]) svg.bars')].filter(svg => {
          const values = [...svg.querySelectorAll('rect')].map(node => Number(node.dataset.value));
          const ordered = svg.dataset.order === 'desc'
            ? [...values].sort((a, b) => b - a)
            : [...values].sort((a, b) => a - b);
          return JSON.stringify(values) !== JSON.stringify(ordered);
        }).length"""
    )
    assert unsorted == 0
    size = page.evaluate("() => parseFloat(getComputedStyle(document.body).fontSize)")
    assert size >= 14


def test_desktop_and_mobile_layout(server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width, height in ((1280, 800), (390, 844)):
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(server)
            assert "Melbourne" in page.locator("#clock").inner_text() or "AEDT" in page.locator("#clock").inner_text() or "AEST" in page.locator("#clock").inner_text()
            for name in ["Recession odds", "States", "Industries", "Early warnings"]:
                page.get_by_role("button", name=name).click()
                page.locator(".page:not([hidden]) h1").wait_for()
                _check(page)
            page.locator(".page:not([hidden]) summary").click()
            assert page.locator(".page:not([hidden]) table").is_visible()
            page.close()
        browser.close()
