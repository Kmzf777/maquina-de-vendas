# Janela de 24h no espelho da cadência + inspetor com body real do template

## Diagnóstico (auditoria antes do código)

RUNTIME NÃO VIOLA a janela de 24h da Meta em nenhum motor: o follow-up checa a janela
no fire-time de CADA toque (fechada → template de reabertura; Rodadas 3–5) e o
automation engine bloqueia `send_text` com janela fechada
(`engine.py:_execute_send_text` → `last_error="24h_window_expired"`, sem envio). O
defeito real é REPRESENTACIONAL: o grafo-espelho mostrava T3/T4 como texto livre após
waits de 2/4 dias sem a guarda visível — tecnicamente impossível de ler como correto.
Segundo defeito, de UI: o inspetor não distingue com força Template × Texto Livre e
não mostra o corpo real do template selecionado (o `body` JÁ chega ao builder via
/api/templates → parseTemplateComponents).

## Correções

### 1. Espelho (backend/app/campaigns/system_cadence.py)
Topologia nova: TODO toque livre é precedido da SUA checagem de janela —
`trigger → cond_t1 ─SIM→ T1 → wait D+1 → cond_t2 ─SIM→ T2 → wait +2d → cond_t3 ─SIM→
T3 → wait +4d → cond_t4 ─SIM→ T4 → end_concluída`, e TODOS os ramos NÃO convergem no
nó único `send` do template de reabertura → `end_aguardando (R1)`. 15 nós. As
condições usam `replied_recently days=1` (semântica: janela aberta). Textos dos
toques anotam a regra. Testes novos fixam o INVARIANTE: nenhum `send_text` sem uma
condição de janela apontando para ele via `yes_node_id`; o nó de reabertura recebe os
4 ramos NÃO.

### 2. Regressão de motor (backend/tests)
Teste pinando a guarda existente do automation engine: `_execute_send_text` com
`last_customer_message_at` > 24h → provider NÃO é chamado e o enrollment recebe
`last_error="24h_window_expired"`. (Sem mudança de comportamento — só trava contra
regressão futura.)

### 3. Inspetor (frontend)
- Cartão-resumo ganha CHIP DE TIPO: `send` → "TEMPLATE APROVADO · permitido com
  janela fechada" (laranja); `send_text` → "TEXTO LIVRE · exige janela de 24h aberta"
  (teal). Demais tipos sem chip.
- Nós `send`: novo bloco "Texto real do template" renderizando
  `selectedTemplate.body` com as variáveis configuradas substituídas — helper puro
  `renderTemplateBody(body, variables, paramsType)` ({{n}} posicional, {{nome}}
  nomeado; placeholder mantido quando não preenchido) + aviso quando o template não
  está sincronizado no catálogo local.
- `describeNode`: sentenças de send/send_text passam a citar a regra da janela.

## Testes
pytest: invariantes novos do grafo + regressão da guarda do engine; suíte completa.
vitest: `renderTemplateBody` + updates do describe-node; suíte completa + type-check
+ build. Smoke pós-deploy: grafo re-sincronizado em prod com 15 nós/4 condições.
