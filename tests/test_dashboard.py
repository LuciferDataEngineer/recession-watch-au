from pathlib import Path

from recession_watch.dashboard import pretty_period

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "site" / "index.html"
FORBIDDEN = [
    "DuckDB",
    "DataFusion",
    "Hamilton",
    "Kestra",
    "probit",
    "logit",
    "RMSE",
    "Brier",
    "bitemporal",
    "DynamicFactor",
    "Pandera",
    "nowcast",
    "vintage",
    "SDMX",
]


def test_period_labels_are_plain_dates():
    assert pretty_period("2026Q3") == "Sep 2026"
    assert pretty_period("2026-Q4") == "Dec 2026"
    assert pretty_period("2026-10") == "Oct 2026"


def test_dashboard_uses_plain_language_and_four_tabs():
    html = PAGE.read_text()
    for word in FORBIDDEN:
        assert word not in html
    for tab in ["Recession odds", "States", "Industries", "Early warnings"]:
        assert tab in html
    for fact in ["4.9%", "4.85%", "4.3%", "11.3%", "−43,500", "2 Dec 2026"]:
        assert fact in html
    assert "Australia/Melbourne" in html
