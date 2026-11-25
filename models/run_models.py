"""Moran, OLS, GWR, cenários transformados/paper, hierárquico e resumo final.

Lê data/processed/deforestation_dengue_geo.gpkg e grava métricas e tabelas em
data/results/ e figuras em figures/.
"""

import json
from pathlib import Path

import geopandas as gpd
import libpysal
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import statsmodels.api as sm
import statsmodels.formula.api as smf
from esda.moran import Moran, Moran_Local
from mgwr.gwr import GWR
from mgwr.search import golden_section
from mgwr.sel_bw import Sel_BW
from scipy.stats import norm
from spreg import OLS
from statsmodels.stats.outliers_influence import variance_inflation_factor

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "processed" / "deforestation_dengue_geo.gpkg"
RESULTS_DIR = ROOT / "data" / "results"
FIGURES_DIR = ROOT / "figures"
PRED_COLS = [
    "avg_deforestation", "dist_roads", "average_min_precipitation", "gdp_capita",
    "std_rural_pop", "std_urban_pop", "std_agri_credit", "std_live_credit",
    "std_crop_area",
]  # fmt: skip
PAPER_COLS = ["std_deforestation", "std_agri_credit", "std_live_credit", "gdp_capita"]  # Tabela 1 do artigo
RNG = np.random.default_rng(42)  # ruído mínimo contra colinearidade exata; fixo para reprodutibilidade
LISA_COLORS = {0: "lightgrey", 1: "red", 2: "lightblue", 3: "blue", 4: "pink"}
LISA_LABELS = {
    0: "Não Significativo",
    1: "Alto-Alto (Hotspot)",
    2: "Baixo-Alto",
    3: "Baixo-Baixo (Coldspot)",
    4: "Alto-Baixo",
}


def save_json(data: dict, name: str) -> None:
    with open(RESULTS_DIR / name, "w") as f:
        json.dump(data, f, indent=4)


def zscore(x: np.ndarray, eps: float = 0.0) -> np.ndarray:
    return (x - x.mean(axis=0)) / (x.std(axis=0) + eps)


def gwr_aicc(coords: np.ndarray, y: np.ndarray, X: np.ndarray, bw: int) -> float:
    """AICc do GWR gaussiano (bisquare adaptativo, com intercepto), em lote; igual ao do mgwr sem a inferência."""
    n, y = len(y), y.reshape(-1)
    xd = np.column_stack([np.ones(n), X])
    p = xd.shape[1]
    dist = np.sqrt(((coords[:, None, :] - coords[None, :, :]) ** 2).sum(axis=2))
    h = np.partition(dist, bw - 1, axis=1)[:, bw - 1, None] * 1.0000001
    w = np.where(dist < h, (1 - (dist / h) ** 2) ** 2, 0.0)
    outer = (xd[:, :, None] * xd[:, None, :]).reshape(n, p * p)
    sol = np.linalg.solve((w @ outer).reshape(n, p, p), np.stack([w @ (xd * y[:, None]), xd], axis=2))
    resid = y - np.einsum("ij,ij->i", xd, sol[:, :, 0])
    tr_s = np.einsum("ij,ij->i", xd, sol[:, :, 1]).sum()
    llf = -0.5 * n * (np.log(2 * np.pi) + np.log(resid @ resid / n) + 1)
    return float(-2 * llf + 2 * n * (tr_s + 1) / (n - tr_s - 2))


def fit_gwr(coords: np.ndarray, y: np.ndarray, X: np.ndarray):
    """GWR bisquare adaptativo com banda escolhida por AICc (seção áurea do mgwr, AICc em lote)."""
    bw = golden_section(
        40 + 2 * (X.shape[1] + 1), len(y), 0.38197, lambda b: gwr_aicc(coords, y, X, int(b)), 1e-6, 200, None, True
    )[0]
    return bw, GWR(coords, y, X, bw, kernel="bisquare", fixed=False).fit()


def fit_gwr_fixed(coords: np.ndarray, y: np.ndarray, X: np.ndarray):
    """GWR com núcleo gaussiano fixo e banda (m) por AICc, como no GWmodel usado pelo artigo."""
    bw = Sel_BW(coords, y, X, kernel="gaussian", fixed=True).search(criterion="AICc")
    return bw, GWR(coords, y, X, bw, kernel="gaussian", fixed=True).fit()


def gwmodel_adj_r2(results, n: int) -> float:
    """R² ajustado do GWmodel: parâmetros efetivos = 2 tr(S) - tr(S'S)."""
    enp = 2 * results.tr_S - results.tr_STS
    return float(1 - (1 - results.R2) * (n - 1) / (n - enp - 1))


def plot_map(gdf, column, ax, cmap, **kwargs) -> None:
    gdf.plot(column=column, cmap=cmap, legend=True, ax=ax, edgecolor="black", linewidth=0.1, **kwargs)


def with_gdp_log(cols: list[str]) -> list[str]:
    return ["log_gdp_capita" if c == "gdp_capita" else c for c in cols]


def run_moran(gdf, w) -> dict:
    mi = Moran(gdf["dengue_incidence"], w)
    metrics = {"global_moran_i": float(mi.I), "global_moran_p": float(mi.p_sim)}
    save_json(metrics, "moran_metrics.json")

    lisa = Moran_Local(gdf["dengue_incidence"], w)
    gdf["lisa_q"], gdf["lisa_p"] = lisa.q, lisa.p_sim
    gdf["lisa_cluster"] = 0
    significant = lisa.p_sim < 0.05
    for q in (1, 2, 3, 4):
        gdf.loc[(lisa.q == q) & significant, "lisa_cluster"] = q

    fig, ax = plt.subplots(figsize=(10, 8))
    patches = []
    for cluster, color in LISA_COLORS.items():
        subset = gdf[gdf["lisa_cluster"] == cluster]
        if not subset.empty:
            subset.plot(ax=ax, color=color, edgecolor="black", linewidth=0.1)
            patches.append(mpatches.Patch(color=color, label=LISA_LABELS[cluster]))
    ax.legend(handles=patches, loc="lower left", title="Clusters LISA")
    ax.set_title("Clusters Espaciais de Incidência de Dengue (LISA)")
    ax.axis("off")
    fig.savefig(FIGURES_DIR / "07_lisa_clusters.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return metrics


def run_ols(gdf, w) -> dict:
    y, X = gdf["dengue_incidence"].values, gdf[PRED_COLS].values
    vif = pd.DataFrame({"Feature": PRED_COLS, "VIF": [variance_inflation_factor(X, i) for i in range(X.shape[1])]})
    vif.to_csv(RESULTS_DIR / "ols_vif.csv", index=False)

    ols = OLS(y.reshape(-1, 1), X, w=w, name_y="dengue", name_x=PRED_COLS)
    resid = ols.u.flatten()
    mi = Moran(resid, w)
    (RESULTS_DIR / "ols_summary.txt").write_text(ols.summary)
    metrics = {
        "ols_r2": float(ols.r2),
        "ols_adj_r2": float(ols.ar2),
        "ols_aic": float(ols.aic),
        "ols_residual_moran_i": float(mi.I),
        "ols_residual_moran_p": float(mi.p_sim),
    }
    save_json(metrics, "ols_metrics.json")
    gdf["residuo_ols"], gdf["fitted_ols"] = resid, y - resid
    return metrics


def run_gwr(gdf, coords) -> dict:
    cols = with_gdp_log(PRED_COLS)
    y = gdf["dengue_incidence"].values.reshape(-1, 1)
    bw, results = fit_gwr(coords, y, zscore(gdf[cols].values))

    gdf["r2_local_gwr"] = results.localR2
    gdf["y_pred_gwr"] = results.predy.flatten()
    gdf["resid_gwr"] = results.resid_response.flatten()
    pvals = results.pvalues if results.pvalues is not None else 2 * norm.sf(np.abs(results.tvalues))
    for i, name in enumerate(["Intercepto", *PRED_COLS]):
        gdf[f"coef_{name}"] = results.params[:, i]
        gdf[f"tvalue_{name}"] = results.tvalues[:, i]
        gdf[f"pvalue_{name}"] = pvals[:, i]

    metrics = {
        "gwr_r2": float(results.R2),
        "gwr_adj_r2": float(results.adj_R2),
        "gwr_aic": float(results.aic),
        "gwr_bw": float(bw),
    }
    save_json(metrics, "gwr_metrics.json")
    return metrics


def plot_baseline_diagnostics(gdf, gwr_r2: float) -> None:
    """Resíduos do OLS, R² local do GWR e resumo dos coeficientes locais."""
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    axes[0].hist(gdf["residuo_ols"], bins=40, edgecolor="k")
    axes[0].set_title("OLS Residuals Distribution")
    axes[1].scatter(gdf["fitted_ols"], gdf["residuo_ols"], alpha=0.4, s=10)
    axes[1].set_title("Residuals vs Fitted")
    plot_map(gdf, "residuo_ols", axes[2], "PRGn")
    axes[2].set_title("OLS Residuals Map")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "08_ols_residuals.png", dpi=150)

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    gdf["r2_local_gwr"].hist(bins=30, ax=axes[0], edgecolor="k")
    axes[0].set_title("Local R² Distribution (GWR)")
    plot_map(gdf, "r2_local_gwr", axes[1], "YlOrBr")
    axes[1].set_title(f"Local R² Map (Global R²={gwr_r2:.2f})")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "09_gwr_r2_local.png", dpi=150)

    names = ["Intercepto", *PRED_COLS]
    stats = gdf[[f"coef_{n}" for n in names]].describe().T
    significant = gdf[[f"pvalue_{n}" for n in names]].apply(lambda x: (x < 0.05).sum())
    significant.index = [f"coef_{n}" for n in names]
    pd.concat([stats, significant.rename("sig_count")], axis=1).to_csv(RESULTS_DIR / "gwr_coefficients_summary.csv")


def run_transformed(gdf, w, coords, gwr_r2: float) -> dict:
    """log1p em y e X, padronização, OLS + GWR; compara o R² local com o baseline."""
    y = np.log1p(gdf["dengue_incidence"].values).reshape(-1, 1)
    X_log = np.log1p(np.maximum(gdf[PRED_COLS].values, 0))
    X = zscore(X_log, 1e-9)
    X += RNG.normal(0, 1e-10, X.shape)

    norm_df = pd.DataFrame(X, columns=PRED_COLS).assign(dengue_incidence_log=y.flatten())
    fig, ax = plt.subplots(figsize=(11, 9))
    sns.heatmap(
        norm_df.corr(), mask=np.triu(np.ones_like(norm_df.corr(), dtype=bool)),
        annot=True, fmt=".2f", cmap="RdBu_r", center=0, ax=ax,
    )  # fmt: skip
    fig.savefig(FIGURES_DIR / "10_normalized_correlation.png", dpi=150)
    plt.close(fig)

    ols = OLS(y, X, w=w, name_x=PRED_COLS)
    bw, results = fit_gwr(coords, y, X)
    gdf["r2_local_gwr_transformed"] = results.localR2

    base, trans = gdf["r2_local_gwr"], gdf["r2_local_gwr_transformed"]
    limits = {"vmin": min(base.min(), trans.min()), "vmax": max(base.max(), trans.max())}
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    plot_map(gdf, "r2_local_gwr", axes[0], "YlOrBr", **limits)
    axes[0].set_title(f"GWR (R²={gwr_r2:.3f})")
    plot_map(gdf, "r2_local_gwr_transformed", axes[1], "YlOrBr", **limits)
    axes[1].set_title(f"GWR com Transformações (R²={float(results.R2):.3f})")
    for ax in axes:
        ax.axis("off")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "11_gwr_r2_comparison.png", dpi=150)
    plt.close(fig)

    metrics = {
        "ols_trans_r2": float(ols.r2),
        "ols_trans_aic": float(ols.aic),
        "gwr_trans_r2": float(results.R2),
        "gwr_trans_adj_r2": float(results.adj_R2),
        "gwr_trans_aic": float(results.aic),
        "gwr_trans_bw": float(bw),
    }
    save_json(metrics, "transformed_metrics.json")
    return metrics


def run_paper(gdf, w, coords) -> dict:
    """Reprodução do artigo: 4 variáveis, versões transformada e bruta, GWR gaussiano fixo (AICc)."""
    cols = PAPER_COLS  # como na Tabela 2 do artigo: PIB per capita sem log
    X_raw = gdf[cols].values.astype(float)
    y_raw = gdf["dengue_incidence"].values.astype(float).reshape(-1, 1)
    X_std = zscore(X_raw, 1e-9)
    X_std += RNG.normal(0, 1e-10, X_std.shape)
    y_trans = np.log1p(y_raw)

    n = len(y_raw)
    ols_trans = OLS(y_trans, X_std, w=w, name_y="dengue", name_x=cols)
    _, res_trans = fit_gwr_fixed(coords, y_trans, X_std)
    ols_raw = OLS(y_raw, X_raw, w=w, name_y="dengue", name_x=cols)
    bw_raw, res_raw = fit_gwr_fixed(coords, y_raw, X_raw)
    k = len(cols) + 1
    delta_aicc = float(res_raw.aicc - (ols_raw.aic + 2 * k * (k + 1) / (n - k - 1)))

    vifs = [variance_inflation_factor(sm.add_constant(X_raw), i) for i in range(1, X_raw.shape[1] + 1)]
    pd.DataFrame(
        {
            "Name": ["Intercept"] + ["Average GDP per capita" if n == "gdp_capita" else n for n in cols],
            "Estimate": ols_raw.betas.flatten(),
            "Std.Err": ols_raw.std_err.flatten(),
            "VIF": ["-"] + [round(v, 2) for v in vifs],
        }
    ).to_csv(RESULTS_DIR / "paper_table2_ols.csv", index=False)
    pd.DataFrame(res_raw.params, columns=["Intercept", *cols]).describe().T.to_csv(RESULTS_DIR / "paper_table3_gwr.csv")

    metrics = {
        "ols_paper_r2": float(ols_trans.r2),
        "ols_paper_aic": float(ols_trans.aic),
        "gwr_paper_r2": float(res_trans.R2),
        "gwr_paper_adj_r2": float(res_trans.adj_R2),
        "gwr_paper_aic": float(res_trans.aic),
        "ols_raw_paper_r2": float(ols_raw.r2),
        "ols_raw_paper_aic": float(ols_raw.aic),
        "gwr_raw_paper_r2": float(res_raw.R2),
        "gwr_raw_paper_adj_r2": float(res_raw.adj_R2),
        "gwr_raw_paper_adj_r2_gwmodel": gwmodel_adj_r2(res_raw, n),
        "gwr_raw_paper_delta_aicc_vs_ols": delta_aicc,
        "gwr_raw_paper_bw_km": float(bw_raw) / 1000,
        "ols_raw_paper_adj_r2": float(ols_raw.ar2),
        "gwr_raw_paper_aic": float(res_raw.aic),
    }
    save_json(metrics, "paper_metrics.json")
    return metrics


def run_hierarchical(gdf) -> dict:
    """MixedLM por estado e OLS com dummies de estado, nos quatro cenários."""
    gdf["y_raw"] = gdf["dengue_incidence"]
    gdf["y_trans"] = np.log1p(gdf["dengue_incidence"])
    for col in dict.fromkeys(PRED_COLS + PAPER_COLS):
        gdf[f"std_{col}"] = zscore(np.log1p(np.maximum(gdf[col].values, 0)), 1e-9)
    trans = [f"std_{c}" for c in PRED_COLS]
    scenarios = {
        "raw_9": ("y_raw", PRED_COLS),
        "trans_9": ("y_trans", trans),
        "raw_4": ("y_raw", PAPER_COLS),
        "trans_4": ("y_trans", [f"std_{c}" for c in PAPER_COLS]),
    }

    results = {}
    for label, (y_col, x_cols) in scenarios.items():
        print(f"\n--- Cenário: {label} ---")
        formula = f"{y_col} ~ " + " + ".join(x_cols)
        state = smf.mixedlm(formula, gdf, groups=gdf["abbrev_state"], re_formula=f"~{x_cols[0]}").fit()
        n_params = len(state.fe_params) + len(state.cov_re.values.flatten())
        muni = smf.ols(formula + " + C(abbrev_state)", data=gdf).fit()
        results[label] = {
            "state_r2": float(np.corrcoef(gdf[y_col], state.fittedvalues)[0, 1] ** 2),
            "state_aic": float(-2 * state.llf + 2 * n_params),
            "muni_r2": float(muni.rsquared),
            "muni_aic": float(muni.aic),
        }
    save_json(results, "hierarchical_metrics_expanded.json")

    best = smf.mixedlm(
        "y_trans ~ " + " + ".join(trans), gdf,
        groups=gdf["abbrev_state"], re_formula="~std_avg_deforestation",
    ).fit()  # fmt: skip
    for state_code, effects in best.random_effects.items():
        in_state = gdf["abbrev_state"] == state_code
        gdf.loc[in_state, "re_intercept"] = effects["Group"]
        gdf.loc[in_state, "re_deforestation"] = effects["std_avg_deforestation"]
    return results


def print_summary(moran: dict, metrics: dict[str, dict], hierarchical: dict) -> None:
    def fmt(r2, aic) -> str:
        return f"{round(r2, 3) if r2 else 0} ({round(aic, 1) if aic else '-'})"

    print(f"Moran global dengue: {moran['global_moran_i']:.3f} (p={moran['global_moran_p']:.3f})\n")
    ols, gwr, trans, paper = (metrics[k] for k in ("ols", "gwr", "trans", "paper"))
    scenarios = [
        ("1. Baseline (Raw)", 9, "raw_9", ols["ols_r2"], ols["ols_aic"], gwr["gwr_r2"], gwr["gwr_aic"]),
        ("2. Transformado Otimizado", 9, "trans_9", trans["ols_trans_r2"], trans["ols_trans_aic"],
         trans["gwr_trans_r2"], trans["gwr_trans_aic"]),
        ("3. Paper (Raw, GWR fixo)", 4, "raw_4", paper["ols_raw_paper_r2"], paper["ols_raw_paper_aic"],
         paper["gwr_raw_paper_r2"], paper["gwr_raw_paper_aic"]),
        ("4. Paper (Transf, GWR fixo)", 4, "trans_4", paper["ols_paper_r2"], paper["ols_paper_aic"],
         paper["gwr_paper_r2"], paper["gwr_paper_aic"]),
    ]  # fmt: skip
    rows = []
    for label, n_vars, key, ols_r2, ols_aic, gwr_r2, gwr_aic in scenarios:
        h = hierarchical[key]
        rows.append(
            {
                "Iteração": label,
                "Vars": n_vars,
                "OLS R² (AIC)": fmt(ols_r2, ols_aic),
                "Hier (Muni) R² (AIC)": f"{round(h['muni_r2'], 3)} ({round(h['muni_aic'], 1)})",
                "Hier (Est.) R² (AIC)": f"{round(h['state_r2'], 3)} ({round(h['state_aic'], 1)})",
                "GWR R² (AIC)": fmt(gwr_r2, gwr_aic),
            }
        )
    table = pd.DataFrame(rows)
    print(table.to_string(index=False))
    table.to_csv(RESULTS_DIR / "10_final_model_comparison.csv", index=False)


def main() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    FIGURES_DIR.mkdir(exist_ok=True)
    gdf = gpd.read_file(DATA_PATH)
    # Municípios sem desmatamento não têm distância às rodovias: usa a mediana (só afeta os cenários de 9 variáveis).
    gdf["dist_roads"] = gdf["dist_roads"].fillna(gdf["dist_roads"].median())
    gdf["log_gdp_capita"] = np.log1p(gdf["gdp_capita"])
    w = libpysal.weights.Queen.from_dataframe(gdf, use_index=False)
    w.transform = "r"
    projected = gdf.to_crs("EPSG:5880").geometry.centroid
    coords = np.column_stack([projected.x, projected.y])

    moran = run_moran(gdf, w)
    metrics = {"ols": run_ols(gdf, w), "gwr": run_gwr(gdf, coords)}
    plot_baseline_diagnostics(gdf, metrics["gwr"]["gwr_r2"])
    metrics["trans"] = run_transformed(gdf, w, coords, metrics["gwr"]["gwr_r2"])
    metrics["paper"] = run_paper(gdf, w, coords)
    hierarchical = run_hierarchical(gdf)
    gdf.to_file(RESULTS_DIR / "results_geo.gpkg", layer="results", driver="GPKG")
    print_summary(moran, metrics, hierarchical)


if __name__ == "__main__":
    main()
