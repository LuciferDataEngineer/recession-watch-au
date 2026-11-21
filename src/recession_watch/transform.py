"""Silver transforms in DuckDB and DataFusion.

Both engines answer the same question from the snapshot: how employment and
state final demand have moved. The benchmark times that query.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
from datafusion import SessionContext

STATE_SQL = """
SELECT series_id,
       period,
       value,
       value - lag(value) OVER (PARTITION BY series_id ORDER BY period) AS change
FROM observations
WHERE series_id LIKE 'lf_employed_%'
   OR series_id LIKE 'sfd_%'
ORDER BY series_id, period
"""


def duckdb_state_changes(observations: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect()
    con.register("observations", observations)
    frame = con.execute(STATE_SQL).df()
    con.close()
    return frame


def datafusion_state_changes(parquet_path: Path) -> pd.DataFrame:
    ctx = SessionContext()
    ctx.register_parquet("observations", str(parquet_path))
    return ctx.sql(STATE_SQL).to_pandas()


def frames_agree(left: pd.DataFrame, right: pd.DataFrame, tol: float = 1e-6) -> bool:
    left = left.sort_values(["series_id", "period"]).reset_index(drop=True)
    right = right.sort_values(["series_id", "period"]).reset_index(drop=True)
    if list(left.columns) != list(right.columns) or len(left) != len(right):
        return False
    if not left["series_id"].equals(right["series_id"]) or not left["period"].equals(right["period"]):
        return False
    for column in ("value", "change"):
        a = left[column].astype(float)
        b = right[column].astype(float)
        both_missing = a.isna() & b.isna()
        if not ((a - b).abs().le(tol) | both_missing).all():
            return False
    return True
