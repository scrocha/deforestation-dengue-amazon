import geopandas as gpd
import libpysal
from esda.moran import Moran, Moran_Local
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path
import json

__DIR = Path(__file__).parent
DATA_DIR = __DIR.parent / "data" / "processed"
RESULTS_DIR = __DIR.parent / "data" / "results"
FIGURES_DIR = __DIR.parent / "figures"

RESULTS_DIR.mkdir(exist_ok=True)
FIGURES_DIR.mkdir(exist_ok=True)


def main():
    gdf = gpd.read_file(DATA_DIR / "deforestation_dengue_geo.gpkg")
    w = libpysal.weights.Queen.from_dataframe(gdf, use_index=False)
    w.transform = 'r'

    mi = Moran(gdf['dengue_incidence'], w)
    metrics = {
        "global_moran_i": float(mi.I),
        "global_moran_p": float(mi.p_sim),
    }
    with open(RESULTS_DIR / "moran_metrics.json", "w") as f:
        json.dump(metrics, f, indent=4)

    lisa = Moran_Local(gdf['dengue_incidence'], w)
    gdf['lisa_q'], gdf['lisa_p'] = lisa.q, lisa.p_sim
    gdf['lisa_cluster'] = 0

    sig = lisa.p_sim < 0.05
    for q in [1, 2, 3, 4]:
        gdf.loc[(lisa.q == q) & sig, 'lisa_cluster'] = q

    gdf.to_file(RESULTS_DIR / "results_geo.gpkg", driver="GPKG")

    fig, ax = plt.subplots(figsize=(10, 8))
    colors = {0: 'lightgrey', 1: 'red', 2: 'lightblue', 3: 'blue', 4: 'pink'}
    labels = {
        0: 'Não Significativo',
        1: 'Alto-Alto (Hotspot)',
        2: 'Baixo-Alto',
        3: 'Baixo-Baixo (Coldspot)',
        4: 'Alto-Baixo',
    }

    patches = []
    for cid, color in colors.items():
        subset = gdf[gdf['lisa_cluster'] == cid]
        if not subset.empty:
            subset.plot(ax=ax, color=color, edgecolor='black', linewidth=0.1)
            patches.append(mpatches.Patch(color=color, label=labels[cid]))

    ax.legend(handles=patches, loc='lower left', title="Clusters LISA")
    ax.set_title("Clusters Espaciais de Incidência de Dengue (LISA)")
    ax.axis('off')
    fig.savefig(
        FIGURES_DIR / "07_lisa_clusters.png", dpi=150, bbox_inches='tight'
    )
    plt.close(fig)


if __name__ == "__main__":
    main()
