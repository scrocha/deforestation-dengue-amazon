import math
import textwrap
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.colors import PowerNorm
from scipy.stats import spearmanr
from statsmodels.nonparametric.smoothers_lowess import lowess

plt.switch_backend("Agg")  # sem janela: o pipeline só grava figuras

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "processed"
FIGURES_DIR = ROOT / "figures"
FIGURES_DIR.mkdir(exist_ok=True)

MODEL_VARS = [
    "dengue_incidence", "avg_deforestation", "std_deforestation", "dist_roads", "average_min_precipitation",
    "gdp_capita", "urban_pop", "rural_pop", "population_estimated", "std_urban_pop", "std_rural_pop",
    "std_population_estimated", "std_agri_credit", "std_live_credit", "std_crop_area",
]  # fmt: skip


LABELS = {
    "dengue_incidence": "Incidência de dengue (casos/100 mil, média semanal)",
    "avg_deforestation": "Desmatamento médio anual (km²)",
    "std_deforestation": "Desmatamento por área (km²/km²)",
    "dist_roads": "Distância às rodovias (km)",
    "average_min_precipitation": "Precipitação mínima (mm)",
    "gdp_capita": "PIB per capita (mil R$/hab.)",
    "urban_pop": "População urbana (hab.)",
    "rural_pop": "População rural (hab.)",
    "population_estimated": "População estimada (hab.)",
    "std_urban_pop": "População urbana por área (hab./km²)",
    "std_rural_pop": "População rural por área (hab./km²)",
    "std_population_estimated": "População estimada por área (hab./km²)",
    "std_agri_credit": "Crédito agrícola por área (R$/km²)",
    "std_live_credit": "Crédito pecuário por área (R$/km²)",
    "std_crop_area": "Área de lavoura por área (km²/km²)",
}


def short(col):
    """Nome sem a unidade, para títulos de painel."""
    return textwrap.fill(LABELS[col].split(" (")[0], 24)


def unit(col):
    return LABELS[col].split(" (")[1].rstrip(")")


def panel_grid(columns, width, height, n_cols=4):
    """Grade de painéis, um por coluna (os sobrantes ficam ocultos)."""
    n_rows = math.ceil(len(columns) / n_cols)
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(width * n_cols, height * n_rows))
    axes = np.array(axes).flatten()
    for ax in axes[len(columns) :]:
        ax.set_visible(False)
    return fig, axes[: len(columns)]


def save(fig, name):
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(FIGURES_DIR / name, dpi=150)
    plt.close(fig)


def hide_spines(ax):
    ax.spines[["top", "right"]].set_visible(False)


def export_statistics(df):
    stats = df[MODEL_VARS].describe().T
    stats["zeros"] = (df[MODEL_VARS] == 0).sum()
    stats["nas"] = df[MODEL_VARS].isna().sum()
    stats["skewness"] = df[MODEL_VARS].skew()
    stats.to_csv(DATA_DIR / "03_eda_statistics.csv")


def plot_distributions(df):
    fig, axes = panel_grid(MODEL_VARS, 4, 3)
    for ax, col in zip(axes, MODEL_VARS):
        df[col].hist(ax=ax, bins=40, edgecolor="k", color="lightblue", grid=False)
        median = df[col].median()
        ax.axvline(median, color="crimson", ls="--", lw=1)
        ax.text(0.97, 0.92, f"mediana = {median:.4g}", transform=ax.transAxes, ha="right", fontsize=8, color="crimson")
        ax.set_title(short(col), fontsize=10)
        ax.set_xlabel(unit(col))
        ax.set_ylabel("Municípios")
        hide_spines(ax)
    fig.suptitle("Distribuição das variáveis (560 municípios; linha tracejada = mediana)")
    save(fig, "01_distributions.png")

    # Escalas muito diferentes: boxplot em log(1+x) para que todas as variáveis sejam legíveis.
    fig, ax = plt.subplots(figsize=(9, 7))
    df[MODEL_VARS].apply(np.log1p).rename(columns=lambda c: short(c).replace("\n", " ")).boxplot(ax=ax, vert=False)
    ax.invert_yaxis()
    ax.set_xlabel("log(1 + valor), na unidade de cada variável")
    ax.set_title("Boxplots das variáveis (escala logarítmica)")
    hide_spines(ax)
    save(fig, "02_boxplots.png")


# Variáveis e ordem da Fig. 4 do artigo (resposta primeiro)
PAPER_ORDER = ["dengue_incidence", "std_deforestation", "std_agri_credit", "std_live_credit", "gdp_capita",
               "std_rural_pop", "std_urban_pop", "dist_roads", "average_min_precipitation", "std_crop_area"]  # fmt: skip
# Correlações lidas da Fig. 4 do artigo (n = 550), por par (linha, coluna) na ordem acima
PAPER_CORR = {
    (1, 0): 0.18, (2, 0): 0.36, (2, 1): 0.05, (3, 0): 0.25, (3, 1): 0.06, (3, 2): 0.30, (4, 0): 0.36, (4, 1): 0.07,
    (4, 2): 0.60, (4, 3): 0.26, (5, 0): -0.20, (5, 1): 0.06, (5, 2): -0.18, (5, 3): -0.28, (5, 4): -0.16,
    (6, 0): -0.04, (6, 1): -0.01, (6, 2): -0.05, (6, 3): -0.10, (6, 4): 0.07, (6, 5): 0.17, (7, 0): -0.02,
    (7, 1): -0.05, (7, 2): -0.08, (7, 3): -0.11, (7, 4): -0.10, (7, 6): -0.03, (8, 0): -0.15, (8, 1): -0.11,
    (8, 2): -0.21, (8, 3): -0.26, (8, 4): -0.19, (8, 5): 0.14, (8, 6): 0.06, (8, 7): 0.50, (9, 0): 0.34,
    (9, 1): 0.04, (9, 2): 0.70, (9, 3): 0.09, (9, 4): 0.54, (9, 5): -0.14, (9, 6): -0.03, (9, 7): -0.11,
    (9, 8): -0.22,
}  # fmt: skip


def corr_triangle(matrix, ax, title, annot):
    """Triângulo inferior no estilo da Fig. 4 do artigo: diagonal incluída, escala fixa de -1 a 1, barra horizontal."""
    names = [short(c).replace("\n", " ") for c in PAPER_ORDER]
    sns.heatmap(
        pd.DataFrame(matrix, index=names, columns=names), mask=np.triu(np.ones_like(matrix, dtype=bool), k=1),
        annot=annot, fmt=".2f", cmap="RdBu", vmin=-1, vmax=1, linewidths=0.5, linecolor="lightgrey", ax=ax,
        cbar_kws={"orientation": "horizontal", "shrink": 0.6, "pad": 0.27, "label": "Correlação de Pearson"},
    )  # fmt: skip
    ax.set_title(title)


def plot_correlation(df):
    data = df[PAPER_ORDER].copy()
    data["dist_roads"] = data["dist_roads"].fillna(data["dist_roads"].median())  # como nos modelos
    ours = data.corr().values

    fig, ax = plt.subplots(figsize=(10, 9))
    corr_triangle(ours, ax, "Matriz de correlação (560 municípios)", annot=True)
    save(fig, "03_correlation_matrix.png")

    # Comparação com o artigo: triângulo inferior = este repositório; superior = Fig. 4 do artigo
    combined = ours.copy()
    for (i, j), value in PAPER_CORR.items():
        combined[j, i] = value
    names = [short(c).replace("\n", " ") for c in PAPER_ORDER]
    fig, ax = plt.subplots(figsize=(11, 9))
    sns.heatmap(
        pd.DataFrame(combined, index=names, columns=names), annot=True, fmt=".2f", cmap="RdBu", vmin=-1, vmax=1,
        linewidths=0.5, linecolor="lightgrey", ax=ax,
        cbar_kws={"orientation": "horizontal", "shrink": 0.6, "pad": 0.12, "label": "Correlação de Pearson"},
    )  # fmt: skip
    ax.set_title("Correlações: este repositório (abaixo da diagonal, n = 560) e artigo (acima, Fig. 4, n = 550)")
    ax.xaxis.tick_top()
    plt.setp(ax.get_xticklabels(), rotation=45, ha="left")
    save(fig, "14_correlation_vs_paper.png")


def plot_scatters(df):
    predictors = [c for c in MODEL_VARS if c != "dengue_incidence"]
    fig, axes = panel_grid(predictors, 5, 3.5)
    for ax, col in zip(axes, predictors):
        valid = df[col].notna()  # dist_roads é ausente onde não há desmatamento
        x, y = df.loc[valid, col], df.loc[valid, "dengue_incidence"]
        ax.scatter(x, y, alpha=0.3, s=15, color="steelblue")
        trend = lowess(y, x, frac=0.6)  # tendência sem supor reta e sem extrapolar abaixo de zero
        ax.plot(trend[:, 0], trend[:, 1], color="crimson", lw=1.8)
        positive = x[x > 0]
        ax.set_xscale("symlog", linthresh=positive.quantile(0.1) if len(positive) else 1)  # linear perto de 0, log acima
        rho = spearmanr(x, y)[0]
        ax.text(0.97, 0.92, f"ρ = {rho:.2f}", transform=ax.transAxes, ha="right", fontsize=9)
        ax.set_title(short(col), fontsize=10)
        ax.set_xlabel(unit(col))
        ax.set_ylabel("Dengue (casos/100 mil)")
        hide_spines(ax)
    fig.suptitle("Incidência de dengue contra cada preditor (eixo x simétrico-log; vermelho = LOWESS; ρ = Spearman)")
    save(fig, "04_scatter_plots.png")


def map_panel(gdf, col, ax, cmap, label=None, gamma=0.5, **kwargs):
    """Mapa com escala de cores em raiz quadrada (variáveis assimétricas) e dado ausente em cinza."""
    values = gdf[col].dropna()
    gdf.plot(
        column=col, cmap=cmap, norm=PowerNorm(gamma, vmin=values.min(), vmax=values.max()), legend=True,
        edgecolor="black", linewidth=0.1, ax=ax, legend_kwds={"label": label, "shrink": 0.6},
        missing_kwds={"color": "lightgrey"}, **kwargs,
    )  # fmt: skip
    ax.axis("off")


def plot_maps(gdf):
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    for ax, col in zip(axes, ["dengue_incidence", "avg_deforestation"]):
        map_panel(gdf, col, ax, "YlOrBr", LABELS[col])
        ax.set_title(short(col).replace("\n", " "))
    fig.suptitle("Escala de cores em raiz quadrada, que realça diferenças entre valores baixos")
    save(fig, "05_exploratory_map.png")

    predictors = [c for c in MODEL_VARS if c not in ["dengue_incidence", "avg_deforestation", "std_deforestation"]]
    fig, axes = panel_grid(predictors, 6, 4)
    for ax, col in zip(axes, predictors):
        cmap = "Greens" if any(key in col for key in ("precipitation", "crop", "agri")) else "YlOrBr"
        map_panel(gdf, col, ax, cmap, gamma=0.3)
        ax.set_title(short(col), fontsize=10)
    fig.suptitle("Preditores por município (escala de cores em potência 0,3, que realça diferenças entre valores baixos; cinza = sem dado)")
    save(fig, "06_predictors_maps.png")


def main():
    csv_path = DATA_DIR / "deforestation_dengue_data.csv"
    gpkg_path = DATA_DIR / "deforestation_dengue_geo.gpkg"
    if not (csv_path.exists() and gpkg_path.exists()):
        return
    df = pd.read_csv(csv_path)
    export_statistics(df)
    plot_distributions(df)
    plot_correlation(df)
    plot_scatters(df)
    plot_maps(gpd.read_file(gpkg_path))


if __name__ == "__main__":
    main()
