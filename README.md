# Deforestation and Dengue Modeling in the Brazilian Amazon

Pipeline de reprodução do estudo sobre a relação entre desmatamento e incidência de dengue em municípios da Amazônia brasileira (2016-2021), com foco em rastreabilidade metodológica (ETL -> EDA -> Moran -> OLS -> GWR).

## Artigo de referência

- Silva et al. (2023). Deforestation impacts on dengue incidence in the Brazilian Amazon. Environmental Monitoring and Assessment, 195:593.
- DOI: https://doi.org/10.1007/s10661-023-11174-0

## Objetivo do projeto

Este repositório implementa um fluxo completo de:

1. Download dos dados brutos geoespaciais, epidemiológicos e socioeconômicos.
2. Pré-processamento e integração municipal em base analítica única.
3. EDA pré-modelagem com estatísticas, correlações e mapas.
4. Modelagem espacial com Moran, OLS e GWR.
5. Comparação entre cenários baseline, transformados e reprodução do paper.

## Diagnóstico dos scripts

### ETL

- etl/01_download_data.py
  - Faz download das fontes brutas (IBGE/geobr, SIDRA, InfoDengue, SICOR, PRODES, WorldClim e malha rodoviária).
  - Salva os arquivos em data/raw.

- etl/02_preprocess_data.py
  - Agrega dados por município para 2016-2021.
  - Cria variáveis padronizadas por área municipal (km²).
  - Exporta:
    - data/processed/deforestation_dengue_data.csv
    - data/processed/deforestation_dengue_geo.gpkg

### EDA

- eda/03_eda_pre_modeling.py
  - Estatísticas descritivas, zeros/NA e skewness.
  - Correlação, dispersões e mapas exploratórios.
  - Exporta:
    - data/processed/03_eda_statistics.csv
    - figuras 01 a 06 em figures/

### Modelagem

- models/04_moran.py: Moran global e LISA (clusters locais).
- models/05_ols.py: OLS baseline com 9 preditores, VIF e Moran dos resíduos.
- models/06_gwr.py: GWR baseline (kernel bisquare, banda por AICc).
- models/07_comparison.py: gráficos de diagnóstico e resumo dos coeficientes locais.
- models/08_transformations.py: cenário com transformações (log1p e normalização).
- models/09_paper_reproduction.py: reprodução com as 4 variáveis centrais do paper.
- models/10_final_summary.py: consolidação final das métricas.

## Dados utilizados

- Dengue (InfoDengue/DATASUS): data/raw/dengue.csv
- Desmatamento (PRODES/INPE): data/raw/prodes_biome_amazonia_v20260717.gpkg
- Bioma e municípios (geobr/IBGE): data/raw/amazon.gpkg e data/raw/municipality.gpkg
- PIB per capita (SIDRA tabela 5938): data/raw/pib.csv
- População urbana/rural (SIDRA tabela 202): data/raw/populacao_situacao.csv
- População estimada (SIDRA tabela 6579): data/raw/populacao_estimativa.csv
- Lavoura temporária (SIDRA tabela 1612): data/raw/lavoura_temporaria.csv
- Crédito rural (SICOR/BCB): data/raw/sicor_contratos_*.csv
- Precipitação mínima (WorldClim bio14): data/raw/precipitation_min_amzl.asc
- Rodovias (IBGE 2014): data/raw/2014/rodovia_2014.shp

## Variáveis analisadas

### Resposta

- `dengue_incidence`: incidência média de dengue por 100 mil habitantes.

### Preditores do baseline (9)

- `avg_deforestation`: média anual de área desmatada (km²).
- `dist_roads`: distância média entre áreas desmatadas e rodovias (km).
- `average_min_precipitation`: precipitação média mínima no mês mais seco.
- `gdp_capita`: PIB per capita.
- `std_rural_pop`: população rural padronizada por km².
- `std_urban_pop`: população urbana padronizada por km².
- `std_agri_credit`: crédito agrícola padronizado por km².
- `std_live_credit`: crédito pecuário padronizado por km².
- `std_crop_area`: área de lavoura temporária padronizada por km².

### Preditores da reprodução do paper (4)

- `avg_deforestation`: +0.0191
- `std_agri_credit`: +0.3213
- `std_live_credit`: +0.0768
- `Average log GDP per capita`: +0.6621

## Métricas principais salvas no repositório

- Moran global (dengue): I = 0.5307, p = 0.001 (data/results/moran_metrics.json)
- OLS baseline: R² = 0.156, AIC = 4154.6 (data/results/ols_metrics.json)
- GWR baseline: R² = 0.488, AIC = 3972.7 (data/results/gwr_metrics.json)

Comparação consolidada (data/results/10_final_model_comparison.csv):

| Iteração | Variáveis | Transformações | OLS R² | OLS AIC | GWR R² | GWR AIC |
|---|---:|---|---:|---:|---:|---:|
| 1. Baseline | 9 | Nenhuma (Raw) | 0.156 | 4154.6 | 0.488 | 3972.7 |
| 2. Transformado Otimizado | 9 | Log1p(y) e Log1p/Norm(X) | 0.429 | 1375.7 | 0.646 | 1213.1 |
| 3. Reprodução Paper (Original) | 4 | Nenhuma (Escala Raw) | 0.143 | 4153.1 | 0.555 | 3916.0 |
| 4. Reprodução Paper (Transf) | 4 | Log1p(y) e Z-Score(X) | 0.220 | 1540.3 | 0.658 | 1216.6 |

## Figuras relevantes

### 1) Matriz de correlação dos preditores e resposta

![Matriz de correlação](figures/03_correlation_matrix.png)

### 2) Mapa exploratório de dengue e desmatamento

![Mapa exploratório](figures/05_exploratory_map.png)

### 3) Clusters LISA (autocorrelação local)

![Clusters LISA](figures/07_lisa_clusters.png)

### 4) R² local do GWR (baseline)

![R2 local GWR](figures/09_gwr_r2_local.png)

### 5) Comparação lado a lado do R² local do GWR completo

Sem transformações vs com transformações, com R² global explícito no título de cada painel.

![R² do GWR por cenário](figures/11_gwr_r2_comparison.png)

## Como executar

Execução completa:

```bash
chmod +x run_pipeline.sh
./run_pipeline.sh
```

Execução por etapas:

```bash
uv run python3 etl/01_download_data.py
uv run python3 etl/02_preprocess_data.py
uv run python3 eda/03_eda_pre_modeling.py
uv run python3 models/04_moran.py
uv run python3 models/05_ols.py
uv run python3 models/06_gwr.py
uv run python3 models/07_comparison.py
uv run python3 models/08_transformations.py
uv run python3 models/09_paper_reproduction.py
uv run python3 models/10_final_summary.py
```
