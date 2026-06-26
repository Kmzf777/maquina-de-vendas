# Design — Roteamento Inbound/Outbound, Contexto de Abordagem, Janela 24h e Inteligência de Vendas

- **Data:** 2026-06-26
- **Autor:** Arquitetura / Produto (`maquina-de-vendas`)
- **Origem:** Relatório forense dos 4 casos de 26/06/2026 (Walter, Helio, Paulo, Pedro)
- **Status:** Design estratégico (sem código de produção, sem commit nesta fase)

## Decisões de produto (tomadas)

| Eixo | Decisão |
|---|---|
| 1 — Roteamento | **Persona dinâmica**: o 1º inbound orgânico promove a conversa para `valeria_inbound`; outbound só persiste enquanto não houve resposta real a um disparo frio. A persona outbound **morre após o 1º turno reativo** e passa o controle para inbound. |
| 3 — Janela fechada | **Template + retomada da IA**: fora da janela, dispara `continuar_conversa` (template padrão confirmado) e retoma o contexto agendado quando o lead responde. Nada é descartado em silêncio. |
| 4 — Vendas | **Módulo compartilhado em `base.py`**: descoberta de porte + unit economics antes de cravar preço/pedido mínimo. |

## Mitigações de risco arquitetural (revisão aprovada 2026-06-26)

| Risco | Mitigação |
|---|---|
| **Contexto Zumbi na retomada (Eixo 3B)** — lead responde meses depois e a IA usa um `<retorno_agendado>` velho, parecendo doida | **TTL de 7 dias** no estado `awaiting_reopen`. Passado o TTL, descartar o contexto pendente (job → `expired`) e tratar a resposta como inbound orgânico normal. |
| **Colisão com intervenção humana (Eixo 1)** — vendedor já respondeu, mas a heurística ainda trata como cold-open não respondido | O gatilho de recuperação fria exige `sent_by != 'human'` em toda a conversa. **Qualquer** mensagem `sent_by == 'human'` invalida a persona outbound → cai para inbound. |
| **Aceleração do SPIN (Eixo 4)** — o Gemini dispara as 4 perguntas de uma vez por "ansiedade" | Forçar um `<scratchpad>` de raciocínio: a IA DECLARA o "estágio atual de descoberta" (situação/problema/implicação/need-payoff) antes de gerar a pergunta, travando 1 pergunta por turno. O scratchpad é interno e nunca vai ao cliente. |

---

## Princípio unificador

A raiz comum dos 4 casos é que o funil de Landing Page / terceirização rotula leads **quentes** como alvos de **recuperação fria** (`valeria_outbound`) e o pipeline inteiro (resolução de persona, contexto de 1º turno, frameworks de sondagem) não distingue *lead que veio até nós* de *reativação de base fria*. O design ataca isso em quatro camadas isoladas e independentemente testáveis:

1. **Resolução de persona em runtime** (substitui o pin estático).
2. **Registro de intenção de template** (frio vs. quente) — fonte de verdade compartilhada entre persona e contexto.
3. **Idempotência de tool + fallback de janela** no agendamento de retorno.
4. **Bloco de descoberta/SPIN** compartilhado no prompt base.

---

## Eixo 1 — Roteamento Inbound vs Outbound

### Problema (evidência)
- `lp_webhook/service.py:33` → `LP_PROFILE_PROMPT_KEY = "valeria_outbound"`; cria a conversa pinada em outbound (`service.py:202-204`).
- `buffer/processor.py:268-282` (`_resolve_agent_profile_id`): prioriza cegamente `conversation.agent_profile_id` sobre o default do canal (`valeria_inbound`). O inbound (`meta_router.py`) nunca reavalia persona.
- `conversations/service.py:34`: conversa existente é retornada **sem** sobrescrever o perfil → o pin frio é permanente.

### Solução: `resolve_persona()` em runtime (núcleo durável)

Criar uma função pura `resolve_persona(conversation, channel, lead, last_dispatch, has_organic_inbound) -> prompt_key`, chamada pelo `processor.py` no lugar do atual `_resolve_agent_profile_id` cego. Regra de decisão:

```
1. Existe disparo FRIO de saída (broadcast/followup com template de intenção
   'cold_reactivation') ainda NÃO respondido pelo lead
   E nenhuma mensagem sent_by == 'human' na conversa?
      → valeria_outbound   (governa só a 1ª reação ao cold-open)
2. Caso contrário (lead respondeu, OU msg orgânica, OU disparo quente de LP,
   OU humano já interveio)
      → valeria_inbound
3. Sem sinais → default do canal (valeria_inbound)
```

- **"Disparo frio não respondido"** = última mensagem assistant é `sent_by ∈ (broadcast, followup)` com template classificado como `cold_reactivation` **e** não há mensagem `user` posterior **e** não há nenhuma mensagem `sent_by == 'human'` na conversa. Isso preserva o frame de recuperação só para o broadcast frio genuíno e nunca atropela uma intervenção humana (mitigação de colisão humana).
- **Morte da persona outbound:** assim que existe a 1ª resposta real do lead, o disparo frio está "respondido" → o próximo turno já resolve para `valeria_inbound`. A persona outbound governa exclusivamente o primeiro turno reativo.
- Leads de LP (disparo quente `warm_lp`) caem direto em `valeria_inbound`.
- Como a decisão é **recomputada por turno**, leads já pinados em outbound (como os 4 casos) são corrigidos automaticamente sem migração de dados.

### Mudanças de criação (defesa em profundidade)
- `lp_webhook/service.py`: passar a criar a conversa como **warm** (não pinar outbound). A persona efetiva continua decidida em runtime, mas a criação deixa de mentir.
- `conversations/service.py`: manter o comportamento de não sobrescrever conversa existente (correto), já que o runtime resolve.

### Isolamento / testes
- `resolve_persona()` é função pura: entradas explícitas, sem I/O → testável com tabela de cenários (cold-open não respondido, cold-open respondido, LP quente, inbound orgânico puro, conversa antiga pinada).
- Substitui a heurística embutida no processor por um boundary nomeado.

---

## Eixo 2 — UX de Placeholder e Primeira Abordagem

### Problema (evidência)
- `follow_up/scheduler.py:822-827`: persiste em `messages.content` a string crua `"olá {nome}\n\n[disparo automático — template {template}]"`. O template real foi enviado corretamente por WhatsApp; a string é só representação de CRM — **mas** ela polui o histórico do LLM.
- `orchestrator.py:497-505`: o 1º turno outbound usa a última msg `broadcast/followup` como `campaign_message` → captura o placeholder inútil.
- `valeria_outbound/context.py:16-19`: **hardcoda** que toda abertura é "estamos atualizando nossos registros de cadastro / falo com {nome}?" — frame frio, cego à intenção quente da LP.

### Solução

**(a) Limpar o que é persistido como conteúdo.**
- Renderizar o **corpo real do template aprovado** (substituindo `{{primeiro_nome}}`, resolvido de `message_templates.components`) e gravar isso como `messages.content`. CRM e LLM passam a ver texto real.
- Gravar metadados de máquina em `messages.metadata.dispatch = { template, intent, params }`. A intenção vem do **Registro de Intenção de Template** (abaixo).
- Remover o literal `[disparo automático — template ...]` do `content`.

**(b) `campaign_message` à prova de placeholder.**
- O orchestrator passa a ler o disparo de `metadata.dispatch` (corpo renderizado), nunca o label cru. Se ausente, faz fallback para `content` já limpo.

**(c) `context.py` ciente de intenção.**
- `build_outbound_first_turn_context(..., template_intent, lp_message=None)`:
  - `cold_reactivation` → mantém o frame atual ("confirmar cadastro/contato", pivotar para valor).
  - `warm_lp` → novo frame: *"o lead PEDIU informações na nossa landing page e recebeu uma confirmação; ele está QUENTE; retome exatamente a solicitação dele"*, injetando `lead.metadata.lp_message` (ex.: "Walter preciso de informação sobre comprar café cru para exportação").
- Com o Eixo 1, leads quentes de LP nem chegam ao contexto outbound (vão para inbound). Esta correção é **defesa em profundidade** + cobre disparos quentes futuros que ainda usem o caminho outbound.

### Registro de Intenção de Template (módulo compartilhado novo)
- Pequeno mapa `template_intent(name) -> {cold_reactivation | warm_lp | quote_followup | ...}`, derivado por prefixo/convensão (`lp_*` = warm_lp; `atualizacao_*`, `reativ*`, `continuar_*` = cold_reactivation; etc.).
- **Fonte única de verdade** consumida por: `resolve_persona()` (Eixo 1), persistência do disparo (Eixo 2a), `context.py` (Eixo 2c).

---

## Eixo 3 — Loop de Tool e Janela Fechada

### Problema (evidência)
- `agendar_retorno` (`tools.py:1114+`) não tem guarda no nível do LLM: cada despedida ("obrigado", "combinado") re-disparou a tool (Walter: 3× em ~1,5h) e re-confirmou ao lead.
- `scheduler.py:_process_ai_scheduled_return` (1016+): janela ABERTA → texto livre; janela FECHADA → `_cancel_job("window_expired")` (1072-1075). **Sem fallback de template** → o retorno de segunda do Walter seria descartado em silêncio.

### Solução A — Idempotência da tool
- Em `_agendar_retorno`, antes de inserir: buscar `ai_scheduled_return` `pending` para a conversa.
  - Se existir: **atualizar** (reschedule) em vez de criar outro, e retornar um tool-result idempotente: *"Você JÁ tem um retorno agendado para {quando}. Apenas confirme ao lead, NÃO agende de novo."*
- Regra de prompt (base.py): *"Se você já agendou um retorno nesta conversa, NÃO chame `agendar_retorno` novamente; apenas confirme com o lead."*
- Efeito: o LLM para de chamar/re-confirmar em loop; DB mantém um único job vivo.

### Solução B — Fallback de janela fechada (template + retomada)
Reescrever o ramo "janela fechada" de `_process_ai_scheduled_return`:

```
janela fechada →
  1. dispara template utility APROVADO de retomada
       (candidatos reais aprovados: retorno_de_solicitacao, continuar_conversa,
        continuidade_cotacao_pendente — usar param nomeado {{primeiro_nome}})
  2. status do job → 'awaiting_reopen' (novo estado), preservando motivo+contexto
  3. persiste o disparo em messages (corpo renderizado, Eixo 2a)
```

**Gancho de retomada (reopen):**
- Quando um inbound chega e existe job `awaiting_reopen` para a conversa **dentro do TTL de 7 dias** (medido a partir de `fire_at`/`sent_at` do disparo de reabertura), injetar `motivo`+`contexto` salvos no contexto do agente (bloco `<retorno_agendado>` no prompt do turno) e marcar o job `sent`. A IA retoma de onde parou, com a janela reaberta pela resposta do lead.
- **TTL / Contexto Zumbi:** se a resposta do lead chega **após 7 dias** do disparo de reabertura, o contexto é considerado obsoleto: marcar o job `expired`, **não** injetar `<retorno_agendado>`, e tratar a mensagem como inbound orgânico normal. Evita a IA retomar um assunto de meses atrás.

**Tratamento de falha do template:**
- `send_template` com erro permanente (4xx / RuntimeError de rejeição Meta) → cancelar com razão logada (`reopen_template_rejected`) e disparar `system_alert` para o vendedor (degradação graciosa; não é silêncio). Mantém a decisão B1 (template+IA) com rede de segurança mínima.
- Respeitar as lições de memória: param **nomeado** `{{primeiro_nome}}` e `language_code` casando com o aprovado (evita o loop de rejeição histórico).

### Isolamento / testes
- Idempotência: teste com 2 chamadas seguidas → 1 job, 2º retorno é a mensagem idempotente.
- Fallback: teste janela fechada → template disparado + status `awaiting_reopen`; inbound subsequente → contexto retomado + job `sent`.

---

## Eixo 4 — Inteligência de Vendas (Descoberta + Unit Economics)

### Problema (evidência — caso Helio)
- Lead iniciante ("ainda não tenho nem o café"); a IA cravou lote mínimo de 100 un (~R$2.670 de entrada) sem dimensionar o porte. À objeção de **margem** ("fica salgado para revenda"), aplicou o turnaround genérico (regra 29) e **re-cotou −R$1,00**.
- O framework só tem sondagem de dor para objeção de **concorrência** (regra 30: "já tenho fornecedor"). Não há play para **margem** nem para **lead iniciante**.

### Solução — Bloco compartilhado em `base.py`: "DESCOBERTA ANTES DE PREÇO"

Inserir um bloco universal (inbound + outbound), acionado **antes** de apresentar lote mínimo / preço nos stages comerciais:

1. **Dimensionar o porte (gate anti-cotação-precoce).** Antes de cravar pedido mínimo, descobrir: iniciante vs. ativo, canal pretendido (convívio/pequeno comércio vs. estabelecido), volume-alvo. Estende a regra 21 (anti-premissa) com "dimensionar antes de cotar".
2. **SPIN-lite explícito com `<scratchpad>` obrigatório.** Situação (o que faz / estágio) → Problema (barreira real) → Implicação (custo da barreira) → Need-payoff (como nossa oferta encaixa na economia dele). Uma pergunta por turno (respeita regra 1 e a Regra do Silêncio). **Anti-aceleração:** antes de gerar a pergunta, a IA DECLARA num `<scratchpad>` interno o estágio atual de descoberta e a ÚNICA próxima pergunta; o scratchpad é 100% interno (nunca vai ao cliente) e trava o disparo das 4 perguntas de uma vez.
3. **Play de objeção de margem (novo).** Quando o lead disser que preço/mínimo inviabiliza a revenda: **NÃO re-cotar**. Fazer a conta da revenda *com* o lead (preço de venda alvo, margem) e:
   - se a barreira real é o mínimo de 100 un → apresentar o menor caminho viável **ou** escalar para o João um arranjo de entrada (`encaminhar_humano`), nunca abandonar com `registrar_sem_interesse_atual` na 1ª objeção (alinha regra 29/30b).
4. **Tag de objeção** (já existe regra 28: "Objeção: Preço") aplicada no gatilho.

### Harmonização obrigatória (contradição detectada)
- `valeria_outbound/private_label.py:29-33` instrui multiplicar preço×qtd na mão ("NUNCA diga que não sabe calcular") — conflita com `base.py:478-479` (proíbe cálculo de cabeça; exige `calcular_orcamento`).
- `private_label` **não tem** `calcular_orcamento` em `get_tools_for_stage` (`tools.py:514`).
- **Decisão de design:** remover a instrução de cálculo manual do `private_label.py` e **adicionar `calcular_orcamento` ao stage `private_label`**, roteando todo cálculo pela tool. Unifica a regra de preço e remove a fonte de erro de arredondamento.

### Isolamento / testes
- Bloco de prompt coberto por testes de prompt (padrão `test_base_prompt.py` / `test_outbound_*`): asserts de presença das diretrizes e cenários de objeção de margem.
- Harmonização de cálculo: teste de que `private_label` expõe `calcular_orcamento` e que o prompt não instrui multiplicação manual.

---

## Ordem de implementação sugerida (incremental, baixo risco → alto valor)

1. **Registro de Intenção de Template** (módulo isolado, sem efeito colateral) — base para 1 e 2.
2. **Eixo 2a/2b** — limpar persistência do disparo + `campaign_message` por metadata.
3. **Eixo 1** — `resolve_persona()` em runtime + criação warm no LP. (Maior impacto nos 4 casos.)
4. **Eixo 2c** — `context.py` ciente de intenção.
5. **Eixo 3A** — idempotência de `agendar_retorno`.
6. **Eixo 3B** — fallback de janela + gancho de retomada.
7. **Eixo 4** — bloco de descoberta/SPIN + harmonização `calcular_orcamento`.

Cada item é um incremento testável e isolado; 1–4 resolvem roteamento/contexto (casos 3 e 4 e o frame frio do caso 2), 5–6 resolvem o caso 1, 7 resolve o déficit comercial do caso 2.

## Fora de escopo (registrado, não endereçado aqui)
- Advisory crítico do Supabase prod: **RLS desabilitado** em 29 tabelas. Decisão de segurança separada (habilitar RLS sem políticas bloqueia acesso).
- Paridade de 9º dígito `phone` vs `wa_id` (já coberta por memória/feature existente).
