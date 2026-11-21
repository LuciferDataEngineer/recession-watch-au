"""Time the same silver query on DuckDB and DataFusion."""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from recession_watch.transform import datafusion_state_changes, duckdb_state_changes, frames_agree


def time_call(fn, repeats: int = 8) -> tuple[float, object]:
    fn()  # warm-up
    start = time.perf_counter()
    result = None
    for _ in range(repeats):
        result = fn()
    elapsed = (time.perf_counter() - start) / repeats
    return elapsed, result


def run_benchmark(observations: pd.DataFrame, parquet_path: Path, repeats: int = 8) -> dict:
    duck_seconds, duck_frame = time_call(lambda: duckdb_state_changes(observations), repeats)
    fusion_seconds, fusion_frame = time_call(lambda: datafusion_state_changes(parquet_path), repeats)
    agree = frames_agree(duck_frame, fusion_frame)
    rows = int(len(duck_frame))
    return {
        "query": "lagged change in employment and state final demand",
        "rows": rows,
        "repeats": repeats,
        "duckdb_seconds": round(duck_seconds, 6),
        "datafusion_seconds": round(fusion_seconds, 6),
        "results_match": agree,
        "note": (
            "Times are a single-thread average on this snapshot after one warm-up. "
            "The table is small, so the numbers describe fixed overhead more than a warehouse bake-off. "
            "Both engines are in-process and free."
        ),
    }
