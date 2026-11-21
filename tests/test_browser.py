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


def test_visual_guards_at_desktop(server):
    """Chart labels, type size, and a quiet console at the 1920×1072 review size."""
    from playwright.sync_api import sync_playwright

    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1072})
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(server, wait_until="networkidle")

        overlap = page.evaluate(
            """() => {
              const labels = [...document.querySelectorAll('.hero-chart text.axis')];
              const boxes = labels.map(el => {
                const b = el.getBoundingClientRect();
                return {t: el.textContent, x: b.x, r: b.right, y: b.y, b: b.bottom};
              });
              const hits = [];
              for (let i = 0; i < boxes.length; i++) {
                for (let j = i + 1; j < boxes.length; j++) {
                  const a = boxes[i], c = boxes[j];
                  const crosses = a.x < c.r - 1 && c.x < a.r - 1 && a.y < c.b - 1 && c.y < a.b - 1;
                  if (crosses) hits.push(a.t + ' / ' + c.t);
                }
              }
              return hits;
            }"""
        )
        assert overlap == [], f"growth chart x labels overlap: {overlap}"

        flat = page.evaluate(
            """() => [...document.querySelectorAll('.growth-chart rect')].filter(node => Math.abs(Number(node.dataset.value)) < 0.05 && Number(node.getAttribute('height')) < 4).map(node => node.dataset.value)"""
        )
        assert flat == [], f"flat growth bar is invisible: {flat}"

        for name in ["Recession odds", "States", "Industries", "Early warnings"]:
            page.get_by_role("button", name=name).click()
            page.locator(".page:not([hidden]) h1").wait_for()
            small = page.evaluate(
                """() => {
                  const painted = (el) => {
                    const specified = parseFloat(getComputedStyle(el).fontSize);
                    const svg = el.ownerSVGElement;
                    if (!svg) return specified;
                    const matrix = el.getScreenCTM();
                    if (!matrix) return specified;
                    return specified * Math.hypot(matrix.a, matrix.b);
                  };
                  const nodes = [
                    ...document.querySelectorAll('.page:not([hidden]) .line-chart .axis, .page:not([hidden]) .line-chart .direct'),
                    ...document.querySelectorAll('.page:not([hidden]) .growth-chart .axis, .page:not([hidden]) .growth-chart .direct'),
                    ...document.querySelectorAll('.page:not([hidden]) .kpi .take'),
                  ];
                  return nodes.filter(el => painted(el) < 12).map(el => el.textContent.trim().slice(0, 40) + ' ' + painted(el).toFixed(1));
                }"""
            )
            assert small == [], f"type under 12px on {name}: {small}"
            outside = page.evaluate(
                """() => {
                  const problems = [];
                  document.querySelectorAll('.page:not([hidden]) .line-chart').forEach(svg => {
                    const matrix = svg.getScreenCTM();
                    const point = svg.createSVGPoint();
                    const map = (x, y) => {
                      point.x = Number(x);
                      point.y = Number(y);
                      return point.matrixTransform(matrix);
                    };
                    const a = map(svg.dataset.plotLeft, svg.dataset.plotTop);
                    const b = map(svg.dataset.plotRight, svg.dataset.plotBottom);
                    const plot = {
                      left: Math.min(a.x, b.x),
                      top: Math.min(a.y, b.y),
                      right: Math.max(a.x, b.x),
                      bottom: Math.max(a.y, b.y),
                    };
                    svg.querySelectorAll('.end-label').forEach(el => {
                      const box = el.getBoundingClientRect();
                      if (box.left < plot.left - 1 || box.right > plot.right + 1 || box.top < plot.top - 1 || box.bottom > plot.bottom + 1) {
                        problems.push(el.textContent);
                      }
                    });
                  });
                  return problems;
                }"""
            )
            assert outside == [], f"end labels outside the plot on {name}: {outside}"

        assert errors == [], f"console errors: {errors}"
        browser.close()
