import os
import zipfile
from pathlib import Path

import pandas as pd
import requests
import sidrapy
from geobr import read_biomes, read_municipality
from geopandas import GeoDataFrame
from mosqlient import get_infodengue

TARGET_YEARS = list(range(2016, 2022))

__DIR = Path(__file__).parent
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

    muni_path = RAW_DIR / "municipality.gpkg"
    if not muni_path.exists():
        amazon_munis = (
            read_municipality(year=TARGET_YEARS[-1], simplified=True)
            .loc[lambda df: df.intersects(amazon.geometry.squeeze())]
            .copy()
        ).to_crs("EPSG:4326")
        amazon_munis.to_file(muni_path, driver=DRIVER)
    else:
        amazon_munis = GeoDataFrame.from_file(muni_path)

    return [str(int(c)) for c in amazon_munis["code_muni"].unique()]


def clean_sidra_data(data):
    if "Município (Código)" in data.columns:
        return data
    data.columns = data.iloc[0]
    return data.iloc[1:].copy()


def get_sidra_data(muni_codes):
    years_str = ",".join(str(y) for y in TARGET_YEARS)

    tables = [
        (
            "pib.csv",
            "5938",
            "37",
            years_str,
            ["Município (Código)", "Município", "Ano", "Valor"],
            None,
        ),
        (
            "populacao_estimativa.csv",
            "6579",
            "9324",
            years_str,
            ["Município (Código)", "Município", "Ano", "Valor"],
            None,
        ),
        (
            "lavoura_temporaria.csv",
            "1612",
            "216",
            years_str,
            ["Município (Código)", "Município", "Ano", "Valor"],
            None,
        ),
        (
            "populacao_situacao.csv",
            "202",
            "93",
            "2010",
            [
                "Município (Código)",
                "Município",
                "Situação do domicílio",
                "Valor",
            ],
            {"1": "allxt"},
        ),
    ]

    for file_name, table, var, period, cols, classifications in tables:
        path = RAW_DIR / file_name
        if not path.exists():
            df = sidrapy.get_table(
                table_code=table,
                territorial_level="6",
                ibge_territorial_code="all",
                variable=var,
                period=period,
                classifications=classifications,
            )
            df = clean_sidra_data(df)
            df = df[df["Município (Código)"].isin(muni_codes)].copy()
            df[cols].to_csv(path, index=False)

    area_path = RAW_DIR / "area_municipal.csv"
    if not area_path.exists():
        munis = GeoDataFrame.from_file(RAW_DIR / "municipality.gpkg")
        munis_area = munis[["code_muni", "name_muni"]].copy()
        munis_area["code_muni"] = munis_area.code_muni.astype(int)
        munis_area["area_km2"] = munis.to_crs("EPSG:5880").geometry.area / 1e6
        munis_area.to_csv(area_path, index=False)


def get_dengue_data():
    api_key = os.getenv("MOSQLIMATE_API_KEY", "")
    path = RAW_DIR / "dengue.csv"

    if not path.exists():
        if not api_key:
            raise EnvironmentError("MOSQLIMATE_API_KEY is missing.")
        dengue = get_infodengue(
            api_key=api_key,
            disease="dengue",
            start_date=f"{TARGET_YEARS[0]}-01-01",
            end_date=f"{TARGET_YEARS[-1]}-12-31",
        )
        dengue.to_csv(path, index=False)


def get_sicor_data():
    base_url = "https://www.bcb.gov.br/htms/sicor/DadosBrutos/SICOR_CONTRATOS_MUNICIPIO_"
    for year in TARGET_YEARS:
        path = RAW_DIR / f"sicor_contratos_{year}.csv"
        if not path.exists():
            pd.read_csv(
                f"{base_url}{year}.gz", sep=";", encoding="latin1"
            ).to_csv(path, index=False)


def download_and_extract(url, zip_name, target_file):
    if not (RAW_DIR / target_file).exists():
        zip_path = RAW_DIR / zip_name
        print(f"Baixando {url}...")
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            with open(zip_path, "wb") as f:
                downloaded = 0
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if (
                        total_size > 0 and downloaded % (1024 * 1024 * 5) == 0
                    ):  # Print a cada 5MB
                        print(f"Progresso: {downloaded / total_size:.1%}")

        print(f"Extraindo {zip_name}...")
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(RAW_DIR)
        zip_path.unlink()


def main():
    print("Iniciando ETL...")
    env_path = __DIR.parent / ".env"
    if env_path.exists():
        from dotenv import load_dotenv

        load_dotenv(env_path)

    print("Baixando shapefiles...")
    muni_codes = download_shapefiles()
    print(f"Shapefiles baixados. Municípios: {len(muni_codes)}")

    print("Baixando dados do SIDRA...")
    get_sidra_data(muni_codes)

    print("Baixando dados de dengue (InfoDengue)...")
    get_dengue_data()

    print("Baixando dados do SICOR...")
    get_sicor_data()

    print("Baixando dados do PRODES...")
    download_and_extract(
        "https://terrabrasilis.dpi.inpe.br/download/dataset/amz-prodes/vector/prodes_biome_amazonia_v20260330.gpkg.zip",
        "deforestation.zip",
        "prodes_biome_amazonia_v20260330.gpkg",
    )

    print("Baixando dados de precipitação...")
    precip_path = RAW_DIR / "precipitation_min_amzl.asc"
    if not precip_path.exists():
        with open(precip_path, "wb") as f:
            f.write(
                requests.get(
                    "http://www.dpi.inpe.br/amb_data/Amazonia/bio14_amzl.asc"
                ).content
            )

    print("Baixando dados de rodovias...")
    download_and_extract(
        "https://geoftp.ibge.gov.br/organizacao_do_territorio/redes_e_fluxos_geograficos/logistica_dos_transportes/base_de_dados/2014.zip",
        "rodovias.zip",
        "2014/rodovia_2014.shp",
    )
    print("ETL concluído com sucesso.")


if __name__ == "__main__":
    main()
