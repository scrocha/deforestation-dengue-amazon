# Deforestation and Dengue Modeling in the Brazilian Amazon

Pipeline de reprodução do estudo sobre a relação entre desmatamento e incidência de dengue em municípios da Amazônia brasileira (2016-2021), com foco em rastreabilidade metodológica (ETL -> EDA -> Moran -> OLS -> GWR).

## Artigo de referência

- Silva et al. (2023). Deforestation impacts on dengue incidence in the Brazilian Amazon. Environmental Monitoring and Assessment, 195:593.
- DOI: https://doi.org/10.1007/s10661-023-11174-0
- Cópia local (acesso pago, fora do git): `references/silva_2023_deforestation_dengue.pdf`

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

- models/run_models.py: Moran/LISA, OLS (VIF), GWR (bisquare, AICc), cenário transformado, reprodução do paper (4 variáveis), modelos hierárquicos e resumo final das métricas.

## Dados utilizados

- Dengue (InfoDengue/DATASUS): data/raw/dengue.csv
- Desmatamento (PRODES/INPE): data/raw/prodes_biome_amazonia.gpkg
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

- `avg_deforestation`: média anual de área desmatada (km²). Cada polígono do PRODES é atribuído ao município do seu centroide.
- `dist_roads`: distância média entre áreas desmatadas e rodovias (km). Ausente (imputada pela mediana nos modelos) em municípios sem desmatamento.
- `average_min_precipitation`: precipitação média mínima no mês mais seco.
- `gdp_capita`: PIB per capita (R$ mil por habitante) = PIB total (SIDRA 5938, mil R$) / população estimada.
- `std_rural_pop`: população rural padronizada por km².
- `std_urban_pop`: população urbana padronizada por km².
- `std_agri_credit`: crédito agrícola padronizado por km².
- `std_live_credit`: crédito pecuário padronizado por km².
- `std_crop_area`: área de lavoura temporária padronizada por km².

### Preditores da reprodução do paper (4), Tabela 1 do artigo

- `std_deforestation`: desmatamento médio anual (km²) padronizado pela área do município.
- `std_agri_credit` e `std_live_credit`: crédito rural agrícola e pecuário por km².
- `gdp_capita`: PIB per capita (sem log, como na Tabela 2 do artigo).

## Comparação com o artigo (Silva et al., 2023)

| Item | Artigo | Este repositório |
|---|---|---|
| Municípios | 550 totalmente dentro do bioma | 560 que intersectam o bioma (geobr 2021) |
| Resposta | taxa média de dengue por 100 mil (DATASUS/Sinan) | média das incidências semanais (InfoDengue) |
| Moran global (dengue) | 0,532 | 0,510 |
| Moran dos resíduos do OLS | 0,359 | 0,366 (resposta anual) / 0,379 |
| OLS (4 variáveis, escala bruta) R² | 0,20 | 0,186 (ajustado 0,180) |
| VIF das 4 variáveis | 1,006 / 1,621 / 1,111 / 1,583 | 1,01 / 1,33 / 1,02 / 1,32 |
| GWR: AIC do OLS → GWR (Δ, independe da escala de y) | 7949 → 7519 (Δ −430) | Δ AICc = −437 (gaussiano fixo, AICc) |
| GWR: R² ajustado (fórmula do GWmodel) | 0,70 | 0,741 (R² global 0,839; banda 103 km) |
| Clusters Alto-Alto | dois, no sul do bioma (69 municípios) | MT e AC (50 municípios) |

**Os 10 municípios a mais (560 vs 550).** São os de menor fração dentro do bioma (todos com menos de 2,2%; 9 com
menos de 1%, como Pium-TO e Luciara-MT). Retirá-los não muda nada: Moran 0,510 nos dois casos, OLS R² 0,186 vs
0,183, GWR fixo R² ajustado 0,741 vs 0,746 e Δ AICc −437 vs −434. Por isso a amostra de 560 foi mantida.

**GWR.** O artigo usou R (GWmodel) sem informar kernel nem critério de banda. O núcleo gaussiano (ou exponencial)
**fixo, com banda por AICc**, reproduz o artigo: Δ AICc de −437 (−430 no exponencial) contra −430, R² ajustado de
0,74 contra 0,70. Os coeficientes locais (Tabela 3) só são comparáveis na escala do artigo (taxa anual): a
resposta daqui é a média das incidências semanais, então os coeficientes saem ~52 vezes menores. Com a soma anual, o
intercepto tem mediana 80 (artigo 82) e o PIB per capita 1,50 (1,71); o desmatamento fica na mesma ordem de grandeza,
mas com sinal e quartis diferentes (mediana −1,8 mil vs 4,1 mil; Q1 −29 mil vs −7,0 mil), e os créditos dependem da
unidade usada pelo artigo, que não é informada. O
bisquare adaptativo, usado no baseline, dá R² ajustado de 0,46. Por isso os cenários 3 e 4 usam GWR fixo gaussiano
(`fit_gwr_fixed`); os cenários 1 e 2 mantêm o bisquare adaptativo.

**Dados (matriz de correlação da Fig. 4).** Erro absoluto médio de 0,07 nas 45 correlações de Pearson. Batem:
dengue~crédito agrícola (0,36), dengue~PIB (0,36), dengue~desmatamento (0,17 vs 0,18), dengue~área plantada
(0,37 vs 0,34), precipitação~crédito (−0,24 vs −0,21). Não batem: crédito pecuário (dengue 0,09 vs 0,25; com
crédito agrícola 0,12 vs 0,30), população rural~crédito pecuário (−0,05 vs −0,28), `dist_roads` (nenhum período
testado reproduz; o artigo usa 2019–2021), área plantada~crédito agrícola (0,96 vs 0,70). Com crédito agrícola
**per capita** a correlação PIB~crédito agrícola fica 0,60 e os VIFs 1,57/1,60, iguais ao artigo (1,62/1,58), o que
sugere que a padronização "por área" descrita no artigo não é a realmente usada. Os dados originais não estão
disponíveis, então essas diferenças não podem ser resolvidas.

## Métricas principais (execução atual)

- Moran global (dengue): I = 0,510, p = 0,001 (`data/results/moran_metrics.json`)
- OLS baseline (9 variáveis): R² = 0,179, AIC = 4145,9
- GWR baseline: R² = 0,506, AIC = 3963,7

Comparação consolidada (`data/results/10_final_model_comparison.csv`):

| Iteração | Variáveis | Transformações | OLS R² | OLS AIC | GWR R² | GWR AIC |
|---|---:|---|---:|---:|---:|---:|
| 1. Baseline | 9 | Nenhuma (Raw) | 0,179 | 4145,9 | 0,506 | 3963,7 |
| 2. Transformado Otimizado | 9 | Log1p(y) e Log1p/Norm(X) | 0,466 | 1340,5 | 0,656 | 1207,9 |
| 3. Reprodução Paper (Original, GWR fixo) | 4 | Nenhuma (Escala Raw) | 0,186 | 4130,8 | 0,839 | 3549,0 |
| 4. Reprodução Paper (Transf, GWR fixo) | 4 | Log1p(y) e Z-Score(X) | 0,266 | 1508,5 | 0,743 | 1132,5 |

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
uv run python3 models/run_models.py
```
