# O painel de Follow-up diz onde o lead está

**Data:** 2026-09-29
**Branch:** `feat/painel-toque-funil`, a partir de `origin/master` (`bac70c53`)

## 1. O que a tela mostra hoje, e o que está errado

A tabela de jobs da aba Follow-up tem seis colunas:
`Lead · Toque · Objetivo · Situação · Quando (BRT) · Ação`.

Para os jobs do João, duas delas estão quebradas:

**A coluna "Toque" mostra a CHAVE CRUA.** `touchTypeLabel` resolve o rótulo por
`JOB_TYPE_LABELS`, e esse mapa não tem nenhuma entrada para os cinco `job_type` do João
(`joao_novo`, `joao_em_conversa`, `joao_proposta`, `joao_reposicao`, `joao_em_atencao`).
Cai no fallback `?? jt` e a tela escreve literalmente `joao_novo`. É a mesma classe de
vazamento de chave que a entrega de 21/09 eliminou do editor de cadências e que voltou
pela porta da tabela.

Pior: o NÚMERO DO TOQUE some. `touchTypeLabel` só devolve `T<seq>` para `standard`/null.
Num job do João o operador não distingue o 1º toque do 4º — que é exatamente a pergunta
que se faz olhando essa lista.

**A coluna "Objetivo" fica vazia.** `metadata.objetivo` é campo da cadência da ValerIA;
job do João nunca o tem. A coluna existe e não diz nada.

E não há nenhuma informação de FUNIL nem de ETAPA, embora as duas sejam o contexto que
torna a linha compreensível: "Marcella, 2º toque" não significa nada sem saber que é o
funil Atacado, etapa Novo.

## 2. O dado já existe — isto é exposição, não coleta

`_montar_jobs_da_matricula` grava no `metadata` de todo job do João:
`cadencia`, `funil`, `toque`, `deal_id`, `pipeline_id`, `stage_id`, `matricula_id`, e
`acao` no job de mover. A rota `GET /api/followups` **já faz `select` do `metadata`
inteiro** — ela só não repassa esses campos, extraindo apenas `objetivo`.

Os RÓTULOS legíveis também já existem: `GET /api/cadence/definition` devolve
`joao.funis[].rotulo` ("João - Atacado"), `cadencias[].rotulo` ("Novo") e
`gatilho_stage_rotulo` ("Cliente Ativo"). E `FollowupBoard` **já carrega essa definição**
no mesmo componente que renderiza a tabela — não há prop drilling a fazer.

Consequência de projeto: **nenhum rótulo é escrito à mão no frontend.** A tradução
código → rótulo sai da definição. Um mapa hardcoded no componente recriaria a divergência
que esta base já pagou três vezes este mês.

## 3. As quatro mudanças

### 3.1 A coluna "Toque" passa a dizer esteira + número

De `joao_novo` para **"Novo · 2º toque"**. A esteira vem do rótulo da cadência na
definição; o número vem de `metadata.toque` (com `sequence` como reserva).

Para os job types que já tinham rótulo (`handoff_rescue`, `lp_welcome`,
`ai_reengage`, `ai_scheduled_return`) e para o `standard` da ValerIA, **nada muda**.

### 3.2 O job de mover não é toque

A matrícula cria um job a mais, marcado `metadata.acao == "mover_etapa"`, que move o card
em vez de enviar mensagem. Ele tem `sequence` = último toque + 1, então sem tratamento
apareceria como "5º toque" — uma mensagem que nunca existiu. Aparece como
**"move o card"**.

### 3.3 Coluna nova: "Funil / Etapa"

Duas linhas na mesma célula: o rótulo do funil em cima ("João - Atacado"), a etapa do
card embaixo. Jobs que não são do João mostram um traço — a ValerIA não tem funil.

### 3.4 A etapa é a ATUAL do card, não a da matrícula

`metadata.stage_id` guarda a etapa de quando o lead foi matriculado. Mostrar aquilo seria
mostrar o passado: desde 25/09 um card que muda de coluna **cancela** a esteira, então a
diferença entre as duas leituras é justamente a informação que o operador precisa.

Com a etapa atual, uma linha "pendente" cujo card já saiu da etapa fica visível — e o
operador entende, olhando, por que aquele job vai morrer em vez de enviar.

Custo: uma consulta a mais, EM LOTE, sobre os `deal_id` da página (no máximo 200 jobs),
mais a resolução do rótulo da etapa. Nunca uma consulta por job.

Falha na consulta é **fail-soft**: a coluna mostra o funil e um traço na etapa. Um painel
de observação não pode quebrar por causa de um enfeite.

## 4. Onde cada mudança mora

| Arquivo | O quê |
|---|---|
| `frontend/src/lib/followup-board.ts` | os campos novos em `BoardJob`; `touchTypeLabel` passa a receber os rótulos e a tratar o job de mover |
| `frontend/src/app/api/followups/route.ts` | expõe `cadencia`, `funil`, `toque`, `acao`, `deal_id`; consulta em lote a etapa atual |
| `frontend/src/components/campaigns/followup-board.tsx` | a coluna nova e o uso da definição para traduzir códigos |

## 5. O que NÃO muda

- O motor de follow-up, em nenhuma linha. Isto é tela.
- As colunas `Situação`, `Quando (BRT)` e `Ação`, e o cancelamento por linha.
- O rótulo dos jobs da ValerIA e dos outros quatro `job_type` especializados.
- A coluna `Objetivo` continua existindo para a ValerIA, que a preenche de verdade.

## 6. Testes

- `touchTypeLabel`: job do João devolve "Novo · 2º toque" e **nunca** a chave crua;
  `standard` continua "T3"; `handoff_rescue` continua "Resgate de handoff"; job com
  `acao=mover_etapa` devolve "move o card" e não um número de toque.
  **Mutação obrigatória:** devolver a chave crua e exigir vermelho.
- Rota: os campos novos aparecem no payload; a etapa atual vem do `deals`, não do
  `metadata.stage_id` (plante os dois diferentes e prove qual vence); a consulta da etapa
  é UMA para a página inteira; falha nela não derruba a resposta.
- Tela: a coluna mostra funil e etapa para job do João e traço para job da ValerIA;
  nenhum rótulo hardcoded (mutação: trocar o rótulo na definição e provar que a tela
  acompanha).
