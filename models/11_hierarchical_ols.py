import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import statsmodels.formula.api as smf

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
    # 1. Carregar dados
    gdf = gpd.read_file(RESULTS_DIR / "results_geo.gpkg")
    
    # 2. Preparar dados (Transformados vs Raw)
    gdf['y_raw'] = gdf['dengue_incidence']
    gdf['y_trans'] = np.log1p(gdf['dengue_incidence'])
    
    X_cols_trans = []
    X_cols_raw = PRED_COLS
    for col in PRED_COLS:
        new_col = f'std_{col}'
        val_log = np.log1p(np.maximum(gdf[col].values, 0))
        gdf[new_col] = (val_log - val_log.mean()) / (val_log.std() + 1e-9)
        X_cols_trans.append(new_col)

    # 3. Definição de subconjuntos de variáveis
    PRED_COLS_4_RAW = [
        'avg_deforestation',
        'std_agri_credit',
        'std_live_credit',
        'gdp_capita',
    ]
    PRED_COLS_4_TRANS = [f'std_{col}' for col in PRED_COLS_4_RAW]

    scenarios = [
        ("raw_9", "y_raw", X_cols_raw),
        ("trans_9", "y_trans", X_cols_trans),
        ("raw_4", "y_raw", PRED_COLS_4_RAW),
        ("trans_4", "y_trans", PRED_COLS_4_TRANS),
    ]
    
    # 4. Executar cenários
    results_all = {}
    for label, y_col, x_cols in scenarios:
        print(f"\n--- Cenário: {label} ---")
        formula = f"{y_col} ~ " + " + ".join(x_cols)
        
        # Estado (MixedLM)
        # Se raw, a escala pode ser problemática, então tentamos fit com mais iterações
        model_state = smf.mixedlm(formula, gdf, groups=gdf["abbrev_state"], 
                                 re_formula=f"~{x_cols[0]}")
        res_state = model_state.fit()
        r2_state = np.corrcoef(gdf[y_col], res_state.fittedvalues)[0,1]**2
        # AIC manual para MixedLM: -2*llf + 2*k 
        # k = número de parâmetros fixos + componentes de variância (neste caso, Intercept, Slopes + Group Var, Group x Slope Cov, Slope Var)
        k = len(res_state.fe_params) + len(res_state.cov_re.values.flatten()) # Aproximação conservadora
        aic_state = -2 * res_state.llf + 2 * k
        
        # Muni Proxy (OLS with Dummies)
        formula_muni = formula + " + C(abbrev_state)"
        res_muni = smf.ols(formula_muni, data=gdf).fit()
        
        results_all[label] = {
            "state_r2": float(r2_state),
            "state_aic": float(aic_state),
            "muni_r2": float(res_muni.rsquared),
            "muni_aic": float(res_muni.aic)
        }

    # 5. Salvar resultados expandidos
    with open(RESULTS_DIR / "hierarchical_metrics_expanded.json", "w") as f:
        json.dump(results_all, f, indent=4)
    
    # Salvar coeficientes aleatórios do melhor modelo (trans_9) para o mapa
    best_formula = scenarios[1][3] if len(scenarios[1]) > 3 else "y_trans ~ " + " + ".join(X_cols_trans)
    model_best = smf.mixedlm(best_formula, gdf, groups=gdf["abbrev_state"], re_formula="~std_avg_deforestation").fit()
    re_effects = model_best.random_effects
    
    for state_code, effects in re_effects.items():
        gdf.loc[gdf['abbrev_state'] == state_code, 're_intercept'] = effects['Group']
        gdf.loc[gdf['abbrev_state'] == state_code, 're_deforestation'] = effects['std_avg_deforestation']

    gdf.to_file(RESULTS_DIR / "results_geo.gpkg", layer='results', driver="GPKG")
    print(f"\nResultados salvos em {RESULTS_DIR}")

if __name__ == "__main__":
    main()
