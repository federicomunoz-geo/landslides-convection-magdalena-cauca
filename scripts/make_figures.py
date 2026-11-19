"""Regenerate the thesis result figures from the CSV files in data/.

    python scripts/make_figures.py            # all figures
    python scripts/make_figures.py --no-sensitivity   # skip Fig. 5 (slower)

Output: figures/generated/*.png
"""
import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import config  # noqa: E402

# ---------------------------------------------------------------- style
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, SURFACE = "#e1e0d9", "#c3c2b7", "#fcfcfb"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
TYPICAL = "#a8a7a0"        # neutral gray = "typical" precipitation
ATYPICAL = BLUE            # highlighted = "atypical" precipitation (≥ P90)

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": ["Segoe UI", "DejaVu Sans", "sans-serif"], "font.size": 10,
    "text.color": INK, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.edgecolor": AXIS, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.axisbelow": True, "axes.titleweight": "bold", "axes.titlesize": 12,
    "axes.titlelocation": "left", "legend.frameon": False, "savefig.dpi": 160,
})

SCALES = [("Percentil_Dia", "Daily"), ("Percentil_2dias", "2 days"), ("Percentil_Week", "Weekly"),
          ("Percentil_Mes", "Monthly"), ("Percentil_Tri_Mes", "3 months")]

# Area of each lithological group inside the basin (thousand km²), as used in
# the thesis (EPSG:3857). Used only when the lithology shapefile is not in
# data/external/; otherwise the areas are recomputed from it.
LITHO_AREA_1000KM2 = {"RIp": 50.42, "RIv": 6.03, "RM": 36.75, "RSc": 76.73,
                      "RSm": 29.18, "SNC": 74.18, "RSq": 3.52}

# Slope class limits of thesis Figure 10, kept as in the thesis. They are the
# deciles of the basin slope raster in DEGREES, applied here (as in the thesis)
# to the landslide slope in PERCENT. See README -> Notes and limitations.
SLOPE_BREAKS = [0.0, 1.1, 2.0, 3.4, 6.1, 9.9, 13.9, 18.3, 23.3, 29.6, np.inf]


def save(fig, name):
    path = config.FIGURES / name
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print("saved", path.relative_to(config.ROOT))


def label_bars(ax, bars, fmt="{:.0f}", inside=False, color=INK2):
    for b in bars:
        h = b.get_height()
        if h == 0 or np.isnan(h):
            continue
        y = b.get_y() + h / 2 if inside else b.get_y() + h
        ax.annotate(fmt.format(h), (b.get_x() + b.get_width() / 2, y),
                    xytext=(0, 0 if inside else 3), textcoords="offset points",
                    ha="center", va="center" if inside else "bottom", fontsize=8.5, color=color)


def is_atypical(series):
    return series >= config.ATYPICAL_PERCENTILE


# ---------------------------------------------------------------- figures
def fig04_per_year(slides):
    counts = pd.to_datetime(slides["Fecha"]).dt.year.value_counts().sort_index()
    fig, ax = plt.subplots(figsize=(9, 4))
    bars = ax.bar(counts.index.astype(str), counts.values, color=BLUE, width=0.6)
    label_bars(ax, bars)
    ax.set(title="Landslides per year in the Magdalena-Cauca basin",
           xlabel="Year", ylabel="Number of landslides")
    save(fig, "fig04_landslides_per_year.png")


def fig05_sensitivity(slides, events):
    from association import sensitivity_table
    tab = sensitivity_table(slides, events, days_options=[1, 2, 3, 4, 5],
                            radius_options=[5, 10, 20, 50, 100])
    tab.to_csv(config.DATA_PROCESSED / "sensitivity_window_radius.csv", index=False)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    for ax, (param, xlabel, fmt, chosen) in zip(axes, [
            ("days", "Time window N (days before the landslide; radius 50 km)", "N={:g}", 3),
            ("radius_km", "Search radius (km; window N = 3 days)", "{:g} km", 50)]):
        t = tab[tab.param == param]
        x = np.arange(len(t))
        w = 0.38
        b1 = ax.bar(x - w / 2 - 0.01, t.with_event, w, color=BLUE, label="With convective event")
        b2 = ax.bar(x + w / 2 + 0.01, t.without_event, w, color=TYPICAL, label="Without convective event")
        label_bars(ax, b1)
        label_bars(ax, b2)
        ax.set_xticks(x, [fmt.format(v) for v in t.value])
        for lbl, v in zip(ax.get_xticklabels(), t.value):
            if v == chosen:
                lbl.set_fontweight("bold")
                lbl.set_color(INK)
        ax.set(xlabel=xlabel, ylabel="Number of landslides")
    axes[0].set_title("Sensitivity to the time window")
    axes[1].set_title("Sensitivity to the search radius")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=2, bbox_to_anchor=(0.5, 1.07))
    save(fig, "fig05_window_radius_sensitivity.png")


def fig06_percentile_boxplot(res):
    data = [res[c].dropna() for c, _ in SCALES]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.boxplot(data, widths=0.5, patch_artist=True,
               boxprops=dict(facecolor="#b7d3f6", edgecolor=BLUE),
               medianprops=dict(color=INK, linewidth=2), whiskerprops=dict(color=MUTED),
               capprops=dict(color=MUTED), flierprops=dict(markeredgecolor=MUTED, markersize=4))
    ax.axhline(config.ATYPICAL_PERCENTILE, color=ORANGE, linestyle="--", linewidth=1.5)
    ax.text(5.45, config.ATYPICAL_PERCENTILE + 1.5, "P90 (atypical threshold)", ha="right",
            fontsize=8.5, color=INK2)
    for i, s in enumerate(data, start=1):
        ax.text(i, -9, f"{is_atypical(s).mean() * 100:.1f}% ≥ P90", ha="center", fontsize=8.5, color=INK2)
    ax.set_xticks(range(1, 6), [lbl for _, lbl in SCALES])
    ax.set_ylim(-14, 104)
    ax.set_yticks(range(0, 101, 10))
    ax.set(title="Precipitation percentile on landslide dates, by accumulation period",
           xlabel="Accumulation period", ylabel="Precipitation percentile")
    save(fig, "fig06_precip_percentiles.png")


def fig07_convective_scatter(res):
    df = res.dropna(subset=["DURATION_H"]).copy()
    panels = [("DURATION_H", "Convective event duration (h)"),
              ("AREA_KM2", "Convective event area (km²)"),
              ("TEMP_MIN", "Minimum brightness temperature (K)")]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), sharey=True)
    for ax, (col, xlabel) in zip(axes, panels):
        atyp = is_atypical(df["Percentil_Dia"])
        ax.scatter(df.loc[~atyp, col], df.loc[~atyp, "Percentil_Dia"], s=28, color=TYPICAL,
                   edgecolor=SURFACE, linewidth=1, label="Typical (< P90)")
        ax.scatter(df.loc[atyp, col], df.loc[atyp, "Percentil_Dia"], s=28, color=ATYPICAL,
                   edgecolor=SURFACE, linewidth=1, label="Atypical (≥ P90)")
        ax.axhline(config.ATYPICAL_PERCENTILE, color=ORANGE, linestyle="--", linewidth=1.2)
        ax.set_xlabel(xlabel)
        ax.grid(axis="x", color=GRID)
    axes[1].set_xscale("log")
    axes[0].set_ylabel("Daily precipitation percentile")
    axes[0].legend(loc="lower right")
    fig.suptitle(f"Associated convective event vs. daily precipitation percentile "
                 f"(n = {len(df)} landslides)", x=0.01, ha="left", fontweight="bold")
    save(fig, "fig07_convective_vs_percentile.png")


GROUP_COLORS = {"RIp": "#eb6834", "RIv": "#e34948", "RM": "#6250d6", "RSc": "#1baf7a",
                "RSm": "#eda100", "RSq": "#e87ba4", "SNC": "#c3c2b7", "CA": "#86b6ef"}
GROUP_NAMES = {"RIp": "Plutonic igneous", "RIv": "Volcanic igneous", "RM": "Metamorphic",
               "RSc": "Clastic sedimentary", "RSm": "Mixed sedimentary", "RSq": "Chemical sedimentary",
               "SNC": "Unconsolidated sediments", "CA": "Water bodies"}


def fig03_lithology_map(shapefile, res):
    import geopandas as gpd
    from matplotlib.patches import Patch
    from geology import HYDRO_TO_LITHO

    litho = gpd.read_file(shapefile)
    litho["grupo"] = litho["Grupo_hidr"].replace(HYDRO_TO_LITHO).replace({"Embalse": "CA"})
    fig, ax = plt.subplots(figsize=(7.5, 9.5))
    for g, color in GROUP_COLORS.items():
        sub = litho[litho.grupo == g]
        if len(sub):
            sub.plot(ax=ax, color=color, edgecolor="none")
    ax.scatter(res["Este"], res["Norte"], s=14, color=INK, edgecolor="#ffffff", linewidth=0.8, zorder=3)
    handles = [Patch(color=c, label=f"{g} – {GROUP_NAMES[g]}") for g, c in GROUP_COLORS.items()]
    handles.append(plt.Line2D([], [], marker="o", linestyle="", color=INK, markeredgecolor="#ffffff",
                              label=f"Landslide (n = {len(res)})"))
    ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(1.01, 0.0), fontsize=9)
    ax.set_aspect("equal")
    ax.grid(axis="both", color=GRID)
    ax.set(title="Lithological groups and landslides, Magdalena-Cauca basin",
           xlabel="Longitude (°)", ylabel="Latitude (°)")
    save(fig, "fig03_lithology_map.png")


def lithology_table(res, areas=None):
    areas = pd.Series(LITHO_AREA_1000KM2) if areas is None else areas
    atyp = is_atypical(res["Percentil_Week"])
    t = (pd.crosstab(res["Grupo_hidrolito"], atyp)
         .rename(columns={False: "typical", True: "atypical"})
         .reindex(list(LITHO_AREA_1000KM2), fill_value=0))
    t["area_1000km2"] = areas.reindex(t.index)
    t["density_typical"] = t.typical / t.area_1000km2
    t["density_atypical"] = t.atypical / t.area_1000km2
    t["density_total"] = t.density_typical + t.density_atypical
    return t


def _stacked(ax, labels, low, high, fmt):
    x = np.arange(len(labels))
    gap = 0.0  # visual gap handled by white edge
    b1 = ax.bar(x, low, 0.6, color=TYPICAL, edgecolor=SURFACE, linewidth=2, label="Typical weekly rain (< P90)")
    b2 = ax.bar(x, high, 0.6, bottom=low + gap, color=ATYPICAL, edgecolor=SURFACE, linewidth=2,
                label="Atypical weekly rain (≥ P90)")
    label_bars(ax, b1, fmt, inside=True, color=INK)
    label_bars(ax, b2, fmt, inside=True, color="#ffffff")
    for xi, tot in zip(x, low + high):
        ax.annotate(fmt.format(tot), (xi, tot), xytext=(0, 3), textcoords="offset points",
                    ha="center", va="bottom", fontsize=9, fontweight="bold", color=INK)
    ax.set_xticks(x, labels)


def fig08_lithology_counts(t):
    fig, ax = plt.subplots(figsize=(9, 4.5))
    _stacked(ax, t.index, t.typical.values, t.atypical.values, "{:.0f}")
    ax.set(title="Landslides by lithological group and weekly precipitation condition",
           xlabel="Lithological group", ylabel="Number of landslides")
    ax.legend(loc="upper left")
    save(fig, "fig08_lithology_counts.png")


def fig09_lithology_density(t):
    t = t[t.typical + t.atypical > 0]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    _stacked(ax, t.index, t.density_typical.values, t.density_atypical.values, "{:.2f}")
    ax.set(title="Landslide density by lithological group (per 1,000 km²)",
           xlabel="Lithological group", ylabel="Landslides per 1,000 km²")
    ax.legend(loc="upper right")
    save(fig, "fig09_lithology_density.png")


def fig10_slope(res):
    slope = res["Pendiente_%"].dropna()
    bins = pd.cut(slope, SLOPE_BREAKS, right=False)
    pct = bins.value_counts(sort=False) / len(slope) * 100
    labels = [f"{a:.1f}–{b:.1f}" if np.isfinite(b) else f"≥ {a:.1f}"
              for a, b in zip(SLOPE_BREAKS[:-1], SLOPE_BREAKS[1:])]
    fig, ax = plt.subplots(figsize=(10, 4.5))
    bars = ax.bar(labels, pct.values, color=AQUA, width=0.7)
    label_bars(ax, bars, "{:.1f}%")
    ax.set(title="Share of landslides per slope class (class limits as in the thesis)",
           xlabel="Terrain slope (%)", ylabel="% of landslides")
    save(fig, "fig10_slope_intervals.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-sensitivity", action="store_true")
    a = ap.parse_args()
    config.FIGURES.mkdir(parents=True, exist_ok=True)

    res = pd.read_csv(config.RESULTS_CSV)
    fig04_per_year(res)
    if not a.no_sensitivity:
        from association import filter_dates, load_convective_events, load_landslides
        slides = filter_dates(load_landslides(config.LANDSLIDES_CSV), "Fecha",
                              pd.Timestamp(config.START_DATE).date(), pd.Timestamp(config.END_DATE).date())
        events = load_convective_events(config.CONVECTIVE_CSV)
        fig05_sensitivity(slides, events)
    fig06_percentile_boxplot(res)
    fig07_convective_scatter(res)

    areas = None
    if config.LITHOLOGY_SHP.is_file():
        from geology import group_areas
        fig03_lithology_map(config.LITHOLOGY_SHP, res)
        # Rounded like LITHO_AREA_1000KM2 so the outputs are identical with or without the shapefile
        areas = group_areas(config.LITHOLOGY_SHP, "EPSG:3857").round(2)       # same CRS as the thesis
        true_areas = group_areas(config.LITHOLOGY_SHP, "EPSG:9377").round(2)  # equal-area CRS
        lithology_table(res, true_areas).round(2).to_csv(
            config.DATA_PROCESSED / "lithology_summary_equal_area.csv")
    else:
        print("Lithology shapefile not found: skipping Fig. 3, using thesis areas.")
    t = lithology_table(res, areas)
    t.round(2).to_csv(config.DATA_PROCESSED / "lithology_summary.csv")
    fig08_lithology_counts(t)
    fig09_lithology_density(t)
    fig10_slope(res)

    print("\nKey numbers")
    for c, lbl in SCALES:
        print(f"  {lbl:9s} atypical (≥ P90): {is_atypical(res[c]).mean() * 100:5.1f}%")
    print(f"  Landslides with an associated convective event: {res['# E_Convectivos'].notna().sum()}")
    print(f"  Landslides on slopes > 30%: {(res['Pendiente_%'] > 30).mean() * 100:.1f}%")
    print(t[["typical", "atypical", "density_total"]].round(2).to_string())


if __name__ == "__main__":
    main()
