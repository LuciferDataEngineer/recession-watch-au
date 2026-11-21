"""The backtest must not see a vintage before it was published."""

from datetime import datetime, timezone

import pandas as pd

from recession_watch.vintage import asof, connect

COLUMNS = [
    "series_id",
    "period",
    "period_start",
    "period_end",
    "value",
    "vintage_id",
    "publication_time",
    "ingestion_time",
    "source",
    "unit",
    "title",
]


def _row(**kwargs):
    base = {column: "" for column in COLUMNS}
    base.update(kwargs)
    return base


def test_asof_keeps_the_vintage_that_had_been_published():
    observations = pd.DataFrame(columns=COLUMNS)
    vintages = pd.DataFrame(
        [
            _row(
                series_id="gdp_qoq",
                period="2024-Q1",
                period_start="2024-01-01",
                period_end="2024-03-31",
                value=0.1,
                vintage_id="abs-ana-mar-2024",
                publication_time="2024-06-05T01:30:00+00:00",
                source="abs-ana-vintages",
                unit="percent",
                title="GDP",
            ),
            _row(
                series_id="gdp_qoq",
                period="2024-Q1",
                period_start="2024-01-01",
                period_end="2024-03-31",
                value=0.4,
                vintage_id="abs-ana-jun-2026",
                publication_time="2026-09-02T01:30:00+00:00",
                source="abs-ana-vintages",
                unit="percent",
                title="GDP",
            ),
        ]
    )
    connection = connect(observations, vintages)
    early = asof(connection, datetime(2024, 7, 1, tzinfo=timezone.utc))
    late = asof(connection, datetime(2026, 10, 1, tzinfo=timezone.utc))
    connection.close()
    assert float(early.loc[early["period"] == "2024-Q1", "value"].iloc[0]) == 0.1
    assert float(late.loc[late["period"] == "2024-Q1", "value"].iloc[0]) == 0.4


def test_asof_hides_a_series_until_its_release_lag():
    observations = pd.DataFrame(
        [
            _row(
                series_id="lf_unemp_AUS",
                period="2026-10",
                period_start="2026-10-01",
                period_end="2026-10-31",
                value=4.86,
                vintage_id="abs-api-latest",
                publication_time="2026-11-19T00:30:00+00:00",
                source="abs-lf",
                unit="percent",
                title="Unemployment",
            )
        ]
    )
    vintages = pd.DataFrame(columns=COLUMNS)
    connection = connect(observations, vintages)
    before = asof(connection, datetime(2026, 11, 1, tzinfo=timezone.utc))
    after = asof(connection, datetime(2026, 11, 20, tzinfo=timezone.utc))
    connection.close()
    assert before.empty
    assert float(after["value"].iloc[0]) == 4.86
