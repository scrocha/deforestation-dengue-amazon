import pandas as pd
import geopandas as gpd
from spreg import OLS
import libpysal
from esda.moran import Moran
from statsmodels.stats.outliers_influence import variance_inflation_factor
from pathlib import Path
import json

__DIR = Path(__file__).parent
RESULTS_DIR = __DIR.parent / "data" / "results"
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
    y = gdf['dengue_incidence'].values
    X = gdf[PRED_COLS].values
    w = libpysal.weights.Queen.from_dataframe(gdf, use_index=False)
    w.transform = 'r'

    vif = pd.DataFrame(
        {
            'Feature': PRED_COLS,
            'VIF': [
                variance_inflation_factor(X, i) for i in range(X.shape[1])
            ],
        }
    )
    vif.to_csv(RESULTS_DIR / "ols_vif.csv", index=False)

    ols = OLS(y.reshape(-1, 1), X, w=w, name_y='dengue', name_x=PRED_COLS)
    resid = ols.u.flatten()
    mi = Moran(resid, w)

    with open(RESULTS_DIR / "ols_summary.txt", "w") as f:
        f.write(ols.summary)
    metrics = {
        "ols_r2": float(ols.r2),
        "ols_aic": float(ols.aic),
        "ols_residual_moran_i": float(mi.I),
        "ols_residual_moran_p": float(mi.p_sim),
    }
    with open(RESULTS_DIR / "ols_metrics.json", "w") as f:
        json.dump(metrics, f, indent=4)

    gdf['residuo_ols'], gdf['fitted_ols'] = resid, y - resid
    gdf.to_file(RESULTS_DIR / "results_geo.gpkg", driver="GPKG")


if __name__ == "__main__":
    main()
