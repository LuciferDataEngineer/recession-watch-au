"""Checks that the snapshot still matches the published ABS and RBA anchors."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import pandas as pd
import pandera.pandas as pa

from recession_watch.catalog import ANCHORS


class ObservationSchema(pa.DataFrameModel):
    series_id: str
    period: str
    value: float = pa.Field(nullable=False)
    vintage_id: str
    publication_time: str
    source: str

    class Config:
        strict = False


def round_half_up(value: float, places: int = 1) -> float:
    quantum = Decimal("1") if places == 0 else Decimal("0." + ("0" * (places - 1)) + "1")
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def nearest(value: float, unit: int) -> int:
    quantum = Decimal(unit)
    scaled = (Decimal(str(value)) / quantum).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(scaled * quantum)


def validate_observations(frame: pd.DataFrame) -> None:
    ObservationSchema.validate(frame)


def _value(frame: pd.DataFrame, series_id: str, period: str) -> float:
    rows = frame.loc[(frame["series_id"] == series_id) & (frame["period"] == period), "value"]
    if rows.empty:
        raise AssertionError(f"missing {series_id} {period}")
    return float(rows.iloc[-1])


def assert_anchors(observations: pd.DataFrame, vintages: pd.DataFrame) -> dict[str, float]:
    """Fail the pipeline if a headline number does not match the primary release."""
    validate_observations(observations)
    validate_observations(vintages)
    unemp = _value(observations, "lf_unemp_AUS", "2026-10")
    unemp_prev = _value(observations, "lf_unemp_AUS", "2026-09")
    employed = _value(observations, "lf_employed_AUS", "2026-10")
    employed_prev = _value(observations, "lf_employed_AUS", "2026-09")
    youth = _value(observations, "lf_youth_unemp_AUS", "2026-10")
    cpi = _value(observations, "cpi_annual", "2026-09")
    hsi = _value(observations, "hsi_AUS", "2026-09")
    hsi_prev = _value(observations, "hsi_AUS", "2026-08")
    latest_vintage = vintages.loc[vintages["vintage_id"].str.contains("jun-2026")]
    gdp = _value(latest_vintage, "gdp_qoq", "2026-Q2")
    gdp_pc = _value(latest_vintage, "gdp_pc_qoq", "2026-Q2")
    cash = observations.loc[observations["series_id"] == "cash_rate"].sort_values("period")
    cash_rate = float(cash.loc[cash["value"].notna(), "value"].iloc[-1])
    job_change = nearest(employed - employed_prev, 100)
    checks = {
        "unemployment_oct_2026": round_half_up(unemp, 1),
        "employment_change_oct_2026": job_change,
        "youth_unemployment_oct_2026": round_half_up(youth, 1),
        "cpi_annual_sep_2026": round_half_up(cpi, 1),
        "gdp_qoq_2026q2": round_half_up(gdp, 1),
        "gdp_pc_qoq_2026q2": round_half_up(gdp_pc, 1),
        "cash_rate_target": round_half_up(cash_rate, 2),
        "hsi_mom_sep_2026": round_half_up((hsi / hsi_prev - 1) * 100, 1),
    }
    for key, expected in ANCHORS.items():
        got = checks[key]
        if got != expected:
            raise AssertionError(f"{key}: snapshot says {got}, published figure is {expected}")
    if round_half_up(unemp_prev, 1) != 4.7:
        raise AssertionError(f"September unemployment rounded to {round_half_up(unemp_prev, 1)}")
    return checks
