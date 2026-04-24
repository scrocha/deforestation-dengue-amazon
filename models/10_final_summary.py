import json
from pathlib import Path

import pandas as pd

__DIR = Path(__file__).parent
RESULTS_DIR = __DIR.parent / "data" / "results"


def load_json(name):
    path = RESULTS_DIR / name
    if path.exists():
        with open(path, "r") as f:
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
    hier_metrics_exp = load_json("hierarchical_metrics_expanded.json")

    if moran_metrics:
        print("=== DIAGNÓSTICO ESPACIAL ===")
        print(
            f"Moran global dengue: {moran_metrics.get('global_moran_i', 0):.3f} "
            f"(p={moran_metrics.get('global_moran_p', 0):.3f})\n"
        )

    rows = []

    # Mapeamento para facilitar loop do resumo
    scenarios_meta = [
        (
            "1. Baseline (Raw)",
            9,
            "raw_9",
            "ols_metrics.json",
            "gwr_metrics.json",
        ),
        (
            "2. Transformado Otimizado",
            9,
            "trans_9",
            "transformed_metrics.json",
            "transformed_metrics.json",
        ),
        (
            "3. Paper (Raw)",
            4,
            "raw_4",
            "paper_metrics.json",
            "paper_metrics.json",
        ),
        (
            "4. Paper (Transformado)",
            4,
            "trans_4",
            "paper_metrics.json",
            "paper_metrics.json",
        ),
    ]

    for label, vars_count, h_key, ols_file, gwr_file in scenarios_meta:
        ols_m = load_json(ols_file)
        gwr_m = load_json(gwr_file)
        hier_m = hier_metrics_exp.get(h_key, {})

        # Lógica para extrair as chaves corretas dos arquivos OLS/GWR antigos
        if label == "1. Baseline (Raw)":
            ols_r2, ols_aic = ols_m.get("ols_r2"), ols_m.get("ols_aic")
            gwr_r2, gwr_aic = gwr_m.get("gwr_r2"), gwr_m.get("gwr_aic")
        elif label == "2. Transformado Otimizado":
            ols_r2, ols_aic = (
                ols_m.get("ols_trans_r2"),
                ols_m.get("ols_trans_aic"),
            )
            gwr_r2, gwr_aic = (
                gwr_m.get("gwr_trans_r2"),
                gwr_m.get("gwr_trans_aic"),
            )
        elif label == "3. Paper (Raw)":
            ols_r2, ols_aic = (
                ols_m.get("ols_raw_paper_r2"),
                ols_m.get("ols_raw_paper_aic"),
            )
            gwr_r2, gwr_aic = (
                gwr_m.get("gwr_raw_paper_r2"),
                gwr_m.get("gwr_raw_paper_aic"),
            )
        else:  # Paper Transformado
            ols_r2, ols_aic = (
                ols_m.get("ols_paper_r2"),
                ols_m.get("ols_paper_aic"),
            )
            gwr_r2, gwr_aic = (
                gwr_m.get("gwr_paper_r2"),
                gwr_m.get("gwr_paper_aic"),
            )

        rows.append(
            {
                "Iteração": label,
                "Vars": vars_count,
                "OLS R² (AIC)": f"{round(ols_r2, 3) if ols_r2 else 0} ({round(ols_aic, 1) if ols_aic else '-'})",
                "Hier (Muni) R² (AIC)": f"{round(hier_m.get('muni_r2', 0), 3)} ({round(hier_m.get('muni_aic', 0), 1)})",
                "Hier (Est.) R² (AIC)": f"{round(hier_m.get('state_r2', 0), 3)} ({round(hier_m.get('state_aic', 0), 1)})",
                "GWR R² (AIC)": f"{round(gwr_r2, 3) if gwr_r2 else 0} ({round(gwr_aic, 1) if gwr_aic else '-'})",
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
