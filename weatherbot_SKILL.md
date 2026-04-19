---
name: umkt-weatherbot
description: >
  Use this skill for ANY work on the umkt-weatherbot project — adding strategies,
  modifying the pipeline, extending metrics, fixing bugs, or working on any module
  inside core/, data/, storage/, models/, utils/, or messaging/.

  Triggers: "adicionar estratégia", "modificar pipeline", "novo indicador",
  "corrigir bug no bot", "estender métricas", "nova fonte de dados", or any
  request that touches files in the weather_bot directory.

  Do NOT use for the hub dashboard (use umkt-hub skill) or for unrelated projects.
---

# WeatherBot:UMKT — Architecture & Development Skill

Leia este arquivo completamente antes de tocar em qualquer linha do projeto.

---

## 1. O que o bot faz

Paper trading em mercados de previsão de temperatura da Polymarket. Opera três estratégias em paralelo (torneio Darwinista) para determinar qual gera mais retorno antes de promover qualquer uma a regime real.

**Ciclo de vida de uma decisão:**
```
Discovery (Gamma API)
  → Filtro de janela operacional
  → Filtro barato (liquidez, preço fora de faixa)
  → Clima (geocoding + Open-Meteo)
  → CLOB fresca (preço e book em tempo real)
  → Avaliação por estratégia (score + faixa de preço)
  → Paper trade aberto (estado isolado por estratégia)
```

---

## 2. Estrutura de arquivos

```
weather_bot/
├── app.py                      ← entrypoint principal (roda via cron a cada 5min)
├── config.py                   ← toda a configuração (dataclasses frozen)
├── parallel_strategies.py      ← definição das 3 estratégias
├── strategy_comparison.py      ← comparador e métricas consolidadas
├── multi_strategy_runner.py    ← scaffold do runner multi-estratégia
├── copytrading_cycle.py        ← ciclo de copytrading (roda via cron)
├── copytrading_competitor.py   ← lógica de mirror da carteira ColdMath
├── wallet_intelligence.py      ← auditoria de carteiras externas
│
├── core/
│   ├── pipeline.py             ← orquestra discovery + clima + decisão
│   ├── scanner.py              ← scan de mercados via Gamma API
│   ├── normalizer.py           ← normaliza buckets de temperatura
│   ├── paper_broker.py         ← abre e fecha paper trades
│   ├── strategy_engine.py      ← avalia um candidato por StrategySpec
│   ├── multi_strategy_engine.py← avalia candidato em todas as estratégias
│   ├── strategy_monitor.py     ← fecha trades por estratégia (TP/SL/Time)
│   ├── monitor.py              ← monitora trades do pipeline base
│   └── state_machine.py        ← decide can_open / can_monitor
│
├── data/
│   ├── polymarket_client.py    ← Gamma API (discovery)
│   ├── polymarket_clob_client.py← CLOB API (preço e book)
│   ├── weather_client.py       ← Open-Meteo (forecast)
│   ├── geocoding_client.py     ← geocodificação de cidades
│   ├── alerts_client.py        ← stub de alertas (pendente)
│   └── weather_catalog.py      ← catálogo local de mercados (TTL 45min)
│
├── models/
│   └── strategy.py             ← StrategySpec dataclass
│
├── storage/
│   ├── state_store.py          ← lê/salva bot_state.json
│   ├── journal.py              ← log de eventos de runtime
│   ├── strategy_store.py       ← estado isolado por estratégia
│   ├── strategy_journal.py     ← logs de decisões/ciclos por estratégia
│   ├── strategy_report.py      ← relatórios por estratégia e comparativo
│   └── ledger_db.py            ← SQLite ledger (trades e posições)
│
├── utils/
│   ├── process_lock.py         ← lock de processo (evita ciclos paralelos)
│   └── time_utils.py           ← now_iso(), now_dt()
│
├── messaging/
│   └── status_publisher.py     ← monta mensagem de status do ciclo
│
└── data_runtime/               ← gerado em runtime, nunca commitar
    ├── state/
    │   ├── bot_state.json
    │   ├── portfolio_ledger.sqlite3
    │   ├── parallel_strategies.json
    │   └── strategies/{id}/state.json
    ├── logs/
    │   ├── cron.log
    │   ├── runtime_events.jsonl
    │   └── strategies/{id}/decisions.jsonl
    │                          /cycles.jsonl
    └── reports/
        ├── strategy_comparison_latest.json
        ├── latest_funnel_report.json
        └── copytrading_latest.json
```

---

## 3. Configuração (`config.py`)

Toda a config usa `@dataclass(frozen=True)` — imutável em runtime. Valores configuráveis via variáveis de ambiente.

### RiskConfig
```python
initial_bankroll_usd    = 10_000.0
risk_per_trade_pct      = 0.01    # 1% por trade
max_total_exposure_pct  = 0.10    # 10% exposição máxima
max_open_trades         = 8
max_cluster_exposure_pct= 0.03    # 3% por cluster (cidade)
max_trades_per_cluster  = 3
daily_stop_pct          = -0.04   # -4% stop diário
weekly_stop_pct         = -0.08   # -8% stop semanal
kill_switch_pct         = -0.12   # -12% kill switch
```

### MarketConfig
```python
min_no_price            = 0.95    # faixa NO base
max_no_price            = 0.999
min_yes_price           = 0.00    # faixa YES base
max_yes_price           = 0.90
min_liquidity_usd       = 750     # liquidez mínima
max_spread_pct          = 0.99
min_hours_to_resolution = 2       # janela operacional
max_days_to_resolution  = 3
relaxed_observe_mode    = True    # observa sem entrar
```

### ExitConfig
```python
tp          = 0.02    # +2% take profit
sl          = -0.03   # -3% stop loss
time_hours  = 12      # saída por tempo
```

### SchedulingConfig
```python
market_scan_interval_min       = 5
open_trades_check_interval_min = 5
near_resolution_check_interval_min = 3
final_hour_check_interval_min  = 1
near_resolution_hours          = 6
final_hour_hours               = 1
```

---

## 4. StrategySpec (`models/strategy.py`)

Cada estratégia do torneio é um `StrategySpec`:

```python
@dataclass
class StrategySpec:
    strategy_id:   str    # ex: "NO_EXTREME"
    side_mode:     str    # "NO", "YES" ou "BOTH"
    min_price:     float  # faixa de preço mínima
    max_price:     float  # faixa de preço máxima
    preferred_low: float  # faixa preferida (score bonus)
    preferred_high:float
    max_entries_per_market: int
    score_bias:    int    # bonus de score para esta estratégia
    notes:         str    # contexto da estratégia
    min_hours_to_resolution: float
    max_hours_to_resolution: float
    required_min_distance_threshold: float  # °C
    exclusive_cities: tuple[str, ...]       # cidades exclusivas desta estratégia
```

### As 3 estratégias atuais

| ID | Lado | Faixa | Resolução | Cidades-chave | Dist. min. |
|---|---|---|---|---|---|
| `NO_EXTREME` | NO | 0.80–0.995 | > 2h | Todas liberadas | 0.5°C |
| `YES_CONVEX` | YES | 0.04–0.60 | 4–30h | Todas liberadas | 0°C |
| `MID_RANGE_BALANCED` | BOTH | 0.30–0.90 | 4–72h | Todas liberadas | 0°C |

---

## 5. Política de cache — CRÍTICA

**Princípio:** cache existe para acelerar discovery, nunca para maquiar decisão.

### O que PODE ser cacheado
- Metadados de discovery: `market_id`, `slug`, título, cidade, `resolution_time`, `clob_token_ids`
- Forecast de clima (reutilizável para mesma cidade/data)
- Catálogo local de mercados weather válidos (TTL: 45 minutos)

### O que NUNCA pode ser cacheado para decisão
- `best_bid` / `best_ask`
- Spread executável
- Liquidez executável
- `last_trade_price`
- Book da CLOB em geral

**Qualquer entrada depende de leitura fresca da CLOB no momento da decisão.**

### Catálogo local
```
data_runtime/state/weather_market_catalog.json
TTL: 45 minutos
```
- Leitura sempre passa por filtro de janela operacional
- Se vencido → bot refaz discovery ao vivo
- Deduplicado por `market_id`

---

## 6. Janela operacional

O bot só trabalha mercados dentro de:
- Mínimo: `MARKET_MIN_HOURS_TO_RESOLUTION` = **2 horas**
- Máximo: `MARKET_MAX_DAYS_TO_RESOLUTION` = **3 dias**

Esse filtro acontece **cedo no pipeline**, antes de qualquer chamada externa.

---

## 7. Filtros baratos antes do clima

Antes de geocoding e forecast, o pipeline elimina candidatos com:
- `low_liquidity` (abaixo de $750)
- `price_out_of_range`
- Fora da janela operacional

**Objetivo:** não gastar clima em candidato estruturalmente morto.

---

## 8. Regras de segurança para decisão

Uma entrada **só ocorre** se:
1. Market dentro da janela operacional
2. Market válido estruturalmente (liquidez, spread)
3. Preço dentro da faixa da estratégia
4. CLOB confirma dado fresco de preço e book
5. Risco de portfólio permite (exposure, cluster, daily stop, kill switch)

Se qualquer condição falhar → candidato rejeitado. **Sem heroísmo. Sem fanfic estatística.**

---

## 9. State machine (`core/state_machine.py`)

O `bot_state.json` controla o que o bot pode fazer em cada ciclo:

```python
state.can_open_new_trades    # False se kill switch, daily stop, etc.
state.can_monitor_open_trades# sempre True exceto em erro fatal
```

`refresh_bot_mode(state)` é chamado no início de cada ciclo para reavaliação.

### Campos principais do `bot_state.json`
```json
{
  "current_bankroll_usd": 10000.0,
  "current_cash_usd": 9800.0,
  "capital_alocado_aberto_usd": 200.0,
  "open_exposure_pct": 0.02,
  "realized_pnl_total_usd": 87.50,
  "max_drawdown_pct": 0.012,
  "open_trades_count": 3,
  "closed_trades_count": 41,
  "markets_scanned_today": 0,
  "approved_today": 0,
  "rejected_today": 0,
  "last_cycle_finished_at": "2026-04-18T14:33:00",
  "next_market_scan_at": "2026-04-18T14:38:00",
  "last_error_code": null,
  "last_error_at": null,
  "can_open_new_trades": true,
  "can_monitor_open_trades": true
}
```

---

## 10. Métricas por estratégia (`strategy_comparison.py`)

Geradas a cada ciclo e salvas em `strategy_comparison_latest.json`. Cada entrada de estratégia contém:

### `strategy` (StrategySpec serializado)
Todos os campos do StrategySpec, incluindo `exclusive_cities`, `score_bias`, faixas de preço e janela de resolução.

### `state` (estado financeiro isolado)
```json
{
  "current_bankroll_usd": 10231.50,
  "current_cash_usd": 9981.50,
  "realized_pnl_total_usd": 231.50,
  "open_trades_count": 3,
  "closed_trades_count": 10,
  "approved_trades_count": 13,
  "markets_scanned_today": 45,
  "approved_today": 2,
  "rejected_today": 43,
  "open_exposure_pct": 0.024,
  "max_drawdown_pct": 0.008,
  "last_score_approved": 72
}
```

### `metrics` (calculadas dos logs)
```json
{
  "decisions_logged": 31,
  "approved_decisions_logged": 13,
  "rejected_decisions_logged": 18,
  "approval_rate": 0.419,
  "open_trades_logged": 3,
  "closed_trades_logged": 10,
  "win_rate_closed_only": 0.625,
  "profit_factor": 1.875,
  "avg_hold_hours_closed_only": 9.8,
  "gross_profit_closed_usd": 231.50,
  "gross_loss_closed_usd": 123.40,
  "avg_decision_score": 68.2,
  "avg_entry_price_approved_only": 0.22,
  "approved_yes_count": 10,
  "approved_no_count": 3,
  "roi_vs_initial_bankroll": 0.0232,
  "resolution_sources": {"real": 7, "mark_to_market": 3}
}
```

### Critério de maturidade
**200 decisões elegíveis por estratégia** antes de declarar vencedora. Abaixo disso, qualquer ranking é prematuro.

---

## 11. Logs de estratégia

Cada estratégia tem seus próprios logs em append-only `.jsonl`:

```
data_runtime/logs/strategies/{strategy_id}/
  decisions.jsonl   ← cada decisão avaliada (aprovada ou rejeitada)
  cycles.jsonl      ← resumo de cada ciclo com ROI acumulado
```

### Formato de `decisions.jsonl`
```json
{
  "timestamp": "2026-04-18T14:33:01",
  "market_id": "0xabc...",
  "city": "Miami",
  "decision": {
    "approved": true,
    "score": 74,
    "trade_side": "YES",
    "entry_price": 0.18,
    "rejection_reason": null
  }
}
```

### Formato de `cycles.jsonl`
```json
{
  "timestamp": "2026-04-18T14:33:05",
  "roi_vs_initial_bankroll": 0.0232,
  "current_bankroll_usd": 10231.50,
  "approved_today": 2,
  "markets_scanned_today": 45
}
```

---

## 12. Copytrading (`copytrading_competitor.py`)

Estratégia `COPYTRADING_COLDMATH` opera como competidor do torneio:
- **Não depende de clima** para disparar entradas
- Replica fills reais da carteira ColdMath com notional proporcional
- Usa as mesmas guardrails de risco do torneio principal
- Estado em `data_runtime/state/copytrading_competitor_state.json`
- Relatório em `data_runtime/reports/copytrading_latest.json`

**Regra:** copytrading é um espelho, não uma estratégia de análise. Nenhuma lógica de clima, score ou threshold deve ser adicionada nele.

---

## 13. Padrões de código do projeto

### Config: sempre via `load_config()`
```python
from config import load_config
config = load_config()
# use config.risk.max_open_trades, config.market.min_liquidity_usd, etc.
```
Nunca hardcode valores que existem na config.

### Tempo: sempre via `utils/time_utils.py`
```python
from utils.time_utils import now_iso, now_dt
ts = now_iso()   # ISO string em America/Sao_Paulo
dt = now_dt()    # datetime com timezone
```
Nunca use `datetime.now()` diretamente.

### Leitura de JSONL
```python
def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows
```
Todo leitor de JSONL deve ignorar linhas inválidas sem explodir.

### Escrita de relatórios
```python
path.parent.mkdir(parents=True, exist_ok=True)
with path.open('w', encoding='utf-8') as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
```

### Logging
```python
import logging
logger = logging.getLogger(__name__)
# Nunca use print() exceto em scripts de CLI standalone
```

---

## 14. Como adicionar uma nova estratégia

**1.** Adicione um `StrategySpec` em `parallel_strategies.py`:
```python
StrategySpec(
    strategy_id="MINHA_ESTRATEGIA",
    side_mode="YES",          # "YES", "NO" ou "BOTH"
    min_price=0.10,
    max_price=0.40,
    preferred_low=0.10,
    preferred_high=0.25,
    max_entries_per_market=3,
    score_bias=6,
    notes="Descrição da lógica e inspiração.",
    min_hours_to_resolution=12.0,
    max_hours_to_resolution=48.0,
    required_min_distance_threshold=1.0,
    exclusive_cities=("Cidade1", "Cidade2"),
)
```

**2.** A estratégia é automaticamente:
- Incluída no `strategy_comparison_latest.json`
- Avaliada pelo `multi_strategy_engine.py` em cada ciclo
- Monitorada pelo `strategy_monitor.py` para TP/SL/Time

**3.** Não há step 3. O pipeline é agnóstico à estratégia.

**Nunca crie estado compartilhado entre estratégias.** Cada uma opera com bankroll, logs e relatórios isolados.

---

## 15. O que NUNCA fazer

### Na lógica de decisão
- **Nunca usar cache para aprovar entrada** — best_bid/ask/book devem ser frescos
- **Nunca entrar sem confirmar CLOB** — mesmo que o catálogo diga que o mercado é bom
- **Nunca ignorar a janela operacional** — mercados fora do range são descartados cedo
- **Nunca fazer heroísmo estatístico** — sem inventar sinal onde não há amostra mínima

### No código
- **Nunca usar `datetime.now()` sem timezone** — sempre `now_iso()` ou `now_dt()`
- **Nunca hardcodar valores que estão em `config.py`**
- **Nunca criar estado compartilhado entre estratégias**
- **Nunca propagar exceção de um ciclo sem capturar e salvar estado** — ver padrão em `app.py`
- **Nunca adicionar dependências externas** — o projeto usa só stdlib + requests (já presente)
- **Nunca alterar o pipeline base para acomodar uma estratégia específica** — o pipeline é agnóstico

### Na comparação de estratégias
- **Nunca declarar vencedora com menos de 200 decisões** — amostra pequena gera falso sinal
- **Nunca usar PnL pontual como critério único** — avaliar win rate, drawdown, profit factor e robustez

---

## 16. Fontes de dados externas

| Fonte | Uso | Pode cachear? |
|---|---|---|
| Gamma API (Polymarket) | Discovery de mercados | ✅ Metadados (TTL 45min) |
| CLOB API (Polymarket) | Preço e book | ❌ Nunca |
| Open-Meteo | Forecast de clima | ✅ Por cidade/data |
| Polymarket Data API | Wallet intelligence e copytrading | ✅ Snapshots periódicos |
| Open-Meteo Geocoding | Geocodificação | ✅ Por cidade |
| NWS / AlertsClient | Alertas meteorológicos | ⚠️ Stub pendente |

---

## 17. Limitações conhecidas

1. `AlertsClient` é stub — alertas reais não implementados
2. Forecast secundário ainda espelha o principal (segunda fonte independente pendente)
3. Ciclo completo pode ficar lento por chamadas externas (timeout configurado em `RUNTIME_CYCLE_TIMEOUT_SECONDS`)
4. Catálogo local reduz custo de discovery mas não resolve book ruim ou mercado sem liquidez

---

## 18. Automação (cron)

```bash
# app.py — scan principal + monitor de trades
*/5 * * * * cd /caminho/do/bot && python3 app.py >> data_runtime/logs/cron.log 2>&1

# copytrading_cycle.py — ciclo de copytrading
*/5 * * * * cd /caminho/do/bot && python3 copytrading_cycle.py >> data_runtime/logs/cron.log 2>&1

# strategy_comparison.py — relatório comparativo
*/5 * * * * cd /caminho/do/bot && python3 strategy_comparison.py >> data_runtime/logs/cron.log 2>&1
```

O `process_lock.py` garante que não haja dois ciclos rodando ao mesmo tempo.

---

## 19. Critério de promoção de estratégia

Uma estratégia pode ser promovida a regime principal **somente** após:
- ≥ 200 decisões elegíveis
- Avaliação de: retorno, win rate, drawdown, profit factor, volume de trades e robustez operacional
- Comparação contra as outras estratégias **no mesmo período**

Não escolha vencedora cedo com base em narrativa ou PnL pontual.
