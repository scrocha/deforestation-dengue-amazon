#!/bin/bash

set -e

echo "------------------------------------------------------------"
echo "Iniciando Pipeline de Reprodução Espacial"
echo "------------------------------------------------------------"

echo "[1/10] Baixando dados brutos da Amazônia"
uv run python3 etl/01_download_data.py

# echo "[2/10] Pré-processamento e cruzamento geoespacial"
# uv run python3 etl/02_preprocess_data.py

echo "[3/10] Gerando estatísticas descritivas e mapas exploratórios"
uv run python3 eda/03_eda_pre_modeling.py

echo "[4/10] Calculando Índice de Moran (Autocorrelação)"
uv run python3 models/04_moran.py

echo "[5/10] Ajustando Modelo Global (OLS)"
uv run python3 models/05_ols.py

echo "[6/10] Ajustando Modelo Local (GWR)"
uv run python3 models/06_gwr.py

echo "[7/10] Gerando comparação entre OLS e GWR"
uv run python3 models/07_comparison.py

echo "[8/10] Testando transformações logarítmicas e normalização"
uv run python3 models/08_transformations.py

echo "[9/10] Executando reprodução exata dos parâmetros do artigo"
uv run python3 models/09_paper_reproduction.py

echo "[10/10] Consolidando resumo final de métricas"
uv run python3 models/10_final_summary.py

echo "------------------------------------------------------------"
echo "PIPELINE CONCLUÍDO COM SUCESSO!"
echo "Resultados disponíveis em: data/results/"
echo "Figuras geradas em: figures/"
echo "------------------------------------------------------------"
