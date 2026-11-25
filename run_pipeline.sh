#!/bin/bash
set -e

echo "[1/4] Baixando dados brutos da Amazônia"
uv run python etl/01_download_data.py

echo "[2/4] Pré-processamento e cruzamento geoespacial"
uv run python etl/02_preprocess_data.py

echo "[3/4] Estatísticas descritivas e mapas exploratórios"
uv run python eda/03_eda_pre_modeling.py

echo "[4/4] Moran, OLS, GWR, transformações, paper, hierárquico e resumo"
uv run python models/run_models.py

echo "Resultados em data/results/ e figuras em figures/"
