"""Bitemporal queries over the vintage store.

valid time  = the reference period the number describes
transaction time = publication_time, when that vintage became public

A backtest asks: what would we have known at date T? The answer is the latest
vintage of each period whose publication_time is on or before T.
"""

from __future__ import annotations

from datetime import datetime

import duckdb
import pandas as pd


def connect(observations: pd.DataFrame, vintages: pd.DataFrame) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.register("observations_df", observations)
    con.register("vintages_df", vintages)
    con.execute(
        """
        CREATE TABLE observations AS SELECT * FROM observations_df;
        CREATE TABLE gdp_vintages AS SELECT * FROM vintages_df;
        """
    )
    return con


def asof(con: duckdb.DuckDBPyConnection, moment: datetime, series: list[str] | None = None) -> pd.DataFrame:
    """Latest vintage of every period that had been published by `moment`.

    GDP growth prefers the real National Accounts vintages. Other series use
    the single API vintage, whose publication_time is the usual release lag.
    """
    stamp = moment.isoformat()
    series_filter = ""
    params: list = [stamp, stamp]
    if series:
        placeholders = ",".join("?" for _ in series)
        series_filter = f"AND series_id IN ({placeholders})"
        params = [stamp, *series, stamp, *series]
    query = f"""
        WITH published AS (
            SELECT * FROM gdp_vintages
            WHERE publication_time <= ?
            {series_filter}
            UNION ALL
            SELECT * FROM observations
            WHERE publication_time <= ?
              AND series_id NOT IN ('gdp_qoq', 'gdp_pc_qoq')
              {series_filter}
        ),
        ranked AS (
            SELECT *,
                   row_number() OVER (
                       PARTITION BY series_id, period
                       ORDER BY publication_time DESC, vintage_id DESC
                   ) AS rn
            FROM published
        )
        SELECT * EXCLUDE (rn)
        FROM ranked
        WHERE rn = 1
        ORDER BY series_id, period
    """
    return con.execute(query, params).df()


def series_frame(frame: pd.DataFrame, series_id: str) -> pd.Series:
    subset = frame.loc[frame["series_id"] == series_id, ["period", "value", "period_end"]].copy()
    if subset.empty:
        return pd.Series(dtype="float64")
    subset = subset.sort_values("period")
    return subset.set_index("period")["value"].astype(float)
