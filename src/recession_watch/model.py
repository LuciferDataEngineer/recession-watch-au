"""Mixed-frequency nowcast and a recession-odds model.

The growth estimate is a one-factor dynamic factor model (statsmodels
DynamicFactorMQ) on monthly activity and quarterly GDP. Recession odds come
from that estimate's historical miss size, plus a regularised logit on jobs,
the bond spread, building approvals and the cash rate.
"""

from __future__ import annotations

import warnings
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.statespace.dynamic_factor_mq import DynamicFactorMQ

from recession_watch.catalog import INDUSTRY_NAMES, STATE_SHORT, STATES
from recession_watch.vintage import asof, connect

FEATURE_COLUMNS = [
    "unemp_change",
    "emp_3m_pct",
    "approvals_yoy",
    "hsi_3m_pct",
    "cash_change_3m",
    "yield_spread",
]
# Household spending begins in the 2020s, so it is missing for the early part of
# the 2014-onwards sample. The factor model tolerates that. Starting in 2000
# made the EM step numerically unstable.
MODEL_START = "2014-01"
LOGIT_COLUMNS = ["sahm_gap", "yield_spread", "emp_3m_pct", "approvals_yoy", "cash_rate"]


def _monthly_last(frame: pd.DataFrame, series_id: str) -> pd.Series:
    subset = frame.loc[frame["series_id"] == series_id, ["period", "value"]].copy()
    if subset.empty:
        return pd.Series(dtype="float64")
    subset["month"] = subset["period"].str.slice(0, 7)
    subset = subset.sort_values("period").groupby("month", as_index=False).tail(1)
    index = pd.PeriodIndex(subset["month"], freq="M")
    series = pd.Series(subset["value"].to_numpy(dtype=float), index=index)
    return series.groupby(level=0).last().sort_index()


def _quarterly(frame: pd.DataFrame, series_id: str) -> pd.Series:
    subset = frame.loc[frame["series_id"] == series_id, ["period", "value"]].copy()
    if subset.empty:
        return pd.Series(dtype="float64")
    subset = subset[subset["period"].str.contains("-Q")]
    index = pd.PeriodIndex(subset["period"], freq="Q")
    series = pd.Series(subset["value"].to_numpy(dtype=float), index=index)
    return series.groupby(level=0).last().sort_index()


def activity_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Monthly model inputs, quarterly targets, and the wider monthly panel."""
    unemp = _monthly_last(frame, "lf_unemp_AUS")
    employed = _monthly_last(frame, "lf_employed_AUS")
    houses = _monthly_last(frame, "approvals_houses_AUS")
    other = _monthly_last(frame, "approvals_other_AUS")
    hsi = _monthly_last(frame, "hsi_AUS")
    cash = _monthly_last(frame, "cash_rate")
    if cash.empty:
        cash = _monthly_last(frame, "cash_rate_monthly")
    yield_2y = _monthly_last(frame, "yield_2y_daily").combine_first(_monthly_last(frame, "yield_2y"))
    yield_10y = _monthly_last(frame, "yield_10y_daily").combine_first(_monthly_last(frame, "yield_10y"))
    approvals = houses.add(other, fill_value=0) if not houses.empty else other
    approvals_3m = approvals.rolling(3, min_periods=3).sum()

    panel = pd.DataFrame(
        {
            "unemp": unemp,
            "employed": employed,
            "approvals": approvals,
            "hsi": hsi,
            "cash_rate": cash,
            "yield_2y": yield_2y,
            "yield_10y": yield_10y,
        }
    ).sort_index()
    panel["unemp_change"] = panel["unemp"].diff()
    panel["emp_3m_pct"] = panel["employed"].pct_change(3) * 100
    panel["approvals_yoy"] = approvals_3m.pct_change(12) * 100
    panel["hsi_3m_pct"] = panel["hsi"].pct_change(3) * 100
    panel["cash_change_3m"] = panel["cash_rate"].diff(3)
    panel["yield_spread"] = panel["yield_10y"] - panel["yield_2y"]
    ma3 = panel["unemp"].rolling(3, min_periods=3).mean()
    panel["sahm_gap"] = ma3 - ma3.shift(1).rolling(12, min_periods=12).min()

    quarterly = pd.DataFrame(
        {
            "gdp": _quarterly(frame, "gdp_qoq"),
            "gdp_pc": _quarterly(frame, "gdp_pc_qoq"),
        }
    ).sort_index()
    monthly = panel[FEATURE_COLUMNS].dropna(how="all")
    # Keep a little history before the factor sample so lags exist, then start
    # where unemployment changes are populated.
    if not monthly.empty:
        start = monthly["unemp_change"].first_valid_index()
        if start is not None:
            monthly = monthly.loc[start:]
    return monthly, quarterly, panel


def _extend_quarterly(quarterly: pd.DataFrame, extra: int = 2) -> pd.DataFrame:
    if quarterly.empty:
        return quarterly
    last = quarterly.index.max()
    future = pd.period_range(last + 1, periods=extra, freq="Q")
    return quarterly.reindex(quarterly.index.union(future))


def fit_factor_model(
    monthly: pd.DataFrame,
    quarterly: pd.DataFrame,
    maxiter: int,
) -> tuple[pd.DataFrame, object]:
    columns = [col for col in FEATURE_COLUMNS if col in monthly.columns]
    endog_m = monthly.loc[MODEL_START:, columns].copy()
    last_jobs = endog_m["unemp_change"].last_valid_index()
    if last_jobs is not None:
        endog_m = endog_m.loc[:last_jobs]
    endog_m = endog_m.dropna(how="all")
    usable = [col for col in endog_m.columns if endog_m[col].notna().sum() >= 24 and endog_m[col].std(skipna=True) > 1e-6]
    gdp = quarterly["gdp"].loc["2014Q1":]
    if len(usable) < 3 or gdp.notna().sum() < 16:
        raise RuntimeError("not enough history to fit the factor model")
    endog_q = _extend_quarterly(gdp.to_frame("gdp"), 2)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = DynamicFactorMQ(
            endog_m[usable],
            endog_quarterly=endog_q,
            factors=1,
            factor_orders=1,
            idiosyncratic_ar1=True,
            standardize=True,
        )
        result = model.fit(disp=False, maxiter=maxiter)
    return result.get_prediction().predicted_mean, result


def _at_quarter(predicted: pd.DataFrame, column: str, quarter: pd.Period) -> float:
    if column not in predicted.columns:
        return float("nan")
    index = predicted.index
    if isinstance(index, pd.PeriodIndex):
        periods = index.asfreq("M")
    else:
        periods = pd.PeriodIndex(pd.DatetimeIndex(index), freq="M")
    end = quarter.asfreq("M", how="end")
    rows = predicted.loc[periods == end, column]
    if rows.empty:
        return float("nan")
    return float(rows.iloc[-1])


def _normal_cdf(x: float) -> float:
    # Standard normal CDF via math.erf, no scipy requirement at the call site.
    from math import erf, sqrt

    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def contraction_probability(mean: float, scale: float) -> float:
    if not np.isfinite(mean) or not np.isfinite(scale) or scale <= 0:
        return float("nan")
    return float(_normal_cdf(-mean / scale))


def both_negative_probability(mean_a: float, mean_b: float, scale_a: float, scale_b: float, correlation: float = 0.35, draws: int = 20000) -> float:
    if not all(np.isfinite(v) for v in (mean_a, mean_b, scale_a, scale_b)):
        return float("nan")
    rng = np.random.default_rng(21)
    cov = correlation * scale_a * scale_b
    covariance = np.array([[scale_a**2, cov], [cov, scale_b**2]])
    sample = rng.multivariate_normal([mean_a, mean_b], covariance, size=draws)
    return float(np.mean((sample[:, 0] < 0) & (sample[:, 1] < 0)))


def _design(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    design = frame[columns].apply(pd.to_numeric, errors="coerce")
    design = sm.add_constant(design, has_constant="add")
    return design


def fit_logit(train: pd.DataFrame) -> object | None:
    clean = train.dropna()
    if len(clean) < 24 or clean["negative"].nunique() < 2:
        return None
    design = _design(clean, LOGIT_COLUMNS)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return sm.Logit(clean["negative"], design).fit_regularized(alpha=0.8, L1_wt=0.0, disp=False)
        except Exception:
            return None


def logit_probability(result, row: pd.Series) -> float:
    if result is None or row[LOGIT_COLUMNS].isna().any():
        return float("nan")
    design = _design(pd.DataFrame([row]), LOGIT_COLUMNS)
    design = design.reindex(columns=result.params.index, fill_value=0.0)
    return float(np.asarray(result.predict(design))[0])


def quarter_features(panel: pd.DataFrame, quarter: pd.Period) -> pd.Series:
    end = quarter.asfreq("M", how="end")
    if end not in panel.index:
        earlier = panel.loc[:end]
        if earlier.empty:
            return pd.Series(dtype="float64")
        return earlier.iloc[-1]
    return panel.loc[end]


def _ar1_predict(history: pd.Series) -> float:
    series = history.dropna()
    if len(series) < 8:
        return float(series.mean()) if len(series) else float("nan")
    lagged = series.shift(1)
    paired = pd.concat([series, lagged], axis=1).dropna()
    y = paired.iloc[:, 0].to_numpy()
    x = np.column_stack([np.ones(len(paired)), paired.iloc[:, 1].to_numpy()])
    beta = np.linalg.lstsq(x, y, rcond=None)[0]
    last = float(series.iloc[-1])
    return float(beta[0] + beta[1] * last)


def _bridge_predict(history: pd.DataFrame, current: pd.Series) -> float:
    clean = history.dropna()
    if len(clean) < 16 or clean["gdp"].nunique() < 3:
        return float("nan")
    needed = ["emp_3m_pct", "approvals_yoy", "unemp_change"]
    if any(not np.isfinite(current.get(column, np.nan)) for column in needed):
        return float("nan")
    y = clean["gdp"].to_numpy()
    x = np.column_stack([np.ones(len(clean)), clean[needed].to_numpy()])
    beta = np.linalg.lstsq(x, y, rcond=None)[0]
    features = [1.0, *[float(current[column]) for column in needed]]
    return float(np.dot(beta, features))


def nowcast_at(
    frame: pd.DataFrame,
    maxiter: int,
    quarters: list[pd.Period] | None = None,
) -> dict:
    monthly, quarterly, panel = activity_frame(frame)
    predicted, _result = fit_factor_model(monthly, quarterly, maxiter=maxiter)
    last_known = quarterly["gdp"].last_valid_index()
    gap = (quarterly["gdp"] - quarterly["gdp_pc"]).dropna()
    if last_known is not None:
        gap = gap.loc[gap.index <= last_known]
    population_growth = float(gap.tail(4).mean()) if len(gap) else 0.0
    if quarters is None:
        quarters = [last_known + 1, last_known + 2] if last_known is not None else []
    points = {}
    for quarter in quarters:
        growth = _at_quarter(predicted, "gdp", quarter)
        points[str(quarter)] = {
            "gdp": growth,
            "gdp_pc": growth - population_growth,
            "population_growth": population_growth,
        }
    return {
        "points": points,
        "last_gdp_quarter": str(last_known) if last_known is not None else None,
        "panel": panel,
        "quarterly": quarterly,
        "monthly_columns": list(monthly.columns),
    }


def _vintage_quarter(vintage_id: str) -> str | None:
    slug = vintage_id.split("abs-ana-")[-1].replace("-approx", "")
    parts = slug.split("-")
    if len(parts) != 2:
        return None
    month, year = parts
    quarter = {"mar": "Q1", "jun": "Q2", "sep": "Q3", "dec": "Q4"}.get(month)
    if quarter is None:
        return None
    return f"{year}-{quarter}"


def run_backtest(observations: pd.DataFrame, vintages: pd.DataFrame, as_of: datetime, maxiter: int) -> pd.DataFrame:
    """Rolling-origin nowcast scored against the first-published GDP print.

    A print counts as first-published only when it comes from that quarter's own
    National Accounts workbook, not from a later vintage that revised history.
    """
    published = vintages.loc[vintages["series_id"] == "gdp_qoq"].copy()
    published["publication_time"] = pd.to_datetime(published["publication_time"], utc=True)
    published["vintage_quarter"] = published["vintage_id"].map(_vintage_quarter)
    first = published.loc[published["vintage_quarter"] == published["period"]].copy()
    first = first.sort_values("period")
    first = first.loc[first["period"] >= "2019-Q3"].copy()
    con = connect(observations, vintages)
    rows = []
    for record in first.itertuples(index=False):
        release = record.publication_time.to_pydatetime()
        origin = release - timedelta(days=14)
        if origin > as_of:
            continue
        known = asof(con, origin)
        # The quarter under review must not already be in the information set.
        leaked = known.loc[
            (known["series_id"] == "gdp_qoq") & (known["period"] == record.period),
            "value",
        ]
        if not leaked.empty:
            continue
        quarter = pd.Period(record.period, freq="Q")
        try:
            cast = nowcast_at(known, maxiter=maxiter, quarters=[quarter])
        except Exception:
            continue
        point = cast["points"].get(str(quarter), {})
        estimate = point.get("gdp", float("nan"))
        if not np.isfinite(estimate):
            continue
        panel = cast["panel"]
        quarterly = cast["quarterly"]["gdp"].dropna()
        quarterly = quarterly.loc[quarterly.index < pd.Period(record.period, freq="Q")]
        history_rows = []
        for quarter, actual in quarterly.items():
            feat = quarter_features(panel, quarter)
            history_rows.append(
                {
                    "gdp": float(actual),
                    "emp_3m_pct": feat.get("emp_3m_pct", np.nan),
                    "approvals_yoy": feat.get("approvals_yoy", np.nan),
                    "unemp_change": feat.get("unemp_change", np.nan),
                }
            )
        history = pd.DataFrame(history_rows)
        current_feat = quarter_features(panel, pd.Period(record.period, freq="Q"))
        rows.append(
            {
                "period": record.period,
                "origin": origin.isoformat(),
                "actual_first_print": float(record.value),
                "dfm": float(estimate),
                "ar1": _ar1_predict(quarterly),
                "bridge": _bridge_predict(history, current_feat),
                "mean": float(quarterly.mean()) if len(quarterly) else float("nan"),
                "sahm_gap": float(current_feat.get("sahm_gap", np.nan)),
                "yield_spread": float(current_feat.get("yield_spread", np.nan)),
                "emp_3m_pct": float(current_feat.get("emp_3m_pct", np.nan)),
                "approvals_yoy": float(current_feat.get("approvals_yoy", np.nan)),
                "cash_rate": float(current_feat.get("cash_rate", np.nan)),
                "negative": int(float(record.value) < 0),
            }
        )
    con.close()
    return pd.DataFrame(rows)


def _rmse(frame: pd.DataFrame, column: str) -> float:
    error = frame[column] - frame["actual_first_print"]
    error = error[np.isfinite(error)]
    if error.empty:
        return float("nan")
    return float(np.sqrt(np.mean(np.square(error))))


def _brier(probability: pd.Series, outcome: pd.Series) -> float:
    paired = pd.concat([probability, outcome], axis=1).dropna()
    if paired.empty:
        return float("nan")
    return float(np.mean(np.square(paired.iloc[:, 0] - paired.iloc[:, 1])))


def score_backtest(backtest: pd.DataFrame) -> dict:
    if backtest.empty:
        return {"n": 0}
    dfm_prob = []
    logit_prob = []
    base_prob = []
    expanding_errors: list[float] = []
    for index, row in backtest.iterrows():
        calm = [err for err in expanding_errors if abs(err) <= 2]
        if len(calm) >= 8:
            scale = float(np.sqrt(np.mean(np.square(calm))))
        else:
            scale = 0.40
        dfm_prob.append(contraction_probability(row["dfm"], scale))
        train = backtest.loc[backtest.index < index]
        result = fit_logit(train.rename(columns={})) if "negative" in train else None
        # fit_logit expects column negative plus LOGIT columns
        logit_prob.append(logit_probability(result, row))
        base = float(train["negative"].mean()) if len(train) else 0.15
        base_prob.append(base)
        expanding_errors.append(float(row["dfm"] - row["actual_first_print"]))
    scored = backtest.copy()
    scored["p_dfm"] = dfm_prob
    scored["p_logit"] = logit_prob
    scored["p_base"] = base_prob
    recent = backtest.loc[backtest["period"] >= "2023-Q1"]
    return {
        "n": int(len(backtest)),
        "n_recent": int(len(recent)),
        "rmse_dfm": _rmse(backtest, "dfm"),
        "rmse_ar1": _rmse(backtest, "ar1"),
        "rmse_bridge": _rmse(backtest, "bridge"),
        "rmse_mean": _rmse(backtest, "mean"),
        "rmse_dfm_recent": _rmse(recent, "dfm"),
        "rmse_ar1_recent": _rmse(recent, "ar1"),
        "rmse_bridge_recent": _rmse(recent, "bridge"),
        "rmse_mean_recent": _rmse(recent, "mean"),
        "brier_dfm": _brier(scored["p_dfm"], scored["negative"]),
        "brier_logit": _brier(scored["p_logit"], scored["negative"]),
        "brier_base": _brier(scored["p_base"], scored["negative"]),
        "brier_dfm_recent": _brier(scored.loc[recent.index, "p_dfm"], scored.loc[recent.index, "negative"]),
        "brier_logit_recent": _brier(scored.loc[recent.index, "p_logit"], scored.loc[recent.index, "negative"]),
        "correlation_errors": _error_correlation(recent if len(recent) >= 8 else backtest),
    }


def _error_correlation(backtest: pd.DataFrame) -> float:
    error = (backtest["dfm"] - backtest["actual_first_print"]).to_numpy()
    if len(error) < 6:
        return 0.35
    a, b = error[1:], error[:-1]
    if np.std(a) == 0 or np.std(b) == 0:
        return 0.35
    return float(np.corrcoef(a, b)[0, 1])


def _pct_change(latest: float, previous: float) -> float:
    if previous == 0 or not np.isfinite(latest) or not np.isfinite(previous):
        return float("nan")
    return (latest / previous - 1.0) * 100


def _last_two(series: pd.Series, steps: int) -> tuple[float, float]:
    clean = series.dropna()
    if len(clean) <= steps:
        return float("nan"), float("nan")
    return float(clean.iloc[-1]), float(clean.iloc[-1 - steps])


def state_exposure(frame: pd.DataFrame) -> list[dict]:
    rows = []
    for code, name in STATES.items():
        if code == "AUS":
            continue
        employed = _monthly_last(frame, f"lf_employed_{code}")
        unemp = _monthly_last(frame, f"lf_unemp_{code}")
        sfd = _quarterly(frame, f"sfd_{code}")
        approvals = _monthly_last(frame, f"approvals_houses_{code}").add(
            _monthly_last(frame, f"approvals_other_{code}"), fill_value=0
        )
        emp_now, emp_then = _last_two(employed, 3)
        unemp_now, unemp_then = _last_two(unemp, 3)
        sfd_now, sfd_then = _last_two(sfd, 1)
        app_now, app_then = _last_two(approvals.rolling(3, min_periods=3).sum(), 12)
        rows.append(
            {
                "code": code,
                "name": name,
                "short": STATE_SHORT[code],
                "jobs_3m_pct": _pct_change(emp_now, emp_then),
                "unemp": unemp_now,
                "unemp_change": unemp_now - unemp_then if np.isfinite(unemp_now) and np.isfinite(unemp_then) else float("nan"),
                "sfd_qoq": _pct_change(sfd_now, sfd_then),
                "approvals_yoy": _pct_change(app_now, app_then),
                "jobs_basis": "smoothed" if code in {"7", "8"} else "seasonally adjusted",
                "jobs_month": str(employed.dropna().index.max()) if not employed.dropna().empty else "",
                "sfd_quarter": str(sfd.dropna().index.max()) if not sfd.dropna().empty else "",
            }
        )
    pressure_inputs = {
        "jobs_3m_pct": False,  # lower (job losses) means more pressure
        "unemp_change": True,
        "sfd_qoq": False,
        "approvals_yoy": False,
    }
    table = pd.DataFrame(rows)
    ranks = []
    for column, higher_is_pressure in pressure_inputs.items():
        values = table[column]
        # Percentile rank. Missing values stay missing and are skipped later.
        rank = values.rank(pct=True, ascending=higher_is_pressure)
        ranks.append(rank)
    rank_frame = pd.concat(ranks, axis=1)
    table["pressure"] = rank_frame.mean(axis=1, skipna=True) * 100
    table = table.sort_values("pressure", ascending=False)
    return table.to_dict(orient="records")


def industry_exposure(frame: pd.DataFrame) -> list[dict]:
    rows = []
    for code, name in INDUSTRY_NAMES.items():
        series = _quarterly(frame, f"sales_{code}")
        clean = series.dropna()
        if clean.empty:
            continue
        rows.append(
            {
                "code": code,
                "name": name,
                "sales_qoq": float(clean.iloc[-1]),
                "quarter": str(clean.index.max()),
            }
        )
    rows.sort(key=lambda row: row["sales_qoq"])
    return rows


def latest_signal(panel: pd.DataFrame) -> dict:
    if panel.empty:
        return {}
    jobs = panel.dropna(subset=["unemp"])
    latest_jobs = jobs.iloc[-1] if len(jobs) else pd.Series(dtype=float)
    unemp = panel["unemp"].dropna()
    hsi = panel["hsi"].dropna()
    return {
        "month": str(jobs.index.max()) if len(jobs) else "",
        "unemp": float(unemp.iloc[-1]) if len(unemp) else float("nan"),
        "unemp_prev": float(unemp.iloc[-2]) if len(unemp) > 1 else float("nan"),
        "sahm_gap": float(latest_jobs.get("sahm_gap", np.nan)),
        "yield_spread": float(panel["yield_spread"].dropna().iloc[-1]) if panel["yield_spread"].notna().any() else float("nan"),
        "yield_month": str(panel["yield_spread"].dropna().index.max()) if panel["yield_spread"].notna().any() else "",
        "cash_rate": float(panel["cash_rate"].dropna().iloc[-1]) if panel["cash_rate"].notna().any() else float("nan"),
        "emp_3m_pct": float(latest_jobs.get("emp_3m_pct", np.nan)),
        "approvals_yoy": float(panel["approvals_yoy"].dropna().iloc[-1]) if panel["approvals_yoy"].notna().any() else float("nan"),
        "hsi_3m_pct": float(panel["hsi_3m_pct"].dropna().iloc[-1]) if panel["hsi_3m_pct"].notna().any() else float("nan"),
        "hsi_mom": _pct_change(float(hsi.iloc[-1]), float(hsi.iloc[-2])) if len(hsi) > 1 else float("nan"),
        "employed": float(panel["employed"].dropna().iloc[-1]) if panel["employed"].notna().any() else float("nan"),
        "employed_prev": float(panel["employed"].dropna().iloc[-2]) if panel["employed"].dropna().shape[0] > 1 else float("nan"),
    }
