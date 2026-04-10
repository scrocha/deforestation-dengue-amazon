import pandas as pd
import geopandas as gpd
import numpy as np
from mgwr.gwr import GWR
from mgwr.sel_bw import Sel_BW
from pathlib import Path
import json
from scipy.stats import norm

__DIR = Path(__file__).parent
RESULTS_DIR = __DIR.parent / "data" / "results"
PRED_COLS = ['avg_deforestation','dist_roads','average_min_precipitation','gdp_capita','std_rural_pop','std_urban_pop','std_agri_credit','std_live_credit','std_crop_area']

def main():
    gdf = gpd.read_file(RESULTS_DIR / "results_geo.gpkg")
    gdf['log_gdp_capita'] = np.log1p(gdf['gdp_capita'])
    current_cols = [c if c != 'gdp_capita' else 'log_gdp_capita' for c in PRED_COLS]
    
    y = gdf['dengue_incidence'].values.reshape(-1, 1)
    X = gdf[current_cols].values
    X = (X - X.mean(axis=0)) / X.std(axis=0)
    
    gdf_proj = gdf.to_crs('EPSG:5880')
    coords = np.column_stack([gdf_proj.geometry.centroid.x, gdf_proj.geometry.centroid.y])
    
    bw = Sel_BW(coords, y, X, kernel='bisquare', fixed=False).search(criterion='AICc')
    results = GWR(coords, y, X, bw, kernel='bisquare', fixed=False).fit()
    
    gdf['r2_local_gwr'], gdf['y_pred_gwr'], gdf['resid_gwr'] = results.localR2, results.predy.flatten(), results.resid_response.flatten()
    
    pvals = results.pvalues if results.pvalues is not None else 2 * norm.sf(np.abs(results.tvalues))
    names = ['Intercepto'] + PRED_COLS
    for i, name in enumerate(names):
        gdf[f'coef_{name}'], gdf[f'tvalue_{name}'], gdf[f'pvalue_{name}'] = results.params[:, i], results.tvalues[:, i], pvals[:, i]
        
    gdf.to_file(RESULTS_DIR / "results_geo.gpkg", driver="GPKG")
    metrics = {"gwr_r2": float(results.R2), "gwr_aic": float(results.aic), "gwr_bw": float(bw)}
    with open(RESULTS_DIR / "gwr_metrics.json", "w") as f: json.dump(metrics, f, indent=4)

if __name__ == "__main__":
    main()
