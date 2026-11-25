import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import geopandas as gpd
from pathlib import Path
import math

__DIR = Path(__file__).parent
DATA_DIR = __DIR.parent / "data" / "processed"
FIGURES_DIR = __DIR.parent / "figures"
FIGURES_DIR.mkdir(exist_ok=True)

MODEL_VARS = [
    "dengue_incidence",
    "avg_deforestation",
    "std_deforestation",
    "dist_roads",
    "average_min_precipitation",
    "gdp_capita",
    "urban_pop",
    "rural_pop",
    "population_estimated",
    "std_urban_pop",
    "std_rural_pop",
    "std_population_estimated",
    "std_agri_credit",
    "std_live_credit",
    "std_crop_area",
]


def apply_style(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def export_statistics(df):
    stats = df[MODEL_VARS].describe().T
    stats["zeros"] = (df[MODEL_VARS] == 0).sum()
    stats["nas"] = df[MODEL_VARS].isna().sum()
    stats["skewness"] = df[MODEL_VARS].skew()
    stats.to_csv(DATA_DIR / "03_eda_statistics.csv")


def plot_distributions(df):
    n_cols = 4
    n_rows = math.ceil(len(MODEL_VARS) / n_cols)
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(4 * n_cols, 3 * n_rows))
    axes = np.array(axes).flatten()

    for ax, col in zip(axes[: len(MODEL_VARS)], MODEL_VARS):
        df[col].hist(ax=ax, bins=40, edgecolor="k", color="lightblue")
        ax.set_title(col)
        apply_style(ax)
    for i in range(len(MODEL_VARS), len(axes)):
        axes[i].set_visible(False)
    plt.tight_layout()
    fig.savefig(FIGURES_DIR / "01_distributions.png", dpi=150)
    plt.close(fig)

    fig2, ax2 = plt.subplots(figsize=(14, 5))
    df[MODEL_VARS].boxplot(ax=ax2, rot=45)
    apply_style(ax2)
    fig2.tight_layout()
    fig2.savefig(FIGURES_DIR / "02_boxplots.png", dpi=150)
    plt.close(fig2)


def plot_correlation(df):
    corr = df[MODEL_VARS].corr()
    mask = np.triu(np.ones_like(corr, dtype=bool))
    fig, ax = plt.subplots(figsize=(11, 9))
    sns.heatmap(corr, mask=mask, annot=True, fmt=".2f", cmap="RdBu_r", center=0, ax=ax)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "03_correlation_matrix.png", dpi=150)
    plt.close(fig)


def plot_scatters(df):
    predictors = [c for c in MODEL_VARS if c != "dengue_incidence"]
    n_cols = 4
    n_rows = math.ceil(len(predictors) / n_cols)
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(5 * n_cols, 3.5 * n_rows))
    axes = np.array(axes).flatten()

    for ax, col in zip(axes[: len(predictors)], predictors):
        ax.scatter(df[col], df["dengue_incidence"], alpha=0.3, s=15, color="steelblue")
        ax.set_title(f"{col}")
        z = np.polyfit(df[col].fillna(0), df["dengue_incidence"], 1)
        p = np.poly1d(z)
        xseq = np.linspace(df[col].min(), df[col].max(), 100)
        ax.plot(xseq, p(xseq), "r--", lw=1.5)
        apply_style(ax)
    for i in range(len(predictors), len(axes)):
        axes[i].set_visible(False)
    plt.tight_layout()
    fig.savefig(FIGURES_DIR / "04_scatter_plots.png", dpi=150)
    plt.close(fig)


def plot_maps(gdf):
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    gdf.plot(column="dengue_incidence", cmap="YlOrBr", legend=True, edgecolor="black", linewidth=0.2, ax=axes[0])
    axes[0].set_title("Dengue Incidence")
    axes[0].axis("off")

    gdf.plot(column="avg_deforestation", cmap="YlOrBr", legend=True, edgecolor="black", linewidth=0.2, ax=axes[1])
    axes[1].set_title("Avg Deforestation")
    axes[1].axis("off")

    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "05_exploratory_map.png", dpi=150)
    plt.close(fig)

    predictors = [c for c in MODEL_VARS if c not in ["dengue_incidence", "avg_deforestation", "std_deforestation"]]
    n_cols = 4
    n_rows = math.ceil(len(predictors) / n_cols)
    fig2, axes2 = plt.subplots(n_rows, n_cols, figsize=(6 * n_cols, 4 * n_rows))
    axes2 = np.array(axes2).flatten()

    for ax, col in zip(axes2[: len(predictors)], predictors):
        vmin = gdf[col].quantile(0.05)
        vmax = gdf[col].quantile(0.95)
        if vmin == vmax:
            vmin, vmax = None, None

        cmap = "Greens" if "precipitation" in col or "crop" in col or "agri" in col else "YlOrBr"

        gdf.plot(column=col, cmap=cmap, legend=True, vmin=vmin, vmax=vmax, edgecolor="black", linewidth=0.1, ax=ax)
        ax.set_title(col)
        ax.axis("off")
    for i in range(len(predictors), len(axes2)):
        axes2[i].set_visible(False)
    fig2.tight_layout()
    fig2.savefig(FIGURES_DIR / "06_predictors_maps.png", dpi=150)
    plt.close(fig2)


def main():
    csv_path = DATA_DIR / "deforestation_dengue_data.csv"
    gpkg_path = DATA_DIR / "deforestation_dengue_geo.gpkg"

    if not (csv_path.exists() and gpkg_path.exists()):
        return

    df = pd.read_csv(csv_path)
    gdf = gpd.read_file(gpkg_path)

    export_statistics(df)
    plot_distributions(df)
    plot_correlation(df)
    plot_scatters(df)
    plot_maps(gdf)


if __name__ == "__main__":
    main()
