from pathlib import Path
import geopandas as gpd
import pandas as pd
import rasterio
from rasterstats import zonal_stats

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
    dengue = (
        filtered.groupby("municipio_geocodigo")['p_inc100k']
        .mean()
        .reset_index()
        .rename(
            columns={
                "municipio_geocodigo": "code_muni",
                "p_inc100k": "dengue_incidence",
            }
        )
    )
    return dengue


def process_deforestation(muni_gdf, prodes):
    prodes = prodes.to_crs(muni_gdf.crs)
    joined = gpd.sjoin(
        prodes, muni_gdf[['code_muni', 'geometry']], predicate='within'
    )
    annual_sum = (
        joined.groupby(['code_muni', 'year'])['area_km'].sum().reset_index()
    )
    return (
        annual_sum.groupby('code_muni')['area_km']
        .mean()
        .reset_index()
        .rename(columns={'area_km': 'avg_deforestation'})
    )


def process_road_distance(muni_gdf, prodes):
    roads = gpd.read_file(RAW_DIR / "2014" / "rodovia_2014.shp")
    if roads.crs is None:
        roads = roads.set_crs("EPSG:4674")
    roads = roads.to_crs("EPSG:5880")

    def_recent = prodes.to_crs("EPSG:5880")
    def_recent['centroid'] = def_recent.geometry.centroid

    joined = gpd.sjoin(
        def_recent,
        muni_gdf[['code_muni', 'geometry']].to_crs("EPSG:5880"),
        predicate='within',
    )
    road_union = roads.geometry.union_all()
    joined['dist'] = joined['centroid'].distance(road_union) / 1000
    return (
        joined.groupby('code_muni')['dist']
        .mean()
        .reset_index()
        .rename(columns={'dist': 'dist_roads'})
    )


def process_socioeconomics():
    pib = pd.read_csv(RAW_DIR / "pib.csv")
    pib['Valor'] = pd.to_numeric(pib['Valor'], errors='coerce')
    pib_avg = (
        pib[pib['Ano'].isin(TARGET_YEARS)]
        .groupby("Município (Código)")['Valor']
        .mean()
        .reset_index()
        .rename(columns={'Valor': 'gdp_capita'})
    )

    pop_legacy = pd.read_csv(RAW_DIR / "populacao_situacao.csv")
    pop_legacy['Valor'] = pd.to_numeric(pop_legacy['Valor'], errors='coerce')
    pop_avg = (
        pop_legacy[
            pop_legacy['Situação do domicílio'].isin(['Urbana', 'Rural'])
        ]
        .groupby(["Município (Código)", "Situação do domicílio"])['Valor']
        .mean()
        .unstack()
        .reset_index()
        .rename(columns={'Urbana': 'urban_pop', 'Rural': 'rural_pop'})
    )

    pop_est = pd.read_csv(RAW_DIR / "populacao_estimativa.csv")
    pop_est['Valor'] = pd.to_numeric(pop_est['Valor'], errors='coerce')
    pop_est_avg = (
        pop_est[pop_est['Ano'].isin(TARGET_YEARS)]
        .groupby("Município (Código)")['Valor']
        .mean()
        .reset_index()
        .rename(columns={'Valor': 'population_estimated'})
    )

    return (
        pib_avg.merge(pop_avg, on="Município (Código)", how="left")
        .merge(pop_est_avg, on="Município (Código)", how="left")
        .rename(columns={"Município (Código)": "code_muni"})
    )


def process_crops():
    crop = pd.read_csv(RAW_DIR / "lavoura_temporaria.csv")
    crop['Valor'] = pd.to_numeric(crop['Valor'], errors='coerce')
    crop_avg = crop.groupby("Município (Código)")['Valor'].mean().reset_index()
    return (
        crop_avg.assign(avg_crop_area=crop_avg.Valor / 100.0)
        .drop(columns=['Valor'])
        .rename(columns={"Município (Código)": "code_muni"})
    )


def process_sicor_credit():
    credits = []
    for y in TARGET_YEARS:
        df = pd.read_csv(RAW_DIR / f"sicor_contratos_{y}.csv")
        df['total'] = pd.to_numeric(df.VlCusteio, errors='coerce').fillna(
            0
        ) + pd.to_numeric(df.VlInvestimento, errors='coerce').fillna(0)
        df['code_muni'] = df.codMunicIbge.fillna(0).astype(int)
        credits.append(
            df.groupby(['code_muni', 'Atividade'])['total']
            .sum()
            .unstack()
            .reindex(columns=[1, 2], fill_value=0)
            .rename(columns={1: 'agri', 2: 'live'})
        )

    return (
        pd.concat(credits)
        .groupby(level=0)
        .mean()
        .reset_index()
        .rename(
            columns={'agri': 'avg_agri_credit', 'live': 'avg_livestock_credit'}
        )
    )


def process_precipitation(muni_gdf):
    muni_proj = muni_gdf[['code_muni', 'geometry']].to_crs("EPSG:4326")
    with rasterio.open(str(RAW_DIR / "precipitation_min_amzl.asc")) as src:
        data, affine, nodata = src.read(1), src.transform, src.nodata

    stats = zonal_stats(
        muni_proj, data, affine=affine, stats="mean sum", nodata=nodata
    )
    return pd.DataFrame(
        {
            'code_muni': muni_proj.code_muni,
            'average_min_precipitation': [s['mean'] or 0 for s in stats],
            'total_min_precipitation': [s['sum'] or 0 for s in stats],
        }
    )


def main():
    muni_gdf = load_base_municipalities()
    prodes = gpd.read_file(
        RAW_DIR / "prodes_biome_amazonia.gpkg",
        layer="yearly_deforestation_biome",
    )
    prodes = prodes[prodes["year"].isin(TARGET_YEARS)]
    data = (
        muni_gdf.merge(process_dengue(), on="code_muni", how="left")
        .merge(process_deforestation(muni_gdf, prodes), on="code_muni", how="left")
        .merge(process_road_distance(muni_gdf, prodes), on="code_muni", how="left")
        .merge(process_socioeconomics(), on="code_muni", how="left")
        .merge(process_crops(), on="code_muni", how="left")
        .merge(process_sicor_credit(), on="code_muni", how="left")
        .merge(process_precipitation(muni_gdf), on="code_muni", how="left")
    ).fillna(0)

    std_columns = {
        'std_deforestation': 'avg_deforestation',
        'std_urban_pop': 'urban_pop',
        'std_rural_pop': 'rural_pop',
        'std_population_estimated': 'population_estimated',
        'std_crop_area': 'avg_crop_area',
        'std_agri_credit': 'avg_agri_credit',
        'std_live_credit': 'avg_livestock_credit',
    }
    for std_col, source_col in std_columns.items():
        data[std_col] = data[source_col] / data['area_km2']

    data.to_csv(PROCESSED_DIR / "deforestation_dengue_data.csv", index=False)
    data.to_file(
        PROCESSED_DIR / "deforestation_dengue_geo.gpkg", driver="GPKG"
    )
    print(f"Preprocessamento concluído para {len(data)} municípios.")


if __name__ == "__main__":
    main()
