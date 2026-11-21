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


def _projected(ring: list) -> list[tuple[float, float]]:
    return [_project(lon, lat) for lon, lat in ring]


def _contains(x: float, y: float, pts: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(pts) - 1
    for i, (xi, yi) in enumerate(pts):
        xj, yj = pts[j]
        if (yi > y) != (yj > y):
            cross = (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
            if x < cross:
                inside = not inside
        j = i
    return inside


def _label_box(x: float, y: float, text: str) -> tuple[float, float, float, float]:
    """Baseline-centred box, wide enough for Avenir Next as well as the fallback font."""
    half = len(text) * 9.2 / 2 + 3
    return x - half, y - 14, x + half, y + 5


def _box_inside(box: tuple[float, float, float, float], pts: list[tuple[float, float]]) -> bool:
    x0, y0, x1, y1 = box
    for px in (x0 + 1, (x0 + x1) / 2, x1 - 1):
        for py in (y0 + 1, (y0 + y1) / 2, y1 - 1):
            if not _contains(px, py, pts):
                return False
    return True


def _box_clear(box: tuple[float, float, float, float], rings: list[list[tuple[float, float]]]) -> bool:
    x0, y0, x1, y1 = box
    samples = [
        (x0, y0),
        (x1, y0),
        (x0, y1),
        (x1, y1),
        ((x0 + x1) / 2, (y0 + y1) / 2),
        ((x0 + x1) / 2, y0),
        ((x0 + x1) / 2, y1),
        (x0, (y0 + y1) / 2),
        (x1, (y0 + y1) / 2),
    ]
    return all(not any(_contains(px, py, ring) for ring in rings) for px, py in samples)


def _refine_label(
    x: float,
    y: float,
    text: str,
    pts: list[tuple[float, float]],
) -> tuple[float, float]:
    """Prefer a spot whose label still fits if the type is a little wider."""

    def fits(px: float, py: float) -> bool:
        left, top, right, bottom = _label_box(px, py, text)
        return _box_inside((left - 3, top - 2, right + 3, bottom + 2), pts)

    if fits(x, y):
        return x, y
    best = None
    best_distance = float("inf")
    for dx in range(-20, 22, 2):
        for dy in range(-16, 18, 2):
            distance = dx * dx + dy * dy
            if distance < best_distance and fits(x + dx, y + dy):
                best = (x + dx, y + dy)
                best_distance = distance
    return best or (x, y)


def _place_state_label(
    short: str,
    pts: list[tuple[float, float]],
    rings: list[list[tuple[float, float]]],
) -> tuple[float, float, tuple[float, float] | None]:
    """Return a baseline point inside the state, or a leader target outside it."""
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    for radius in [0, *range(8, 120, 8)]:
        steps = 1 if radius == 0 else 20
        for step in range(steps):
            angle = (step / steps) * math.tau - math.pi / 2
            x = cx + math.cos(angle) * radius
            y = cy + math.sin(angle) * radius * 0.85
            if _box_inside(_label_box(x, y, short), pts):
                refined = _refine_label(x, y, short, pts)
                return refined[0], refined[1], None
    view_w, view_h = 820.0, 640.0
    best = None
    best_distance = float("inf")
    for y in range(40, int(view_h) - 24, 8):
        for x in range(40, int(view_w) - 24, 8):
            box = _label_box(x, y, short)
            if box[0] < 8 or box[1] < 8 or box[2] > view_w - 8 or box[3] > view_h - 8:
                continue
            if not _box_clear(box, rings):
                continue
            distance = (x - cx) ** 2 + (y - cy) ** 2
            if distance < best_distance:
                best_distance = distance
                best = (float(x), float(y))
    if best is None:
        best = (min(view_w - 36, cx + 48), min(view_h - 20, cy + 28))
    return best[0], best[1], (cx, cy)


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
    prepared = []
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
        prepared.append((short, _projected(ring)))
    all_rings = [pts for _, pts in prepared]
    labels = []
    for short, pts in prepared:
        x, y, leader = _place_state_label(short, pts, all_rings)
        if leader is not None:
            # Stop the leader at the label box so the stroke does not cross the letters.
            half = len(short) * 9.2 / 2 + 6
            labels.append(
                f'<line x1="{leader[0]:.1f}" y1="{leader[1]:.1f}" x2="{x - half:.1f}" y2="{y - 4:.1f}" class="leader"/>'
            )
        labels.append(f'<text class="map-label" x="{x:.1f}" y="{y:.1f}" text-anchor="middle">{short}</text>')
    return (
        '<svg class="map" viewBox="0 0 820 640" role="img" aria-label="Australia, states coloured by pressure">'
        + "".join(shapes)
        + "".join(labels)
        + "</svg>"
    )


def _period_parts(token: str) -> tuple[int, int]:
    cleaned = (token or "").replace("-", "")
    if "Q" in cleaned:
        year, quarter = cleaned.split("Q", 1)
        if year.isdigit() and quarter.isdigit():
            return int(year), int(quarter) * 3
    if len(cleaned) >= 6 and cleaned[:4].isdigit() and cleaned[4:6].isdigit():
        return int(cleaned[:4]), int(cleaned[4:6])
    return 0, 0


def _digits(step: float) -> int:
    if abs(step - round(step)) > 1e-6:
        return 1 if step >= 0.1 else 2
    if step >= 1:
        return 0
    if step >= 0.1:
        return 1
    return 2


def _nice_ticks(low: float, high: float) -> list[float]:
    span = high - low
    if span <= 0:
        return [low]

    def step_for(target: int) -> float:
        raw = span / target
        magnitude = 10 ** math.floor(math.log10(raw))
        residual = raw / magnitude
        if residual <= 1:
            nice = 1
        elif residual <= 2:
            nice = 2
        elif residual <= 2.5:
            nice = 2.5
        elif residual <= 5:
            nice = 5
        else:
            nice = 10
        return nice * magnitude

    def build(step: float) -> list[float]:
        start = math.ceil((low - step * 1e-8) / step) * step
        values = []
        cursor = start
        for _ in range(16):
            if cursor > high + step * 1e-6:
                break
            if low - step * 1e-6 <= cursor <= high + step * 1e-6:
                values.append(round(cursor, 6))
            cursor += step
        return values

    step = step_for(4)
    values = build(step)
    if len(values) > 5:
        step *= 2
        values = build(step)
    if len(values) < 3:
        step /= 2
        values = build(step)
    if len(values) > 5:
        values = [values[0], values[len(values) // 2], values[-1]]
    return values


def _point_label(point: dict) -> str:
    return point["label"] if point.get("label") else pretty_period(point.get("period", ""))


def _x_tick_indices(points: list[dict]) -> list[int]:
    parsed = [_period_parts(point.get("period", "")) for point in points]
    if any(year == 0 for year, _month in parsed):
        middle = len(points) // 2
        return sorted({0, middle, len(points) - 1})
    span = (parsed[-1][0] - parsed[0][0]) * 12 + (parsed[-1][1] - parsed[0][1])
    indices: list[int] = []
    if span > 27:
        seen_years: list[int] = []
        for _index, (year, _month) in enumerate(parsed):
            if year not in seen_years:
                seen_years.append(year)
        for year in seen_years:
            group = [index for index, (item_year, _month) in enumerate(parsed) if item_year == year]
            # July keeps neighbouring year labels about twelve months apart.
            best = min(group, key=lambda index: (abs(parsed[index][1] - 7), index))
            indices.append(best)
    else:
        anchors = (1, 4, 7, 10) if any(month in (1, 4, 7, 10) for _year, month in parsed) else (3, 6, 9, 12)
        seen: set[tuple[int, int]] = set()
        for index, (year, month) in enumerate(parsed):
            if month not in anchors:
                continue
            key = (year, (month - 1) // 3)
            if key in seen:
                continue
            seen.add(key)
            indices.append(index)
    return indices


def line_chart(points: list[dict], title: str, aria: str, zero: bool = True, formatter=signed_pct) -> str:
    values = [p["value"] for p in points if p.get("value") is not None and math.isfinite(p["value"])]
    if len(values) < 2:
        return f'<div class="chart-card"><h3>{title}</h3><p>Not enough history.</p></div>'
    low, high = min(values + ([0] if zero else [])), max(values + ([0] if zero else []))
    pad = max(0.15, (high - low) * 0.08)
    low, high = low - pad, high + pad
    ticks = _nice_ticks(low, high)
    if ticks:
        low = min(low, ticks[0])
        high = max(high, ticks[-1])
    # Room above and below the series so the end labels sit inside the plot, off the line.
    width, height = 640, 300
    left, right, top, bottom = 72, 20, 12, 42
    plot_w, plot_h = width - left - right, height - top - bottom
    label_room, bottom_room = 36, 24
    span = high - low or 1

    def y_at(value: float) -> float:
        usable_top = top + label_room
        usable_h = plot_h - label_room - bottom_room
        return usable_top + usable_h * (1 - (value - low) / span)

    def xy(i: int, value: float) -> tuple[float, float]:
        x = left + plot_w * i / (len(points) - 1)
        return x, y_at(value)

    parts: list[str] = []
    step = abs(ticks[1] - ticks[0]) if len(ticks) > 1 else 1
    for tick in ticks:
        y = y_at(tick)
        if y < top + 8 or y > height - bottom - 8:
            continue
        parts.append(f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{width - right:.1f}" y2="{y:.1f}"/>')
        parts.append(
            f'<text class="axis" x="{left - 8}" y="{y:.1f}" text-anchor="end" dominant-baseline="middle">'
            f"{formatter(tick, _digits(step))}</text>"
        )
    if zero and low < 0 < high:
        zero_y = y_at(0)
        parts.append(
            f'<line class="zero" x1="{left}" y1="{zero_y:.1f}" x2="{width - right:.1f}" y2="{zero_y:.1f}"/>'
        )
    series: list[tuple[float, float]] = []
    coords = []
    for index, point in enumerate(points):
        x, y = xy(index, point["value"])
        series.append((x, y))
        coords.append(f"{x:.1f},{y:.1f}")
    parts.append(f'<polyline fill="none" class="series" points="{" ".join(coords)}"/>')

    def _tick_choices(point: dict) -> list[str]:
        full = _point_label(point)
        parts_of = full.split()
        if len(parts_of) == 2 and len(parts_of[1]) == 4 and parts_of[1].isdigit():
            short = f"{parts_of[0]} {parts_of[1][2:]}"
            first = _period_parts(points[0].get("period", ""))
            last = _period_parts(points[-1].get("period", ""))
            span_months = (last[0] - first[0]) * 12 + (last[1] - first[1])
            # Under about two years, "Oct 24" fits a quarterly tick. Longer series use the full month or the year.
            if span_months <= 27:
                return [short]
            return [full, parts_of[1]]
        return [full]

    placed: list[tuple[float, float]] = []
    used_labels: set[str] = set()
    for index in _x_tick_indices(points):
        x, _y = xy(index, points[index]["value"])
        drawn = None
        for label in _tick_choices(points[index]):
            if label in used_labels:
                continue
            text_w = len(label) * 9.2
            anchor = "middle"
            edge_l, edge_r = x - text_w / 2, x + text_w / 2
            if edge_l < 2:
                anchor, edge_l, edge_r = "start", x, x + text_w
            if edge_r > width - 2:
                anchor, edge_l, edge_r = "end", x - text_w, x
            if any(not (edge_r < kept_l - 8 or edge_l > kept_r + 8) for kept_l, kept_r in placed):
                continue
            drawn = (label, anchor, edge_l, edge_r)
            break
        if drawn is None:
            continue
        label, anchor, edge_l, edge_r = drawn
        placed.append((edge_l, edge_r))
        used_labels.add(label)
        parts.append(
            f'<text class="axis" x="{x:.1f}" y="{height - 14}" text-anchor="{anchor}">{label}</text>'
        )

    def _line_hits(box: tuple[float, float, float, float], pad: float = 6) -> bool:
        x0, y0, x1, y1 = box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad
        for (ax, ay), (bx, by) in zip(series, series[1:]):
            if max(ax, bx) < x0 or min(ax, bx) > x1:
                continue
            for step_index in range(11):
                sample = step_index / 10
                sx = ax + (bx - ax) * sample
                sy = ay + (by - ay) * sample
                if x0 <= sx <= x1 and y0 <= sy <= y1:
                    return True
        return False

    def callout(index: int) -> str:
        x, y = series[index]
        text = formatter(points[index]["value"])
        text_w = max(28.0, len(text) * 9.2)
        ascent, descent = 15.0, 5.0
        other = 1 if index == 0 else index - 1
        _ox, oy = series[other]
        signs = (-1, 1) if oy >= y else (1, -1)
        plot_left, plot_right = float(left), float(width - right)
        plot_top, plot_bottom = float(top), float(height - bottom)
        chosen = None
        for sign in signs:
            for gap in (20, 32, 46, 60):
                for shift in (10, 28, 46):
                    baseline = y + sign * gap
                    if index == 0:
                        anchor = "start"
                        lx = min(max(x + shift, plot_left), plot_right - text_w)
                        box = (lx, baseline - ascent, lx + text_w, baseline + descent)
                    else:
                        anchor = "end"
                        lx = max(min(x - shift, plot_right), plot_left + text_w)
                        box = (lx - text_w, baseline - ascent, lx, baseline + descent)
                    inside = (
                        box[0] >= plot_left - 0.5
                        and box[2] <= plot_right + 0.5
                        and box[1] >= plot_top
                        and box[3] <= plot_bottom
                    )
                    if inside and not _line_hits(box):
                        chosen = (lx, baseline, anchor)
                        break
                if chosen:
                    break
            if chosen:
                break
        if chosen is None:
            anchor = "start" if index == 0 else "end"
            lx = x + 10 if index == 0 else x - 10
            baseline = min(plot_bottom - descent, max(plot_top + ascent, y - 20))
            chosen = (lx, baseline, anchor)
        lx, baseline, anchor = chosen
        return (
            f'<text class="direct end-label" x="{lx:.1f}" y="{baseline:.1f}" text-anchor="{anchor}">{text}</text>'
        )

    parts.append(callout(0))
    parts.append(callout(len(points) - 1))
    return (
        f'<div class="chart-card"><h3>{title}</h3>'
        f'<svg class="line-chart" viewBox="0 0 {width} {height}" role="img" aria-label="{aria}" '
        f'data-plot-left="{left}" data-plot-top="{top}" data-plot-right="{width - right}" '
        f'data-plot-bottom="{height - bottom}">'
        f'<rect class="plot-bounds" x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" fill="none"/>'
        + "".join(parts)
        + "</svg></div>"
    )


def _estimate_axis_label(label: str) -> str:
    parts = label.split()
    if len(parts) == 2 and len(parts[1]) == 4 and parts[1].isdigit():
        return f"{parts[0]} {parts[1][2:]} (est)"
    return f"{label} (est)"


def fan_chart(history: list[dict], forecast: list[dict]) -> str:
    points = history + forecast
    values = []
    for point in points:
        values.append(point["value"])
        if "low" in point:
            values.extend([point["low"], point["high"]])
    low, high = min(values), max(values)
    pad = max(0.2, (high - low) * 0.16)
    low, high = low - pad, high + pad
    # Forecast slots are wider than history slots so "Sep 26 (est)" and "Dec 26 (est)" do not collide.
    width, height = 920, 372
    left, right, top, bottom = 28, 22, 8, 56
    plot_w, plot_h = width - left - right, height - top - bottom
    n_history = len(history)
    forecast_pitch = 118
    history_pitch = (plot_w - forecast_pitch * len(forecast)) / max(n_history, 1)
    label_room = 28
    span = high - low or 1

    def x_at(i: int) -> float:
        if i < n_history:
            return left + history_pitch * (i + 0.5)
        return left + history_pitch * n_history + forecast_pitch * (i - n_history + 0.5)

    def y_at(value: float) -> float:
        usable_top = top + label_room
        usable_h = plot_h - label_room - 8
        return usable_top + usable_h * (1 - (value - low) / span)

    bars = []
    labels = []
    base = y_at(0)
    for i, point in enumerate(points):
        x = x_at(i)
        y = y_at(point["value"])
        color = "#8eb6ff" if point.get("kind") == "history" else "#f6c453"
        whisker_top = None
        if "high" in point:
            whisker_top = y_at(point["high"])
            whisker_bottom = y_at(point["low"])
            bars.append(
                f'<line x1="{x:.1f}" y1="{whisker_top:.1f}" x2="{x:.1f}" y2="{whisker_bottom:.1f}" class="whisker"/>'
            )
            bars.append(
                f'<line x1="{x - 8:.1f}" y1="{whisker_top:.1f}" x2="{x + 8:.1f}" y2="{whisker_top:.1f}" class="whisker"/>'
            )
            bars.append(
                f'<line x1="{x - 8:.1f}" y1="{whisker_bottom:.1f}" x2="{x + 8:.1f}" y2="{whisker_bottom:.1f}" class="whisker"/>'
            )
        bar_height = abs(base - y)
        bar_y = min(y, base)
        if bar_height < 7:
            # A flat quarter would otherwise disappear into the axis.
            bar_height = 7
            bar_y = base - 3.5
        bars.append(
            f'<rect data-value="{point["value"]:.4f}" x="{x - 10:.1f}" y="{bar_y:.1f}" '
            f'width="20" height="{bar_height:.1f}" rx="3" fill="{color}"/>'
        )
        if whisker_top is not None:
            label_y = whisker_top - 16
        elif point["value"] >= 0:
            label_y = bar_y - 14
        else:
            label_y = bar_y + bar_height + 16
        label_y = max(16, label_y)
        bars.append(
            f'<text class="direct" x="{x:.1f}" y="{label_y:.1f}" text-anchor="middle">{signed_pct(point["value"])}</text>'
        )
        if point.get("kind") == "nowcast":
            labels.append(
                f'<text class="axis" x="{x:.1f}" y="{height - 18}" text-anchor="middle">{_estimate_axis_label(point["label"])}</text>'
            )
        elif i % 4 == 0:
            labels.append(
                f'<text class="axis" x="{x:.1f}" y="{height - 18}" text-anchor="middle">{point["label"]}</text>'
            )
    return (
        '<div class="chart-card hero-chart"><h3>Economic growth, and the estimate for the next two quarters</h3>'
        '<p class="chart-note">Blue bars are the official figures. Amber bars are this page’s estimate. The range is the usual miss since 2023, not a 2020-sized shock.</p>'
        f'<svg class="growth-chart" viewBox="0 0 {width} {height}" role="img" aria-label="Quarterly economic growth and the estimate ahead">'
        f'<line x1="{left}" y1="{base:.1f}" x2="{width - right}" y2="{base:.1f}" class="zero"/>'
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
    cx, cy, radius = 140, 118, 86
    x = cx + radius * math.cos(angle)
    y = cy - radius * math.sin(angle)
    color = _heat(probability)
    reading = odds(probability)
    note = (
        f"{reading} is the chance the next two quarters of GDP both shrink. "
        "The needle sits toward Low when that chance is small, and toward High when it is not. "
        "Beside this, blue bars are the official figures. Amber bars are this page’s estimate, "
        "and the whisker on each amber bar is the usual miss."
    )
    return (
        '<div class="chart-card gauge-card"><h3>Chance of two shrinking quarters in a row</h3>'
        '<svg viewBox="0 0 280 176" role="img" aria-label="Recession chance gauge">'
        f'<path d="M54,118 A86,86 0 0 1 226,118" fill="none" stroke="#243044" stroke-width="16" stroke-linecap="round"/>'
        f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="{color}" stroke-width="6" stroke-linecap="round"/>'
        f'<circle cx="{cx}" cy="{cy}" r="6" fill="{color}"/>'
        f'<text class="gauge-value" x="{cx}" y="78" text-anchor="middle">{reading}</text>'
        '<text class="axis" x="48" y="146">Low</text><text class="axis" x="232" y="146" text-anchor="end">High</text>'
        "</svg>"
        f'<p class="gauge-note">{note}</p></div>'
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
    highest_unemp = max(states, key=lambda row: _finite(row["unemp"]))
    weakest_demand = min(states, key=lambda row: _finite(row["sfd_qoq"], 99))
    if highest_unemp["short"] == weakest_demand["short"]:
        state_contrast = (
            f"{highest_unemp['name']} has the highest unemployment, {pct(highest_unemp['unemp'])}, "
            f"and the weakest June-quarter demand, {signed_pct(weakest_demand['sfd_qoq'])}. "
        )
    else:
        state_contrast = (
            f"{highest_unemp['name']} has the highest unemployment, {pct(highest_unemp['unemp'])}. "
            f"{weakest_demand['name']} has the weakest June-quarter demand, {signed_pct(weakest_demand['sfd_qoq'])}. "
        )
    state_means = (
        f"{weakest['name']} ranks highest on the combined score: "
        f"jobs {signed_pct(weakest['jobs_3m_pct'])} over three months, unemployment {pct(weakest['unemp'])}, "
        f"and June-quarter demand {signed_pct(weakest['sfd_qoq'])}. "
        + state_contrast
        + "October’s job losses were spread across several states, so a national average hides the patchiness. "
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
<link rel="icon" href="favicon.svg" type="image/svg+xml"/>
<link rel="icon" href="favicon.ico" sizes="32x32"/>
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
.kpi .take {{ margin:0; color:var(--muted); font-size:15px; }}
.kpi.bad .value {{ color:var(--red); }}
.kpi.warn .value {{ color:var(--amber); }}
.kpi.ok .value {{ color:var(--teal); }}
.hero {{ display:grid; grid-template-columns:280px 1fr; gap:12px; align-items:stretch; }}
.grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:12px; align-items:start; }}
.chart-card, .means, details {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:12px 14px; }}
.chart-card h3, .means h2 {{ margin:0 0 4px; font-size:1.02rem; }}
.chart-note, .means p {{ color:var(--muted); margin:4px 0 8px; }}
.gauge-card {{ display:flex; flex-direction:column; justify-content:space-between; }}
.gauge-note {{ color:var(--muted); margin:12px 0 0; font-size:15px; }}
svg {{ width:100%; height:auto; display:block; }}
.series {{ stroke:var(--blue); stroke-width:2.5; }}
.grid {{ stroke:#31425a; stroke-width:1; }}
.zero {{ stroke:#4a5d78; stroke-width:1.25; }}
.whisker {{ stroke:var(--amber); stroke-width:2; }}
.direct {{ fill:var(--text); font-size:13px; }}
.axis, .bar-label, .map-label {{ fill:var(--muted); font-size:13px; }}
.map-label {{ fill:var(--text); font-size:13px; font-weight:650; }}
.line-chart .axis, .line-chart .direct {{ font-size:17px; }}
.growth-chart .axis, .growth-chart .direct {{ font-size:15px; }}
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
  .kpi .take {{ font-size:14px; }}
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
