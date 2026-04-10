import pandas as pd
import geopandas as gpd
import numpy as np
import libpysal
import json
from spreg import OLS
from mgwr.gwr import GWR
from mgwr.sel_bw import Sel_BW
from statsmodels.stats.outliers_influence import variance_inflation_factor
import statsmodels.api as sm
from pathlib import Path

__DIR, RESULTS_DIR = (
    Path(__file__).parent,
    Path(__file__).parent.parent / "data" / "results",
)
PRED_COLS = [
    'avg_deforestation',
    'std_agri_credit',
    'std_live_credit',
    'gdp_capita',
]


def main():
    gdf = gpd.read_file(RESULTS_DIR / "results_geo.gpkg")
    gdf['log_gdp_capita'] = np.log1p(gdf['gdp_capita'])
    y_trans = np.log1p(gdf.dengue_incidence.values.astype(float)).reshape(
        -1, 1
    )
    current_cols = [
        c if c != 'gdp_capita' else 'log_gdp_capita' for c in PRED_COLS
    ]
    X_orig = gdf[current_cols].values.astype(float)
    X_std = (X_orig - X_orig.mean(axis=0)) / (X_orig.std(axis=0) + 1e-9)
    X_std += np.random.normal(0, 1e-10, X_std.shape)
    y_raw = gdf.dengue_incidence.values.astype(float).reshape(-1, 1)
    X_raw = X_orig.copy()
    w = libpysal.weights.Queen.from_dataframe(gdf, use_index=False)
    w.transform = 'r'
    ols_trans = OLS(y_trans, X_std, w=w, name_y='dengue', name_x=current_cols)

    gdf_p = gdf.to_crs('EPSG:5880')
    coords = np.column_stack(
        [gdf_p.geometry.centroid.x, gdf_p.geometry.centroid.y]
    )

    bw_trans = Sel_BW(
        coords, y_trans, X_std, kernel='bisquare', fixed=False
    ).search(criterion='AICc')
    res_trans = GWR(
        coords, y_trans, X_std, bw_trans, kernel='bisquare', fixed=False
    ).fit()
    ols_raw = OLS(y_raw, X_raw, w=w, name_y='dengue', name_x=current_cols)
    bw_raw = Sel_BW(
        coords, y_raw, X_raw, kernel='bisquare', fixed=False
    ).search(criterion='AICc')
    res_raw = GWR(
        coords, y_raw, X_raw, bw_raw, kernel='bisquare', fixed=False
    ).fit()

    vifs = [
        variance_inflation_factor(sm.add_constant(X_raw), i)
        for i in range(1, X_raw.shape[1] + 1)
    ]
    table2 = pd.DataFrame(
        {
            'Name': ['Intercept']
            + [
                n if n != 'log_gdp_capita' else 'Average log GDP per capita'
                for n in current_cols
            ],
            'Estimate': ols_raw.betas.flatten(),
            'Std.Err': ols_raw.std_err.flatten(),
            'VIF': ['-'] + [round(v, 2) for v in vifs],
        }
    )
    table2.to_csv(RESULTS_DIR / "paper_table2_ols.csv", index=False)

    pd.DataFrame(
        res_raw.params, columns=['Intercept'] + current_cols
    ).describe().T.to_csv(RESULTS_DIR / "paper_table3_gwr.csv")

    metrics = {
        "ols_paper_r2": float(ols_trans.r2),
        "ols_paper_aic": float(ols_trans.aic),
        "gwr_paper_r2": float(res_trans.R2),
        "gwr_paper_aic": float(res_trans.aic),
        "ols_raw_paper_r2": float(ols_raw.r2),
        "ols_raw_paper_aic": float(ols_raw.aic),
        "gwr_raw_paper_r2": float(res_raw.R2),
        "gwr_raw_paper_aic": float(res_raw.aic),
    }
    with open(RESULTS_DIR / "paper_metrics.json", "w") as f:
        json.dump(metrics, f, indent=4)
    print("Reprodução do paper (Transformed & Raw) concluída.")


if __name__ == "__main__":
    main()
