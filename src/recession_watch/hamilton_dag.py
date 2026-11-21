"""Hamilton dataflow. The driver, not a side script, produces the dashboard payload."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from recession_watch.benchmark import run_benchmark
from recession_watch.ingest import load_snapshot
from recession_watch.model import (
    industry_exposure,
    latest_signal,
    nowcast_at,
    run_backtest,
    score_backtest,
    state_exposure,
)
from recession_watch.quality import assert_anchors
from recession_watch.vintage import asof, connect


def snapshot_bundle(snapshot_dir: str) -> dict:
    observations, vintages, manifest = load_snapshot(Path(snapshot_dir))
    return {"observations": observations, "vintages": vintages, "manifest": manifest}


def anchors(snapshot_bundle: dict) -> dict:
    return assert_anchors(snapshot_bundle["observations"], snapshot_bundle["vintages"])


def information_set(snapshot_bundle: dict) -> pd.DataFrame:
    created = datetime.fromisoformat(snapshot_bundle["manifest"]["created_at_utc"])
    connection = connect(snapshot_bundle["observations"], snapshot_bundle["vintages"])
    frame = asof(connection, created)
    connection.close()
    return frame


def growth_nowcast(information_set: pd.DataFrame, max_em_iter: int) -> dict:
    cast = nowcast_at(information_set, maxiter=max_em_iter)
    quarterly = cast.get("quarterly")
    if quarterly is not None and not quarterly.empty:
        history = quarterly["gdp"].dropna().tail(20)
        history_pc = quarterly["gdp_pc"].dropna().tail(20)
        cast["history"] = [{"period": str(idx), "value": float(val)} for idx, val in history.items()]
        cast["history_pc"] = [{"period": str(idx), "value": float(val)} for idx, val in history_pc.items()]
    cast.pop("panel", None)
    cast.pop("quarterly", None)
    return cast


def realtime_backtest(snapshot_bundle: dict, backtest_iter: int) -> pd.DataFrame:
    created = datetime.fromisoformat(snapshot_bundle["manifest"]["created_at_utc"])
    return run_backtest(
        snapshot_bundle["observations"],
        snapshot_bundle["vintages"],
        created,
        maxiter=backtest_iter,
    )


def backtest_scores(realtime_backtest: pd.DataFrame) -> dict:
    return score_backtest(realtime_backtest)


def state_rows(information_set: pd.DataFrame) -> list:
    return state_exposure(information_set)


def industry_rows(information_set: pd.DataFrame) -> list:
    return industry_exposure(information_set)


def _path(series: pd.Series, n: int = 36) -> list[dict]:
    clean = series.dropna().tail(n)
    return [{"period": str(idx), "value": float(val)} for idx, val in clean.items()]


def signals(information_set: pd.DataFrame) -> dict:
    from recession_watch.model import _monthly_last, activity_frame

    _monthly, quarterly, panel = activity_frame(information_set)
    latest = latest_signal(panel)
    latest["unemp_path"] = _path(panel["unemp"], 36)
    latest["spread_path"] = _path(panel["yield_spread"], 60)
    latest["hsi_path"] = _path(panel["hsi_3m_pct"], 24)
    latest["approvals_path"] = _path(panel["approvals_yoy"], 36)
    latest["cpi_path"] = _path(_monthly_last(information_set, "cpi_annual"), 24)
    youth = _monthly_last(information_set, "lf_youth_unemp_AUS")
    latest["youth_unemp"] = float(youth.dropna().iloc[-1]) if not youth.dropna().empty else float("nan")
    gdp = quarterly["gdp"].dropna()
    latest["gdp_history"] = _path(gdp, 24)
    latest["gdp_pc_history"] = _path(quarterly["gdp_pc"].dropna(), 24)
    return latest


def engine_benchmark(snapshot_dir: str) -> dict:
    observations, _vintages, _manifest = load_snapshot(Path(snapshot_dir))
    parquet = Path(snapshot_dir) / "observations.parquet"
    return run_benchmark(observations, parquet)


def payload(
    snapshot_bundle: dict,
    anchors: dict,
    information_set: pd.DataFrame,
    growth_nowcast: dict,
    realtime_backtest: pd.DataFrame,
    backtest_scores: dict,
    state_rows: list,
    industry_rows: list,
    signals: dict,
    engine_benchmark: dict,
) -> dict:
    return {
        "created_at_utc": snapshot_bundle["manifest"]["created_at_utc"],
        "anchors": anchors,
        "nowcast": growth_nowcast,
        "backtest_rows": realtime_backtest.to_dict(orient="records"),
        "scores": backtest_scores,
        "states": state_rows,
        "industries": industry_rows,
        "signals": signals,
        "benchmark": engine_benchmark,
        "n_observations": int(len(information_set)),
        "sources": snapshot_bundle["manifest"]["sources"],
    }
