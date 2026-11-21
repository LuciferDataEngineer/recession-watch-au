"""Static dashboard. Plain language only — methods live in the README."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from recession_watch.model import (
    both_negative_probability,
    contraction_probability,
    fit_logit,
    logit_probability,
)
from recession_watch.periods import melbourne_label
from recession_watch.quality import round_half_up

ROOT = Path(__file__).resolve().parents[2]
GEOJSON = ROOT / "data" / "reference" / "au_states.geojson"

QUARTER_MONTH = {"Q1": "Mar", "Q2": "Jun", "Q3": "Sep", "Q4": "Dec"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def pretty_period(token: str) -> str:
    if not token:
        return ""
    if "Q" in token and token[:4].isdigit():
        year, quarter = token.replace("-", "").split("Q", 1)
        quarter = quarter if quarter.startswith("Q") else f"Q{quarter}"
        return f"{QUARTER_MONTH.get(quarter, quarter)} {year}"
    parts = token.split("-")
    if len(parts) >= 2 and parts[1].isdigit():
        return f"{MONTHS[int(parts[1]) - 1]} {parts[0]}"
    return token


def signed_pct(value, digits: int = 1) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    number = round_half_up(float(value), digits)
    text = f"{abs(number):.{digits}f}"
    if number > 0:
        return f"+{text}%"
    if number < 0:
        return f"−{text}%"
    return f"{text}%"


def pct(value, digits: int = 1) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    number = round_half_up(float(value), digits)
    return f"{number:.{digits}f}%"


def people(value) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    number = int(round_half_up(float(value), 0))
    sign = "−" if number < 0 else "+" if number > 0 else ""
    return f"{sign}{abs(number):,}"


def odds(value) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    return f"{round_half_up(value * 100, 0):.0f}%"


def status_for(kind: str, value: float) -> str:
    if not math.isfinite(value):
        return "warn"
    if kind == "recession":
        return "ok" if value < 0.15 else "warn" if value < 0.30 else "bad"
    if kind == "growth":
        return "bad" if value < 0 else "warn" if value < 0.3 else "ok"
    if kind == "jobs":
        return "bad" if value < 0 else "ok"
    if kind == "prices":
        return "bad" if value > 3 else "warn" if value > 2.5 else "ok"
    if kind == "gap":
        return "bad" if value >= 0.5 else "warn" if value >= 0.3 else "ok"
    if kind == "spread":
        return "ok" if value > 0 else "bad"
    return "warn"


def _finite(value, default=float("nan")) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def build_view(payload: dict) -> dict:
    """Turn pipeline output into the numbers and sentences the page shows."""
    scores = payload["scores"]
    points = payload["nowcast"]["points"]
    ordered = list(points.items())
    q1_name, q1 = ordered[0]
    q2_name, q2 = ordered[1] if len(ordered) > 1 else (q1_name, q1)
    # Bands use the miss size since 2023. The 2020 collapse was several percent
    # in one quarter and would make every current estimate look directionless.
    scale = _finite(scores.get("rmse_dfm_recent"), _finite(scores.get("rmse_dfm"), 0.40))
    if not math.isfinite(scale) or scale <= 0:
        scale = 0.40
    further = scale * 1.15
    p1 = contraction_probability(q1["gdp"], scale)
    p2 = contraction_probability(q2["gdp"], further)
    correlation = _finite(scores.get("correlation_errors"), 0.35)
    technical = both_negative_probability(q1["gdp"], q2["gdp"], scale, further, correlation)
    pc1 = contraction_probability(q1["gdp_pc"], scale)
    pc2 = contraction_probability(q2["gdp_pc"], further)
    technical_pc = both_negative_probability(q1["gdp_pc"], q2["gdp_pc"], scale, further, correlation)

    backtest = pd.DataFrame(payload["backtest_rows"])
    logit = fit_logit(backtest) if not backtest.empty else None
    signal_row = pd.Series(payload["signals"])
    logit_p = logit_probability(logit, signal_row) if logit is not None else float("nan")

    anchors = payload["anchors"]
    signals = payload["signals"]
    job_change = anchors["employment_change_oct_2026"]
    technical_status = status_for("recession", technical)
    per_person_slipping = q1["gdp_pc"] < 0 and q2["gdp_pc"] < 0 and q1["gdp"] >= 0
    if per_person_slipping and technical_status != "bad":
        headline = "Output per person is set to fall, even if the economy still grows"
        detail = (
            "The next two quarters still look more likely to be positive for the economy as a whole. "
            "Once population growth is taken out, output per person is estimated to shrink in both."
        )
    elif technical_status == "bad":
        headline = "The risk of a recession is now hard to dismiss"
        detail = (
            "The growth estimate is weak enough that two shrinking quarters belong in the planning range, "
            "not just in a footnote."
        )
    elif technical_status == "warn" or q2["gdp"] < 0.2:
        headline = "Growth is fading toward a stall, and a shrinking quarter is a live risk"
        detail = (
            "Employment has fallen and unemployment is at a four-year high. "
            "The December quarter is close to flat. One negative quarter would not yet be a recession."
        )
    else:
        headline = "Two shrinking quarters are not the central case"
        detail = (
            "The jobs market has weakened, but the growth estimate for the rest of 2026 is still positive. "
            "A single soft quarter would not, on its own, be a recession."
        )

    created = melbourne_label(pd.Timestamp(payload["created_at_utc"]).to_pydatetime())
    band = 1.036
    history = []
    for point in payload["nowcast"].get("history", [])[-12:]:
        history.append({"period": point["period"], "label": pretty_period(point["period"]), "value": point["value"], "kind": "history"})
    forecast = [
        {
            "period": q1_name,
            "label": pretty_period(q1_name),
            "value": q1["gdp"],
            "low": q1["gdp"] - band * scale,
            "high": q1["gdp"] + band * scale,
            "kind": "nowcast",
        },
        {
            "period": q2_name,
            "label": pretty_period(q2_name),
            "value": q2["gdp"],
            "low": q2["gdp"] - band * further,
            "high": q2["gdp"] + band * further,
            "kind": "nowcast",
        },
    ]
    pc_forecast = [
        {"period": q1_name, "label": pretty_period(q1_name), "value": q1["gdp_pc"], "kind": "nowcast"},
        {"period": q2_name, "label": pretty_period(q2_name), "value": q2["gdp_pc"], "kind": "nowcast"},
    ]
    return {
        "created_label": created,
        "headline": headline,
        "detail": detail,
        "next_release": "2 Dec 2026, 11:30 am AEDT",
        "scale": scale,
        "quarters": {"first": q1_name, "second": q2_name},
        "estimate": {"first": q1["gdp"], "second": q2["gdp"], "pc_first": q1["gdp_pc"], "pc_second": q2["gdp_pc"]},
        "probability": {
            "first": p1,
            "second": p2,
            "technical": technical,
            "pc_first": pc1,
            "pc_second": pc2,
            "technical_pc": technical_pc,
            "logit": logit_p,
        },
        "history": history,
        "forecast": forecast,
        "pc_history": payload["nowcast"].get("history_pc", [])[-12:],
        "pc_forecast": pc_forecast,
        "anchors": anchors,
        "signals": signals,
        "states": payload["states"],
        "industries": payload["industries"],
        "scores": scores,
        "job_change": job_change,
        "sources": payload["sources"],
    }


def _project(lon: float, lat: float) -> tuple[float, float]:
    x = 36 + (lon - 112.0) / 44.0 * 700
    y = 28 + ((-9.5 - lat) / 35.5) * 560
    return x, y


def _rings(geometry: dict) -> list:
    if geometry["type"] == "Polygon":
        return geometry["coordinates"]
    if geometry["type"] == "MultiPolygon":
        return [ring for polygon in geometry["coordinates"] for ring in polygon]
    return []


def _path(ring: list) -> str:
    commands = []
    for index, (lon, lat) in enumerate(ring):
        x, y = _project(lon, lat)
        commands.append(f"{'M' if index == 0 else 'L'}{x:.1f},{y:.1f}")
    commands.append("Z")
    return " ".join(commands)


def _centroid(ring: list) -> tuple[float, float]:
    xs, ys = [], []
    for lon, lat in ring:
        x, y = _project(lon, lat)
        xs.append(x)
        ys.append(y)
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _heat(t: float) -> str:
    t = min(1.0, max(0.0, t))
    # teal -> amber -> red
    stops = [(31, 138, 112), (246, 196, 83), (255, 93, 93)]
    if t < 0.5:
        a, b, mix = stops[0], stops[1], t / 0.5
    else:
        a, b, mix = stops[1], stops[2], (t - 0.5) / 0.5
    rgb = tuple(int(a[i] + (b[i] - a[i]) * mix) for i in range(3))
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


NAME_TO_SHORT = {
    "New South Wales": "NSW",
    "Victoria": "VIC",
    "Queensland": "QLD",
    "South Australia": "SA",
    "Western Australia": "WA",
    "Tasmania": "TAS",
    "Northern Territory": "NT",
    "Australian Capital Territory": "ACT",
}


def map_svg(states: list[dict]) -> str:
    by_short = {row["short"]: row for row in states}
    geo = json.loads(GEOJSON.read_text())
    shapes = []
    labels = []
    for feature in geo["features"]:
        short = NAME_TO_SHORT.get(feature["properties"]["name"])
        if short is None or short not in by_short:
            continue
        row = by_short[short]
        rings = _rings(feature["geometry"])
        if not rings:
            continue
        ring = max(rings, key=len)
        pressure = _finite(row.get("pressure"), 50) / 100
        jobs = _finite(row.get("jobs_3m_pct"), 0)
        unemp = _finite(row.get("unemp"), 0)
        demand = _finite(row.get("sfd_qoq"), 0)
        shapes.append(
            f'<path class="state" data-short="{short}" data-pressure="{pressure:.3f}" '
            f'data-jobs="{jobs:.3f}" data-unemp="{unemp:.3f}" data-demand="{demand:.3f}" '
            f'd="{_path(ring)}" fill="{_heat(pressure)}"><title>{row["name"]}</title></path>'
        )
        x, y = _centroid(ring)
        if short == "ACT":
            labels.append(
                f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x+46:.1f}" y2="{y+28:.1f}" class="leader"/>'
                f'<text class="map-label" x="{x+50:.1f}" y="{y+32:.1f}" text-anchor="start">{short}</text>'
            )
        elif short == "TAS":
            labels.append(f'<text class="map-label" x="{x:.1f}" y="{y+16:.1f}" text-anchor="middle">{short}</text>')
        elif short == "VIC":
            labels.append(f'<text class="map-label" x="{x:.1f}" y="{y+8:.1f}" text-anchor="middle">{short}</text>')
        else:
            labels.append(f'<text class="map-label" x="{x:.1f}" y="{y:.1f}" text-anchor="middle">{short}</text>')
    return (
        '<svg class="map" viewBox="0 0 820 640" role="img" aria-label="Australia, states coloured by pressure">'
        + "".join(shapes)
        + "".join(labels)
        + "</svg>"
    )


def line_chart(points: list[dict], title: str, aria: str, zero: bool = True, formatter=signed_pct) -> str:
    values = [p["value"] for p in points if p.get("value") is not None and math.isfinite(p["value"])]
    if len(values) < 2:
        return f'<div class="chart-card"><h3>{title}</h3><p>Not enough history.</p></div>'
    low, high = min(values + ([0] if zero else [])), max(values + ([0] if zero else []))
    pad = max(0.2, (high - low) * 0.15)
    low, high = low - pad, high + pad
    width, height = 640, 260
    left, right, top, bottom = 46, 16, 16, 36
    plot_w, plot_h = width - left - right, height - top - bottom

    def xy(i, value):
        x = left + plot_w * i / (len(points) - 1)
        y = top + plot_h * (1 - (value - low) / (high - low))
        return x, y

    coords = []
    dots = []
    for i, point in enumerate(points):
        x, y = xy(i, point["value"])
        coords.append(f"{x:.1f},{y:.1f}")
        if i == len(points) - 1 or i == 0:
            dots.append(
                f'<text class="direct" x="{x:.1f}" y="{y-8:.1f}" text-anchor="{"start" if i==0 else "end"}">{formatter(point["value"])}</text>'
            )
    zero_y = top + plot_h * (1 - (0 - low) / (high - low)) if zero and low < 0 < high else None
    grid = f'<line x1="{left}" y1="{zero_y:.1f}" x2="{width-right}" y2="{zero_y:.1f}" class="zero"/>' if zero_y else ""
    start_label = points[0]["label"] if "label" in points[0] else pretty_period(points[0]["period"])
    end_label = points[-1]["label"] if "label" in points[-1] else pretty_period(points[-1]["period"])
    return (
        f'<div class="chart-card"><h3>{title}</h3>'
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{aria}">'
        f"{grid}<polyline fill=\"none\" class=\"series\" points=\"{' '.join(coords)}\"/>"
        + "".join(dots)
        + f'<text class="axis" x="{left}" y="{height-8}">{start_label}</text>'
        f'<text class="axis" x="{width-right}" y="{height-8}" text-anchor="end">{end_label}</text>'
        "</svg></div>"
    )


def fan_chart(history: list[dict], forecast: list[dict]) -> str:
    points = history + forecast
    values = []
    for point in points:
        values.append(point["value"])
        if "low" in point:
            values.extend([point["low"], point["high"]])
    low, high = min(values), max(values)
    pad = max(0.25, (high - low) * 0.18)
    low, high = low - pad, high + pad
    width, height = 720, 320
    left, right, top, bottom = 44, 20, 18, 42
    plot_w, plot_h = width - left - right, height - top - bottom
    n = len(points)

    def x_at(i):
        return left + plot_w * (i + 0.5) / n

    def y_at(value):
        return top + plot_h * (1 - (value - low) / (high - low))

    bars = []
    labels = []
    for i, point in enumerate(points):
        x = x_at(i)
        y = y_at(point["value"])
        base = y_at(0)
        color = "#8eb6ff" if point.get("kind") == "history" else "#f6c453"
        if "low" in point:
            y0, y1 = y_at(point["high"]), y_at(point["low"])
            bars.append(f'<line x1="{x:.1f}" y1="{y0:.1f}" x2="{x:.1f}" y2="{y1:.1f}" class="whisker"/>')
            bars.append(f'<line x1="{x-8:.1f}" y1="{y0:.1f}" x2="{x+8:.1f}" y2="{y0:.1f}" class="whisker"/>')
            bars.append(f'<line x1="{x-8:.1f}" y1="{y1:.1f}" x2="{x+8:.1f}" y2="{y1:.1f}" class="whisker"/>')
        bar_y = min(y, base)
        bars.append(
            f'<rect x="{x-10:.1f}" y="{bar_y:.1f}" width="20" height="{abs(base-y):.1f}" rx="3" fill="{color}"/>'
        )
        anchor = "middle"
        label_y = y - 10 if point["value"] >= 0 else y + 16
        bars.append(f'<text class="direct" x="{x:.1f}" y="{label_y:.1f}" text-anchor="{anchor}">{signed_pct(point["value"])}</text>')
        if point.get("kind") == "nowcast" or i % 4 == 0:
            labels.append(f'<text class="axis" x="{x:.1f}" y="{height-12}" text-anchor="middle">{point["label"]}</text>')
    zero = y_at(0)
    return (
        '<div class="chart-card hero-chart"><h3>Economic growth, and the estimate for the next two quarters</h3>'
        '<p class="chart-note">Blue bars are the official figures. Amber bars are this page’s estimate. The range is the usual miss since 2023, not a 2020-sized shock.</p>'
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Quarterly economic growth and the estimate ahead">'
        f'<line x1="{left}" y1="{zero:.1f}" x2="{width-right}" y2="{zero:.1f}" class="zero"/>'
        + "".join(bars)
        + "".join(labels)
        + "</svg></div>"
    )


def bar_chart(
    rows: list[dict],
    value_key: str,
    label_key: str,
    title: str,
    aria: str,
    note: str = "",
    formatter=signed_pct,
    order: str = "asc",
) -> str:
    if not rows:
        return ""
    values = [_finite(row[value_key]) for row in rows]
    span = max(abs(v) for v in values if math.isfinite(v)) or 1
    width, height = 640, 36 * len(rows) + 24
    left, right = 168, 72
    plot_w = width - left - right
    all_positive = all(value >= 0 for value in values if math.isfinite(value))
    mid = left + plot_w / 2
    parts = [
        f'<div class="chart-card"><h3>{title}</h3>',
        f'<p class="chart-note">{note}</p>' if note else "",
        f'<svg class="bars" data-sorted="true" data-order="{order}" viewBox="0 0 {width} {height}" role="img" aria-label="{aria}">',
    ]
    for i, row in enumerate(rows):
        value = _finite(row[value_key])
        y = 16 + i * 36
        if all_positive:
            length = (value / span) * (plot_w - 8)
            x = left
            color = "#8eb6ff"
        else:
            length = (abs(value) / span) * (plot_w / 2 - 8)
            color = "#ff6d6d" if value < 0 else "#3ee0b0"
            x = mid - length if value < 0 else mid
        parts.append(
            f'<rect data-value="{value:.4f}" x="{x:.1f}" y="{y:.1f}" width="{length:.1f}" height="22" rx="4" fill="{color}"/>'
        )
        parts.append(f'<text class="bar-label" x="{left-10}" y="{y+16:.1f}" text-anchor="end">{row[label_key]}</text>')
        if value < 0 and not all_positive:
            label_x, anchor = mid + 8, "start"
        else:
            label_x, anchor = x + length + 6, "start"
        parts.append(
            f'<text class="direct" x="{label_x:.1f}" y="{y+16:.1f}" text-anchor="{anchor}">{formatter(value)}</text>'
        )
    parts.append("</svg></div>")
    return "".join(parts)


def gauge_svg(probability: float) -> str:
    probability = 0 if not math.isfinite(probability) else min(1.0, max(0.0, probability))
    angle = math.pi * (1 - probability)
    cx, cy, radius = 140, 132, 96
    x = cx + radius * math.cos(angle)
    y = cy - radius * math.sin(angle)
    color = _heat(probability)
    return (
        '<div class="chart-card gauge-card"><h3>Chance of two shrinking quarters in a row</h3>'
        '<svg viewBox="0 0 280 190" role="img" aria-label="Recession chance gauge">'
        f'<path d="M44,132 A96,96 0 0 1 236,132" fill="none" stroke="#243044" stroke-width="16" stroke-linecap="round"/>'
        f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="{color}" stroke-width="6" stroke-linecap="round"/>'
        f'<circle cx="{cx}" cy="{cy}" r="6" fill="{color}"/>'
        f'<text class="gauge-value" x="{cx}" y="86" text-anchor="middle">{odds(probability)}</text>'
        '<text class="axis" x="44" y="156">Low</text><text class="axis" x="236" y="156" text-anchor="end">High</text>'
        "</svg></div>"
    )


def kpi(label: str, value: str, take: str, status: str) -> str:
    return (
        f'<article class="kpi {status}"><p class="kicker">{label}</p>'
        f'<p class="value">{value}</p><p class="take">{take}</p></article>'
    )


def exact_table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{cell}</th>" for cell in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def sources_footer(sources: list[dict]) -> str:
    items = []
    for source in sources:
        if source["id"] == "natural-earth":
            continue
        items.append(
            f'<li><a href="{source.get("api") or source["url"]}">{source["title"]}</a> — {source["publisher"]}, {source["licence"]}</li>'
        )
    return (
        '<footer class="sources"><p>Figures checked against the publishers’ releases. '
        "Map boundaries are Natural Earth, public domain.</p><ul>"
        + "".join(items)
        + "</ul></footer>"
    )


def render(payload: dict) -> str:
    view = build_view(payload)
    anchors = view["anchors"]
    signals = view["signals"]
    prob = view["probability"]
    est = view["estimate"]
    q1 = pretty_period(view["quarters"]["first"])
    q2 = pretty_period(view["quarters"]["second"])
    job_change = view["job_change"]
    states = sorted(view["states"], key=lambda row: _finite(row["pressure"]), reverse=True)
    weakest = states[0]
    industries = view["industries"]
    weakest_industry = industries[0] if industries else {"name": "—", "sales_qoq": float("nan")}
    strongest_industry = max(industries, key=lambda row: row["sales_qoq"]) if industries else weakest_industry
    short_name = {
        "Arts and recreation": "Arts",
        "Professional services": "Prof. services",
        "Other services": "Other",
    }
    shrinking = sum(1 for row in industries if row["sales_qoq"] < 0)

    kpis_odds = "".join(
        [
            kpi("Two shrinking quarters", odds(prob["technical"]), "Chance the next two GDP prints are both negative.", status_for("recession", prob["technical"])),
            kpi(f"{q1} growth", signed_pct(est["first"]), "Estimate for the quarter the Bureau publishes on 2 December.", status_for("growth", est["first"])),
            kpi(f"{q2} growth", signed_pct(est["second"]), "A first look at the December quarter, with less information.", status_for("growth", est["second"])),
            kpi("Unemployment", pct(anchors["unemployment_oct_2026"]), "October, the highest since 2021. It was 4.7% in September.", "bad"),
            kpi("Cash rate", pct(anchors["cash_rate_target"], 2), "Set on 3 November. The next decision is 8 December.", "warn"),
        ]
    )
    kpis_states = "".join(
        [
            kpi("Most pressure", weakest["short"], f"{weakest['name']} ranks highest on jobs, unemployment, demand and housing.", "bad"),
            kpi("Jobs, October", people(job_change), "Change in employed people from September, Australia.", "bad" if job_change < 0 else "ok"),
            kpi("Highest unemployment", max(states, key=lambda row: _finite(row["unemp"]))["short"], "Among the states and territories, using the latest month.", "warn"),
            kpi("Weakest demand", min(states, key=lambda row: _finite(row["sfd_qoq"], 99))["short"], "State final demand in the June quarter.", "warn"),
        ]
    )
    kpis_industry = "".join(
        [
            kpi("Softest sales", short_name.get(weakest_industry["name"], weakest_industry["name"]), f"{weakest_industry['name']} sales volumes, June quarter, {signed_pct(weakest_industry['sales_qoq'])}.", "bad" if weakest_industry["sales_qoq"] < 0 else "warn"),
            kpi("Strongest sales", short_name.get(strongest_industry["name"], strongest_industry["name"]), f"{strongest_industry['name']} sales volumes, June quarter, {signed_pct(strongest_industry['sales_qoq'])}.", "ok"),
            kpi("Industries shrinking", str(shrinking), f"Out of {len(industries)} industry groups in the June quarter.", "warn" if shrinking else "ok"),
            kpi("Household spending", signed_pct(signals.get("hsi_mom")), "September, compared with August. Still rising.", status_for("growth", _finite(signals.get("hsi_mom")))),
        ]
    )
    sahm = _finite(signals.get("sahm_gap"))
    spread = _finite(signals.get("yield_spread"))
    kpis_watch = "".join(
        [
            kpi("Unemployment gap", signed_pct(sahm).replace("%", " pts"), "How far unemployment sits above its low of the past year.", status_for("gap", sahm)),
            kpi("Bond gap", signed_pct(spread).replace("%", " pts"), "Ten-year yield minus two-year yield. Still positive.", status_for("spread", spread)),
            kpi("Youth unemployment", pct(anchors["youth_unemployment_oct_2026"]), "People aged 15 to 24. The highest since 2021.", "bad"),
            kpi("Inflation", pct(anchors["cpi_annual_sep_2026"]), "Consumer prices in the year to September. Target is 2–3%.", "bad"),
            kpi("Next GDP release", "2 Dec", "11:30 am Melbourne time. September quarter.", "warn"),
        ]
    )

    unemp_points = [
        {"period": point["period"], "label": pretty_period(point["period"]), "value": point["value"]}
        for point in signals.get("unemp_path", [])
    ]
    spread_points = [
        {"period": point["period"], "label": pretty_period(point["period"]), "value": point["value"]}
        for point in signals.get("spread_path", [])
    ]
    spend_points = [
        {"period": point["period"], "label": pretty_period(point["period"]), "value": point["value"]}
        for point in signals.get("hsi_path", [])
    ]
    approval_points = [
        {"period": point["period"], "label": pretty_period(point["period"]), "value": point["value"]}
        for point in signals.get("approvals_path", [])
    ]
    pc_points = [
        {"period": point["period"], "label": pretty_period(point["period"]), "value": point["value"]}
        for point in view["pc_history"]
    ] + view["pc_forecast"]

    jobs_sorted = sorted(states, key=lambda row: _finite(row["jobs_3m_pct"]))
    unemp_sorted = sorted(states, key=lambda row: _finite(row["unemp"]), reverse=True)
    demand_sorted = sorted(states, key=lambda row: _finite(row["sfd_qoq"]))
    industry_sorted = sorted(industries, key=lambda row: row["sales_qoq"])

    state_rows = [
        [
            row["name"],
            signed_pct(row["jobs_3m_pct"]),
            pct(row["unemp"]),
            signed_pct(row["unemp_change"]),
            signed_pct(row["sfd_qoq"]),
            signed_pct(row["approvals_yoy"]),
            f"{round_half_up(_finite(row['pressure']), 0):.0f}",
            "Smoothed official count" if row["short"] in {"NT", "ACT"} else "Adjusted for the time of year",
        ]
        for row in states
    ]
    industry_rows = [[row["name"], pretty_period(row["quarter"]), signed_pct(row["sales_qoq"])] for row in industry_sorted]
    growth_rows = [
        [point["label"], signed_pct(point["value"]), "Official"]
        for point in view["history"]
    ] + [
        [point["label"], f"{signed_pct(point['value'])} ({signed_pct(point['low'])} to {signed_pct(point['high'])})", "Estimate"]
        for point in view["forecast"]
    ]

    means = (
        f"The estimate is {signed_pct(est['first'])} for {q1} and {signed_pct(est['second'])} for {q2}. "
        f"The chance {q1} shrinks is {odds(prob['first'])}. The chance {q2} shrinks is {odds(prob['second'])}, "
        f"because that estimate sits close to zero. The chance both shrink is {odds(prob['technical'])}. "
        f"Per person, the estimates are {signed_pct(est['pc_first'])} and {signed_pct(est['pc_second'])}, "
        f"and the chance both of those are negative is {odds(prob['technical_pc'])}. "
        f"A second check, using whether similar quarters in the past actually shrank, "
        f"puts the chance the next GDP print is negative at only {odds(prob['logit'])}. "
        "Westpac’s published note of 20 November put September-quarter growth near 0.5%, "
        "the chance of a shrinking December quarter at 30%, and the chance of two shrinking quarters at 5 to 6%. "
        "Those are their figures, not this page’s."
    )
    state_means = (
        f"{weakest['name']} is where the strain shows up first on this scorecard: "
        f"jobs {signed_pct(weakest['jobs_3m_pct'])} over three months, unemployment {pct(weakest['unemp'])}, "
        f"and June-quarter demand {signed_pct(weakest['sfd_qoq'])}. "
        "October’s job losses were spread across several states, so a national average hides the patchiness. "
        "Northern Territory and the ACT use the Bureau’s smoothed jobs count, because it does not publish the same adjusted series there."
    )
    industry_means = (
        f"In the June quarter, {weakest_industry['name'].lower()} sales volumes moved {signed_pct(weakest_industry['sales_qoq'])} "
        f"and {strongest_industry['name'].lower()} moved {signed_pct(strongest_industry['sales_qoq'])}. "
        f"{shrinking} of {len(industries)} industry groups shrank. "
        "That quarter was not a collapse. The sharper turn is the jobs report that came after it."
    )
    watch_means = (
        f"Unemployment is {signed_pct(sahm).replace('%', ' points')} above its low of the past year. "
        f"Longer-term government bond yields are still {signed_pct(spread).replace('%', ' points')} above shorter-term yields, "
        "so the bond market is not signalling a recession the way an inverted gap would. "
        "Inflation at 4.3% is why the cash rate is 4.85% even as hiring falls. "
        "The September-quarter national accounts, out on 2 December, are the next number that can settle the argument."
    )

    page = f"""<!DOCTYPE html>
<html lang="en-AU">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Recession watch · Australia</title>
<style>
:root {{
  --bg:#0c121b; --card:#151d2b; --line:#2c3a50; --text:#eef3f8; --muted:#9aabc2;
  --teal:#3ee0b0; --amber:#f6c453; --red:#ff6d6d; --blue:#8eb6ff;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:16px/1.45 "Avenir Next","Segoe UI","Helvetica Neue",sans-serif; }}
a {{ color:var(--blue); }}
.top {{ position:sticky; top:0; z-index:5; display:flex; gap:12px; align-items:center; justify-content:space-between;
  padding:10px 18px; background:#101826ee; border-bottom:1px solid var(--line); backdrop-filter:blur(8px); max-width:100%; }}
.brand {{ font-weight:700; letter-spacing:.01em; flex:0 0 auto; }}
.brand span {{ color:var(--muted); font-weight:500; }}
.tabs {{ display:flex; gap:6px; overflow-x:auto; min-width:0; flex:1 1 auto; }}
.tabs button {{ background:transparent; color:var(--muted); border:1px solid transparent; border-radius:999px; padding:6px 12px; font:inherit; cursor:pointer; white-space:nowrap; }}
.tabs button.active {{ color:var(--text); border-color:var(--line); background:#1c2738; }}
.clock {{ color:var(--muted); font-size:13px; white-space:nowrap; }}
details:not([open]) > *:not(summary) {{ display:none !important; }}
main {{ max-width:1120px; margin:0 auto; padding:18px; }}
.banner {{ background:linear-gradient(180deg,#1a2433,#141c2a); border:1px solid var(--line); border-radius:16px; padding:18px 18px 14px; margin-bottom:14px; }}
.banner h1 {{ margin:0 0 6px; font-size:clamp(1.45rem, 2.4vw, 2rem); line-height:1.2; }}
.banner p {{ margin:0; color:var(--muted); max-width:70ch; }}
.kpis {{ display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:10px; margin:12px 0; }}
.kpi {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:12px 12px 10px; min-width:0; }}
.kpi .kicker {{ margin:0; color:var(--muted); font-size:13px; }}
.kpi .value {{ margin:4px 0; font-size:clamp(1.35rem, 2.2vw, 2.05rem); font-weight:720; letter-spacing:-.03em; white-space:nowrap; line-height:1.1; }}
.kpi .take {{ margin:0; color:var(--muted); font-size:13.5px; }}
.kpi.bad .value {{ color:var(--red); }}
.kpi.warn .value {{ color:var(--amber); }}
.kpi.ok .value {{ color:var(--teal); }}
.hero {{ display:grid; grid-template-columns:280px 1fr; gap:12px; }}
.grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:12px; }}
.chart-card, .means, details {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:12px 14px; }}
.chart-card h3, .means h2 {{ margin:0 0 4px; font-size:1.02rem; }}
.chart-note, .means p {{ color:var(--muted); margin:4px 0 8px; }}
svg {{ width:100%; height:auto; display:block; }}
.series {{ stroke:var(--blue); stroke-width:2.5; }}
.zero {{ stroke:#3d4d66; stroke-width:1; }}
.whisker {{ stroke:var(--amber); stroke-width:2; }}
.direct {{ fill:var(--text); font-size:12px; }}
.axis, .bar-label, .map-label {{ fill:var(--muted); font-size:12px; }}
.map-label {{ fill:var(--text); font-size:13px; font-weight:650; }}
.leader {{ stroke:var(--muted); stroke-width:1; }}
.state {{ stroke:#0c121b; stroke-width:1.2; }}
.gauge-value {{ fill:var(--text); font-size:42px; font-weight:720; }}
.pills {{ display:flex; gap:8px; flex-wrap:wrap; margin:8px 0 0; }}
.pills button {{ background:#1c2738; color:var(--text); border:1px solid var(--line); border-radius:999px; padding:6px 12px; font:inherit; cursor:pointer; }}
.pills button.active {{ border-color:var(--blue); }}
.means {{ margin-top:12px; }}
details {{ margin-top:12px; }}
details summary {{ cursor:pointer; font-weight:650; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; margin-top:8px; }}
th, td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); white-space:nowrap; }}
th {{ color:var(--muted); font-weight:600; }}
.sources {{ color:var(--muted); font-size:13px; margin-top:16px; }}
.sources ul {{ padding-left:18px; }}
@media (max-width:980px) {{
  .kpis {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
  .hero, .grid-2 {{ grid-template-columns:1fr; }}
  .top {{ flex-wrap:wrap; }}
  .clock {{ flex-basis:100%; white-space:normal; }}
}}
@media (max-width:560px) {{
  main {{ padding:12px; }}
  .kpi .take {{ font-size:13px; }}
  th, td {{ white-space:normal; }}
}}
</style>
</head>
<body>
<header class="top">
  <div class="brand">Recession watch <span>Australia</span></div>
  <nav class="tabs" aria-label="Sections">
    <button type="button" class="active" data-tab="odds">Recession odds</button>
    <button type="button" data-tab="states">States</button>
    <button type="button" data-tab="industries">Industries</button>
    <button type="button" data-tab="watch">Early warnings</button>
  </nav>
  <div class="clock" id="clock">{view["created_label"]}</div>
</header>
<main>
<section class="page" id="odds">
  <div class="banner"><h1>{view["headline"]}</h1><p>{view["detail"]}</p></div>
  <div class="kpis">{kpis_odds}</div>
  <div class="hero">{gauge_svg(prob["technical"])}{fan_chart(view["history"], view["forecast"])}</div>
  <div class="grid-2">
    {line_chart(pc_points, "Growth per person is weaker than growth for the economy", "Growth per person", True)}
    {line_chart(unemp_points, "Unemployment has climbed through 2026", "Unemployment rate", False, formatter=pct)}
  </div>
  <div class="grid-2">
    {line_chart(spread_points, "Longer-term bond yields are still above shorter-term yields", "Bond yield gap", True)}
    <div class="means"><h2>What this means</h2><p>{means}</p>
      <p>Official September-quarter GDP is due {view["next_release"]}. Until then, treat the amber bars as an estimate with a wide range, not as a fact.</p></div>
  </div>
  <details><summary>Exact values</summary>
    {exact_table(["Quarter","Growth","Status"], growth_rows)}
    <p class="chart-note">Per person: {q1} {signed_pct(est["pc_first"])}, {q2} {signed_pct(est["pc_second"])}. Chance each quarter shrinks: {q1} {odds(prob["first"])}, {q2} {odds(prob["second"])}. Chance both per-person figures are negative: {odds(prob["technical_pc"])}.</p>
  </details>
  {sources_footer(view["sources"])}
</section>
<section class="page" id="states" hidden>
  <div class="banner"><h1>The strain is not spread evenly</h1><p>October’s job losses and the June-quarter demand figures do not point at the same state. The map colours a simple pressure score that uses both.</p></div>
  <div class="kpis">{kpis_states}</div>
  <div class="chart-card">
    <h3>Where pressure is highest</h3>
    <div class="pills" id="map-pills">
      <button type="button" class="active" data-metric="pressure">Pressure</button>
      <button type="button" data-metric="jobs">Jobs</button>
      <button type="button" data-metric="unemp">Unemployment</button>
      <button type="button" data-metric="demand">Demand</button>
    </div>
    {map_svg(states)}
  </div>
  <div class="grid-2">
    {bar_chart(jobs_sorted, "jobs_3m_pct", "short", "Jobs over the past three months", "Employment change by state, weakest first")}
    {bar_chart(unemp_sorted, "unemp", "short", "Unemployment in the latest month", "Unemployment by state, highest first", "Sorted from highest to lowest.", formatter=pct, order="desc")}
  </div>
  {bar_chart(demand_sorted, "sfd_qoq", "short", "State demand in the June quarter", "State final demand, weakest first")}
  <div class="means"><h2>What this means</h2><p>{state_means}</p></div>
  <details><summary>Exact values</summary>
    {exact_table(["State","Jobs, 3 months","Unemployment","Unemployment change","June demand","Home approvals, year","Pressure","Jobs series"], state_rows)}
  </details>
  {sources_footer(view["sources"])}
</section>
<section class="page" id="industries" hidden>
  <div class="banner"><h1>June sales were soft in a few industries, not across the board</h1><p>Business sales volumes are the latest full industry picture. They stop in June. The jobs report is newer, and it is weaker.</p></div>
  <div class="kpis">{kpis_industry}</div>
  {bar_chart(industry_sorted, "sales_qoq", "name", "Sales volumes in the June quarter", "Industry sales growth, weakest first", "Sorted from the weakest industry to the strongest.")}
  <div class="grid-2">
    {line_chart(spend_points, "Household spending is still up on three months earlier", "Household spending, three-month change", True)}
    {line_chart(approval_points, "New home approvals compared with a year earlier", "Dwelling approvals, year change", True)}
  </div>
  <div class="means"><h2>What this means</h2><p>{industry_means}</p></div>
  <details><summary>Exact values</summary>
    {exact_table(["Industry","Quarter","Sales volume change"], industry_rows)}
  </details>
  {sources_footer(view["sources"])}
</section>
<section class="page" id="watch" hidden>
  <div class="banner"><h1>Watch jobs and the 2 December GDP release</h1><p>Hiring has turned down while inflation is still too high for the Reserve Bank to relax. The bond market has not confirmed a recession.</p></div>
  <div class="kpis">{kpis_watch}</div>
  <div class="grid-2">
    {line_chart(unemp_points, "The unemployment rate is the early warning that has already moved", "Unemployment rate path", False, formatter=pct)}
    {line_chart(spread_points, "The gap between long and short bond yields is still positive", "Yield gap", True)}
  </div>
  <div class="means"><h2>What this means</h2><p>{watch_means}</p></div>
  <details><summary>Exact values</summary>
    {exact_table(["Signal","Latest"], [
      ["Unemployment, October", pct(anchors["unemployment_oct_2026"])],
      ["Unemployment, September", "4.7%"],
      ["Youth unemployment, October", pct(anchors["youth_unemployment_oct_2026"])],
      ["Employed people, change in October", people(job_change)],
      ["Cash rate target", pct(anchors["cash_rate_target"], 2)],
      ["Inflation, year to September", pct(anchors["cpi_annual_sep_2026"])],
      ["Household spending, September vs August", signed_pct(signals.get("hsi_mom"))],
      ["Unemployment gap vs past-year low", f"{signed_pct(sahm).replace('%',' points')}"],
      ["10-year yield minus 2-year yield", f"{signed_pct(spread).replace('%',' points')}"],
      ["Chance next GDP print is negative, jobs-and-rates check", odds(prob["logit"])],
    ])}
  </details>
  {sources_footer(view["sources"])}
</section>
</main>
<script>
const zone = "Australia/Melbourne";
function tick() {{
  const label = new Intl.DateTimeFormat("en-AU", {{
    timeZone: zone, day:"numeric", month:"short", year:"numeric",
    hour:"numeric", minute:"2-digit", hour12:true, timeZoneName:"short"
  }}).format(new Date());
  const node = document.getElementById("clock");
  node.textContent = label.replace("am","am").replace("pm","pm") + " · data as at {view["created_label"]}";
}}
tick();
setInterval(tick, 30000);
document.querySelectorAll(".tabs button").forEach((button) => {{
  button.addEventListener("click", () => {{
    document.querySelectorAll(".tabs button").forEach((item) => item.classList.toggle("active", item === button));
    document.querySelectorAll(".page").forEach((page) => {{ page.hidden = page.id !== button.dataset.tab; }});
  }});
}});
function heat(t) {{
  t = Math.min(1, Math.max(0, t));
  const stops = [[31,138,112],[246,196,83],[255,93,93]];
  const pair = t < 0.5 ? [stops[0], stops[1], t / 0.5] : [stops[1], stops[2], (t - 0.5) / 0.5];
  const rgb = pair[0].map((channel, i) => Math.round(channel + (pair[1][i] - channel) * pair[2]));
  return "rgb(" + rgb.join(",") + ")";
}}
document.querySelectorAll("#map-pills button").forEach((button) => {{
  button.addEventListener("click", () => {{
    document.querySelectorAll("#map-pills button").forEach((item) => item.classList.toggle("active", item === button));
    const metric = button.dataset.metric;
    document.querySelectorAll(".state").forEach((shape) => {{
      const jobs = parseFloat(shape.dataset.jobs);
      const unemp = parseFloat(shape.dataset.unemp);
      const demand = parseFloat(shape.dataset.demand);
      let t = parseFloat(shape.dataset.pressure);
      if (metric === "jobs") t = Math.min(1, Math.max(0, 0.5 - jobs / 4));
      if (metric === "unemp") t = Math.min(1, Math.max(0, (unemp - 3.5) / 2.5));
      if (metric === "demand") t = Math.min(1, Math.max(0, 0.5 - demand / 3));
      shape.setAttribute("fill", heat(t));
    }});
  }});
}});
</script>
</body>
</html>
"""
    return page


def write_site(payload: dict, directory: Path | None = None) -> Path:
    directory = directory or (ROOT / "site")
    directory.mkdir(parents=True, exist_ok=True)
    html = render(payload)
    path = directory / "index.html"
    path.write_text(html)
    (directory / "dashboard.json").write_text(json.dumps(_public_json(payload), indent=2, default=str))
    return path


def _public_json(payload: dict) -> dict:
    """A small JSON companion for tests. Drops bulky backtest rows."""
    return {
        "created_at_utc": payload["created_at_utc"],
        "anchors": payload["anchors"],
        "nowcast": payload["nowcast"].get("points"),
        "scores": payload["scores"],
        "states": payload["states"],
        "industries": payload["industries"],
        "signals": {key: value for key, value in payload["signals"].items() if not key.endswith("_path") and not key.endswith("_history")},
        "benchmark": payload["benchmark"],
    }
