"""Default paths and parameters used in the thesis.

Every value here can be overridden from the command line (see ``pipeline.py``).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
DATA_EXTERNAL = ROOT / "data" / "external"   # large inputs not included in the repo
FIGURES = ROOT / "figures" / "generated"

# --- Input files ---------------------------------------------------------------
LANDSLIDES_CSV = DATA_RAW / "landslides_magdalena_cauca.csv"
CONVECTIVE_CSV = DATA_RAW / "convective_events_magdalena_cauca.csv"
RESULTS_CSV = DATA_PROCESSED / "results_2011-2023_N3_50km.csv"
# Daily CHIRPS mean within 10 km of each landslide (built by src/chirps_extract.py)
CHIRPS_SERIES_CSV = DATA_PROCESSED / "chirps_daily_10km_per_landslide.csv.gz"

# Not included (see README -> Data): CHIRPS NetCDF, lithology shapefile, slope raster
CHIRPS_DIR = DATA_EXTERNAL / "chirps"                       # Rectangulo_Cuenca_en_p05_<year>.nc
CHIRPS_TOTAL_NC = CHIRPS_DIR / "Rectangulo_Cuenca_en_p05_TOTAL.nc"
LITHOLOGY_SHP = DATA_EXTERNAL / "Cuenca_hidrolito_division_tiempo.shp"
SLOPE_TIF = DATA_EXTERNAL / "Raster_Pendientes.tif"
SLOPE_CRS = "ESRI:103599"                                   # CRS of the slope raster

# --- Analysis parameters (values chosen in the thesis) -------------------------
START_DATE = "2011-01-01"
END_DATE = "2023-12-31"
DAYS_BEFORE = 3            # time window: days before the landslide
RADIUS_KM = 50.0           # max distance landslide <-> convective event
CHIRPS_RADIUS_KM = 10      # radius used to average CHIRPS pixels around a landslide
CLIMATOLOGY_YEARS = range(2011, 2024)
ATYPICAL_PERCENTILE = 90   # precipitation above P90 is "atypical"
