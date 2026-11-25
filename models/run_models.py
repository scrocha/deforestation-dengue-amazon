"""Moran, OLS, GWR, cenários transformados/paper, hierárquico e resumo final.

Lê data/processed/deforestation_dengue_geo.gpkg e grava métricas e tabelas em
data/results/ e figuras em figures/.
"""

import json
from pathlib import Path

import geopandas as gpd
import libpysal
import matplotlib.patches as mpatches
from matplotlib.colors import BoundaryNorm
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

plt.switch_backend("Agg")  # sem janela: o pipeline só grava figuras
plt.rcParams["hatch.linewidth"] = 0.4

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
LABELS = {
    "avg_deforestation": "Desmatamento médio anual", "dist_roads": "Distância às rodovias",
    "average_min_precipitation": "Precipitação mínima", "gdp_capita": "PIB per capita",
    "std_rural_pop": "População rural por área", "std_urban_pop": "População urbana por área",
    "std_agri_credit": "Crédito agrícola por área", "std_live_credit": "Crédito pecuário por área",
    "std_crop_area": "Área de lavoura por área", "dengue_incidence_log": "log(1 + incidência de dengue)",
}  # fmt: skip
LISA_COLORS = {0: "#f0f0eb", 1: "#e41a1c", 2: "#1fb5f0", 3: "#1b5fd6", 4: "#f7b6bd"}  # cores do artigo (Fig. 3)
LISA_LABELS = {
    0: "Não significativo",
    1: "Alto-Alto (cluster)",
    2: "Baixo-Alto (outlier)",
    3: "Baixo-Baixo (cluster)",
    4: "Alto-Baixo (outlier)",
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
    return bw, GWR(coords, y, X, bw, kernel="bisquare", fixed=False, n_jobs=1).fit()


def fit_gwr_fixed(coords: np.ndarray, y: np.ndarray, X: np.ndarray):
    """GWR com núcleo gaussiano fixo e banda (m) por AICc, como no GWmodel usado pelo artigo."""
    bw = Sel_BW(coords, y, X, kernel="gaussian", fixed=True, n_jobs=1).search(criterion="AICc")
    return bw, GWR(coords, y, X, bw, kernel="gaussian", fixed=True, n_jobs=1).fit()


def gwmodel_adj_r2(results, n: int) -> float:
    """R² ajustado do GWmodel: parâmetros efetivos = 2 tr(S) - tr(S'S)."""
    enp = 2 * results.tr_S - results.tr_STS
    return float(1 - (1 - results.R2) * (n - 1) / (n - enp - 1))


def standardize(x: np.ndarray) -> np.ndarray:
    """Z-score com ruído mínimo contra colinearidade exata."""
    z = zscore(x, 1e-9)
    return z + RNG.normal(0, 1e-10, z.shape)


def save_fig(fig, name: str, tight: bool = True, **kwargs) -> None:
    if tight:
        fig.tight_layout()
    fig.savefig(FIGURES_DIR / name, dpi=150, **kwargs)
    plt.close(fig)


def frame_map(ax, bounds, decorate) -> None:
    """Moldura no estilo do artigo: caixa, graticule em graus e, se 'full', seta norte e barra de escala."""
    xmin, ymin, xmax, ymax = bounds
    ax.set_xlim(xmin - 0.5, xmax + 0.5)
    ax.set_ylim(ymin - 0.5, ymax + 0.5)
    ax.axis("on")
    if decorate != "full":
        ax.set_xticks([])
        ax.set_yticks([])
        return
    ax.set_xticks([-70, -60, -50], [f"{-x}°O" for x in (-70, -60, -50)], fontsize=8)
    ax.set_yticks([-10, 0], ["10°S", "0°"], fontsize=8)
    km_deg = 111.32 * np.cos(np.radians(10))  # 1° de longitude a ~10°S
    x0, y0 = xmax - 6, ymin + 0.4
    ax.plot([x0, x0 + 500 / km_deg], [y0, y0], "k-", lw=3, solid_capstyle="butt")
    ax.text(x0 + 250 / km_deg, y0 + 0.4, "500 km", ha="center", fontsize=8)
    ax.annotate("N", xy=(xmin + 1.5, ymax - 0.2), xytext=(xmin + 1.5, ymax - 2.8), ha="center", fontsize=10,
                arrowprops={"arrowstyle": "-|>", "color": "k"})  # fmt: skip


def plot_map(gdf, column, ax, cmap, label=None, bins=None, extend="neither", decorate="box", **kwargs) -> None:
    """Mapa coroplético; com `bins`, classes discretas como nas figuras do artigo."""
    legend_kwds = {"label": label, "shrink": 0.7}
    if bins is not None:
        n_colors = len(bins) - 1 + (2 if extend == "both" else 0)
        cmap = plt.get_cmap(cmap, n_colors)
        kwargs["norm"] = BoundaryNorm(bins, n_colors, extend=extend)
        legend_kwds["extend"] = extend
    gdf.plot(column=column, cmap=cmap, legend=True, ax=ax, edgecolor="black", linewidth=0.1,
             legend_kwds=legend_kwds, **kwargs)  # fmt: skip
    frame_map(ax, gdf.total_bounds, decorate)


def r2_bins(*values):
    low = np.floor(min(v.min() for v in values) * 10) / 10
    high = np.ceil(max(v.max() for v in values) * 10) / 10
    return np.round(np.arange(low, high + 0.05, 0.1), 1)


def with_gdp_log(cols: list[str]) -> list[str]:
    return ["log_gdp_capita" if c == "gdp_capita" else c for c in cols]


def run_moran(gdf, w) -> dict:
    np.random.seed(42)  # as permutações do Moran usam o RNG global; fixa os clusters LISA entre execuções
    mi = Moran(gdf["dengue_incidence"], w)
    metrics = {"global_moran_i": float(mi.I), "global_moran_p": float(mi.p_sim)}
    save_json(metrics, "moran_metrics.json")

    lisa = Moran_Local(gdf["dengue_incidence"], w)
    gdf["lisa_q"], gdf["lisa_p"] = lisa.q, lisa.p_sim
    gdf["lisa_cluster"] = 0
    significant = lisa.p_sim < 0.05
    for q in (1, 2, 3, 4):
        gdf.loc[(lisa.q == q) & significant, "lisa_cluster"] = q

    fig, (ax, ax_moran) = plt.subplots(1, 2, figsize=(16, 7), gridspec_kw={"width_ratios": [2.2, 1]})
    patches = []
    for cluster, color in LISA_COLORS.items():
        subset = gdf[gdf["lisa_cluster"] == cluster]
        if not subset.empty:
            subset.plot(ax=ax, color=color, edgecolor="black", linewidth=0.15)
            patches.append(mpatches.Patch(facecolor=color, edgecolor="black", label=f"{LISA_LABELS[cluster]} (n = {len(subset)})"))
    ax.legend(handles=patches, loc="lower left", title="Legenda", fontsize=9, fancybox=False, edgecolor="black")
    ax.set_title(f"Índice local de associação espacial (LISA) da incidência de dengue\n(I de Moran global = {mi.I:.3f}; p < 0.05)")
    frame_map(ax, gdf.total_bounds, "full")

    lag = libpysal.weights.lag_spatial(w, lisa.z)
    ax_moran.scatter(lisa.z, lag, c=gdf["lisa_cluster"].map(LISA_COLORS), s=14, edgecolor="none")
    ax_moran.axhline(0, color="k", lw=0.8)
    ax_moran.axvline(0, color="k", lw=0.8)
    line = np.array([lisa.z.min(), lisa.z.max()])
    ax_moran.plot(line, mi.I * line, "k--", lw=1, label=f"inclinação = I = {mi.I:.3f}")
    ax_moran.set(title="Diagrama de Moran", xlabel="Incidência (z-score)", ylabel="Média dos vizinhos (z-score)")
    ax_moran.legend(loc="upper left", fontsize=9)
    save_fig(fig, "07_lisa_clusters.png", tight=False, bbox_inches="tight")
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
    pvalues = 2 * norm.sf(np.abs(results.tvalues))  # o mgwr não calcula p-valores locais
    for i, name in enumerate(["Intercepto", *PRED_COLS]):
        gdf[f"coef_{name}"] = results.params[:, i]
        gdf[f"tvalue_{name}"] = results.tvalues[:, i]
        gdf[f"pvalue_{name}"] = pvalues[:, i]

    metrics = {
        "gwr_r2": float(results.R2),
        "gwr_adj_r2": float(results.adj_R2),
        "gwr_aic": float(results.aic),
        "gwr_bw": float(bw),
    }
    save_json(metrics, "gwr_metrics.json")
    return metrics


def plot_baseline_diagnostics(gdf, gwr_r2: float) -> None:
    """Resíduos do OLS, R² local do GWR e resumo dos coeficientes locais (cenário A)."""
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.5))
    axes[0].hist(gdf["residuo_ols"], bins=40, edgecolor="k")
    axes[0].set(title="Distribuição dos resíduos do OLS", xlabel="Resíduo (casos/100 mil)", ylabel="Municípios")
    axes[1].scatter(gdf["fitted_ols"], gdf["residuo_ols"], alpha=0.4, s=10)
    axes[1].axhline(0, color="k", lw=0.8)
    axes[1].set(title="Resíduos contra valores ajustados", xlabel="Valor ajustado (casos/100 mil)", ylabel="Resíduo")
    limit = np.percentile(np.abs(gdf["residuo_ols"]), 95)  # escala simétrica: branco = resíduo zero
    plot_map(gdf, "residuo_ols", axes[2], "PRGn", "Resíduo (casos/100 mil)", vmin=-limit, vmax=limit)
    axes[2].set_title("Resíduos do OLS por município")
    fig.suptitle("Cenário A: OLS com 9 variáveis, escala original")
    save_fig(fig, "08_ols_residuals.png")

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    gdf["r2_local_gwr"].hist(bins=30, ax=axes[0], edgecolor="k", grid=False)
    axes[0].set(title="Distribuição do R² local", xlabel="R² local", ylabel="Municípios")
    plot_map(gdf, "r2_local_gwr", axes[1], "YlOrBr", "R² local", bins=r2_bins(gdf["r2_local_gwr"]))
    axes[1].set_title("R² local por município")
    fig.suptitle(f"Cenário A: GWR adaptativo (bisquare), 9 variáveis, escala original (R² global = {gwr_r2:.3f})")
    save_fig(fig, "09_gwr_r2_local.png")

    names = ["Intercepto", *PRED_COLS]
    stats = gdf[[f"coef_{n}" for n in names]].describe().T
    significant = gdf[[f"pvalue_{n}" for n in names]].apply(lambda x: (x < 0.05).sum())
    significant.index = [f"coef_{n}" for n in names]
    pd.concat([stats, significant.rename("sig_count")], axis=1).to_csv(RESULTS_DIR / "gwr_coefficients_summary.csv")


def run_transformed(gdf, w, coords, gwr_r2: float) -> dict:
    """log1p em y e X, padronização, OLS + GWR; compara o R² local com o baseline."""
    y = np.log1p(gdf["dengue_incidence"].values).reshape(-1, 1)
    X_log = np.log1p(np.maximum(gdf[PRED_COLS].values, 0))
    X = standardize(X_log)

    norm_df = pd.DataFrame(X, columns=PRED_COLS).assign(dengue_incidence_log=y.flatten()).rename(columns=LABELS)
    corr = norm_df.corr().iloc[1:, :-1]  # sem a diagonal nem o triângulo superior
    fig, ax = plt.subplots(figsize=(11, 9))
    sns.heatmap(
        corr, mask=np.triu(np.ones_like(corr, dtype=bool), k=1), annot=True, fmt=".2f", cmap="RdBu_r", center=0,
        cbar_kws={"label": "Correlação de Pearson"}, ax=ax,
    )  # fmt: skip
    ax.set_title("Cenário B: correlação após log(1 + x) e z-score")
    save_fig(fig, "10_normalized_correlation.png")

    ols = OLS(y, X, w=w, name_x=PRED_COLS)
    bw, results = fit_gwr(coords, y, X)
    gdf["r2_local_gwr_transformed"] = results.localR2

    base, trans = gdf["r2_local_gwr"], gdf["r2_local_gwr_transformed"]
    bins = r2_bins(base, trans)
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    plot_map(gdf, "r2_local_gwr", axes[0], "YlOrBr", "R² local", bins=bins)
    axes[0].set_title(f"A. escala original (R² global = {gwr_r2:.3f})")
    plot_map(gdf, "r2_local_gwr_transformed", axes[1], "YlOrBr", "R² local", bins=bins)
    axes[1].set_title(f"B. log(1 + x) e z-score (R² global = {float(results.R2):.3f})")
    fig.suptitle("R² local do GWR adaptativo (bisquare), 9 variáveis, na mesma escala de cores")
    save_fig(fig, "11_gwr_r2_comparison.png")

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


def plot_paper_gwr(gdf, results) -> None:
    """Cenário C no formato das Figs. 5 a 9 do artigo: R² local; coeficientes (A) e p-valores (B) por variável."""
    r2 = results.localR2
    fig, ax = plt.subplots(figsize=(9, 7))
    gdf["_v"] = r2
    plot_map(gdf, "_v", ax, "YlOrBr", "R² local", bins=r2_bins(r2), decorate="full")
    ax.set_title("Cenário C: R² local do GWR gaussiano fixo (4 variáveis, escala original)")
    save_fig(fig, "12_paper_gwr_r2.png")

    variables = {  # título: (coluna em params/tvalues, fator de unidade, unidade do coeficiente)
        "Desmatamento": (1, 1, "por km²/km²"),
        "Crédito agrícola": (2, 1000, "por mil R$/km²"),
        "Crédito pecuário": (3, 1000, "por mil R$/km²"),
        "PIB per capita": (4, 1, "por mil R$/hab."),
    }
    p_bins = [0, 0.01, 0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 1.0]
    fig, axes = plt.subplots(2, 4, figsize=(22, 9))
    for col, (title, (k, factor, unit)) in enumerate(variables.items()):
        gdf["_v"] = results.params[:, k] * factor
        limit = np.percentile(np.abs(gdf["_v"]), 95)  # extremos agrupados nas classes das pontas
        plot_map(gdf, "_v", axes[0, col], "RdBu_r", f"Coeficiente ({unit})", bins=np.linspace(-limit, limit, 9), extend="both")
        axes[0, col].set_title(title)
        gdf["_v"] = 2 * norm.sf(np.abs(results.tvalues[:, k]))
        plot_map(gdf, "_v", axes[1, col], "YlGn", "p-valor", bins=p_bins)
        for row, letter in enumerate("AB"):
            axes[row, col].text(0.03, 0.04, letter, transform=axes[row, col].transAxes, fontsize=14,
                                fontweight="bold", bbox={"facecolor": "white", "edgecolor": "black"})  # fmt: skip
    gdf.drop(columns="_v", inplace=True)
    fig.suptitle("Cenário C: (A) coeficientes locais do GWR e (B) p-valores (aproximação normal); nos coeficientes, "
                 "as classes das pontas reúnem os valores acima do percentil 95 de |coef.|")
    save_fig(fig, "13_paper_gwr_coef_pvalues.png")


def run_paper(gdf, w, coords) -> dict:
    """Reprodução do artigo: 4 variáveis, versões transformada e bruta, GWR gaussiano fixo (AICc)."""
    cols = PAPER_COLS  # como na Tabela 2 do artigo: PIB per capita sem log
    X_raw = gdf[cols].values.astype(float)
    y_raw = gdf["dengue_incidence"].values.astype(float).reshape(-1, 1)
    X_std = standardize(X_raw)
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
            "Name": ["Intercept"] + ["Average GDP per capita" if c == "gdp_capita" else c for c in cols],
            "Estimate": ols_raw.betas.flatten(),
            "Std.Err": ols_raw.std_err.flatten(),
            "VIF": ["-"] + [round(v, 2) for v in vifs],
        }
    ).to_csv(RESULTS_DIR / "paper_table2_ols.csv", index=False)
    pd.DataFrame(res_raw.params, columns=["Intercept", *cols]).describe().T.to_csv(RESULTS_DIR / "paper_table3_gwr.csv")
    plot_paper_gwr(gdf, res_raw)

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
        return f"{r2:.3f} ({aic:.1f})"

    print(f"Moran global dengue: {moran['global_moran_i']:.3f} (p={moran['global_moran_p']:.3f})\n")
    ols, gwr, trans, paper = (metrics[k] for k in ("ols", "gwr", "trans", "paper"))
    scenarios = [
        ("A. 9 vars, original", 9, "raw_9", ols["ols_r2"], ols["ols_aic"], gwr["gwr_r2"], gwr["gwr_aic"]),
        ("B. 9 vars, log1p + z-score", 9, "trans_9", trans["ols_trans_r2"], trans["ols_trans_aic"],
         trans["gwr_trans_r2"], trans["gwr_trans_aic"]),
        ("C. 4 vars (artigo), original", 4, "raw_4", paper["ols_raw_paper_r2"], paper["ols_raw_paper_aic"],
         paper["gwr_raw_paper_r2"], paper["gwr_raw_paper_aic"]),
        ("D. 4 vars (artigo), y log1p + X z-score", 4, "trans_4", paper["ols_paper_r2"], paper["ols_paper_aic"],
         paper["gwr_paper_r2"], paper["gwr_paper_aic"]),
    ]  # fmt: skip
    rows = []
    for label, n_vars, key, ols_r2, ols_aic, gwr_r2, gwr_aic in scenarios:
        h = hierarchical[key]
        rows.append(
            {
                "Cenário": label,
                "Vars": n_vars,
                "OLS R² (AIC)": fmt(ols_r2, ols_aic),
                "OLS + efeito fixo de UF R² (AIC)": fmt(h["muni_r2"], h["muni_aic"]),
                "Misto por UF R² (AIC)": fmt(h["state_r2"], h["state_aic"]),
                "GWR (A,B adaptativo; C,D fixo) R² (AIC)": fmt(gwr_r2, gwr_aic),
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
