import calendar
import os
import re
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import requests
import sidrapy
from geobr.utils import download_gpkg, download_metadata
from geopandas import GeoDataFrame
from mosqlient import get_infodengue

TARGET_YEARS = list(range(2016, 2022))

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)
GEOBR_RELEASE_URL = "https://github.com/ipeaGIT/geobr/releases/download/v1.7.0/"
TERRABRASILIS_URL = "https://terrabrasilis.dpi.inpe.br"
PRODES_LINK_REGEX = r"/amz-prodes/vector/prodes_biome_amazonia_v\d+\.gpkg\.zip$"
ROADS_URL = "https://geoftp.ibge.gov.br/organizacao_do_territorio/redes_e_fluxos_geograficos/logistica_dos_transportes/2014/base_de_dados_2014.zip"
DENGUE_KEY_COLUMNS = ["municipio_geocodigo", "SE", "Localidade_id"]
SIDRA_COLUMNS = ["Município (Código)", "Município", "Ano", "Valor"]


def read_geobr_layer(geo, year):
    """Camada simplificada do geobr, pelo espelho do GitHub (o host do IPEA costuma travar)."""
    metadata = download_metadata(url=f"{GEOBR_RELEASE_URL}metadata_1.7.0_gpkg.csv")
    metadata = metadata[(metadata["geo"] == geo) & (metadata["year"] == year)]
    metadata = metadata[metadata["download_path"].str.endswith("_simplified.gpkg")].copy()
    if metadata.empty:
        raise ValueError(f"geobr não tem {geo} para {year}.")
    metadata["download_path"] = metadata["download_path"].map(lambda url: f"{GEOBR_RELEASE_URL}{Path(url).name}")
    return download_gpkg(metadata)


def download_shapefiles():
    """Bioma Amazônia e municípios que o intersectam; devolve os códigos dos municípios."""
    amazon_path, muni_path = RAW_DIR / "amazon.gpkg", RAW_DIR / "municipality.gpkg"
    if not amazon_path.exists():
        biomes = read_geobr_layer("biomes", year=2019)
        biomes[biomes["name_biome"] == "Amazônia"].to_crs("EPSG:4326").to_file(amazon_path, driver="GPKG")
    if not muni_path.exists():
        amazon = GeoDataFrame.from_file(amazon_path).geometry.squeeze()
        munis = read_geobr_layer("municipality", year=TARGET_YEARS[-1])
        munis[munis.intersects(amazon)].to_crs("EPSG:4326").to_file(muni_path, driver="GPKG")
    return [str(int(c)) for c in GeoDataFrame.from_file(muni_path)["code_muni"].unique()]


def get_sidra_data(muni_codes):
    years = ",".join(map(str, TARGET_YEARS))
    # (arquivo, tabela, variável, período, colunas, classificações)
    tables = [
        ("pib.csv", "5938", "37", years, SIDRA_COLUMNS, None),
        ("populacao_estimativa.csv", "6579", "9324", years, SIDRA_COLUMNS, None),
        ("lavoura_temporaria.csv", "1612", "216", years, SIDRA_COLUMNS, None),
        ("populacao_situacao.csv", "202", "93", "2010", ["Município (Código)", "Município", "Situação do domicílio", "Valor"], {"1": "allxt"}),
    ]  # fmt: skip
    for file_name, table, variable, period, columns, classifications in tables:
        path = RAW_DIR / file_name
        if path.exists():
            continue
        df = sidrapy.get_table(
            table_code=table, territorial_level="6", ibge_territorial_code="all", variable=variable,
            period=period, classifications=classifications,
        )  # fmt: skip
        if "Município (Código)" not in df.columns:  # a primeira linha traz os nomes das colunas
            df = df.iloc[1:].set_axis(df.iloc[0], axis=1)
        df[df["Município (Código)"].isin(muni_codes)][columns].to_csv(path, index=False)

    area_path = RAW_DIR / "area_municipal.csv"
    if not area_path.exists():
        munis = GeoDataFrame.from_file(RAW_DIR / "municipality.gpkg")
        areas = munis[["code_muni", "name_muni"]].assign(
            code_muni=munis.code_muni.astype(int), area_km2=munis.to_crs("EPSG:5880").geometry.area / 1e6
        )
        areas.to_csv(area_path, index=False)


def fetch_dengue(api_key, uf, start, end):
    df = get_infodengue(
        api_key=api_key, disease="dengue", start_date=start.isoformat(), end_date=end.isoformat(), uf=uf
    )
    if df.duplicated(subset=DENGUE_KEY_COLUMNS).any():
        raise ValueError("semanas repetidas")
    return df


def fetch_dengue_year(api_key, uf, year):
    """Dengue da UF no ano; se a API falhar ou repetir semanas, busca mês a mês."""
    try:
        return fetch_dengue(api_key, uf, date(year, 1, 1), date(year, 12, 31))
    except Exception as exc:
        print(f"Aviso: dengue {year}/{uf} falhou ({exc}); tentando por mês.")
    months = [
        fetch_dengue(api_key, uf, date(year, m, 1), date(year, m, calendar.monthrange(year, m)[1]))
        for m in range(1, 13)
    ]
    return pd.concat(months, ignore_index=True).drop_duplicates()


def get_dengue_data():
    path = RAW_DIR / "dengue.csv"
    if path.exists():
        return
    api_key = os.getenv("MOSQLIMATE_API_KEY", "")
    if not api_key:
        raise OSError("MOSQLIMATE_API_KEY is missing.")

    ufs = sorted(GeoDataFrame.from_file(RAW_DIR / "municipality.gpkg")["abbrev_state"].dropna().unique())
    frames = []
    for uf in ufs:
        for year in TARGET_YEARS:
            year_path = RAW_DIR / f"dengue_{uf}_{year}.csv"  # um arquivo por UF/ano permite retomar
            if not year_path.exists():
                fetch_dengue_year(api_key, uf, year).to_csv(year_path, index=False)
            frames.append(pd.read_csv(year_path))
    pd.concat(frames, ignore_index=True).to_csv(path, index=False)


def get_sicor_data():
    base_url = "https://www.bcb.gov.br/htms/sicor/DadosBrutos/SICOR_CONTRATOS_MUNICIPIO_"
    for year in TARGET_YEARS:
        path = RAW_DIR / f"sicor_contratos_{year}.csv"
        if not path.exists():
            pd.read_csv(f"{base_url}{year}.gz", sep=";", encoding="latin1").to_csv(path, index=False)


def download(url, path, timeout=300):
    with requests.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with open(path, "wb") as f:
            f.writelines(response.iter_content(chunk_size=1 << 20))


def download_and_extract(url, zip_name):
    print(f"Baixando {url}...")
    zip_path = RAW_DIR / zip_name
    download(url, zip_path)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(RAW_DIR)
    zip_path.unlink()


def get_prodes_data():
    """PRODES mais recente do Terrabrasilis (a versão muda a cada atualização)."""
    path = RAW_DIR / "prodes_biome_amazonia.gpkg"
    if path.exists():
        return
    catalog = requests.get(f"{TERRABRASILIS_URL}/business/api/v1/download/all", timeout=60).json()
    link = next(d["link"] for d in catalog if re.search(PRODES_LINK_REGEX, d["link"]))
    name = Path(link).name
    download_and_extract(f"{TERRABRASILIS_URL}{link}", name)
    (RAW_DIR / name.removesuffix(".zip")).rename(path)


def main():
    env_path = ROOT / ".env"
    if env_path.exists():
        from dotenv import load_dotenv

        load_dotenv(env_path)

    print("Baixando shapefiles...")
    muni_codes = download_shapefiles()
    print(f"Municípios: {len(muni_codes)}")
    print("Baixando dados do SIDRA...")
    get_sidra_data(muni_codes)
    print("Baixando dados do SICOR...")
    get_sicor_data()
    print("Baixando dados do PRODES...")
    get_prodes_data()
    if not (RAW_DIR / "precipitation_min_amzl.asc").exists():
        print("Baixando dados de precipitação...")
        download("https://www.dpi.inpe.br/amb_data/Amazonia/bio14_amzl.asc", RAW_DIR / "precipitation_min_amzl.asc")
    if not (RAW_DIR / "2014" / "rodovia_2014.shp").exists():
        print("Baixando dados de rodovias...")
        download_and_extract(ROADS_URL, "base_de_dados_2014.zip")
    print("Baixando dados de dengue (InfoDengue)...")
    get_dengue_data()
    print("ETL concluído com sucesso.")


if __name__ == "__main__":
    main()
