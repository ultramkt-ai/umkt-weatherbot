# Changelog

## 2026-04-12

### Ajustes no pipeline e discovery
- O pipeline passou a complementar o scan principal com discovery por slug/evento de temperatura, em vez de depender só do feed bruto da Gamma.
- Foi adicionado filtro de janela operacional cedo no pipeline para descartar mercados já vencidos, perto demais da resolução ou fora do horizonte máximo configurado.
- O pipeline passou a deduplicar candidatos por `market_id` antes de seguir com a análise.

### Ajustes de performance e custo
- Candidatos com `low_liquidity` ou `price_out_of_range` agora são rejeitados antes de chamadas de geocoding e forecast.
- Isso reduz custo de rede e evita gastar clima em mercado estruturalmente morto.

### Ajustes de clima
- O cálculo de clima deixou de usar implicitamente o primeiro outcome do market.
- Agora `threshold_distance` e a avaliação meteorológica são calculados por `outcome`, o que reduz distorção na análise.

### Catálogo local de discovery
- Foi criado `data/weather_catalog.py`.
- O bot agora pode salvar e reutilizar um catálogo local de mercados weather válidos para discovery.
- O catálogo guarda apenas metadados de discovery, nunca preço ou book para decisão.
- TTL atual do catálogo: 45 minutos.
- Na leitura, os itens ainda passam por filtro de janela operacional.

### Política de cache consolidada
- Cache é permitido apenas para acelerar discovery e forecast reutilizável.
- Preço, spread, best bid/ask, liquidez executável e book da CLOB permanecem obrigatoriamente frescos no momento da decisão.
- Essa política foi documentada explicitamente em `README.md` para evitar contaminação da análise por cache antigo.

### Documentação
- Foi criado `README.md` no projeto `weather_bot` com a arquitetura atual, política de cache, limitações conhecidas, gargalos e próximos passos.
- A documentação passou a incluir os novos módulos `copytrading.py` e `wallet_intelligence.py`.

### Wallet intelligence, copytrading e estratégias paralelas
- Foi criado `data/polymarket_data_client.py` para consumir a Polymarket Data API pública em `https://data-api.polymarket.com`.
- Foi criado `wallet_intelligence.py` para auditoria de carteiras com foco em padrões de weather trading.
- Foi criado `copytrading.py` para polling de trades recentes com persistência local de snapshots e trilha auditável.
- Foi criado `parallel_strategies.py` para registrar a camada inicial de paper trading com 3 estratégias paralelas.
- Foi criado `models/strategy.py` para representar specs de estratégia.
- Foi criado `core/strategy_engine.py` como primeira camada de avaliação por estratégia.
- Foi criado `multi_strategy_runner.py` como scaffold inicial da execução comparativa multi-estratégia.
- Foi criada e validada a primeira versão do registry `data_runtime/state/parallel_strategies.json` com 3 estratégias paralelas.
- Foram criados `storage/strategy_store.py`, `storage/strategy_journal.py`, `storage/strategy_report.py` e `strategy_comparison.py` para sustentar estado, logs e relatório comparativo por estratégia.
- Foi criado `core/multi_strategy_engine.py` para executar avaliação paralela do mesmo candidato entre as 3 estratégias, com abertura de paper trade e persistência isolada por estratégia.
- O bootstrap de estado por estratégia foi corrigido para nascer limpo, sem herdar contadores contaminados do estado global do bot.
- `strategy_comparison.py` foi ampliado para consumir logs por estratégia e gerar métricas comparativas iniciais de approval rate, score médio, entry price médio, ROI vs bankroll inicial e exposição.
- Foi criado `core/strategy_monitor.py` para fechar trades por estratégia com preferência por resolução real do mercado e fallback para mark-to-market via CLOB, registrando a fonte de precificação para auditoria.
- Foi criado `web_dashboard.py` como interface web local simples para acompanhar o status do bot, o ranking das estratégias e as decisões recentes por estratégia.
- O dashboard evoluiu para uma interface em React via CDN com sidebar modular, status operacional do bot, datas normalizadas para GMT-3, indicador animado de saúde, gráficos de bankroll e decomposição explícita por estratégia entre patrimônio total, caixa livre, capital aberto e PnL realizado.
- Foi criado `copytrading_competitor.py` como primeira camada para transformar copytrading em competidor do torneio, com estado e relatório próprios.
- Ficou explicitamente definido e documentado que `COPYTRADING_COLDMATH` não depende de clima para disparar entradas, apenas de sinais reais da carteira alvo, preços reais de mercado e regras de risco do experimento.
- A automação recorrente do `weather_bot` foi simplificada para um `crontab` do sistema rodando `python3 app.py` a cada 5 minutos com log em `data_runtime/logs/cron.log`.
- O relatório inicial de wallet intelligence foi desenhado para usar `/trades` como fonte primária e `/positions` apenas como snapshot complementar.
- A análise de múltiplas carteiras passou a sustentar 3 regimes iniciais: `NO_EXTREME`, `YES_CONVEX` e `MID_RANGE_BALANCED`.
- Ficou definida a decisão operacional de rodar paper trading paralelo entre os 3 regimes e escolher vencedora depois de amostra mínima comparável, em vez de promover uma tese cedo demais.

### Diagnóstico operacional observado
- O gargalo principal deixou de ser “não encontrar mercados” e passou a ser a qualidade operacional dos mercados encontrados.
- As rejeições dominantes observadas continuaram concentradas em:
  - `invalid_resolution_window`
  - `low_liquidity`
- Isso reforçou a necessidade de filtrar melhor a janela antes do restante da análise.
