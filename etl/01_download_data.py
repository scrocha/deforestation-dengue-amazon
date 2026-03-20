from pathlib import Path
import os
import requests
import zipfile

from geobr import read_municipality, read_biomes
from geopandas import GeoDataFrame
import pandas as pd

import sidrapy

from mosqlient import get_infodengue

TARGET_YEARS = list(range(2016, 2022))

__DIR = Path(__file__).parent
ENV_PATH = __DIR.parent / ".env"
if ENV_PATH.exists():
    from dotenv import load_dotenv

    load_dotenv(ENV_PATH)

DATA_DIR = __DIR.parent / "data"
RAW_DIR = DATA_DIR / "raw"

DATA_DIR.mkdir(exist_ok=True)
RAW_DIR.mkdir(exist_ok=True)


def download_shapefiles():
    DRIVER = "GPKG"

    amazon_path = RAW_DIR / "amazon.gpkg"
    if not amazon_path.exists():
        amazon = (
            read_biomes(simplified=True)
            .loc[lambda df: df["name_biome"] == "Amazônia"]
            .copy()
        ).to_crs("EPSG:4326")
        amazon.to_file(amazon_path, driver=DRIVER)
    else:
        amazon = GeoDataFrame.from_file(amazon_path)

    muni_codes = set()

    muni_path = RAW_DIR / f"municipality.gpkg"
    if not muni_path.exists():
        amazon_munis = (
            read_municipality(year=TARGET_YEARS[-1], simplified=True)
            .loc[lambda df: df.intersects(amazon.geometry.squeeze())]
            .copy()
        ).to_crs("EPSG:4326")
        amazon_munis.to_file(muni_path, driver=DRIVER)
    else:
        amazon_munis = GeoDataFrame.from_file(muni_path)

    muni_codes.update(amazon_munis["code_muni"].unique())

    return [str(int(c)) for c in muni_codes]


def clean_sidra_data(data):
    if "Município (Código)" in data.columns:
        return data

    data.columns = data.iloc[0]
    data = data.iloc[1:].copy()
    return data


def get_sidra_data(muni_codes):
    target_years_str = ",".join(str(y) for y in TARGET_YEARS)

    # PIB per capita - Tabela 5938, Variável 37
    pib_path = RAW_DIR / "pib.csv"
    if not pib_path.exists():
        pib = sidrapy.get_table(
            table_code="5938",
            territorial_level="6",  # município
            ibge_territorial_code="all",
            variable="37",  # PIB per capita
            period=target_years_str,
        )
        pib = clean_sidra_data(pib)
        pib = pib.loc[pib["Município (Código)"].isin(muni_codes)].copy()
        pib = pib[["Município (Código)", "Município", "Ano", "Valor"]].copy()
        pib.to_csv(pib_path, index=False)

    # População urbana e rural - Censo 2010
    # Tabela 202, Variável 93 (pessoas residentes)
    # Situação do domicílio: Urbana, Rural
    pop_path = RAW_DIR / "populacao_situacao.csv"
    if not pop_path.exists():
        pop = sidrapy.get_table(
            table_code="202",
            territorial_level="6",  # município
            ibge_territorial_code="all",
            variable="93",  # pessoas residentes
            classifications={"1": "allxt"},
            period="2010",
        )
        pop = clean_sidra_data(pop)
        pop = pop.loc[pop["Município (Código)"].isin(muni_codes)].copy()
        pop = pop[
            [
                "Município (Código)",
                "Município",
                "Situação do domicílio",
                "Valor",
            ]
        ].copy()
        pop.to_csv(pop_path, index=False)

    # Área plantada de lavouras temporárias - PAM
    # Tabela 1612, Variável 216 (área plantada, em hectares)
    crop_path = RAW_DIR / "lavoura_temporaria.csv"
    if not crop_path.exists():
        crop = sidrapy.get_table(
            table_code="1612",
            territorial_level="6",  # município
            ibge_territorial_code="all",
            variable="216",  # área plantada (ha)
            period=target_years_str,
        )
        crop = clean_sidra_data(crop)
        crop = crop.loc[crop["Município (Código)"].isin(muni_codes)].copy()
        crop = crop[
            [
                "Município (Código)",
                "Município",
                "Ano",
                "Valor",
            ]
        ].copy()
        crop.to_csv(crop_path, index=False)

    area_path = RAW_DIR / "area_municipal.csv"
    if not area_path.exists():
        munis = GeoDataFrame.from_file(RAW_DIR / f"municipality.gpkg")
        munis_area = munis[["code_muni", "name_muni"]].copy()
        munis_area["code_muni"] = munis_area["code_muni"].astype(int)
        munis_area["area_km2"] = munis.to_crs("EPSG:5880").geometry.area / 1e6
        munis_area.to_csv(area_path, index=False)


def get_dengue_data():
    MOSQLIMATE_API_KEY = os.getenv("MOSQLIMATE_API_KEY", "")
    dengue_path = RAW_DIR / "dengue.csv"

    if not dengue_path.exists():
        START_DATE = f"{TARGET_YEARS[0]}-01-01"
        END_DATE = f"{TARGET_YEARS[-1]}-12-31"
        dengue = get_infodengue(
            api_key=MOSQLIMATE_API_KEY,
            disease="dengue",
            start_date=START_DATE,
            end_date=END_DATE,
        )
        dengue.to_csv(dengue_path, index=False)


def get_sicor_data():
    link_contratos = "https://www.bcb.gov.br/htms/sicor/DadosBrutos/SICOR_CONTRATOS_MUNICIPIO_"

    for year in TARGET_YEARS:
        contratos_path = RAW_DIR / f"sicor_contratos_{year}.csv"
        if not contratos_path.exists():
            contratos = pd.read_csv(
                f"{link_contratos}{year}.gz", sep=";", encoding="latin1"
            )
            contratos.to_csv(contratos_path, index=False)


def download_file(url, path):
    response = requests.get(url)
    with open(path, "wb") as f:
        f.write(response.content)


def get_deforestation_data():
    url = "https://terrabrasilis.dpi.inpe.br/download/dataset/amz-prodes/vector/prodes_amazonia_nb.gpkg.zip"

    deforestation_path = RAW_DIR / "deforestation.zip"
    deforestation_gpkg_path = RAW_DIR / "prodes_amazonia_nb.gpkg"

    if not deforestation_gpkg_path.exists():
        download_file(url, deforestation_path)

        with zipfile.ZipFile(deforestation_path, 'r') as zip_ref:
            zip_ref.extractall(RAW_DIR)

        os.remove(deforestation_path)

def get_precipitation_data():
    url = "http://www.dpi.inpe.br/amb_data/Amazonia/bio14_amzl.asc"

    precip_path = RAW_DIR / "precipitation_min_amzl.asc"

    if not precip_path.exists():
        download_file(url, precip_path)


def get_rodovias_data():
    url = "https://geoftp.ibge.gov.br/organizacao_do_territorio/redes_e_fluxos_geograficos/logistica_dos_transportes/base_de_dados/2014.zip"
    rodovias_path = RAW_DIR / "rodovias.zip"
    rodovias_shp_path = RAW_DIR / "2014" / "rodovia_2014.shp"

    if not rodovias_shp_path.exists():
        download_file(url, rodovias_path)
        
        with zipfile.ZipFile(rodovias_path, 'r') as zip_ref:
            zip_ref.extractall(RAW_DIR)

        os.remove(rodovias_path)


def main():
    muni_codes = download_shapefiles()

    get_sidra_data(muni_codes)

    get_dengue_data()

    get_sicor_data()

    get_deforestation_data()

    get_precipitation_data()

    get_rodovias_data()

if __name__ == "__main__":
    main()
