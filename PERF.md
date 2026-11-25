# Registro de otimizações (tempo e RAM)

| Etapa | Antes | Depois | Mudança | Veredito |
|---|---|---|---|---|
| `etl/02_preprocess_data.py` | > 25 min, > 3,7 GB | 13,3 s, 1,9 GB | filtro `where`/`columns` ao ler o PRODES, uma junção espacial, `sjoin_nearest` em vez de distância à união das rodovias | mantido |
| `eda/03_eda_pre_modeling.py` | n/m | 7,2 s, 0,47 GB | sem mudança | — |
| `models/run_models.py` | 20,5 s, 0,5 GB | 14,2 s, 0,5 GB | busca de banda com AICc em lote (a seção áurea do mgwr continua); ajuste final no mgwr por causa dos `tvalues`; coeficientes e métricas iguais (~1e-11) | mantido |

Todas as colunas numéricas do CSV processado e as métricas dos modelos saíram idênticas às anteriores.
