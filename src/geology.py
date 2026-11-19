"""Lithology (hydro-lithological groups) and terrain slope for each landslide."""
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

# Re-grouping of the hydrogeological units of Cárdenas Giraldo (2022) into
# lithological groups proposed in the thesis.
HYDRO_TO_LITHO = {
    "FV": "RIv",    # volcanic igneous rocks
    "V": "RIp",     # plutonic igneous rocks
    "PM-f": "RIp",
    "PM": "RM",     # metamorphic rocks
    "PM-n": "RM",
    "S-Cz": "RSc",  # clastic sedimentary rocks
    "S": "RSc",
    "VS": "RSc",
    "SC-Cz": "RSq", # chemical sedimentary rocks
    "SC": "RSm",    # mixed sedimentary rocks
    "NC": "SNC",    # unconsolidated sediments
}

LITHO_LABELS = {
    "RIv": "Volcanic igneous rocks",
    "RIp": "Plutonic igneous rocks",
    "RM": "Metamorphic rocks",
    "RSc": "Clastic sedimentary rocks",
    "RSm": "Mixed sedimentary rocks",
    "RSq": "Chemical sedimentary rocks",
    "SNC": "Unconsolidated sediments",
    "CA": "Water bodies",
}


def group_areas(shapefile, crs="EPSG:3857") -> pd.Series:
    """Area (thousand km²) of each lithological group inside the basin.

    The thesis used EPSG:3857 (Web Mercator), which overestimates areas by
    ~1-3 % at these latitudes. Use an equal-area CRS such as EPSG:9377
    (MAGNA-SIRGAS / Origen Nacional) for true areas.
    """
    litho = gpd.read_file(shapefile).to_crs(crs)
    group = litho["Grupo_hidr"].replace(HYDRO_TO_LITHO).replace({"Embalse": "CA"})
    return (litho.area / 1e9).groupby(group).sum()


def add_lithology(results: pd.DataFrame, shapefile, lat_col, lon_col) -> pd.DataFrame:
    """Spatial join of each landslide with the lithology polygons."""
    litho = gpd.read_file(shapefile)
    points = gpd.GeoDataFrame(
        results.copy(),
        geometry=[Point(xy) for xy in zip(results[lon_col], results[lat_col])],
        crs="EPSG:4326")
    litho = litho.to_crs(points.crs)
    attrs = ["Grupo_hidr", "Litologia", "Edad"]

    if (litho.geom_type == "Point").any():
        # Point layer: take the nearest feature (metric CRS)
        joined = gpd.sjoin_nearest(points.to_crs(3857), litho.to_crs(3857)[attrs + ["geometry"]],
                                   how="left")
    else:
        joined = gpd.sjoin(points, litho[attrs + ["geometry"]], how="left", predicate="intersects")
    joined = joined[~joined.index.duplicated(keep="first")]

    out = results.copy()
    for a in attrs:
        out[a] = joined[a].values
    out["Grupo_hidr"] = out["Grupo_hidr"].replace(HYDRO_TO_LITHO)
    return out.rename(columns={"Grupo_hidr": "Grupo_hidrolito"})


def add_slope(results: pd.DataFrame, slope_tif, lat_col, lon_col, raster_crs) -> pd.DataFrame:
    """Sample the slope raster (degrees) and convert it to percent."""
    import rasterio  # only needed for this step

    pts = gpd.GeoSeries(gpd.points_from_xy(results[lon_col], results[lat_col]), crs="EPSG:4326")
    pts = pts.to_crs(raster_crs)
    with rasterio.open(slope_tif) as src:
        nodata = src.nodata if src.nodata is not None else -9999
        values = [v[0] for v in src.sample([(p.x, p.y) for p in pts])]
    deg = np.array([np.nan if v == nodata else v for v in values], dtype=float)

    out = results.copy()
    out["Pendiente_Grados"] = deg
    out["Pendiente_%"] = np.tan(np.radians(deg)) * 100
    return out
