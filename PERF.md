# Registro de otimizações (tempo e RAM)

| Etapa | Antes | Depois | Mudança | Veredito |
|---|---|---|---|---|
| `etl/02_preprocess_data.py` | > 25 min, > 3,7 GB | 12,5 s, 1,7 GB | filtro `where`/`columns` ao ler o PRODES, uma junção espacial, `sjoin_nearest` em vez de distância à união das rodovias | mantido |
| `eda/03_eda_pre_modeling.py` | n/m | 7,2 s, 0,47 GB | sem mudança | — |
| `models/run_models.py` (com o GWR fixo do artigo) | 14,8 s (sem GWR fixo) → 20,0 s | 12,2 s, 0,5 GB | busca de banda do bisquare em lote (AICc igual ao do mgwr); `n_jobs=1` nos GWR e `Sel_BW`, porque com 560 municípios a partida dos processos do joblib custava ~6 s por ajuste; ajuste final no mgwr por causa dos `tvalues`. Coeficientes e métricas idênticos | mantido |

Todas as colunas numéricas do CSV processado e as métricas dos modelos saíram idênticas às anteriores.

Limpeza final: 1.402 → 866 linhas nos scripts (download 332 → 187, pré-processamento 202 → 159, EDA 158 → 124, modelos 389 → 396 com helpers; o monitor `polymarket-monitor.py`, sem relação com o projeto, foi removido, e a dependência scikit-learn, não usada). Pré-processamento e modelos com saídas idênticas às anteriores.
