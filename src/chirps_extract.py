"""Daily CHIRPS precipitation series around each landslide (pure Python, no CDO).

Reproduces what the thesis did with CDO on the university server:

    cdo -fldmean -selcircle,lon=<lon>,lat=<lat>,radius=10km  chirps.nc

* ``selcircle``: keep the grid cells whose centre lies within ``radius_km``
  (great-circle distance) of the landslide.
* ``fldmean``: area-weighted mean of those cells, ignoring missing values.

The result is one daily series per landslide (rows = dates, columns = landslide
index), saved as a small compressed CSV. Accumulations and percentiles are then
computed from it by ``precipitation.py`` in seconds.

    python src/chirps_extract.py --chirps-dir <folder with chirps-v2.0.<year>.days_p05.nc>
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

EARTH_RADIUS_KM = 6371.0
CELL_DEG = 0.05


def _great_circle_km(lat0, lon0, lat, lon):
    p0, p = np.radians(lat0), np.radians(lat)
    dlat, dlon = p - p0, np.radians(lon - lon0)
    a = np.sin(dlat / 2) ** 2 + np.cos(p0) * np.cos(p) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def circle_weights(lats, lons, lat0, lon0, radius_km):
    """Cell-area weights for the cells inside the circle (zero elsewhere)."""
    lat2d, lon2d = np.meshgrid(lats, lons, indexing="ij")
    inside = _great_circle_km(lat0, lon0, lat2d, lon2d) <= radius_km
    half = np.radians(CELL_DEG / 2)
    area = np.sin(np.radians(lat2d) + half) - np.sin(np.radians(lat2d) - half)
    return np.where(inside, area, 0.0)


def chirps_file(chirps_dir, year):
    return Path(chirps_dir) / f"chirps-v2.0.{year}.days_p05.nc"


def point_key(lat, lon) -> str:
    """Column name of a location in the series table."""
    return f"{lat:.4f},{lon:.4f}"


def extract_series(points: pd.DataFrame, chirps_dir, years, radius_km=10.0,
                   lat_col="Norte", lon_col="Este") -> pd.DataFrame:
    """One column per distinct location (the series only depends on coordinates)."""
    points = points.drop_duplicates([lat_col, lon_col]).reset_index(drop=True)
    keys = [point_key(la, lo) for la, lo in zip(points[lat_col], points[lon_col])]
    margin = 0.25
    box = dict(latitude=slice(points[lat_col].min() - margin, points[lat_col].max() + margin),
               longitude=slice(points[lon_col].min() - margin, points[lon_col].max() + margin))
    weights, frames = None, []

    for year in years:
        path = chirps_file(chirps_dir, year)
        print(f"  reading {path.name} ...", flush=True)
        with xr.open_dataset(path) as ds:
            cube = ds["precip"].sel(**box).load()
        if weights is None:
            lats, lons = cube.latitude.values, cube.longitude.values
            weights = np.stack([circle_weights(lats, lons, la, lo, radius_km)
                                for la, lo in zip(points[lat_col], points[lon_col])])
            empty = (weights.sum(axis=(1, 2)) == 0).sum()
            if empty:
                print(f"  warning: {empty} points have no CHIRPS cell within {radius_km} km")

        data = cube.values                                  # (time, lat, lon)
        valid = ~np.isnan(data)
        x = np.where(valid, data, 0.0)
        num = np.einsum("tij,pij->tp", x, weights)
        den = np.einsum("tij,pij->tp", valid.astype(float), weights)
        with np.errstate(invalid="ignore", divide="ignore"):
            frames.append(pd.DataFrame(num / den, index=pd.to_datetime(cube.time.values).date,
                                       columns=keys))
    return pd.concat(frames)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chirps-dir", type=Path, default=config.CHIRPS_DIR)
    ap.add_argument("--results", type=Path, default=config.RESULTS_CSV,
                    help="table with the landslide coordinates (Norte/Este)")
    ap.add_argument("--radius", type=float, default=config.CHIRPS_RADIUS_KM)
    ap.add_argument("--out", type=Path, default=config.CHIRPS_SERIES_CSV)
    a = ap.parse_args()

    missing = [chirps_file(a.chirps_dir, y).name for y in config.CLIMATOLOGY_YEARS
               if not chirps_file(a.chirps_dir, y).is_file()]
    if missing:
        ap.error(f"{len(missing)} CHIRPS file(s) not found in {a.chirps_dir}: {', '.join(missing)}\n"
                 "Download them from https://data.chc.ucsb.edu/products/CHIRPS/v2.0/global_daily/netcdf/p05/ "
                 "or point to their folder with --chirps-dir.")

    points = pd.read_csv(a.results)[["Fecha", "Norte", "Este"]]
    series = extract_series(points, a.chirps_dir, config.CLIMATOLOGY_YEARS, a.radius)
    series.index.name = "date"
    # 6 significant digits, the same precision as `cdo output`
    series.to_csv(a.out, compression="gzip", float_format="%.6g")
    print(f"Saved {a.out}  ({series.shape[0]} days x {series.shape[1]} locations)")


if __name__ == "__main__":
    main()
