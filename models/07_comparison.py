import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
from pathlib import Path
import json

__DIR = Path(__file__).parent
RESULTS_DIR = __DIR.parent / "data" / "results"
FIGURES_DIR = __DIR.parent / "figures"
PRED_COLS = [
    'avg_deforestation',
    'dist_roads',
    'average_min_precipitation',
    'gdp_capita',
    'std_rural_pop',
    'std_urban_pop',
    'std_agri_credit',
    'std_live_credit',
    'std_crop_area',
]


def main():
    gdf = gpd.read_file(RESULTS_DIR / "results_geo.gpkg")

    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    axes[0].hist(gdf['residuo_ols'], bins=40, edgecolor='k')
    axes[0].set_title('OLS Residuals Distribution')
    axes[1].scatter(gdf['fitted_ols'], gdf['residuo_ols'], alpha=0.4, s=10)
    axes[1].set_title('Residuals vs Fitted')
    gdf.plot(
        column='residuo_ols',
        cmap='PRGn',
        legend=True,
        ax=axes[2],
        edgecolor='black',
        linewidth=0.1,
    )
    axes[2].set_title('OLS Residuals Map')
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "08_ols_residuals.png", dpi=150)

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    with open(RESULTS_DIR / "gwr_metrics.json", "r") as f:
        g_r2 = json.load(f).get("gwr_r2", 0)
    gdf['r2_local_gwr'].hist(bins=30, ax=axes[0], edgecolor='k')
    axes[0].set_title('Local R² Distribution (GWR)')
    gdf.plot(
        column='r2_local_gwr',
        cmap='YlOrBr',
        legend=True,
        ax=axes[1],
        edgecolor='black',
        linewidth=0.1,
    )
    axes[1].set_title(f'Local R² Map (Global R²={g_r2:.2f})')
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "09_gwr_r2_local.png", dpi=150)

    coef_names = ['Intercepto'] + PRED_COLS
    available_coefs = [
        f'coef_{n}' for n in coef_names if f'coef_{n}' in gdf.columns
    ]
    available_pvals = [
        f'pvalue_{n}' for n in coef_names if f'pvalue_{n}' in gdf.columns
    ]

    if available_coefs:
        summary_stats = gdf[available_coefs].describe().T
        sig_counts = (
            gdf[available_pvals]
            .apply(lambda x: (x < 0.05).sum())
            .rename('sig_count')
        )
        sig_counts.index = [
            n.replace('pvalue_', 'coef_') for n in sig_counts.index
        ]

        summary = pd.concat([summary_stats, sig_counts], axis=1)
        summary.to_csv(RESULTS_DIR / "gwr_coefficients_summary.csv")
    else:
        print("No GWR coefficients found in results_geo.gpkg.")


if __name__ == "__main__":
    main()
