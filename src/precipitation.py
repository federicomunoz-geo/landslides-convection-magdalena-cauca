"""CHIRPS accumulated precipitation and its historical percentile.

Precipitation is extracted with CDO (Climate Data Operators), averaging the
CHIRPS pixels within ``radius_km`` of the landslide. CDO must be installed and
available on the PATH (it is Linux/macOS software; on Windows use WSL).

Five time scales are evaluated. For each one, the accumulated precipitation
before the landslide is compared against a "population" of accumulations
built from 2011-2023 for the same location and season, and its percentile is
computed. A value above P90 is considered atypical precipitation.

The window definitions below are exactly the ones used in the thesis.
"""
import calendar
import subprocess
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

# Accumulation window before the landslide (start offset in days, end = landslide day)
ACCUMULATION_WINDOWS = {
    "Dia": 0,       # landslide day
    "2Dia": 1,      # previous day + landslide day
    "week": 7,
    "Mon": 30,
    "3Mon": 90,
}


# ----------------------------------------------------------------------------- CDO helper
def cdo_sum(nc_file, lat, lon, start: date, end: date, radius_km=10) -> float:
    """Sum over [start, end] of the spatial mean of CHIRPS within radius_km."""
    dates = start.isoformat() if start == end else f"{start.isoformat()},{end.isoformat()}"
    cmd = ["cdo", "-s", "output", "-timsum", "-fldmean",
           f"-selcircle,lon={lon},lat={lat},radius={radius_km}km",
           f"-seldate,{dates}", str(nc_file)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
        return float(out) if out else np.nan
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
        return np.nan


# ----------------------------------------------------------------------------- accumulations
def accumulated_precipitation(results: pd.DataFrame, chirps_dir, lat_col, lon_col,
                              radius_km=10) -> pd.DataFrame:
    """Add Precip_Acum_<scale> columns using the yearly CHIRPS files."""
    out = results.copy()
    for scale in ACCUMULATION_WINDOWS:
        out[f"Precip_Acum_{scale}"] = np.nan

    for idx, row in out.iterrows():
        d = pd.to_datetime(row["Fecha"]).date()
        nc = Path(chirps_dir) / f"Rectangulo_Cuenca_en_p05_{d.year}.nc"
        if not nc.is_file():
            continue
        for scale, days in ACCUMULATION_WINDOWS.items():
            out.at[idx, f"Precip_Acum_{scale}"] = cdo_sum(
                nc, row[lat_col], row[lon_col], d - timedelta(days=days), d, radius_km)
    return out


# ----------------------------------------------------------------------------- populations
def windows_day(d: date, years):
    """Every single day of the landslide's month, for every year."""
    for y in years:
        for day in range(1, calendar.monthrange(y, d.month)[1] + 1):
            x = date(y, d.month, day)
            yield x, x


def windows_2days(d: date, years):
    """15 consecutive, non-overlapping 2-day pairs starting on day 1 of the
    month (pairs may spill into the next month)."""
    for y in years:
        first = date(y, d.month, 1)
        for i in range(15):
            start = first + timedelta(days=2 * i)
            yield start, start + timedelta(days=1)


def windows_week(d: date, years):
    """Monday-to-Sunday weeks that overlap the landslide's month."""
    for y in years:
        first = date(y, d.month, 1)
        last = date(y, d.month, calendar.monthrange(y, d.month)[1])
        start = first - timedelta(days=first.weekday())
        while start <= last:
            yield start, start + timedelta(days=6)
            start += timedelta(days=7)


def _centered_windows(d: date, years, length):
    """Three windows per year around the same calendar day: before, centred, after."""
    half = length // 2
    for y in years:
        ref = date(y, d.month, d.day)
        yield ref - timedelta(days=length), ref
        yield ref - timedelta(days=half), ref + timedelta(days=half - 1)
        yield ref, ref + timedelta(days=length)


def windows_month(d, years):
    return _centered_windows(d, years, 30)


def windows_3months(d, years):
    return _centered_windows(d, years, 90)


POPULATIONS = {
    "Dia": ("Percentil_Dia", windows_day),
    "2Dia": ("Percentil_2dias", windows_2days),
    "week": ("Percentil_Week", windows_week),
    "Mon": ("Percentil_Mes", windows_month),
    "3Mon": ("Percentil_Tri_Mes", windows_3months),
}


def _percentile_task(args):
    value, d, lat, lon, scale, total_nc, years, radius_km = args
    if pd.isnull(value) or pd.isnull(lat) or pd.isnull(lon):
        return np.nan
    builder = POPULATIONS[scale][1]
    try:
        population = np.array([cdo_sum(total_nc, lat, lon, a, b, radius_km)
                               for a, b in builder(d, years)])
    except ValueError:          # e.g. 29 February in a non-leap year
        return np.nan
    population = population[~np.isnan(population)]
    if len(population) == 0:
        return np.nan
    return stats.percentileofscore(population, value, kind="rank")


# ----------------------------------------------------------------------------- Python backend
class SeriesStore:
    """Fast window sums over the per-location daily series built by chirps_extract.py.

    ``window_sum`` mimics ``cdo timsum -seldate,a,b``: days outside the series are
    ignored and the result is NaN only when no valid day falls in the window.
    """

    def __init__(self, series: pd.DataFrame):
        idx = pd.to_datetime(series.index)
        if not (idx.to_series().diff().dropna() == pd.Timedelta(days=1)).all():
            raise ValueError("the series must have one row per consecutive day")
        self.first, self.n = idx[0].date(), len(idx)
        self.col = {c: i for i, c in enumerate(series.columns)}
        v = series.to_numpy(dtype=float)
        zeros = np.zeros((1, v.shape[1]))
        self.csum = np.vstack([zeros, np.nancumsum(v, axis=0)])
        self.ccnt = np.vstack([zeros, np.cumsum(~np.isnan(v), axis=0)])

    @classmethod
    def from_csv(cls, path):
        return cls(pd.read_csv(path, index_col=0))

    def window_sum(self, key, a: date, b: date, clip_year=None) -> float:
        if clip_year is not None:                       # emulate one CHIRPS file per year
            a = max(a, date(clip_year, 1, 1))
            b = min(b, date(clip_year, 12, 31))
        i = max((a - self.first).days, 0)
        j = min((b - self.first).days, self.n - 1)
        c = self.col[key]
        if i > j or self.ccnt[j + 1, c] - self.ccnt[i, c] == 0:
            return np.nan
        return self.csum[j + 1, c] - self.csum[i, c]


def precipitation_from_series(results: pd.DataFrame, store: SeriesStore, lat_col, lon_col,
                              years=range(2011, 2024)) -> pd.DataFrame:
    """Accumulations and percentiles without CDO (same windows as the CDO backend)."""
    from chirps_extract import point_key

    out = results.copy()
    for scale, days in ACCUMULATION_WINDOWS.items():
        acc, pct = [], []
        col = POPULATIONS[scale][0]
        builder = POPULATIONS[scale][1]
        for _, row in out.iterrows():
            d = pd.to_datetime(row["Fecha"]).date()
            key = point_key(row[lat_col], row[lon_col])
            value = store.window_sum(key, d - timedelta(days=days), d, clip_year=d.year)
            acc.append(value)
            if np.isnan(value):
                pct.append(np.nan)
                continue
            try:
                population = np.array([store.window_sum(key, a, b) for a, b in builder(d, years)])
            except ValueError:                           # 29 February in a non-leap year
                pct.append(np.nan)
                continue
            population = population[~np.isnan(population)]
            pct.append(stats.percentileofscore(population, value, kind="rank") if len(population) else np.nan)
        out[f"Precip_Acum_{scale}"] = acc
        out[col] = pct
    return out


def precipitation_percentiles(results: pd.DataFrame, total_nc, lat_col, lon_col,
                              years=range(2011, 2024), radius_km=10) -> pd.DataFrame:
    """Add the percentile columns, computed in parallel (one process per CPU)."""
    out = results.copy()
    with ProcessPoolExecutor() as pool:
        for scale, (col, _) in POPULATIONS.items():
            tasks = [(row[f"Precip_Acum_{scale}"], pd.to_datetime(row["Fecha"]).date(),
                      row[lat_col], row[lon_col], scale, str(total_nc), list(years), radius_km)
                     for _, row in out.iterrows()]
            out[col] = list(pool.map(_percentile_task, tasks))
    return out
