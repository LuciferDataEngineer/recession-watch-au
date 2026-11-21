"""Download ABS SDMX and RBA tables into a bitemporal parquet snapshot."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import xlrd
from openpyxl import load_workbook

from recession_watch.catalog import (
    ABS_API,
    GDP_PC_SERIES_ID,
    GDP_SERIES_ID,
    RBA_CSV,
    SOURCES,
)
from recession_watch.periods import (
    parse_period,
    publish_monthly,
    publish_quarterly,
    quarter_token,
)

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "data" / "snapshot"
UA = "recession-watch-au/0.1 (github.com/LuciferDataEngineer/recession-watch-au)"
RELEASE_RE = re.compile(
    r"Release date and time</div>\s*<div class=\"field__item\">"
    r"(\d{2})/(\d{2})/(\d{4})\s+(\d{1,2}):(\d{2})(am|pm)\s+(AEST|AEDT)",
    re.I,
)


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "text/csv,application/xml,*/*"})
    return session


def _get(session: requests.Session, url: str, **kwargs) -> requests.Response:
    last: Exception | None = None
    for _ in range(4):
        try:
            response = session.get(url, timeout=180, **kwargs)
            if response.status_code >= 500:
                last = RuntimeError(f"{response.status_code} {url}")
                continue
            return response
        except requests.RequestException as exc:
            last = exc
    raise RuntimeError(f"failed to fetch {url}") from last


def _rows_from_sdmx(text: str) -> list[dict[str, str]]:
    if not text or text.startswith("NoRecords") or text.startswith("No Results"):
        return []
    return list(csv.DictReader(io.StringIO(text)))


def _scaled(raw: str, unit_mult: str) -> float | None:
    if raw is None or raw == "":
        return None
    value = float(raw)
    mult = int(unit_mult or "0")
    return value * (10**mult)


def _obs(
    *,
    series_id: str,
    period: str,
    value: float,
    vintage_id: str,
    publication_time: datetime,
    source: str,
    unit: str,
    title: str,
    ingestion_time: datetime,
) -> dict:
    start, end, token = parse_period(period)
    return {
        "series_id": series_id,
        "period": token,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "value": float(value),
        "vintage_id": vintage_id,
        "publication_time": publication_time.astimezone(timezone.utc).isoformat(),
        "ingestion_time": ingestion_time.isoformat(),
        "source": source,
        "unit": unit,
        "title": title,
    }


def _abs_csv(session: requests.Session, dataflow: str, key: str, start: str) -> list[dict[str, str]]:
    url = f"{ABS_API}/ABS,{dataflow}/{key}"
    response = _get(session, url, params={"startPeriod": start, "format": "csv"})
    if response.status_code == 404:
        return []
    response.raise_for_status()
    return _rows_from_sdmx(response.text)


def _monthly_frame(rows: list[dict], series_id: str, title: str, unit: str, kind: str, source: str, ingested: datetime, vintage: str) -> list[dict]:
    out = []
    for row in rows:
        scaled = _scaled(row.get("OBS_VALUE", ""), row.get("UNIT_MULT", "0"))
        if scaled is None:
            continue
        period = row["TIME_PERIOD"]
        _start, end, token = parse_period(period)
        out.append(
            _obs(
                series_id=series_id,
                period=token,
                value=scaled,
                vintage_id=vintage,
                publication_time=publish_monthly(end, kind),
                source=source,
                unit=unit,
                title=title,
                ingestion_time=ingested,
            )
        )
    return out


def _quarter_frame(rows, series_id, title, unit, kind, source, ingested, vintage) -> list[dict]:
    out = []
    for row in rows:
        scaled = _scaled(row.get("OBS_VALUE", ""), row.get("UNIT_MULT", "0"))
        if scaled is None:
            continue
        _start, end, token = parse_period(row["TIME_PERIOD"])
        out.append(
            _obs(
                series_id=series_id,
                period=token,
                value=scaled,
                vintage_id=vintage,
                publication_time=publish_quarterly(end, kind),
                source=source,
                unit=unit,
                title=title,
                ingestion_time=ingested,
            )
        )
    return out


def _filter(rows: list[dict], **wanted: str) -> list[dict]:
    kept = []
    for row in rows:
        if all(row.get(key) == value for key, value in wanted.items()):
            kept.append(row)
    return kept


def fetch_abs(session: requests.Session, ingested: datetime) -> list[dict]:
    vintage = "abs-api-latest"
    out: list[dict] = []

    gdp = _abs_csv(session, "ANA_AGG", "M2.GPM+GPM_PCA.20.AUS.Q", "1980-Q1")
    out += _quarter_frame(
        _filter(gdp, MEASURE="M2", DATA_ITEM="GPM"),
        "gdp_qoq",
        "GDP growth, seasonally adjusted",
        "percent",
        "gdp",
        "abs-ana",
        ingested,
        vintage,
    )
    out += _quarter_frame(
        _filter(gdp, MEASURE="M2", DATA_ITEM="GPM_PCA"),
        "gdp_pc_qoq",
        "GDP per capita growth, seasonally adjusted",
        "percent",
        "gdp",
        "abs-ana",
        ingested,
        vintage,
    )

    sfd = _abs_csv(session, "ANA_SFD", "VCH.SFD.SSS.20.1+2+3+4+5+6+7+8.Q", "1990-Q1")
    for code in "12345678":
        out += _quarter_frame(
            _filter(sfd, REGION=code),
            f"sfd_{code}",
            f"State final demand, region {code}",
            "index_or_dollars",
            "sfd",
            "abs-sfd",
            ingested,
            vintage,
        )

    lf = _abs_csv(session, "LF", "M13+M3+M12.3.1599.20.AUS+1+2+3+4+5+6.M", "2000-01")
    measure_map = {
        "M13": ("unemp", "Unemployment rate", "percent"),
        "M3": ("employed", "Employed persons", "persons"),
        "M12": ("participation", "Participation rate", "percent"),
    }
    for measure, (slug, title, unit) in measure_map.items():
        for region in ["AUS", "1", "2", "3", "4", "5", "6"]:
            subset = _filter(lf, MEASURE=measure, REGION=region)
            if not subset:
                continue
            out += _monthly_frame(
                subset,
                f"lf_{slug}_{region}",
                f"{title} {region}",
                unit,
                "lf",
                "abs-lf",
                ingested,
                vintage,
            )

    # NT and ACT: trend, because seasonally adjusted is not published here.
    lf_small = _abs_csv(session, "LF", "M13+M3.3.1599.30.7+8.M", "2000-01")
    for measure, (slug, title, unit) in {
        "M13": ("unemp", "Unemployment rate, smoothed", "percent"),
        "M3": ("employed", "Employed persons, smoothed", "persons"),
    }.items():
        for region in ["7", "8"]:
            subset = _filter(lf_small, MEASURE=measure, REGION=region)
            out += _monthly_frame(
                subset,
                f"lf_{slug}_{region}",
                f"{title} {region}",
                unit,
                "lf",
                "abs-lf",
                ingested,
                vintage,
            )

    youth = _abs_csv(session, "LF_AGES", "M13.3.1524.20.AUS.M", "2000-01")
    out += _monthly_frame(
        youth,
        "lf_youth_unemp_AUS",
        "Youth unemployment rate 15-24",
        "percent",
        "lf",
        "abs-lf-ages",
        ingested,
        vintage,
    )

    cpi = _abs_csv(session, "CPI", "1+3.10001.10.50.M", "2000-01")
    out += _monthly_frame(
        _filter(cpi, MEASURE="1"),
        "cpi_index",
        "Monthly CPI index",
        "index",
        "cpi",
        "abs-cpi",
        ingested,
        vintage,
    )
    out += _monthly_frame(
        _filter(cpi, MEASURE="3"),
        "cpi_annual",
        "Monthly CPI annual change",
        "percent",
        "cpi",
        "abs-cpi",
        ingested,
        vintage,
    )

    hsi = _abs_csv(session, "HSI_M", "7.TOT.CUR.20.AUS+1+2+3+4+5+6+7+8.M", "2019-01")
    for region in ["AUS", "1", "2", "3", "4", "5", "6", "7", "8"]:
        subset = _filter(hsi, STATE=region)
        if not subset:
            continue
        out += _monthly_frame(
            subset,
            f"hsi_{region}",
            f"Household spending {region}",
            "aud_millions",
            "hsi",
            "abs-hsi",
            ingested,
            vintage,
        )

    approvals = _abs_csv(
        session,
        "BA_GCCSA",
        "1.1.9.1.110+150.10.AUS+1+2+3+4+5+6+7+8.M",
        "2000-01",
    )
    # Sum houses and other dwellings inside the caller; store the parts.
    for region in ["AUS", "1", "2", "3", "4", "5", "6", "7", "8"]:
        for building, slug in (("110", "houses"), ("150", "other")):
            subset = _filter(approvals, REGION=region, BUILDING_TYPE=building)
            out += _monthly_frame(
                subset,
                f"approvals_{slug}_{region}",
                f"New {slug} approvals {region}",
                "dwellings",
                "ba",
                "abs-ba",
                ingested,
                vintage,
            )

    industries = "A+B+C+E+F+G+H+I+K+L+M+Q+R+S"
    qbis = _abs_csv(session, "QBIS", f"M2.CVM.{industries}.TOT.20.AUS.Q", "2002-Q1")
    for code in INDUSTRY_CODES:
        subset = _filter(qbis, INDUSTRY=code)
        if not subset:
            continue
        out += _quarter_frame(
            subset,
            f"sales_{code}",
            f"Business sales volume growth {code}",
            "percent",
            "qbis",
            "abs-qbis",
            ingested,
            vintage,
        )
    return out


INDUSTRY_CODES = list("ABCEFGHIKLMQRS")


def _parse_release(html: str) -> datetime | None:
    match = RELEASE_RE.search(html)
    if not match:
        return None
    day, month, year, hour, minute, ampm, zone = match.groups()
    hour_i = int(hour) % 12
    if ampm.lower() == "pm":
        hour_i += 12
    offset = 11 if zone.upper() == "AEDT" else 10
    # Build UTC directly from the stated civil time.
    local = datetime(int(year), int(month), int(day), hour_i, int(minute), tzinfo=timezone.utc)
    return local - pd.Timedelta(hours=offset).to_pytimedelta()


def _quarter_slug(token: str) -> str:
    year, quarter = token.split("-Q")
    month = {"1": "mar", "2": "jun", "3": "sep", "4": "dec"}[quarter]
    return f"{month}-{year}"


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _archive_file(html: str, page_url: str) -> str | None:
    hrefs = re.findall(r'href="([^"]*5206001[^"]*)"', html, re.I)
    hrefs = [href for href in hrefs if "mock" not in href.lower()]
    if not hrefs:
        return None
    href = hrefs[-1]
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return "https://www.abs.gov.au" + href
    return page_url.rstrip("/") + "/" + href


def fetch_gdp_vintages(session: requests.Session, ingested: datetime) -> list[dict]:
    """Each National Accounts workbook is one publication vintage."""
    out: list[dict] = []
    periods = []
    for year in range(2012, 2027):
        for quarter in range(1, 5):
            token = f"{year}-Q{quarter}"
            if token > "2026-Q2":
                break
            periods.append(token)
    base = (
        "https://www.abs.gov.au/statistics/economy/national-accounts/"
        "australian-national-accounts-national-income-expenditure-and-product"
    )
    for token in periods:
        slug = _quarter_slug(token)
        page_url = f"{base}/{slug}"
        page = _get(session, page_url)
        if page.status_code != 200 or "5206001" not in page.text:
            continue
        # A soft redirect of an unknown slug repeats the latest release title.
        if slug not in page.url and slug not in page.text[:5000] and token[-2:] not in page.text[:800]:
            title = re.search(r"<title>([^<]+)", page.text)
            if title and slug.replace("-", " ") not in title.group(1).lower() and slug[-4:] not in title.group(1):
                # Still accept the page when the workbook link itself contains the slug.
                if slug not in page.text:
                    continue
        file_url = _archive_file(page.text, page_url)
        if not file_url or slug not in file_url:
            continue
        workbook = _get(session, file_url)
        if workbook.status_code != 200:
            continue
        published = _parse_release(page.text)
        approximate = False
        if published is None:
            _start, end, _token = parse_period(token)
            published = publish_quarterly(end, "gdp")
            approximate = True
        vintage_id = f"abs-ana-{slug}" + ("-approx" if approximate else "")
        try:
            extracted = _gdp_from_workbook(workbook.content)
        except Exception as exc:
            print(f"  skip {slug}: {exc}")
            continue
        if not extracted[GDP_SERIES_ID]:
            print(f"  skip {slug}: no GDP points")
            continue
        for series_key, points in extracted.items():
            series_id = "gdp_qoq" if series_key == GDP_SERIES_ID else "gdp_pc_qoq"
            title = "GDP growth vintage" if series_id == "gdp_qoq" else "GDP per capita growth vintage"
            for period, value in points:
                out.append(
                    _obs(
                        series_id=series_id,
                        period=period,
                        value=value,
                        vintage_id=vintage_id,
                        publication_time=published,
                        source="abs-ana-vintages",
                        unit="percent",
                        title=title,
                        ingestion_time=ingested,
                    )
                )
        print(
            f"  vintage {slug}: {len(extracted[GDP_SERIES_ID])} gdp points, published {published.date()}"
        )
    return out


def _points_from_rows(rows: list[tuple], datemode: int | None) -> dict[str, list[tuple[str, float]]]:
    wanted = {GDP_SERIES_ID, GDP_PC_SERIES_ID}
    points: dict[str, list[tuple[str, float]]] = {key: [] for key in wanted}
    colmap: dict[int, str] = {}
    for row in rows:
        if not colmap:
            labels = {str(cell) for cell in row if cell not in (None, "")}
            if wanted & labels:
                for col, cell in enumerate(row):
                    if cell in wanted:
                        colmap[col] = str(cell)
            continue
        stamp = row[0]
        if isinstance(stamp, datetime):
            day = stamp.date()
        elif isinstance(stamp, date):
            day = stamp
        elif isinstance(stamp, (int, float)) and stamp > 20000 and datemode is not None:
            day = xlrd.xldate_as_datetime(stamp, datemode).date()
        else:
            continue
        period = quarter_token(day)
        for col, series_key in colmap.items():
            raw = row[col] if col < len(row) else None
            if raw in (None, ""):
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            points[series_key].append((period, value))
    if not colmap:
        raise ValueError("series ids not found")
    return points


def _gdp_from_workbook(content: bytes) -> dict[str, list[tuple[str, float]]]:
    if content[:2] == b"PK":
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        sheet = book["Data1"]
        rows = [tuple(row) for row in sheet.iter_rows(values_only=True)]
        book.close()
        return _points_from_rows(rows, None)
    book = xlrd.open_workbook(file_contents=content)
    sheet = book.sheet_by_name("Data1")
    rows = [tuple(sheet.row_values(i)) for i in range(sheet.nrows)]
    return _points_from_rows(rows, book.datemode)


def _parse_rba_date(token: str) -> date | None:
    token = token.strip()
    for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue
    return None


def _read_rba(text: str) -> tuple[list[str], list[list[str]], date | None]:
    lines = text.splitlines()
    series_idx = None
    published = None
    for i, line in enumerate(lines[:15]):
        if line.startswith("Series ID"):
            series_idx = i
        if line.startswith("Publication date"):
            cells = next(csv.reader([line]))
            for cell in cells[1:]:
                parsed = _parse_rba_date(cell.replace(" ", "-"))
                if parsed:
                    published = parsed
                    break
    if series_idx is None:
        raise ValueError("RBA series id row missing")
    ids = next(csv.reader([lines[series_idx]]))
    data = []
    for line in lines[series_idx + 1 :]:
        if not line.strip():
            continue
        data.append(next(csv.reader([line])))
    return ids, data, published


def fetch_rba(session: requests.Session, ingested: datetime) -> list[dict]:
    out: list[dict] = []
    specs = [
        ("f1-data.csv", "FIRMMCRTD", "cash_rate", "Cash rate target", "rba-f1", True),
        ("f1.1-data.csv", "FIRMMCRT", "cash_rate_monthly", "Cash rate target, monthly average", "rba-f1", False),
        ("f2.1-data.csv", "FCMYGBAG2", "yield_2y", "2-year government bond yield", "rba-f2", False),
        ("f2.1-data.csv", "FCMYGBAG10", "yield_10y", "10-year government bond yield", "rba-f2", False),
        ("f2-data.csv", "FCMYGBAG2D", "yield_2y_daily", "2-year yield, daily", "rba-f2", True),
        ("f2-data.csv", "FCMYGBAG10D", "yield_10y_daily", "10-year yield, daily", "rba-f2", True),
    ]
    cache: dict[str, tuple[list[str], list[list[str]], date | None]] = {}
    for filename, series_code, series_id, title, source, daily in specs:
        if filename not in cache:
            response = _get(session, f"{RBA_CSV}/{filename}")
            response.raise_for_status()
            cache[filename] = _read_rba(response.content.decode("utf-8-sig"))
        ids, data, published = cache[filename]
        try:
            col = ids.index(series_code)
        except ValueError:
            print(f"  missing RBA column {series_code}")
            continue
        table_pub = datetime(published.year, published.month, published.day, tzinfo=timezone.utc) if published else ingested
        for cells in data:
            if not cells or col >= len(cells):
                continue
            day = _parse_rba_date(cells[0])
            raw = cells[col].strip() if col < len(cells) else ""
            if day is None or raw == "":
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            if daily:
                period = f"{day.year:04d}-{day.month:02d}-{day.day:02d}"
                # A cash rate or yield is public on the day it is observed.
                publication = datetime(day.year, day.month, day.day, 6, 0, tzinfo=timezone.utc)
                # Store daily points with a synthetic daily period by using month token?
                # The vintage table uses YYYY-MM or YYYY-Qn. Keep daily as YYYY-MM-DD
                # via a direct dict so parse_period is not required.
                out.append(
                    {
                        "series_id": series_id,
                        "period": period,
                        "period_start": day.isoformat(),
                        "period_end": day.isoformat(),
                        "value": value,
                        "vintage_id": f"rba-{filename}-{table_pub.date().isoformat()}",
                        "publication_time": publication.isoformat(),
                        "ingestion_time": ingested.isoformat(),
                        "source": source,
                        "unit": "percent",
                        "title": title,
                    }
                )
            else:
                token = f"{day.year:04d}-{day.month:02d}"
                # Monthly average is public when the table that contains it is released.
                # Use the later of month-end+5 days and... we only know the current table date.
                # Availability for history: month-end + 7 days (F2.1 is the first Friday after month-end).
                end = parse_period(token)[1]
                publication = datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + pd.Timedelta(days=7)
                out.append(
                    _obs(
                        series_id=series_id,
                        period=token,
                        value=value,
                        vintage_id=f"rba-{filename}-{table_pub.date().isoformat()}",
                        publication_time=_as_utc(publication),
                        source=source,
                        unit="percent",
                        title=title,
                        ingestion_time=ingested,
                    )
                )
    return out


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_snapshot(frame: pd.DataFrame, vintages: pd.DataFrame, ingested: datetime) -> Path:
    SNAPSHOT.mkdir(parents=True, exist_ok=True)
    obs_path = SNAPSHOT / "observations.parquet"
    vin_path = SNAPSHOT / "gdp_vintages.parquet"
    frame.to_parquet(obs_path, index=False)
    vintages.to_parquet(vin_path, index=False)
    files = []
    for path in (obs_path, vin_path):
        files.append(
            {
                "path": str(path.relative_to(ROOT)),
                "sha256": _sha256(path),
                "rows": int(len(pd.read_parquet(path))),
                "bytes": path.stat().st_size,
            }
        )
    manifest = {
        "created_at_utc": ingested.isoformat(),
        "note": "CI reads this snapshot and does not call the network. Refresh with `make snapshot`.",
        "files": files,
        "sources": SOURCES,
        "series_counts": frame.groupby("series_id").size().sort_index().to_dict(),
        "vintage_ids": sorted(vintages["vintage_id"].unique().tolist()) if len(vintages) else [],
    }
    manifest_path = SNAPSHOT / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    files.append(
        {
            "path": str(manifest_path.relative_to(ROOT)),
            "sha256": _sha256(manifest_path),
            "rows": None,
            "bytes": manifest_path.stat().st_size,
        }
    )
    # Rewrite manifest so its own hash is recorded alongside the parquet hashes.
    # The hash below is of the parquet files only; manifest.json is hashed by CI separately.
    manifest["files"] = [item for item in files if item["path"].endswith(".parquet")]
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest_path


def download() -> Path:
    ingested = datetime.now(timezone.utc).replace(microsecond=0)
    session = _session()
    print("downloading ABS")
    observations = fetch_abs(session, ingested)
    print(f"  ABS rows {len(observations)}")
    print("downloading GDP vintages")
    vintages = fetch_gdp_vintages(session, ingested)
    print(f"  vintage rows {len(vintages)}")
    print("downloading RBA")
    observations.extend(fetch_rba(session, ingested))
    frame = pd.DataFrame(observations)
    vintage_frame = pd.DataFrame(vintages)
    print(f"snapshot rows {len(frame)} vintages {len(vintage_frame)}")
    return write_snapshot(frame, vintage_frame, ingested)


def load_snapshot(directory: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    directory = directory or SNAPSHOT
    observations = pd.read_parquet(directory / "observations.parquet")
    vintages = pd.read_parquet(directory / "gdp_vintages.parquet")
    manifest = json.loads((directory / "manifest.json").read_text())
    return observations, vintages, manifest
