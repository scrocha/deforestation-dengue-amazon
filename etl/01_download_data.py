import calendar
import os
import re
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
import sidrapy
from geobr.utils import download_gpkg, download_metadata
from geopandas import GeoDataFrame
from mosqlient import get_infodengue

TARGET_YEARS = list(range(2016, 2022))

__DIR = Path(__file__).parent
DATA_DIR = __DIR.parent / "data"
RAW_DIR = DATA_DIR / "raw"
DATA_DIR.mkdir(exist_ok=True)
RAW_DIR.mkdir(exist_ok=True)
GEOBR_RELEASE_URL = (
    "https://github.com/ipeaGIT/geobr/releases/download/v1.7.0/"
)
TERRABRASILIS_API = "https://terrabrasilis.dpi.inpe.br/business/api/v1/download/all"
PRODES_LINK_REGEX = r"/amz-prodes/vector/prodes_biome_amazonia_v\d+\.gpkg\.zip$"
DENGUE_KEY_COLUMNS = ("municipio_geocodigo", "SE", "Localidade_id")


def read_geobr_layer(geo, year, simplified=True):
    # Use the geobr release mirror directly; the IPEA host currently hangs.
    metadata = download_metadata(
        url=f"{GEOBR_RELEASE_URL}metadata_1.7.0_gpkg.csv"
    )
    metadata = metadata[(metadata["geo"] == geo) & (metadata["year"] == year)]
    is_simplified = metadata["download_path"].str.endswith("_simplified.gpkg")
    metadata = metadata[is_simplified if simplified else ~is_simplified].copy()
    if metadata.empty:
        raise ValueError(f"geobr não tem {geo} para {year}.")
    metadata["download_path"] = metadata["download_path"].map(
        lambda url: f"{GEOBR_RELEASE_URL}{Path(url).name}"
    )
    return download_gpkg(metadata)


def download_shapefiles():
    DRIVER = "GPKG"
    amazon_path = RAW_DIR / "amazon.gpkg"

    if not amazon_path.exists():
        amazon = (
            read_geobr_layer("biomes", year=2019)
            .loc[lambda df: df["name_biome"] == "Amazônia"]
            .copy()
        ).to_crs("EPSG:4326")
        amazon.to_file(amazon_path, driver=DRIVER)
    else:
        amazon = GeoDataFrame.from_file(amazon_path)

    muni_path = RAW_DIR / "municipality.gpkg"
    if not muni_path.exists():
        amazon_munis = (
            read_geobr_layer("municipality", year=TARGET_YEARS[-1])
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


def has_duplicate_dengue_rows(df):
    if df.empty:
        return False
    missing = set(DENGUE_KEY_COLUMNS).difference(df.columns)
    if missing:
        raise ValueError(
            f"Resposta do Infodengue sem as chaves semanais esperadas: {sorted(missing)}"
        )
    return df.duplicated(subset=DENGUE_KEY_COLUMNS).any()


def save_dengue_checkpoint(df, path):
    temp_path = path.with_suffix(path.suffix + ".part")
    df.to_csv(temp_path, index=False)
    temp_path.replace(path)


def fetch_dengue_period(api_key, uf, year, start, end):
    path = RAW_DIR / (
        f"dengue_{uf}_{year}_range_{start:%Y%m%d}_{end:%Y%m%d}.csv"
    )
    if path.exists():
        cached = pd.read_csv(path)
        if not has_duplicate_dengue_rows(cached):
            return cached

    try:
        df = get_infodengue(
            api_key=api_key,
            disease="dengue",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            uf=uf,
        )
    except Exception as exc:
        return split_dengue_period(
            api_key,
            uf,
            year,
            start,
            end,
            f"requisição falhou ({type(exc).__name__})",
            exc,
        )
    if has_duplicate_dengue_rows(df):
        return split_dengue_period(
            api_key, uf, year, start, end, "semanas repetidas"
        )
    save_dengue_checkpoint(df, path)
    return df


def split_dengue_period(api_key, uf, year, start, end, reason, error=None):
    days = (end - start).days
    if days < 7:
        message = f"Dengue {year}/{uf} sem resposta limpa em {start}–{end}: {reason}."
        if error:
            raise RuntimeError(message) from error
        raise RuntimeError(message)
    print(f"Dengue {year}/{uf} {start}–{end}: {reason}; subdividindo.")
    middle = start + timedelta(days=days // 2)
    left = fetch_dengue_period(api_key, uf, year, start, middle)
    right = fetch_dengue_period(api_key, uf, year, middle + timedelta(days=1), end)
    df = pd.concat([left, right], ignore_index=True).drop_duplicates()
    if has_duplicate_dengue_rows(df):
        raise RuntimeError(
            f"Dengue {year}/{uf} tem registros conflitantes em {start}–{end}."
        )
    path = RAW_DIR / (
        f"dengue_{uf}_{year}_range_{start:%Y%m%d}_{end:%Y%m%d}.csv"
    )
    save_dengue_checkpoint(df, path)
    return df


def fetch_dengue_months(api_key, uf, year):
    frames = []
    for month in range(1, 13):
        path = RAW_DIR / f"dengue_{uf}_{year}_{month:02}.csv"
        if path.exists():
            df = pd.read_csv(path)
            if not has_duplicate_dengue_rows(df):
                frames.append(df)
                continue
        start = date(year, month, 1)
        end = date(year, month, calendar.monthrange(year, month)[1])
        df = fetch_dengue_period(api_key, uf, year, start, end)
        save_dengue_checkpoint(df, path)
        frames.append(df)
    combined = pd.concat(frames, ignore_index=True).drop_duplicates()
    if has_duplicate_dengue_rows(combined):
        raise RuntimeError(f"Dados conflitantes de dengue para {year}/{uf}.")
    return combined


def get_dengue_data():
    api_key = os.getenv("MOSQLIMATE_API_KEY", "")
    path = RAW_DIR / "dengue.csv"

    if path.exists():
        existing = pd.read_csv(
            path,
            usecols=["municipio_geocodigo", "SE", "Localidade_id"],
        )
        if not existing.duplicated().any():
            return
        print("Dengue consolidada contém semanas repetidas; refazendo downloads.")
    if not api_key:
        raise EnvironmentError("MOSQLIMATE_API_KEY is missing.")

    munis = GeoDataFrame.from_file(RAW_DIR / "municipality.gpkg")
    for uf in sorted(munis["abbrev_state"].dropna().unique()):
        state_path = RAW_DIR / f"dengue_{uf}.csv"
        if state_path.exists():
            state_data = pd.read_csv(state_path)
            state_data["year"] = pd.to_datetime(
                state_data["data_iniSE"], errors="coerce"
            ).dt.year
        else:
            state_data = pd.DataFrame()

        for year in TARGET_YEARS:
            year_path = RAW_DIR / f"dengue_{uf}_{year}.csv"
            if year_path.exists():
                cached_year = pd.read_csv(year_path)
                if not has_duplicate_dengue_rows(cached_year):
                    continue
            if not state_data.empty:
                cached_year = state_data[state_data["year"] == year].drop(
                    columns="year"
                )
                if not cached_year.empty and not has_duplicate_dengue_rows(
                    cached_year
                ):
                    save_dengue_checkpoint(cached_year, year_path)
                    continue
            try:
                dengue = get_infodengue(
                    api_key=api_key,
                    disease="dengue",
                    start_date=f"{year}-01-01",
                    end_date=f"{year}-12-31",
                    uf=uf,
                )
            except Exception as exc:
                print(
                    f"Aviso: dengue {year}/{uf} falhou ({type(exc).__name__}); "
                    "tentando por mês."
                )
                dengue = fetch_dengue_months(api_key, uf, year)
            else:
                if has_duplicate_dengue_rows(dengue):
                    print(
                        f"Aviso: dengue {year}/{uf} veio com semanas repetidas; "
                        "refazendo por mês."
                    )
                    dengue = fetch_dengue_months(api_key, uf, year)
            if not dengue.empty:
                save_dengue_checkpoint(dengue, year_path)

    frames = [
        pd.read_csv(RAW_DIR / f"dengue_{uf}_{year}.csv")
        for uf in sorted(munis["abbrev_state"].dropna().unique())
        for year in TARGET_YEARS
    ]
    combined = pd.concat(frames, ignore_index=True)
    if has_duplicate_dengue_rows(combined):
        raise RuntimeError("Dengue consolidada ainda contém semanas repetidas.")
    temp_path = path.with_suffix(".csv.part")
    combined.to_csv(temp_path, index=False)
    temp_path.replace(path)


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
        with requests.get(url, stream=True, timeout=300) as r:
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

    print("Baixando dados do SICOR...")
    get_sicor_data()

    print("Baixando dados do PRODES...")
    prodes_path = RAW_DIR / "prodes_biome_amazonia.gpkg"
    if not prodes_path.exists():
        # A versão (data) muda a cada atualização; pega a mais recente na API.
        catalog = requests.get(TERRABRASILIS_API, timeout=60).json()
        link = next(
            d["link"] for d in catalog if re.search(PRODES_LINK_REGEX, d["link"])
        )
        name = Path(link).name
        download_and_extract(
            f"https://terrabrasilis.dpi.inpe.br{link}",
            name,
            name.removesuffix(".zip"),
        )
        (RAW_DIR / name.removesuffix(".zip")).rename(prodes_path)

    print("Baixando dados de precipitação...")
    precip_path = RAW_DIR / "precipitation_min_amzl.asc"
    if not precip_path.exists():
        response = requests.get(
            "https://www.dpi.inpe.br/amb_data/Amazonia/bio14_amzl.asc",
            timeout=300,
        )
        response.raise_for_status()
        with open(precip_path, "wb") as f:
            f.write(response.content)

    print("Baixando dados de rodovias...")
    download_and_extract(
        "https://geoftp.ibge.gov.br/organizacao_do_territorio/redes_e_fluxos_geograficos/logistica_dos_transportes/2014/base_de_dados_2014.zip",
        "base_de_dados_2014.zip",
        "2014/rodovia_2014.shp",
    )

    print("Baixando dados de dengue (InfoDengue)...")
    get_dengue_data()

    print("ETL concluído com sucesso.")


if __name__ == "__main__":
    main()
