import pandas as pd
import json
from pathlib import Path

__DIR = Path(__file__).parent
RESULTS_DIR = __DIR.parent / "data" / "results"


def load_json(name):
    path = RESULTS_DIR / name
    if path.exists():
        with open(path, 'r') as f:
            return json.load(f)
    return {}


def main():
    print("=========================================")
    print("=== RESUMO FINAL DE MODELOS GEOSPATIAIS ===")
    print("=========================================\n")

    moran_metrics = load_json("moran_metrics.json")
    ols_base = load_json("ols_metrics.json")
    gwr_base = load_json("gwr_metrics.json")
    trans_metrics = load_json("transformed_metrics.json")
    paper_metrics = load_json("paper_metrics.json")

    if moran_metrics:
        print("=== DIAGNÓSTICO ESPACIAL ===")
        print(
            f"Moran global dengue: {moran_metrics.get('global_moran_i', 0):.3f} "
            f"(p={moran_metrics.get('global_moran_p', 0):.3f})\n"
        )

    rows = []
    if ols_base and gwr_base:
        rows.append(
            {
                "Iteração": "1. Baseline",
                "Variáveis": 9,
                "Transformações": "Nenhuma (Raw)",
                "OLS R²": round(ols_base.get("ols_r2", 0), 3),
                "OLS AIC": round(ols_base.get("ols_aic", 0), 1),
                "GWR R²": round(gwr_base.get("gwr_r2", 0), 3),
                "GWR AIC": round(gwr_base.get("gwr_aic", 0), 1),
            }
        )
    if trans_metrics:
        rows.append(
            {
                "Iteração": "2. Transformado Otimizado",
                "Variáveis": 9,
                "Transformações": "Log1p(y) e Log1p/Norm(X)",
                "OLS R²": round(trans_metrics.get("ols_trans_r2", 0), 3),
                "OLS AIC": round(trans_metrics.get("ols_trans_aic", 0), 1),
                "GWR R²": round(trans_metrics.get("gwr_trans_r2", 0), 3),
                "GWR AIC": round(trans_metrics.get("gwr_trans_aic", 0), 1),
            }
        )
    if paper_metrics:
        rows.append(
            {
                "Iteração": "3. Reprodução Paper (Original)",
                "Variáveis": 4,
                "Transformações": "Nenhuma (Escala Raw)",
                "OLS R²": round(paper_metrics.get("ols_raw_paper_r2", 0), 3),
                "OLS AIC": round(paper_metrics.get("ols_raw_paper_aic", 0), 1),
                "GWR R²": round(paper_metrics.get("gwr_raw_paper_r2", 0), 3),
                "GWR AIC": round(paper_metrics.get("gwr_raw_paper_aic", 0), 1),
            }
        )
        if "ols_raw_paper_r2" in paper_metrics:
            rows.append(
                {
                    "Iteração": "4. Reprodução Paper (Transf)",
                    "Variáveis": 4,
                    "Transformações": "Log1p(y) e Z-Score(X)",
                    "OLS R²": round(paper_metrics.get("ols_paper_r2", 0), 3),
                    "OLS AIC": round(paper_metrics.get("ols_paper_aic", 0), 1),
                    "GWR R²": round(paper_metrics.get("gwr_paper_r2", 0), 3),
                    "GWR AIC": round(paper_metrics.get("gwr_paper_aic", 0), 1),
                }
            )

    df_models = pd.DataFrame(rows)
    print(df_models.to_string(index=False))
    df_models.to_csv(
        RESULTS_DIR / "10_final_model_comparison.csv", index=False
    )
    print("\nResumo exportado para data/results/10_final_model_comparison.csv")


if __name__ == "__main__":
    main()
