"""Spatio-temporal association between landslides and deep convective events.

For every landslide, all convective events that occurred within ``days_before``
days before (and including) the landslide date and within ``radius_km`` of the
landslide are counted. When more than one event matches, the event with the
largest area is kept as the representative event.
"""
from datetime import timedelta

import numpy as np
import pandas as pd
from geopy.distance import geodesic
from scipy import stats

EVENT_COLUMNS = ["LAT_MIN", "LON_MIN", "TEMP_MIN", "DURATION_H", "AREA_KM2", "FECHA_MIN"]


def load_landslides(path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["Fecha"] = pd.to_datetime(df["Fecha"]).dt.date
    return df


def load_convective_events(path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["FECHA_MIN"] = pd.to_datetime(df["FECHA_MIN"]).dt.date
    if "ID_Con" not in df.columns:
        df = df.reset_index().rename(columns={"index": "ID_Con"})
    df["ID_Con"] = df["ID_Con"].astype(str)
    return df


def coordinate_columns(df: pd.DataFrame) -> tuple[str, str]:
    """Return the (lat, lon) column names. The landslide file uses Norte/Este."""
    lat = next(c for c in df.columns if c.lower() in ("lat", "norte"))
    lon = next(c for c in df.columns if c.lower() in ("lon", "este"))
    return lat, lon


def filter_dates(df: pd.DataFrame, column: str, start, end) -> pd.DataFrame:
    return df[(df[column] >= start) & (df[column] <= end)]


def associate_events(landslides: pd.DataFrame, events: pd.DataFrame,
                     days_before: int, radius_km: float) -> pd.DataFrame:
    """Attach the representative convective event (if any) to each landslide."""
    lat_col, lon_col = coordinate_columns(landslides)
    records = []

    for _, slide in landslides.iterrows():
        slide_xy = (slide[lat_col], slide[lon_col])
        date = slide["Fecha"]
        window = events[(events["FECHA_MIN"] >= date - timedelta(days=days_before))
                        & (events["FECHA_MIN"] <= date)]

        matches = []
        for _, ev in window.iterrows():
            dist = geodesic(slide_xy, (ev["LAT_MIN"], ev["LON_MIN"])).kilometers
            if dist <= radius_km:
                matches.append((ev, dist))

        record = slide.to_dict()
        if matches:
            ev, dist = max(matches, key=lambda m: float(m[0]["AREA_KM2"]))
            record.update(ev.to_dict())
            record["Distancia_km"] = dist
            record["# E_Convectivos"] = len(matches)
            record["ID_Con"] = ",".join(str(m[0]["ID_Con"]) for m in matches)
        else:
            record.update({c: np.nan for c in EVENT_COLUMNS})
            record["Distancia_km"] = np.nan
            record["# E_Convectivos"] = np.nan
            record["ID_Con"] = np.nan
        records.append(record)

    return pd.DataFrame(records)


def convective_percentiles(results: pd.DataFrame, events: pd.DataFrame,
                           years=range(2011, 2024)) -> pd.DataFrame:
    """Percentile of the associated event's TEMP_MIN, DURATION_H and AREA_KM2
    relative to every historical event whose extent contains the landslide."""
    lat_col, lon_col = coordinate_columns(results)
    year = pd.to_datetime(events["FECHA_MIN"]).dt.year
    hist = events[year.isin(list(years))]
    out = results.copy()

    for var in ("TEMP_MIN", "DURATION_H", "AREA_KM2"):
        out[f"Percentil_{var}"] = np.nan

    for idx, row in out.iterrows():
        lat, lon = row[lat_col], row[lon_col]
        pixel = hist[(hist["LON_MIN"] <= lon) & (hist["LON_MAX"] >= lon)
                     & (hist["LAT_MIN"] <= lat) & (hist["LAT_MAX"] >= lat)]
        for var in ("TEMP_MIN", "DURATION_H", "AREA_KM2"):
            population = pd.to_numeric(pixel[var], errors="coerce").dropna()
            value = pd.to_numeric(row[var], errors="coerce")
            if len(population) and not np.isnan(value):
                out.at[idx, f"Percentil_{var}"] = stats.percentileofscore(
                    population, value, kind="rank")
    return out


def sensitivity_table(landslides, events, days_options, radius_options,
                      fixed_days=3, fixed_radius=50.0) -> pd.DataFrame:
    """How many landslides get >=1 associated event for different N and radius.
    Reproduces thesis Figure 5."""
    rows = []
    for n in days_options:
        res = associate_events(landslides, events, n, fixed_radius)
        rows.append({"param": "days", "value": n, "with_event": res["# E_Convectivos"].notna().sum(),
                     "without_event": res["# E_Convectivos"].isna().sum()})
    for r in radius_options:
        res = associate_events(landslides, events, fixed_days, r)
        rows.append({"param": "radius_km", "value": r, "with_event": res["# E_Convectivos"].notna().sum(),
                     "without_event": res["# E_Convectivos"].isna().sum()})
    return pd.DataFrame(rows)
