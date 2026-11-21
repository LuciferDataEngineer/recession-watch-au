# Methods and results

Snapshot time: 2026-11-21T22:23:54Z, which is 22 November 2026, 9:23 am Australian Eastern Daylight Time. All growth rates are quarter-on-quarter unless noted. “Shrinking” means a negative rate.

## What was published, and what we estimated

Official, from the ABS and the RBA, checked by `tests/test_quality.py`:

| Fact | Value | Source |
| --- | --- | --- |
| Unemployment rate, October 2026, seasonally adjusted | 4.9% (unrounded 4.865%). September was 4.7% (4.742%). Highest since October 2021. | ABS Labour Force, released 19 Nov 2026, 11:30 am AEDT |
| Employed people, October minus September | −43,531 people, which the ABS rounds to −43,500 | Same release. Levels are 14,738,637 and 14,782,168. |
| Youth unemployment, 15–24, October | 11.3% (unrounded 11.250%) | ABS Labour Force by age |
| CPI, year to September 2026 | 4.3%. The September quarter itself was +1.3%. | ABS CPI, released 28 Oct 2026. Trimmed mean 3.6% is on the release and is not a model input. |
| Cash-rate target | 4.85% from 4 November 2026, up 0.25 from 4.60% | RBA decision of 3 November 2026. Next decision 8 December 2026. |
| Real GDP, June quarter 2026 | +0.4%. Through the year +2.1%. | ABS National Accounts, released 2 Sep 2026, 11:30 am AEST |
| GDP per person, June quarter 2026 | 0.0% (the Bureau’s rounded figure). March quarter was −0.1%. | Same release |
| Household spending, September, seasonally adjusted | +0.6% on the month, to $82,610.8 million | ABS Monthly Household Spending Indicator, released 4 Nov 2026 |
| 10-year minus 2-year bond yield, 18 Nov 2026 | 5.080 − 4.813 = +0.27 percentage points | RBA table F2, file publication date 20 Nov 2026 |

The September-quarter national accounts are scheduled for **2 December 2026, 11:30 am AEDT**. They are not in this snapshot.

Westpac’s note of 20 November 2026, “Westpac Nowcast Q3 2026: Final estimate”, says their model points to about 0.5% growth in the September quarter (70% interval 0.1% to 0.9%), a model-implied chance of a negative quarter of about 16% for September and 30% for December, and a technical-recession chance of about 5–6%. Those numbers are theirs. They are cited so a reader can compare, not as inputs.

## Bitemporal store

Two clocks:

- **Valid time** is the period the number describes (`2026-10`, `2026-Q2`).
- **Transaction time** is `publication_time`, when that vintage became public.

GDP vintages are the key-aggregates workbook from each quarter’s own release page, June 2019 through June 2026 (29 releases; the March 2025 page also hosts a mock workbook, which is ignored). The release timestamp is parsed from the page (“Release date and time”). Series ids `A2304370T` (GDP growth, seasonally adjusted) and `A2304372W` (GDP per person) are stable across the xlsx and the older xls files.

A quarter counts as a first print only when the vintage id matches that quarter (`abs-ana-jun-2026` is the first print of 2026-Q2, not a revision of 2019). Later workbooks also contain revised history. The as-of query keeps the latest vintage whose publication time is on or before the origin, so a backtest dated 19 February 2025 cannot see the 5 March 2025 release.

For series that the API publishes only as a latest vintage, `publication_time` is the reference-period end plus the lag that matches the current release calendar:

| Series | Lag rule | Checked against |
| --- | --- | --- |
| Labour force | Month-end + 19 days, 11:30 Australia/Sydney | October 2026 released 19 Nov 2026 |
| CPI | Last Wednesday of the next month, 11:30 | September 2026 released 28 Oct 2026 |
| Household spending | Month-end + 35 days | September 2026 released 4 Nov 2026 |
| Building approvals | Month-end + 40 days | September 2026 page dated 9 Nov 2026 |
| State final demand and the API copy of GDP | Quarter-end + 64 days | June 2026 released 2 Sep 2026 |
| Business sales | Quarter-end + 58 days | A few days before the national accounts |
| Cash rate and bond yields | The day of the observation | They are market or policy rates, public that day |

This is pseudo-real-time for those series: the value is today’s revised value, revealed on the historical release lag. It is not a revision history. GDP is the exception, and it is the series the backtest scores.

## Growth model

`DynamicFactorMQ` (Bańbura and Modugno, the statsmodels implementation) with:

- one factor, AR(1)
- idiosyncratic AR(1)
- standardisation inside the estimation sample
- monthly block from January 2014 through the last month with an unemployment figure (October 2026 in this snapshot)
- quarterly block: real GDP growth, missing for the quarters being estimated

Monthly inputs: unemployment-rate change, three-month employment percent change, year-on-year change in a three-month sum of new dwelling approvals (houses plus other, original), three-month percent change in household spending, three-month change in the cash-rate target, and the 10-year minus 2-year yield. Household spending is missing for the early part of the sample; the filter allows that. Starting the sample in 2000 made the EM step return values in the millions, so it was rejected. EM iterations are capped at 15 for the published estimate and 8 for each backtest origin. The fit is not driven to a 1e-6 tolerance.

In-sample, the October-2026 information set reproduces the June quarter at 0.42 against the published 0.4. The estimates beyond the last print are:

| Quarter | GDP | GDP per person |
| --- | --- | --- |
| September 2026 | +0.25% | −0.13% |
| December 2026 | +0.05% | −0.32% |

The dashboard rounds those to +0.2%, +0.1%, −0.1% and −0.3%.

GDP per person equals the GDP estimate minus 0.375 percentage points. That 0.375 is the average, over the last four published quarters, of GDP growth minus GDP-per-person growth. It is the population growth implied by the accounts (June quarter: 0.4 − 0.0 = 0.4; March: 0.3 − (−0.1) = 0.4; December 2025: 0.9 − 0.6 = 0.3; September 2025: 0.5 − 0.1 = 0.4).

The 70% range drawn on the chart is the estimate ± 1.036 times the since-2023 root-mean-square error (0.21 points), and 1.15 times that for the December quarter because it is one step further. On the page that is about 0.0% to +0.5% for September and −0.2% to +0.3% for December.

## Chances

Assume a normal miss with that scale, and a correlation of successive misses of 0.06 (the since-2023 figure). The joint chance uses 20,000 paired draws with a fixed seed.

| Event | Chance |
| --- | --- |
| September quarter GDP shrinks | 12% |
| December quarter GDP shrinks | 41% |
| Both shrink (technical recession) | 5% |
| Both per-person figures shrink | 67% |
| Logit, “the next GDP print shrinks” | 1% |

The December chance is high because +0.05% is inside the usual miss. The technical-recession chance stays low because September is still clearly positive, and the two misses are only weakly related. The per-person chance is high because both per-person estimates are already negative.

The logit (L2-regularised, `alpha=0.8`) uses the unemployment gap, the bond spread, three-month jobs growth, approvals growth and the cash rate. At the October feature row the unemployment gap is **+0.60 percentage points** (three-month average unemployment minus the lowest three-month average in the previous year). The bond gap is **+0.27 points** and is not inverted. Jobs over three months are **−0.34%**. Approvals are still up about **5%** on a year earlier. That mix has rarely been followed by a negative quarter in this sample, so the logit says 1%. The disagreement with the 41% is real: one number says “the estimate is close to zero”, the other says “indicators that look like this have usually still produced a small positive”. Both are on the dashboard. Neither is a policy recommendation.

## Backtest

28 first prints, 2019-Q3 through 2026-Q2. Origin is 14 days before the release parsed from that quarter’s page. Three benchmarks:

- **AR(1):** this quarter equals a fitted function of the previous quarter only.
- **Bridge:** a linear regression of GDP growth on three-month jobs growth, approvals growth and the monthly unemployment change, fitted on earlier quarters and applied to the target quarter’s features.
- **Mean:** the average of GDP growth in the vintages available at the origin.

Root-mean-square error, percentage points:

| | Factor model | AR(1) | Bridge | Mean |
| --- | ---: | ---: | ---: | ---: |
| All 28 quarters | 2.33 | 1.84 | 1.38 | 1.83 |
| 14 quarters from 2023-Q1 | 0.21 | 0.55 | 0.51 | 0.51 |

The factor model is best since 2023 (bias of the miss about +0.05 points, so it has not been systematically high or low by much). It is worst over the full window because 2020-Q2 was a first print of −7.0% and the model, using data available before that release, still said about +0.3%. The rebound prints (2020-Q3 +3.3%, 2020-Q4 +3.1%) were also missed. A one-factor model of ordinary monthly indicators is not a model of a lockdown.

Brier score for the probability that the quarter shrinks (lower is better; a coin flip is 0.25):

| | Factor-model chance | Logit | Constant base rate |
| --- | ---: | ---: | ---: |
| All 28 quarters | 0.23 | 0.0002 | 0.12 |
| From 2023 | 0.10 | 0.0002 | — |

The logit’s score is not evidence of sharp timing. After 2021 every outcome is “did not shrink”, and the logit’s probability sits near zero, so the squared error is tiny. It also did not have many recessions to learn. The factor-model chance looks worse on the full sample because it assigned meaningful odds to ordinary quarters and still missed 2020. Since 2023, with the calm error scale, a nowcast of +0.4% implies only a small chance of a negative print, and there were no negative prints, so the score improves.

## Where it would hit

State pressure is the average of four percentile ranks across the eight states. It is a ordering, not a probability.

| State | Jobs, 3 months | Unemployment | Unemployment change, 3 months | June-quarter demand | Home approvals, year | Pressure |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| NSW | −0.94% | 4.63% | +0.36 | +0.03% | +5.7% | 72 |
| Victoria | +0.30% | 5.39% | +0.27 | −0.34% | −2.5% | 69 |
| Tasmania | −1.29% | 5.35% | +0.32 | +0.08% | +14% | 66 |
| Queensland | −0.48% | 4.81% | +0.56 | +1.13% | −1.7% | 63 |
| South Australia | −0.30% | 4.80% | +0.66 | 0.00% | +32% | 63 |
| Northern Territory | −0.92% | 5.01% | +0.23 | +1.36% | +5.4% | 47 |
| ACT | +0.10% | 4.21% | +0.08 | +0.68% | −1.7% | 47 |
| Western Australia | +1.11% | 4.47% | +0.10 | +1.04% | +21% | 25 |

NT and ACT jobs and unemployment are the smoothed series. The others are seasonally adjusted. October’s national fall of 43,500 is not a Victorian story: Victoria’s unemployment is the highest, and it was the only state with falling June-quarter demand, but its job count over three months is up. NSW combines a jobs decline with little demand growth. WA is the clear exception, with rising jobs and rising demand.

Industry sales volumes, June quarter, chain volume, seasonally adjusted, from the business-indicators dataflow:

| Industry | Quarterly change |
| --- | ---: |
| Arts and recreation | −0.3% |
| Manufacturing | −0.1% |
| Property | −0.1% |
| Finance | 0.0% |
| Retail | +0.4% |
| Construction | +0.5% |
| Hospitality | +0.5% |
| Wholesale | +0.6% |
| Other services | +1.0% |
| Transport | +1.2% |
| Professional services | +2.3% |
| Mining | +3.3% |

June was not an industry collapse. Three groups were at or under zero. The sharper turn is the labour-force release that came after that quarter.

## What a user should watch

1. The 2 December national accounts. A September print below zero would put a technical recession one quarter away. A print near +0.2% would match this estimate.
2. The unemployment gap, currently +0.6 points above its low of the past year. The US rule of thumb is half a point; that threshold is not an Australian law, and it is already met.
3. The bond gap. It is still positive (+0.3 points on the monthly/daily mix shown on the page, +0.27 on 18 November). An inversion would be new information. It has not happened.
4. Whether employment keeps falling. Two large monthly declines are already in the data (September and October).
5. Inflation. 4.3% is why the cash rate is 4.85% while hiring is falling. The next cash-rate decision is 8 December, six days after the GDP release.

## Reproducibility

`make run` rebuilds `site/index.html`, `data/gold/summary.json` and `artifacts/engine_benchmark.json` from `data/snapshot/` with no network. `make snapshot` re-downloads. The Hamilton graph is `artifacts/hamilton_lineage.png`.
