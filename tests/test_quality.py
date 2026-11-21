import pandas as pd
import pytest

from recession_watch.ingest import load_snapshot
from recession_watch.quality import assert_anchors, nearest


def test_nearest_hundred_matches_the_abs_jobs_rounding():
    assert nearest(-43530.74, 100) == -43500


def test_snapshot_matches_published_anchors():
    observations, vintages, _manifest = load_snapshot()
    anchors = assert_anchors(observations, vintages)
    assert anchors["unemployment_oct_2026"] == 4.9
    assert anchors["cpi_annual_sep_2026"] == 4.3
    assert anchors["cash_rate_target"] == 4.85
    assert anchors["gdp_qoq_2026q2"] == 0.4


def test_schema_rejects_a_missing_value():
    from recession_watch.quality import validate_observations

    frame = pd.DataFrame(
        [
            {
                "series_id": "x",
                "period": "2026-10",
                "value": None,
                "vintage_id": "v",
                "publication_time": "2026-11-19T00:30:00+00:00",
                "source": "abs-lf",
            }
        ]
    )
    with pytest.raises(Exception):
        validate_observations(frame)
