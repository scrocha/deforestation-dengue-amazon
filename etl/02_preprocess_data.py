from pathlib import Path

import geopandas as gpd
import pandas as pd
import rasterio
from rasterstats import zonal_stats

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

TARGET_YEARS = list(range(2016, 2022))


def read_sidra(name):
    df = pd.read_csv(RAW_DIR / name).rename(columns={"Município (Código)": "code_muni"})
    return df.assign(Valor=pd.to_numeric(df["Valor"], errors="coerce"))


def load_base_municipalities():
    munis = gpd.read_file(RAW_DIR / "municipality.gpkg")
    areas = pd.read_csv(RAW_DIR / "area_municipal.csv")
    munis["code_muni"] = munis["code_muni"].astype(int)
    return munis.merge(areas[["code_muni", "area_km2"]], on="code_muni")


def process_dengue():
    df = pd.read_csv(RAW_DIR / "dengue.csv")
    df = df[pd.to_datetime(df["data_iniSE"]).dt.year.isin(TARGET_YEARS)]
    mean = df.groupby("municipio_geocodigo")["p_inc100k"].mean()
    return mean.rename_axis("code_muni").rename("dengue_incidence").reset_index()


def locate_deforestation(muni_gdf, prodes):
    """Atribui cada polígono do PRODES a um único município, o que contém seu centroide.

    `within` descartava polígonos que cruzam divisas e contava em dobro os que caem na sobreposição
    das geometrias simplificadas (58,3 mil km² contra 54,0 mil km² no PRODES).
    """
    points = prodes.copy()
    points["geometry"] = prodes.to_crs("EPSG:5880").centroid.to_crs(muni_gdf.crs)
    joined = gpd.sjoin(points, muni_gdf[["code_muni", "geometry"]], predicate="within")
    return joined[~joined.index.duplicated()]


def process_deforestation(joined):
    annual = joined.groupby(["code_muni", "year"])["area_km"].sum()
    return annual.groupby("code_muni").mean().rename("avg_deforestation").reset_index()


def process_road_distance(joined):
    """Distância média (km) do centroide de cada polígono desmatado à rodovia mais próxima."""
    roads = gpd.read_file(RAW_DIR / "2014" / "rodovia_2014.shp")
    if roads.crs is None:
        roads = roads.set_crs("EPSG:4674")
    points = joined[["code_muni", "geometry"]].reset_index(drop=True).to_crs("EPSG:5880")
    nearest = points.sjoin_nearest(roads.to_crs("EPSG:5880")[["geometry"]], distance_col="dist")
    nearest = nearest[~nearest.index.duplicated()]
    return (nearest.groupby("code_muni")["dist"].mean() / 1000).rename("dist_roads").reset_index()


def process_socioeconomics():
    def yearly_mean(name, column):
        df = read_sidra(name)
        return df[df["Ano"].isin(TARGET_YEARS)].groupby("code_muni")["Valor"].mean().rename(column)

    census = read_sidra("populacao_situacao.csv")
    census = census[census["Situação do domicílio"].isin(["Urbana", "Rural"])]
    census = census.groupby(["code_muni", "Situação do domicílio"])["Valor"].mean().unstack()
    census = census.rename(columns={"Urbana": "urban_pop", "Rural": "rural_pop"})
    gdp = yearly_mean("pib.csv", "gdp_total_thousand")
    return pd.concat(
        [gdp, census, yearly_mean("populacao_estimativa.csv", "population_estimated")], axis=1
    ).reset_index()


def process_crops():
    crop = read_sidra("lavoura_temporaria.csv").groupby("code_muni")["Valor"].mean()
    return (crop / 100.0).rename("avg_crop_area").reset_index()


def process_sicor_credit():
    credits = []
    for year in TARGET_YEARS:
        df = pd.read_csv(RAW_DIR / f"sicor_contratos_{year}.csv")
        df["total"] = pd.to_numeric(df.VlCusteio, errors="coerce").fillna(0) + pd.to_numeric(
            df.VlInvestimento, errors="coerce"
        ).fillna(0)
        df["code_muni"] = df.codMunicIbge.fillna(0).astype(int)
        by_activity = df.groupby(["code_muni", "Atividade"])["total"].sum().unstack()
        credits.append(by_activity.reindex(columns=[1, 2], fill_value=0).rename(columns={1: "agri", 2: "live"}))
    mean = pd.concat(credits).groupby(level=0).mean()
    return mean.rename(columns={"agri": "avg_agri_credit", "live": "avg_livestock_credit"}).reset_index()


def process_precipitation(muni_gdf):
    muni_proj = muni_gdf[["code_muni", "geometry"]].to_crs("EPSG:4326")
    with rasterio.open(RAW_DIR / "precipitation_min_amzl.asc") as src:
        data, affine, nodata = src.read(1), src.transform, src.nodata
    stats = zonal_stats(muni_proj, data, affine=affine, stats="mean sum", nodata=nodata)
    return pd.DataFrame(
        {
            "code_muni": muni_proj.code_muni,
            "average_min_precipitation": [s["mean"] or 0 for s in stats],
            "total_min_precipitation": [s["sum"] or 0 for s in stats],
        }
    )


def main():
    muni_gdf = load_base_municipalities()
    prodes = gpd.read_file(
        RAW_DIR / "prodes_biome_amazonia.gpkg",
        layer="yearly_deforestation_biome",
        columns=["year", "area_km"],
        where=f"year IN ({', '.join(map(str, TARGET_YEARS))})",
    ).to_crs(muni_gdf.crs)
    joined = locate_deforestation(muni_gdf, prodes)

    data = muni_gdf
    for table in (
        process_dengue(),
        process_deforestation(joined),
        process_road_distance(joined),
        process_socioeconomics(),
        process_crops(),
        process_sicor_credit(),
        process_precipitation(muni_gdf),
    ):
        data = data.merge(table, on="code_muni", how="left")

    # Sem desmatamento a distância às rodovias é indefinida (não 0 km): fica ausente e os modelos imputam.
    dist_roads = data["dist_roads"]
    data = data.fillna(0)
    data["dist_roads"] = dist_roads
    # PIB (SIDRA 5938, variável 37) vem em mil reais: PIB per capita (R$ mil por habitante, unidade da Tabela 1
    # do artigo) = PIB total / população estimada.
    data["gdp_capita"] = data["gdp_total_thousand"] / data["population_estimated"]

    per_area = {
        "std_deforestation": "avg_deforestation",
        "std_urban_pop": "urban_pop",
        "std_rural_pop": "rural_pop",
        "std_population_estimated": "population_estimated",
        "std_crop_area": "avg_crop_area",
        "std_agri_credit": "avg_agri_credit",
        "std_live_credit": "avg_livestock_credit",
    }
    for std_col, source_col in per_area.items():
        data[std_col] = data[source_col] / data["area_km2"]

    data.to_csv(PROCESSED_DIR / "deforestation_dengue_data.csv", index=False)
    data.to_file(PROCESSED_DIR / "deforestation_dengue_geo.gpkg", driver="GPKG")
    print(f"Preprocessamento concluído para {len(data)} municípios.")


if __name__ == "__main__":
    main()
