import math
import textwrap
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

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
        ax.set_title(short(col), fontsize=10)
        ax.set_xlabel(unit(col))
        ax.set_ylabel("Municípios")
        hide_spines(ax)
    fig.suptitle("Distribuição das variáveis (560 municípios)")
    save(fig, "01_distributions.png")

    # Escalas muito diferentes: boxplot em log(1+x) para que todas as variáveis sejam legíveis.
    fig, ax = plt.subplots(figsize=(9, 7))
    df[MODEL_VARS].apply(np.log1p).rename(columns=lambda c: short(c).replace("\n", " ")).boxplot(ax=ax, vert=False)
    ax.invert_yaxis()
    ax.set_xlabel("log(1 + valor), na unidade de cada variável")
    ax.set_title("Boxplots das variáveis (escala logarítmica)")
    hide_spines(ax)
    save(fig, "02_boxplots.png")


def plot_correlation(df):
    corr = df[MODEL_VARS].corr().rename(index=lambda c: short(c).replace("\n", " "), columns=lambda c: short(c).replace("\n", " "))
    corr = corr.iloc[1:, :-1]  # sem a diagonal nem o triângulo superior
    fig, ax = plt.subplots(figsize=(11, 9))
    sns.heatmap(
        corr, mask=np.triu(np.ones_like(corr, dtype=bool), k=1), annot=True, fmt=".2f", cmap="RdBu_r", center=0,
        cbar_kws={"label": "Correlação de Pearson"}, ax=ax,
    )
    ax.set_title("Correlação entre as variáveis (560 municípios)")
    save(fig, "03_correlation_matrix.png")


def plot_scatters(df):
    predictors = [c for c in MODEL_VARS if c != "dengue_incidence"]
    fig, axes = panel_grid(predictors, 5, 3.5)
    for ax, col in zip(axes, predictors):
        ax.scatter(df[col], df["dengue_incidence"], alpha=0.3, s=15, color="steelblue")
        ax.set_title(short(col), fontsize=10)
        ax.set_xlabel(unit(col))
        ax.set_ylabel("Dengue (casos/100 mil)")
        fit = np.poly1d(np.polyfit(df[col].fillna(0), df["dengue_incidence"], 1))
        x = np.linspace(df[col].min(), df[col].max(), 100)
        ax.plot(x, fit(x), "r--", lw=1.5)
        hide_spines(ax)
    fig.suptitle("Incidência de dengue contra cada preditor (linha tracejada: ajuste linear)")
    save(fig, "04_scatter_plots.png")


def plot_maps(gdf):
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    for ax, col in zip(axes, ["dengue_incidence", "avg_deforestation"]):
        gdf.plot(column=col, cmap="YlOrBr", legend=True, edgecolor="black", linewidth=0.2, ax=ax,
                 legend_kwds={"label": LABELS[col], "shrink": 0.6})  # fmt: skip
        ax.set_title(short(col).replace("\n", " "))
        ax.axis("off")
    save(fig, "05_exploratory_map.png")

    predictors = [c for c in MODEL_VARS if c not in ["dengue_incidence", "avg_deforestation", "std_deforestation"]]
    fig, axes = panel_grid(predictors, 6, 4)
    for ax, col in zip(axes, predictors):
        vmin, vmax = gdf[col].quantile([0.05, 0.95])
        limits = {} if vmin == vmax else {"vmin": vmin, "vmax": vmax}
        cmap = "Greens" if any(key in col for key in ("precipitation", "crop", "agri")) else "YlOrBr"
        gdf.plot(column=col, cmap=cmap, legend=True, edgecolor="black", linewidth=0.1, ax=ax,
                 legend_kwds={"shrink": 0.6}, **limits)  # fmt: skip
        ax.set_title(short(col), fontsize=10)
        ax.axis("off")
    fig.suptitle("Preditores por município (escala de cores truncada nos percentis 5 e 95)")
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
