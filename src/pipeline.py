"""Build the integrated landslide database used in the thesis.

Steps
  1. Associate each landslide with deep convective events (N days, X km).
  2. Percentile of the associated convective event (temperature, duration, area).
  3. CHIRPS accumulated precipitation (1 d, 2 d, week, month, 3 months) and percentiles.
  4. Lithology group and terrain slope.

Steps 1-3 run with the data included in this repository (step 3 uses the
per-landslide CHIRPS series in data/processed/). Step 4 needs the lithology
shapefile and slope raster described in the README; skip it with --skip-geology.

Example
  python src/pipeline.py --start 2011-01-01 --end 2023-12-31 --days 3 --radius 50
"""
import argparse
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from association import (associate_events, convective_percentiles, coordinate_columns,  # noqa: E402
                         filter_dates, load_convective_events, load_landslides)

FINAL_COLUMNS = [
    "Fecha", "Norte", "Este", "Tipo", "Detonante", "Departament", "Incertidumb", "Fallecidos",
    "TEMP_MIN", "DURATION_H", "AREA_KM2", "Distancia_km", "# E_Convectivos", "ID_Con",
    "Precip_Acum_Dia", "Percentil_Dia", "Precip_Acum_2Dia", "Percentil_2dias",
    "Precip_Acum_week", "Percentil_Week", "Precip_Acum_Mon", "Percentil_Mes",
    "Precip_Acum_3Mon", "Percentil_Tri_Mes",
    "Grupo_hidrolito", "Litologia", "Edad", "Pendiente_%",
    "Percentil_TEMP_MIN", "Percentil_DURATION_H", "Percentil_AREA_KM2",
]


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", default=config.START_DATE, type=date.fromisoformat)
    p.add_argument("--end", default=config.END_DATE, type=date.fromisoformat)
    p.add_argument("--days", default=config.DAYS_BEFORE, type=int, help="days before the landslide")
    p.add_argument("--radius", default=config.RADIUS_KM, type=float, help="search radius in km")
    p.add_argument("--landslides", default=config.LANDSLIDES_CSV, type=Path)
    p.add_argument("--events", default=config.CONVECTIVE_CSV, type=Path)
    p.add_argument("--precip-backend", choices=["python", "cdo"], default="python",
                   help="python: uses the per-landslide CHIRPS series (no CDO needed); "
                        "cdo: original method, needs CDO and the cropped NetCDF files")
    p.add_argument("--chirps-series", default=config.CHIRPS_SERIES_CSV, type=Path)
    p.add_argument("--chirps-dir", default=config.CHIRPS_DIR, type=Path)
    p.add_argument("--lithology", default=config.LITHOLOGY_SHP, type=Path)
    p.add_argument("--slope", default=config.SLOPE_TIF, type=Path)
    p.add_argument("--skip-precip", action="store_true", help="skip the CHIRPS precipitation step")
    p.add_argument("--skip-geology", action="store_true", help="skip lithology and slope steps")
    p.add_argument("--out", type=Path, default=None)
    a = p.parse_args()
    if a.start > a.end:
        p.error("--start must be earlier than or equal to --end")
    if a.days < 0 or a.radius <= 0:
        p.error("--days must be >= 0 and --radius > 0")

    # Check every input before starting, so the run never fails halfway
    needed = [a.landslides, a.events]
    if not a.skip_precip:
        needed.append(a.chirps_series if a.precip_backend == "python" else a.chirps_dir)
    if not a.skip_geology:
        needed += [a.lithology, a.slope]
    missing = [str(f) for f in needed if not Path(f).exists()]
    if missing:
        p.error("missing input file(s):\n  " + "\n  ".join(missing) +
                "\nSee data/external/README.md, or skip those steps with "
                "--skip-geology / --skip-precip.")
    return a


def main():
    a = parse_args()
    t0 = time.time()

    landslides = filter_dates(load_landslides(a.landslides), "Fecha", a.start, a.end)
    events_all = load_convective_events(a.events)
    events = filter_dates(events_all, "FECHA_MIN", a.start, a.end)
    if landslides.empty:
        sys.exit(f"No landslides between {a.start} and {a.end}.")
    print(f"{len(landslides)} landslides, {len(events)} convective events in range.")

    print("[1/4] Associating convective events...")
    df = associate_events(landslides, events, a.days, a.radius)
    lat_col, lon_col = coordinate_columns(df)

    print("[2/4] Convective event percentiles...")
    df = convective_percentiles(df, events_all, config.CLIMATOLOGY_YEARS)

    if a.skip_precip:
        print("[3/4] Skipped (--skip-precip)")
    elif a.precip_backend == "python":
        from precipitation import SeriesStore, precipitation_from_series
        if not a.chirps_series.is_file():
            sys.exit(f"{a.chirps_series} not found. Build it first with:\n"
                     f"  python src/chirps_extract.py --chirps-dir <CHIRPS folder>")
        print("[3/4] CHIRPS accumulated precipitation and percentiles (Python backend)...")
        df = precipitation_from_series(df, SeriesStore.from_csv(a.chirps_series), lat_col, lon_col,
                                       config.CLIMATOLOGY_YEARS)
    else:
        from precipitation import accumulated_precipitation, precipitation_percentiles
        print("[3/4] CHIRPS accumulated precipitation and percentiles (CDO backend, slow)...")
        df = accumulated_precipitation(df, a.chirps_dir, lat_col, lon_col, config.CHIRPS_RADIUS_KM)
        df = precipitation_percentiles(df, a.chirps_dir / config.CHIRPS_TOTAL_NC.name, lat_col, lon_col,
                                       config.CLIMATOLOGY_YEARS, config.CHIRPS_RADIUS_KM)

    if not a.skip_geology:
        from geology import add_lithology, add_slope
        print("[4/4] Lithology and slope...")
        df = add_lithology(df, a.lithology, lat_col, lon_col)
        df = add_slope(df, a.slope, lat_col, lon_col, config.SLOPE_CRS)
    else:
        print("[4/4] Skipped (--skip-geology)")

    out = a.out or config.DATA_PROCESSED / f"results_{a.start}_{a.end}_N{a.days}_{a.radius:g}km.csv"
    df[[c for c in FINAL_COLUMNS if c in df.columns]].to_csv(out, index=False)

    minutes = (time.time() - t0) / 60
    with_event = df["# E_Convectivos"].notna().sum()
    print(f"\nSaved: {out}")
    print(f"{len(df)} landslides processed, {with_event} with an associated convective event "
          f"({minutes:.2f} min).")


if __name__ == "__main__":
    main()
