---
title: Redesign do Resumo de Qualificação no Handoff
date: 2026-06-11
status: approved
---

## Contexto

Quando a Valéria qualifica um lead e chama `encaminhar_humano`, o backend gera um resumo automático
via LLM e o salva em `lead_notes` + `lead.metadata.handoff_summary`. O formato atual é genérico
(7 campos simples). O João precisa de um briefing mais rico para abordar o lead com contexto real.

## Objetivo

Substituir o formato do resumo de qualificação pelo template "NOVO LEAD QUALIFICADO PELA VALÉRIA",
com 8 campos que cobrem aquecimento, dor, orçamento, tom e recomendação de abordagem.

## Escopo

- **Afeta:** todos os handoffs (inbound + outbound, todos os stages).
- **Entrega:** somente CRM (lead_notes + lead.metadata.handoff_summary). Sem WhatsApp, sem schema novo.
- **Arquivos alterados:** apenas dois ficheiros Python no backend.

## Design

### Abordagem escolhida: Prompt novo + contexto enriquecido

Em vez de trocar só o prompt, passamos também o `motivo` capturado do `encaminhar_humano` e o
timestamp do handoff como contexto extra. Isso melhora diretamente os campos de aquecimento e
recomendação, sem adicionar complexidade de parsing ou chamadas extras.

### Novo template de saída

```
## NOVO LEAD QUALIFICADO PELA VALÉRIA
**Data/Hora:** {handoff_at}

* **Nome do Lead:** [nome ou "Não informado na triagem"]
* **Interesse Principal:** [categoria + descrição detalhada]
* **Nível de Aquecimento:** [Alto / Médio / Baixo + motivo objetivo]
* **Cenário Atual / Dor:** [situação do lead e problema que deseja resolver]
* **Expectativa de Volume/Orçamento:** [valores, pedido mínimo ou "Não informado na triagem"]
* **Tom da Conversa:** [comportamento e atitude do lead]
* **Recomendação de Abordagem para o João:** [como iniciar o contato com base no histórico]
```

Campos sem informação → `"Não informado na triagem"` (nunca inventar dados).

### Mudanças de código

#### `backend/app/agent/summary.py`

1. Substituir `_SUMMARY_SYSTEM_PROMPT` pelo novo prompt que instrui o LLM a gerar exatamente
   o template acima.
2. Adicionar parâmetros `motivo: str = ""` e `handoff_at: str = ""` em
   `generate_qualification_summary`.
3. Injetar `motivo` e `handoff_at` na string de contexto passada ao LLM.

#### `backend/app/agent/tools.py`

Na chamada a `generate_qualification_summary` dentro de `encaminhar_humano` (linha ~273):
- Capturar `motivo` dos args da tool (já disponível na variável local).
- Capturar `handoff_at` via `datetime.now(TZ_BR).strftime("%d/%m/%Y %H:%M")`.
- Passar ambos como kwargs à função.

### O que NÃO muda

- Mecanismo de entrega (salvar em `lead_notes` + `lead.metadata.handoff_summary`).
- Schema do banco de dados.
- Frontend.
- Fluxo de `handoff_rescue` e WhatsApp ao lead.
- Assinatura pública da função (parâmetros novos têm default, não quebram chamadores existentes).

## Critérios de aceitação

1. Após um handoff, o `lead_notes` gerado contém o cabeçalho `## NOVO LEAD QUALIFICADO PELA VALÉRIA`.
2. Todos os 8 campos aparecem no resumo; campos sem dado mostram "Não informado na triagem".
3. O `motivo` do handoff (ex: "circuit breaker", "lead com intenção de compra") influencia o
   campo "Nível de Aquecimento".
4. O `handoff_at` reflete a data/hora correta (fuso BRT −3h).
5. Testes unitários de `generate_qualification_summary` com histórico vazio e histórico completo
   continuam passando (ou são atualizados para o novo formato).
