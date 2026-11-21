"""Run the Hamilton dataflow and write the site."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from hamilton import driver

from recession_watch import hamilton_dag
from recession_watch.dashboard import write_site

ROOT = Path(__file__).resolve().parents[2]


def execute(snapshot_dir: Path, max_em_iter: int, backtest_iter: int) -> dict:
    graph = driver.Driver(
        {},
        hamilton_dag,
    )
    result = graph.execute(
        ["payload"],
        inputs={
            "snapshot_dir": str(snapshot_dir),
            "max_em_iter": max_em_iter,
            "backtest_iter": backtest_iter,
        },
    )
    _write_lineage(graph)
    return result["payload"]


def _write_lineage(graph: driver.Driver) -> None:
    out = ROOT / "artifacts"
    out.mkdir(exist_ok=True)
    try:
        graph.display_all_functions(
            output_file_path=str(out / "hamilton_lineage.png"),
            render_kwargs={"format": "png"},
        )
    except Exception as exc:
        (out / "hamilton_lineage_error.txt").write_text(str(exc))
    try:
        graph.visualize_execution(
            final_vars=["payload"],
            output_file_path=str(out / "hamilton_execution"),
            render_kwargs={"format": "png"},
            inputs={
                "snapshot_dir": str(ROOT / "data" / "snapshot"),
                "max_em_iter": 1,
                "backtest_iter": 1,
            },
        )
    except Exception:
        # The execution graph still exists as code; a missing binary should not fail the run.
        pass


def persist(payload: dict) -> Path:
    gold = ROOT / "data" / "gold"
    gold.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(payload["backtest_rows"]).to_parquet(gold / "backtest.parquet", index=False)
    pd.DataFrame(payload["states"]).to_parquet(gold / "states.parquet", index=False)
    pd.DataFrame(payload["industries"]).to_parquet(gold / "industries.parquet", index=False)
    summary = {
        "created_at_utc": payload["created_at_utc"],
        "anchors": payload["anchors"],
        "nowcast": payload["nowcast"].get("points"),
        "scores": payload["scores"],
        "benchmark": payload["benchmark"],
        "signals": {
            key: value
            for key, value in payload["signals"].items()
            if not isinstance(value, list)
        },
    }
    (gold / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    (ROOT / "artifacts").mkdir(exist_ok=True)
    (ROOT / "artifacts" / "engine_benchmark.json").write_text(json.dumps(payload["benchmark"], indent=2))
    return write_site(payload, ROOT / "site")


def run(snapshot_dir: Path | None = None, max_em_iter: int = 12, backtest_iter: int = 8) -> Path:
    snapshot_dir = snapshot_dir or (ROOT / "data" / "snapshot")
    payload = execute(snapshot_dir, max_em_iter=max_em_iter, backtest_iter=backtest_iter)
    return persist(payload)
