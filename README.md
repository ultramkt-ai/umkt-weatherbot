# Weather Bot

## Status do estágio atual, 2026-04-19

### Copytrading, estágio atual
Em 2026-04-19, o módulo de copytrading foi endurecido para operar a partir de um estado limpo e coerente com a carteira alvo atual.

Estado operacional atual:
- o copytrading mantém somente posições abertas com match exato na carteira alvo
- posições inválidas ou residuais não viram `closed_trade`
- remoções por inconsistência entram como invalidação técnica, não como saída financeira real
- `realized_pnl` do copytrading permanece zerado até existir mecanismo de fechamento econômico realmente auditável

Dinâmica atual de manutenção de posições:
- posição aberta continua apenas se houver match exato por `market_id`, `token_id` e `outcome_label`
- se a posição local deixar de bater com a carteira alvo e houver evidência estrutural suficiente, ela é removida da simulação
- a lógica atual privilegia limpeza de estado e integridade do ledger, não realização artificial de PnL

Garantias do estágio atual:
- paginação completa de posições remotas
- paginação defensiva de activity
- bloqueio da reimportação indevida de estado legado do copytrading quando o ledger já contém dados
- trilha separada de invalidações técnicas em log próprio

Leitura correta deste estágio:
- o sistema está apto para manter abertas apenas posições válidas da carteira espelhada
- o sistema ainda não contabiliza fechamento financeiro real como trade encerrado auditado
- antes de implementar fechamento econômico real, a prioridade foi limpar a simulação e eliminar mascaramento de dados

## Objetivo
Bot de paper trade para mercados de temperatura da Polymarket.

A ideia atual é simples:
- descobrir mercados de temperatura ainda operáveis
- normalizar os buckets de temperatura
- avaliar oportunidades extremas em `NO` e oportunidades baratas em `YES`
- validar preço executável e book via CLOB antes de qualquer entrada

---

## Arquitetura atual

### 1. Discovery e metadados
Fonte principal:
- Gamma API da Polymarket

Fluxo atual:
1. tenta carregar um catálogo local de mercados weather válidos
2. se o catálogo estiver vazio ou expirado, faz discovery ao vivo
3. no discovery ao vivo:
   - usa `markets/keyset` como scan principal
   - usa `events/slug` descobertos via busca como complemento
4. filtra apenas mercados de temperatura dentro da janela operacional
5. deduplica por `market_id`
6. salva um novo catálogo local de discovery

Arquivos principais:
- `data/polymarket_client.py`
- `core/scanner.py`
- `core/normalizer.py`
- `data/weather_catalog.py`
- `core/pipeline.py`

---

### 2. Pricing e execução simulada
Fonte principal:
- CLOB API da Polymarket

Uso atual:
- book por `token_id`
- leitura de `best_bid`, `best_ask`, profundidade e `last_trade_price`
- atualização do snapshot do market antes da decisão

Importante:
- preço e liquidez executável **não são cacheados para decisão**
- qualquer decisão de entrada depende de leitura fresca da CLOB

Arquivos principais:
- `data/polymarket_clob_client.py`
- `core/pipeline.py`
- `core/paper_broker.py`

---

### 3. Clima
Fluxo atual:
- geocodifica a cidade
- puxa forecast principal via Open-Meteo
- hoje o forecast secundário ainda é espelhado do principal
- alertas ainda estão pendentes, com stub em `alerts_client.py`

Importante:
- o cálculo de clima agora é feito por `outcome`, não pelo primeiro bucket do market
- isso evita distorção de `threshold_distance`

Arquivos principais:
- `data/geocoding_client.py`
- `data/weather_client.py`
- `data/alerts_client.py`

---

## Política de cache

### Princípio
Cache aqui existe para acelerar discovery, não para maquiar decisão.

### O que pode ser cacheado
Somente metadados de discovery, por exemplo:
- `market_id`
- `slug`
- título
- cidade
- data do evento
- `resolution_time`
- `clob_token_ids`
- campos brutos suficientes para reidratação leve

### O que NÃO pode ser cacheado para decisão
Nunca usar cache para aprovar entrada com base em:
- `best_bid`
- `best_ask`
- spread executável
- liquidez executável
- `last_trade_price`
- book da CLOB em geral

Esses dados precisam ser frescos no momento da análise.

### Catálogo local de discovery
Arquivo:
- `data_runtime/state/weather_market_catalog.json`

Política atual:
- TTL curto de **45 minutos**
- leitura sempre passa por filtro de janela operacional
- se o catálogo estiver vencido, é ignorado
- se não houver catálogo válido, o bot refaz discovery ao vivo
- catálogo é deduplicado por `market_id`

Objetivo:
- reduzir dependência do feed bruto da Gamma
- evitar refazer discovery completo a cada ciclo
- sem contaminar a decisão de entrada

### Cache de forecast
Atualmente existe cache do forecast em `WeatherClient`.
Uso pretendido:
- reduzir chamadas repetidas para a mesma cidade/data
- nunca substituir validação de mercado e CLOB

Observação:
- forecast e market cache são separados por design
- clima não pode servir para “forçar” trade quando preço/book não confirmam

---

## Janela operacional

O bot só deve trabalhar mercados que estejam:
- com pelo menos `MARKET_MIN_HOURS_TO_RESOLUTION`
- com no máximo `MARKET_MAX_DAYS_TO_RESOLUTION`

Defaults atuais:
- mínimo: `2` horas
- máximo: `3` dias

Esse filtro agora acontece cedo no pipeline, antes de desperdiçar tempo com mercado morto.

---

## Filtros baratos antes de clima

Antes de gastar chamadas de geocoding/forecast, o pipeline já elimina candidatos obviamente ruins, como:
- `low_liquidity`
- `price_out_of_range`
- mercado fora da janela operacional

Objetivo:
- reduzir custo
- acelerar o ciclo
- não gastar clima em candidato que já morreu por estrutura

---

## Estratégia atual

### Lado `NO`
Estratégia extrema:
- faixa default de `0.98` a `0.999`

### Lado `YES`
Estratégia barata:
- faixa default de `0.00` a `0.90`

A decisão escolhe `NO` ou `YES` conforme a faixa real do outcome.

Importante:
- isso foi ajustado depois da análise do dump do ColdMath
- o padrão observado não sustentou a tese antiga de focar só em `NO` 0.94-0.98

---

## Estado atual dos gargalos

Os gargalos mais relevantes encontrados até aqui foram:
- muito mercado já vencido ou perto demais da resolução
- muita falta de liquidez real
- feed bruto da Gamma nem sempre entrega os mercados weather certos de forma confiável
- pipeline ainda depende de rede externa lenta para fechar o ciclo completo

Em outras palavras:
- discovery melhorou
- agora o problema principal é qualidade operacional do universo encontrado

---

## Limitações conhecidas

1. `AlertsClient` ainda está como stub.
2. Forecast secundário ainda não traz uma segunda fonte real independente.
3. O ciclo completo ainda pode ficar lento por chamadas externas.
4. O catálogo local acelera discovery, mas não resolve book ruim ou mercado sem liquidez.

---

## Regras de segurança para decisão

Uma entrada só deve acontecer se:
1. o market estiver dentro da janela operacional
2. o market continuar válido estruturalmente
3. o preço estiver na faixa da estratégia
4. a CLOB confirmar dado fresco de preço e book
5. o risco de portfólio permitir

Se faltar dado fresco ou houver inconsistência, o candidato deve ser rejeitado.

Sem heroísmo. Sem fanfic estatística.

---

## Próximos passos recomendados

1. Medir o efeito real do catálogo local nos próximos ciclos.
2. Logar métricas separadas de:
   - scan bruto
   - weather detectado
   - weather dentro da janela
   - rejeição estrutural
   - rejeição por liquidez
3. Implementar segunda fonte real de forecast.
4. Implementar alertas reais.
5. Se necessário, manter um catálogo incremental por slug/data para reduzir ainda mais o custo de discovery.

---

## Novos módulos

### `parallel_strategies.py`
Responsável por registrar e documentar a camada de estratégias paralelas do paper trading.

Uso atual:
- define 3 estratégias iniciais baseadas em padrões observados em múltiplas carteiras vencedoras
- salva o registry em `data_runtime/state/parallel_strategies.json`
- prepara o terreno para comparação tipo Darwinismo algorítmico em paper trade

Estratégias iniciais:
- `NO_EXTREME`
- `YES_CONVEX`
- `MID_RANGE_BALANCED`

### `core/strategy_engine.py`
Camada de avaliação por estratégia.

Uso atual:
- recebe um `StrategySpec`
- decide lado (`NO`, `YES` ou adaptativo)
- valida a faixa de preço da estratégia
- aplica score com viés por estratégia

### `multi_strategy_runner.py`
Scaffold inicial da camada multi-estratégia.

Uso atual:
- gera relatório-base em `data_runtime/reports/multi_strategy_latest.json`
- preserva o pipeline atual enquanto a execução paralela completa é integrada

### `storage/strategy_store.py`
Persistência isolada por estratégia.

Uso atual:
- mantém estado individual por estratégia em `data_runtime/state/strategies/`
- prepara trilhas separadas para logs e relatórios

### `storage/strategy_journal.py`
Journaling isolado por estratégia.

### `storage/strategy_report.py`
Relatórios isolados por estratégia e relatório comparativo consolidado.

### `strategy_comparison.py`
Comparador inicial do paper trading multi-estratégia.

Uso atual:
- lê o estado de cada estratégia
- lê os logs isolados de decisões, ciclos e trades abertos
- calcula métricas comparativas iniciais
- gera snapshot consolidado em `data_runtime/reports/strategy_comparison_latest.json`

### `core/multi_strategy_engine.py`
Avaliação paralela por candidato.

Uso atual:
- passa o mesmo candidato pelas 3 estratégias
- gera decisão isolada por estratégia
- abre paper trade separado por estratégia quando aprovado
- grava estado, logs e relatório individuais

### `core/strategy_monitor.py`
Monitoramento e fechamento por estratégia.

Uso atual:
- fecha paper trades por estratégia
- prioriza resolução real do mercado quando disponível
- caso o mercado ainda não esteja resolvido, usa marcação mark-to-market com base no CLOB
- registra a fonte da marcação no trade fechado para auditoria

### `web_dashboard.py`
Interface web local para acompanhar o bot.

Uso atual:
- interface em React via CDN servida por HTTP local simples
- lê `strategy_comparison_latest.json`, `latest_funnel_report.json` e logs de decisão por estratégia
- mostra status geral do ciclo e status operacional do bot
- normaliza datas para GMT-3 (São Paulo)
- mostra ranking atual das estratégias
- mostra métricas e decisões recentes por estratégia
- mostra explicitamente patrimônio total, caixa livre, capital aberto e PnL realizado
- inclui sidebar preparada para múltiplos módulos, incluindo `Copytrading`
- expõe ações da UI para rodar scan/manual refresh e copytrading experimental

### `copytrading_competitor.py`
Camada inicial para tratar copytrading como competidor do torneio.

Uso atual:
- consulta a carteira-alvo
- replica sinais reais da carteira com preços reais de mercado
- não depende de clima para disparar entradas
- salva relatório próprio em `data_runtime/reports/copytrading_latest.json`
- mantém estado em `data_runtime/state/copytrading_competitor_state.json`
- compara edge própria versus copiar carteira boa sob as mesmas guardrails principais de risco

### `copytrading.py`
Responsável por monitorar carteiras externas via Polymarket Data API.

Uso esperado:
- polling periódico de trades recentes
- persistência de snapshot local em `data_runtime/state/copytrading_state.json`
- log append-only em `data_runtime/logs/copytrading_snapshots.jsonl`

Regra operacional:
- polling sugerido a cada 5 minutos
- sem cache de preço para tomada de decisão do bot principal
- foco em detecção de novos trades e construção de trilha auditável

### `wallet_intelligence.py`
Responsável por auditoria e extração de padrões de carteiras.

Uso atual:
- puxar até 2000 trades via `/trades`
- usar `/positions` apenas para snapshot de posições abertas
- gerar relatório com:
  - frequência por cidade
  - frequência por side
  - bandas de preço
  - buckets mais operados
  - posição média em USDC e tokens
  - aberto vs encerrado

Saída:
- `data_runtime/reports/wallet_intelligence/<wallet>_latest.json`
- versões carimbadas por timestamp

## Estratégia atual de evolução

A direção atual do projeto passou a ser:
- manter o pipeline base intacto como referência
- desenvolver uma camada paralela de paper trading multi-estratégia
- comparar estratégias por desempenho e robustez antes de promover qualquer uma a regime principal

A análise de múltiplas wallets fortes indicou 3 regimes iniciais:
- `NO_EXTREME`
- `YES_CONVEX`
- `MID_RANGE_BALANCED`

Decisão operacional atual:
- rodar as 3 em paralelo em paper trading
- usar bankroll virtual, estado e relatórios separados por estratégia
- evitar escolher vencedora cedo demais com base só em narrativa ou PnL pontual

Critério recomendado de comparação:
- pelo menos 200 decisões elegíveis por estratégia
- avaliar retorno, win rate, drawdown, profit factor, quantidade de trades e robustez operacional

## Resumo executivo

O bot agora opera com esta regra central:
- **cache só para discovery**
- **CLOB fresca para decisão**
- **janela operacional filtrada cedo**
- **clima calculado por outcome**
- **Data API pública para wallet intelligence e copytrading**
- **camada multi-estratégia em construção para Darwinismo algorítmico em paper trading**

Esse é o desenho atual mais seguro para não deixar cache contaminar análise de trade e, ao mesmo tempo, evitar escolher estratégia vencedora cedo demais.
