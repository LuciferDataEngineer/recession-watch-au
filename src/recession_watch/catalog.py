"""Series catalogue. Every entry is a free ABS or RBA table."""

from __future__ import annotations

# Verified release facts used as anchors. The pipeline checks the snapshot
# against these so a bad download cannot silently ship.
ANCHORS = {
    "unemployment_oct_2026": 4.9,
    "employment_change_oct_2026": -43500,
    "youth_unemployment_oct_2026": 11.3,
    "cpi_annual_sep_2026": 4.3,
    "gdp_qoq_2026q2": 0.4,
    "gdp_pc_qoq_2026q2": 0.0,
    "cash_rate_target": 4.85,
    "hsi_mom_sep_2026": 0.6,
}

STATES = {
    "1": "New South Wales",
    "2": "Victoria",
    "3": "Queensland",
    "4": "South Australia",
    "5": "Western Australia",
    "6": "Tasmania",
    "7": "Northern Territory",
    "8": "Australian Capital Territory",
    "AUS": "Australia",
}

STATE_SHORT = {
    "1": "NSW",
    "2": "VIC",
    "3": "QLD",
    "4": "SA",
    "5": "WA",
    "6": "TAS",
    "7": "NT",
    "8": "ACT",
    "AUS": "AUS",
}

# Natural Earth names -> ABS region code. NT and ACT have no seasonally
# adjusted labour-force series in the ABS SDMX labour-force dataflow.
STATE_NAME_TO_CODE = {name: code for code, name in STATES.items() if code != "AUS"}

INDUSTRY_NAMES = {
    "A": "Agriculture",
    "B": "Mining",
    "C": "Manufacturing",
    "E": "Construction",
    "F": "Wholesale",
    "G": "Retail",
    "H": "Hospitality",
    "I": "Transport",
    "K": "Finance",
    "L": "Property",
    "M": "Professional services",
    "Q": "Health",
    "R": "Arts and recreation",
    "S": "Other services",
}

# Seasonally adjusted GDP percentage changes in the National Accounts workbook.
GDP_SERIES_ID = "A2304370T"
GDP_PC_SERIES_ID = "A2304372W"

ABS_API = "https://data.api.abs.gov.au/rest/data"
RBA_CSV = "https://www.rba.gov.au/statistics/tables/csv"

SOURCES = [
    {
        "id": "abs-ana",
        "publisher": "Australian Bureau of Statistics",
        "title": "Australian National Accounts: National Income, Expenditure and Product",
        "url": "https://www.abs.gov.au/statistics/economy/national-accounts/australian-national-accounts-national-income-expenditure-and-product",
        "api": f"{ABS_API}/ABS,ANA_AGG",
        "licence": "CC BY 4.0",
        "coverage": "Quarterly GDP and GDP per capita, seasonally adjusted chain volume. Latest published quarter is June 2026 (released 2 Sep 2026). September quarter is scheduled for 2 Dec 2026, 11:30 am AEDT.",
        "free": True,
    },
    {
        "id": "abs-ana-vintages",
        "publisher": "Australian Bureau of Statistics",
        "title": "National Accounts key aggregates, release archive",
        "url": "https://www.abs.gov.au/statistics/economy/national-accounts/australian-national-accounts-national-income-expenditure-and-product/jun-2026/5206001_Key_Aggregates.xlsx",
        "licence": "CC BY 4.0",
        "coverage": "As-published GDP and GDP-per-capita growth from each quarter's key-aggregates workbook, used as real vintages.",
        "free": True,
    },
    {
        "id": "abs-sfd",
        "publisher": "Australian Bureau of Statistics",
        "title": "State final demand",
        "url": f"{ABS_API}/ABS,ANA_SFD",
        "licence": "CC BY 4.0",
        "coverage": "Quarterly chain-volume state final demand, seasonally adjusted, eight states and territories.",
        "free": True,
    },
    {
        "id": "abs-lf",
        "publisher": "Australian Bureau of Statistics",
        "title": "Labour Force, Australia",
        "url": "https://www.abs.gov.au/statistics/labour/employment-and-unemployment/labour-force-australia/latest-release",
        "api": f"{ABS_API}/ABS,LF",
        "licence": "CC BY 4.0",
        "coverage": "Monthly employment, unemployment rate and participation. October 2026 released 19 Nov 2026, 11:30 am AEDT. NT and ACT are the smoothed (trend) series because seasonally adjusted estimates are not in this dataflow.",
        "free": True,
    },
    {
        "id": "abs-lf-ages",
        "publisher": "Australian Bureau of Statistics",
        "title": "Labour Force by age",
        "url": f"{ABS_API}/ABS,LF_AGES",
        "licence": "CC BY 4.0",
        "coverage": "Monthly youth (15–24) unemployment rate, seasonally adjusted.",
        "free": True,
    },
    {
        "id": "abs-cpi",
        "publisher": "Australian Bureau of Statistics",
        "title": "Consumer Price Index, Australia",
        "url": "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia/latest-release",
        "api": f"{ABS_API}/ABS,CPI",
        "licence": "CC BY 4.0",
        "coverage": "Monthly CPI index and annual change, weighted average of eight capital cities. September 2026 released 28 Oct 2026.",
        "free": True,
    },
    {
        "id": "abs-hsi",
        "publisher": "Australian Bureau of Statistics",
        "title": "Monthly Household Spending Indicator",
        "url": "https://www.abs.gov.au/statistics/economy/finance/monthly-household-spending-indicator/latest-release",
        "api": f"{ABS_API}/ABS,HSI_M",
        "licence": "CC BY 4.0",
        "coverage": "Monthly household spending, current prices, seasonally adjusted. September 2026 released 4 Nov 2026.",
        "free": True,
    },
    {
        "id": "abs-ba",
        "publisher": "Australian Bureau of Statistics",
        "title": "Building Approvals, Australia",
        "url": "https://www.abs.gov.au/statistics/industry/building-and-construction/building-approvals-australia/latest-release",
        "api": f"{ABS_API}/ABS,BA_GCCSA",
        "licence": "CC BY 4.0",
        "coverage": "Monthly original counts of new houses and other new dwellings. The September 2026 release page is dated 9 Nov 2026. Seasonally adjusted totals are quoted from that release; the SDMX dataflow used here exposes the original counts.",
        "free": True,
    },
    {
        "id": "abs-qbis",
        "publisher": "Australian Bureau of Statistics",
        "title": "Business Indicators, Australia",
        "url": f"{ABS_API}/ABS,QBIS",
        "licence": "CC BY 4.0",
        "coverage": "Quarterly chain-volume sales growth by industry, seasonally adjusted, through June 2026.",
        "free": True,
    },
    {
        "id": "rba-f1",
        "publisher": "Reserve Bank of Australia",
        "title": "F1 and F1.1 Interest rates and yields – money market",
        "url": "https://www.rba.gov.au/statistics/tables/csv/f1-data.csv",
        "licence": "Reserve Bank of Australia copyright. Statistical tables may be reproduced freely with attribution to the Reserve Bank of Australia.",
        "coverage": "Daily cash-rate target (table published 20 Nov 2026) and the monthly cash-rate history in F1.1.",
        "free": True,
    },
    {
        "id": "rba-f2",
        "publisher": "Reserve Bank of Australia",
        "title": "F2 and F2.1 Capital market yields – government bonds",
        "url": "https://www.rba.gov.au/statistics/tables/csv/f2.1-data.csv",
        "licence": "Reserve Bank of Australia copyright. Statistical tables may be reproduced freely with attribution to the Reserve Bank of Australia.",
        "coverage": "Daily and monthly interpolated 2-year and 10-year Australian Government bond yields. Monthly history in the current file starts in 2013; daily yields through 18 Nov 2026.",
        "free": True,
    },
    {
        "id": "natural-earth",
        "publisher": "Natural Earth",
        "title": "Admin-1 states and provinces, 1:50m",
        "url": "https://www.naturalearthdata.com/downloads/50m-cultural-vectors/",
        "licence": "Public domain",
        "coverage": "State and territory boundaries used only to draw the map.",
        "free": True,
    },
]
