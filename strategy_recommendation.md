# Strategy Recommendation - Weather Bot

## Objetivo
Rodar 3 estratégias de paper trading em paralelo e comparar desempenho antes de promover uma para regime principal.

## Estratégias

### 1. NO_EXTREME
- Lado preferencial: NO
- Faixa operacional: 0.95-0.999
- Faixa preferida: 0.98-0.995
- Entradas máximas por mercado: 2
- Perfil: alta probabilidade, maior convicção, menos parcelamento

### 2. YES_CONVEX
- Lado preferencial: YES
- Faixa operacional: 0.01-0.50
- Faixa preferida: 0.01-0.25
- Entradas máximas por mercado: 4
- Perfil: payoff convexo, mais escala, maior variância

### 3. MID_RANGE_BALANCED
- Lado preferencial: BOTH
- Faixa operacional: 0.30-0.90
- Faixa preferida: 0.55-0.70
- Entradas máximas por mercado: 10
- Janela de resolução: 4h-72h
- Cidades: todas liberadas
- Take profit: 10%
- Sem saída por tempo, fica até TP, SL ou resolução
- Perfil: oportunista, contextual, menos extremo

## Critério de comparação
Avaliar cada estratégia por:
- PnL absoluto
- ROI
- Win rate
- Drawdown máximo
- Profit factor
- Quantidade de trades executados
- Exposição média
- Concentração por mercado/evento
- Robustez operacional

## Critério mínimo antes de escolher vencedora
- Pelo menos 200 decisões elegíveis por estratégia
- Ou janela temporal equivalente com número suficiente de trades executados

## Recomendação operacional
Não escolher vencedora só por PnL bruto. A vencedora deve equilibrar retorno, estabilidade e capacidade de execução em mercados reais.
