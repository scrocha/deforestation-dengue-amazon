import pandas as pd
import geopandas as gpd
from pathlib import Path
import numpy as np
from shapely.ops import nearest_points
import rasterio
from rasterstats import zonal_stats
from concurrent.futures import ThreadPoolExecutor


__DIR = Path(__file__).parent
RAW_DIR = __DIR.parent / "data" / "raw"
PROCESSED_DIR = __DIR.parent / "data" / "processed"
PROCESSED_DIR.mkdir(exist_ok=True)

TARGET_YEARS = list(range(2016, 2022))


def load_base_municipalities():
    munis = gpd.read_file(RAW_DIR / "municipality.gpkg")
    areas = pd.read_csv(RAW_DIR / "area_municipal.csv")
    munis['code_muni'] = munis['code_muni'].astype(int)
    return munis.merge(areas[['code_muni', 'area_km2']], on="code_muni")


def process_dengue():
    df = pd.read_csv(RAW_DIR / "dengue.csv")
    df['ano'] = pd.to_datetime(df['data_iniSE']).dt.year
    filtered = df[df['ano'].isin(TARGET_YEARS)]
    avg_inc = (
        filtered.groupby("municipio_geocodigo")["p_inc100k"]
        .mean()
        .reset_index()
    )
    return avg_inc.rename(
        columns={
            "municipio_geocodigo": "code_muni",
            "p_inc100k": "dengue_incidence",
        }
    )


def process_deforestation(muni_gdf):
    prodes = gpd.read_file(
        RAW_DIR / "prodes_amazonia_nb.gpkg", layer="yearly_deforestation_biome"
    )
    prodes = prodes[prodes["year"].isin(TARGET_YEARS)].to_crs(muni_gdf.crs)

    joined = gpd.sjoin(
        prodes, muni_gdf[['code_muni', 'geometry']], predicate='within'
    )
    annual_sum = (
        joined.groupby(['code_muni', 'year'])['area_km'].sum().reset_index()
    )
    avg_def = annual_sum.groupby('code_muni')['area_km'].mean().reset_index()
    return avg_def.rename(columns={'area_km': 'avg_deforestation'})


def process_road_distance(muni_gdf):
    roads = gpd.read_file(RAW_DIR / "2014" / "rodovia_2014.shp")
    if roads.crs is None:
        roads = roads.set_crs("EPSG:4674")
    roads = roads.to_crs("EPSG:5880")
    prodes = gpd.read_file(
        RAW_DIR / "prodes_amazonia_nb.gpkg", layer="yearly_deforestation_biome"
    )
    def_recent = prodes[prodes["year"].isin([2019, 2020, 2021])].to_crs(
        "EPSG:5880"
    )

    def_recent['centroid'] = def_recent.geometry.centroid
    muni_proj = muni_gdf[['code_muni', 'geometry']].to_crs("EPSG:5880")
    joined = gpd.sjoin(def_recent, muni_proj, predicate='within')

    road_union = roads.geometry.union_all()
    joined['dist'] = joined['centroid'].apply(
        lambda x: x.distance(road_union) / 1000
    )

    dist_avg = joined.groupby('code_muni')['dist'].mean().reset_index()
    return dist_avg.rename(columns={'dist': 'dist_roads'})


def process_socioeconomics():
    pib = pd.read_csv(RAW_DIR / "pib.csv")
    pib['Valor'] = pd.to_numeric(pib['Valor'], errors='coerce')
    pib_filtered = pib[pib['Ano'] <= 2019]
    pib_avg = (
        pib_filtered.groupby("Município (Código)")["Valor"]
        .mean()
        .reset_index()
    )

    pop = pd.read_csv(RAW_DIR / "populacao_situacao.csv")
    pop['Valor'] = pd.to_numeric(pop['Valor'], errors='coerce')
    pop_filtered = pop[pop['Situação do domicílio'].isin(['Urbana', 'Rural'])]
    pop_avg = (
        pop_filtered.groupby(["Município (Código)", "Situação do domicílio"])[
            "Valor"
        ]
        .mean()
        .unstack("Situação do domicílio")
        .reset_index()
    )

    return (
        pib_avg.rename(
            columns={"Município (Código)": "code_muni", "Valor": "gdp_capita"}
        ),
        pop_avg.rename(
            columns={
                "Município (Código)": "code_muni",
                "Rural": "rural_pop",
                "Urbana": "urban_pop",
            }
        ),
    )


def process_crops():
    crop = pd.read_csv(RAW_DIR / "lavoura_temporaria.csv")
    crop['Valor'] = pd.to_numeric(crop['Valor'], errors='coerce')
    crop_avg = crop.groupby("Município (Código)")["Valor"].mean().reset_index()
    return crop_avg.rename(
        columns={
            "Município (Código)": "code_muni",
            "Valor": "avg_crop_area",
        }
    )


def process_sicor_credit():
    credits_all = []
    for year in TARGET_YEARS:
        df = pd.read_csv(RAW_DIR / f"sicor_contratos_{year}.csv")
        df['VlCusteio'] = pd.to_numeric(df['VlCusteio'], errors='coerce')
        df['VlInvestimento'] = pd.to_numeric(
            df['VlInvestimento'], errors='coerce'
        )
        df['total_val'] = df['VlCusteio'] + df['VlInvestimento']
        df['code_muni'] = df['codMunicIbge'].fillna(0).astype(int)

        agri = df[df['Atividade'] == 1].groupby('code_muni')['total_val'].sum()
        live = df[df['Atividade'] == 2].groupby('code_muni')['total_val'].sum()

        credits_all.append(
            pd.DataFrame({'agri': agri, 'live': live, 'year': year})
        )

    combined = pd.concat(credits_all).groupby(level=0).mean().reset_index()
    return combined.rename(
        columns={'agri': 'avg_agri_credit', 'live': 'avg_livestock_credit'}
    )


def process_precipitation(muni_gdf):

    muni_proj = muni_gdf[['code_muni', 'geometry']].to_crs("EPSG:4326")

    asc_path = RAW_DIR / f"precipitation_min_amzl.asc"

    with rasterio.open(str(asc_path)) as src:
        data = src.read(1)
        affine = src.transform
        nodata = src.nodata
    stats_mean = zonal_stats(
        muni_proj, data, affine=affine, stats="mean", nodata=nodata
    )
    stats_sum = zonal_stats(
        muni_proj, data, affine=affine, stats="sum", nodata=nodata
    )

    min_precip_data = [
        s['mean'] if s['mean'] is not None else 0 for s in stats_mean
    ]
    min_precip_sum = [
        s['sum'] if s['sum'] is not None else 0 for s in stats_sum
    ]

    return pd.DataFrame(
        {
            'code_muni': muni_proj['code_muni'],
            'average_min_precipitation': min_precip_data,
            'total_min_precipitation': min_precip_sum,
        }
    )


def main():
    muni_gdf = load_base_municipalities()

    dengue = process_dengue()
    deforest = process_deforestation(muni_gdf)
    roads_dist = process_road_distance(muni_gdf)
    gdp, pop = process_socioeconomics()
    crops = process_crops()
    credit = process_sicor_credit()
    precip = process_precipitation(muni_gdf)

    final_df = muni_gdf.copy()
    for df_part in [
        dengue,
        deforest,
        roads_dist,
        gdp,
        pop,
        crops,
        credit,
        precip,
    ]:
        final_df = final_df.merge(df_part, on="code_muni", how="left")

    final_df['std_deforestation'] = (
        final_df['avg_deforestation'] / final_df['area_km2']
    )
    final_df['std_agri_credit'] = (
        final_df['avg_agri_credit'] / 1000
    ) / final_df['area_km2']
    final_df['std_live_credit'] = (
        final_df['avg_livestock_credit'] / 1000
    ) / final_df['area_km2']
    final_df['std_urban_pop'] = final_df['urban_pop'] / final_df['area_km2']
    final_df['std_rural_pop'] = final_df['rural_pop'] / final_df['area_km2']
    final_df['std_crop_area'] = (
        final_df['avg_crop_area'] / final_df['area_km2']
    )

    final_df_cols = [
        'code_muni',
        'name_muni',
        'area_km2',
        'dengue_incidence',
        'avg_deforestation',
        'std_deforestation',
        'dist_roads',
        'gdp_capita',
        'urban_pop',
        'std_urban_pop',
        'rural_pop',
        'std_rural_pop',
        'avg_crop_area',
        'std_crop_area',
        'avg_agri_credit',
        'std_agri_credit',
        'avg_livestock_credit',
        'std_live_credit',
        'average_min_precipitation',
        'total_min_precipitation',
        'geometry',
    ]
    final_df = final_df[final_df_cols]

    final_df = final_df.fillna(0)
    final_df.drop(columns='geometry').to_csv(
        PROCESSED_DIR / "deforestation_dengue_data.csv", index=False
    )
    final_df.to_file(
        PROCESSED_DIR / "deforestation_dengue_geo.gpkg", driver="GPKG"
    )

    print(f"Dataset processado com {len(final_df)} municípios.")


if __name__ == "__main__":
    main()
