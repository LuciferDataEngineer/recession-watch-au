from pathlib import Path

from recession_watch.benchmark import run_benchmark
from recession_watch.ingest import load_snapshot

ROOT = Path(__file__).resolve().parents[1]


def test_duckdb_and_datafusion_return_the_same_rows():
    observations, _vintages, _manifest = load_snapshot()
    result = run_benchmark(observations, ROOT / "data" / "snapshot" / "observations.parquet", repeats=2)
    assert result["results_match"] is True
    assert result["rows"] > 1000
