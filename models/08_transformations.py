import json
from pathlib import Path

import geopandas as gpd
import libpysal
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from mgwr.gwr import GWR
from mgwr.sel_bw import Sel_BW
from spreg import OLS

__DIR, RESULTS_DIR, FIGURES_DIR = (
    Path(__file__).parent,
    Path(__file__).parent.parent / "data" / "results",
    Path(__file__).parent.parent / "figures",
)
PRED_COLS = [
    "avg_deforestation",
    "dist_roads",
    "average_min_precipitation",
    "gdp_capita",
    "std_rural_pop",
    "std_urban_pop",
    "std_agri_credit",
    "std_live_credit",
    "std_crop_area",
]


def load_json(path):
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return {}


def main():
    gdf = gpd.read_file(RESULTS_DIR / "results_geo.gpkg")
    y_log = np.log1p(gdf.dengue_incidence.values).reshape(-1, 1)

    X_log_data = {}
    for c in PRED_COLS:
        X_log_data[c] = np.log1p(np.maximum(gdf[c].values, 0))

    X_log_df = pd.DataFrame(X_log_data)
    X_scaled = (X_log_df.values - X_log_df.values.mean(axis=0)) / (
        X_log_df.values.std(axis=0) + 1e-9
    )

    X_scaled += np.random.normal(0, 1e-10, X_scaled.shape)

    norm_df = pd.DataFrame(X_scaled, columns=PRED_COLS).assign(
        dengue_incidence_log=y_log.flatten()
    )
    fig, ax = plt.subplots(figsize=(11, 9))
    sns.heatmap(
        norm_df.corr(),
        mask=np.triu(np.ones_like(norm_df.corr(), dtype=bool)),
        annot=True,
        fmt=".2f",
        cmap="RdBu_r",
        center=0,
        ax=ax,
    )
    fig.savefig(FIGURES_DIR / "10_normalized_correlation.png", dpi=150)
    plt.close(fig)

    w = libpysal.weights.Queen.from_dataframe(gdf, use_index=False)
    w.transform = "r"
    ols = OLS(y_log, X_scaled, w=w, name_x=PRED_COLS)

    gdf_proj = gdf.to_crs("EPSG:5880")
    coords = np.column_stack(
        [gdf_proj.geometry.centroid.x, gdf_proj.geometry.centroid.y]
    )
    bw = Sel_BW(
        coords, y_log, X_scaled, kernel="bisquare", fixed=False
    ).search(criterion="AICc")

    results = GWR(
        coords, y_log, X_scaled, bw, kernel="bisquare", fixed=False
    ).fit()

    # Keep transformed local R2 for reproducibility and plotting.
    gdf["r2_local_gwr_transformed"] = results.localR2

    # Compare complete GWR local R2: baseline vs transformed.
    base_metrics = load_json(RESULTS_DIR / "gwr_metrics.json")
    base_r2 = float(base_metrics.get("gwr_r2", np.nan))
    trans_r2 = float(results.R2)

    base_local = gdf["r2_local_gwr"] if "r2_local_gwr" in gdf.columns else None
    trans_local = gdf["r2_local_gwr_transformed"]

    if base_local is not None:
        vmin = min(base_local.min(), trans_local.min())
        vmax = max(base_local.max(), trans_local.max())

        fig2, axes2 = plt.subplots(1, 2, figsize=(16, 7))

        gdf.plot(
            column="r2_local_gwr",
            cmap="YlOrBr",
            legend=True,
            vmin=vmin,
            vmax=vmax,
            ax=axes2[0],
            edgecolor="black",
            linewidth=0.1,
        )
        axes2[0].set_title(f"GWR (R²={base_r2:.3f})")
        axes2[0].axis("off")

        gdf.plot(
            column="r2_local_gwr_transformed",
            cmap="YlOrBr",
            legend=True,
            vmin=vmin,
            vmax=vmax,
            ax=axes2[1],
            edgecolor="black",
            linewidth=0.1,
        )
        axes2[1].set_title(f"GWR com Transformações (R²={trans_r2:.3f})")
        axes2[1].axis("off")

        fig2.tight_layout()
        fig2.savefig(FIGURES_DIR / "11_gwr_r2_comparison.png", dpi=150)
        plt.close(fig2)

    gdf.to_file(RESULTS_DIR / "results_geo.gpkg", driver="GPKG")

    metrics = {
        "ols_trans_r2": float(ols.r2),
        "ols_trans_aic": float(ols.aic),
        "gwr_trans_r2": float(results.R2),
        "gwr_trans_aic": float(results.aic),
        "gwr_trans_bw": float(bw),
    }
    with open(RESULTS_DIR / "transformed_metrics.json", "w") as f:
        json.dump(metrics, f, indent=4)


if __name__ == "__main__":
    main()
