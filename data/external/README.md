# External data (not included / no incluido)

Place these files here to run the full pipeline:

| File | Description |
|---|---|
| `chirps/chirps-v2.0.<year>.days_p05.nc` | Raw CHIRPS v2.0 global daily files 2011–2023, input of `src/chirps_extract.py` (`--chirps-dir`) |
| `chirps/Rectangulo_Cuenca_en_p05_<year>.nc` | Only for `--precip-backend cdo`: | CHIRPS v2.0 daily precipitation (0.05°) cropped to the basin, one file per year 2011–2023 |
| `chirps/Rectangulo_Cuenca_en_p05_TOTAL.nc` | Same data, all years merged (e.g. `cdo mergetime`) |
| `Cuenca_hidrolito_division_tiempo.shp` (+ .shx/.dbf/.prj) | Hydro-lithological units with fields `Grupo_hidr`, `Litologia`, `Edad` |
| `Raster_Pendientes.tif` | Slope in degrees (CRS `ESRI:103599`), derived from the IGAC SRTM 30 m DEM |

Sources and links: see the [main README](../../README.md#data).
