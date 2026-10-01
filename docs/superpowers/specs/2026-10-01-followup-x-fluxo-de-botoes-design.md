# Follow-up × fluxo de botões — um lead, dois motores

**Data:** 2026-10-01
**Branch:** `fix/followup-x-botoes` (de `origin/master`)
**Contexto:** [[project_valeria_botoes]] entrou em produção em 30/09 (`0b420e63`) e o canal
`553492009777` (NUMERO VALERIA) foi apontado para o perfil `cff8c3e7`
(`kind=button_flow`, `flow_id=valeria_botoes_v1`) em 01/10 02:47.

---

## 1. O problema, medido

O motor de follow-up decide por **`ai_enabled`** e por canal humano. Ele **não sabe que
fluxos de botões existem**: `grep -rn "button_flow\|flow_state\|fluxo_da_conversa"
backend/app/follow_up/` devolve vazio.

E o fluxo de botões deixa `ai_enabled = True` na maior parte dos estados:

| Estado do lead | `ai_enabled` | Follow-up dispara? |
|---|---|---|
| **Parou no meio da árvore** (N1…N5, P1…P4, E1…E4) | `True` | **Sim** |
| `T_ADIAR` / `T_ADIADO` | `True` | **Sim** |
| `T_FIM` (consumo sem clique) | `True` | **Sim** |
| `T_HANDOFF` / `_PL` / `_ARTHUR` | `False` | Não |
| `T_HUMANO`, `T_OPTOUT` | `False` | Não |

`follow_up_jobs` tem **694 jobs pendentes** em produção, com `ai_reengage` e
`ai_scheduled_return` entre os tipos — o motor está rodando e não tem kill switch.

### A sequência que quebra

1. Lead toca **"Pro meu negócio"**, recebe *"que tipo de negócio você tem?"* com 3 botões.
2. Some. `ai_enabled` continua `True`, nada o silenciou.
3. O `ai_reengage` dispara uma mensagem **gerada por LLM** (persona `valeria_outbound`,
   `AI_REENGAGE_PROFILE_ID`).
4. Se o lead responder, a resposta cai no **motor de botões** (o canal aponta para lá) como
   texto livre → nudge pedindo que ele toque num botão que a conversa já passou.

Três custos: **"zero IA" deixa de ser verdade**; paga-se token de LLM **mais** mensagem
faturada da Meta; e o lead conversou com dois agentes que não se conhecem.

Pior caso: `T_ADIADO` acabou de prometer *"combinado, em 60 dias, te chamo nessa época"* e o
follow-up pode reengajar antes — quebrando a promessa na cara do lead.

### Causa raiz

Eu desenhei o fluxo de botões como se ele fosse a única coisa falando com o lead. Não é.
Há um segundo motor, já em produção, que decide por um campo (`ai_enabled`) que o fluxo novo
deixa ligado de propósito — porque desligar a IA num lead que está **no meio** da árvore
seria errado pelos outros motivos (ele não foi transbordado nem recusou nada).

---

## 2. O que NÃO está em escopo, e por quê

### 2.1 O recontato prometido não tem worker — e exige decisão sua

`effects._agendar_recontato` (`effects.py:455`) **não cria job**. Grava
`leads.metadata.recontatar_em` e move o card para a etapa de recontato. O comentário na
linha 471 diz, textualmente, que *"o worker de re-disparo (fase 2 da spec) vai ler
`metadata.recontatar_em`"* — **a fase 2 nunca foi construída**, nem para a Recuperação.

Então "Em 60 dias" grava a data, move o card, e **ninguém chama**.

Não construí porque a solução não é mecânica: **60 dias depois a janela de 24h está
fechada**, logo o recontato só pode sair por **template aprovado pela Meta**. Isso implica
criar template, submeter, esperar aprovação (e a janela de 1 edição a cada 24h), e pagar por
mensagem — US$ 0,0069 em utility, US$ 0,0625 em marketing, 9,1x de diferença medida nesta
conta. Qual categoria, qual texto e se vale o custo é decisão de negócio.

**Efeito colateral favorável:** como o fluxo não usa `ai_scheduled_return`, bloquear aquele
tipo de job (§3) não quebra nada que funcione hoje.

### 2.2 Número do Arthur

`EXPORTACAO_PHONE = "553432262600"` (do `+55 34 3226-2600` que o dono informou em resposta
direta). Produção tem um canal **"NUMERO ARTHUR" = `553491553110`** (móvel). Não altero:
sobrepor instrução explícita do dono por inferência minha é pior do que o erro possível.
Pendente de uma palavra dele.

### 2.3 Ordem das guardas do opt-out

O handoff formal engole um "pare" posterior (`runner._motivo_para_nao_rodar` retorna em
`human_control is True` antes de o evento ser construído). Eu declarei que precisaria de
autorização explícita para mexer, porque altera o comportamento da Recuperação em produção, e
ela não foi dada. Segue fixado em
`test_o_que_a_guarda_de_encerramento_NAO_alcanca_no_transbordo_formal`.

---

## 3. A solução

### 3.1 A costura: `_lead_stop_reason` + `_stop_reason_applies`

`scheduler.py:959` já é o **backstop único de 6 caminhos de envio**, e `:1024` já separa "este
lead está marcado para parar?" de "esse motivo cancela ESTE job?". É exatamente a forma que
este problema pede, e já carrega a nuance por tipo de job.

Mudança mínima:

- **Novo motivo `"fluxo_de_botoes"`** em `_lead_stop_reason`.
- `_lead_stop_reason` passa a aceitar `conversation` e `channel` **opcionais** (default
  `None`), porque `runner.fluxo_da_conversa(conversation, channel)` precisa dos dois. Sem
  eles o motivo nunca dispara — fail-open, igual ao resto da função.
- **Há UM call site** (`scheduler.py:687`, dentro de `process_due_followups`). O docstring
  diz "backstop único de 6 caminhos" porque aquele laço despacha os 6 tipos de job — não
  porque haja 6 chamadas. Um ponto de inserção, não seis.
- Naquele ponto **não há** `channel` nem `conversation` resolvidos (o guard de canal humano
  vem depois, em `:765`). Mas `get_due_followups` (`service.py:731`) **já faz join** de
  `channels!inner` e `conversations!inner` — só não seleciona as colunas do perfil. Alargar
  o select resolve com **zero consulta extra por job**:
  `conversations!inner(..., agent_profile_id)` e
  `channels!inner(..., agent_profile_id, agent_profiles(kind, flow_id))`.
  O padrão de trazer o perfil aninhado já existe em `channels/service.py` (`*, agent_profiles(*)`).
- `fluxo_da_conversa` segue **inalterada**: ela resolve o perfil da conversa por
  `get_agent_profile` com cache de 300s, então mesmo o caminho que vai ao banco custa ~1
  consulta por perfil a cada 5 minutos. Reusar sem tocar mantém um dono só da regra.

**Ordem dentro de `_lead_stop_reason`:** depois de `opt_out`/`wrong_number`, **depois de
`is_lead_blacklisted`**, e **antes** de `ai_disabled`.

Contra `ai_disabled`, o motivo é analytics: um lead em fluxo de botões costuma ter
`ai_enabled=False` junto (handoff e `T_HUMANO` desligam), e gravar `"ai_disabled"` perderia a
informação que importa — o lead não parou, está sendo atendido por outro motor.

> **Corrigido na execução, 01/10.** Esta seção mandava pôr a checagem **antes** de
> `is_lead_blacklisted`, para economizar aquela consulta. **Estava errado**, e o próprio
> comentário do `is_lead_blacklisted` (`scheduler.py:1004-1010`) contém o argumento: a
> blacklist precede o `ai_disabled` porque `ai_disabled` é o único motivo com isenção, e
> checá-la depois devolveria `ai_disabled` — fazendo o resgate isento disparar template para
> quem está na Blacklist.
>
> `fluxo_de_botoes` tem **duas** isenções, e a de `lp_welcome` é pior que o bug original: um
> lead na blacklist que resolvesse para `fluxo_de_botoes` teria o `lp_welcome` isentado e a
> **mensagem de boas-vindas sairia para quem pediu para sair**. Hoje ela é cancelada como
> `blacklisted`, que não isenta nada.
>
> Custo da ordem correta: a consulta de blacklist continua rodando para lead de fluxo de
> botões. Não é regressão — ela já roda hoje para todo lead que chega ali; é só uma economia
> não tomada. Fixado em `test_blacklist_vence_fluxo_de_botoes`, que falha sob a ordem que
> esta spec pedia originalmente.

### 3.2 Quem é isento, e por quê

| `job_type` | Bloqueado? | Razão |
|---|---|---|
| `standard` | **Sim** | É a cadência de LLM ao lead. É o caso do problema. |
| `ai_reengage` | **Sim** | Mensagem de LLM ao lead. |
| `ai_scheduled_return` | **Sim** | Mensagem de LLM ao lead. Não quebra o retorno do fluxo (§2.1). |
| `handoff_rescue` | **Isento** | Notifica o **vendedor** por template, não o lead. É o anteparo de quem foi transbordado e ninguém pegou — o caso Wilson Demuth, >21h no vácuo, documentado em `scheduler.py:1004`. Bloquear removeria a rede justamente para quem o fluxo entregou. |
| `lp_welcome` | **Isento** | Primeiro contato de lead de landing page, que **ainda não mandou mensagem** — não há estado de fluxo. O canal aponta para botões, então o motivo dispararia e nenhum lead de LP seria mais recebido. |
| Tipos do João (`_is_joao_job_type`) | **Isento** | Cadência no funil do vendedor, canal do João, já isentos de `ai_disabled` pelo mesmo tipo de circularidade. |

A isenção de `lp_welcome` deixa uma costura em aberto e ela fica declarada: o lead de LP
recebe boas-vindas de um motor e, ao responder, cai nos botões. Não é o caso que motivou esta
spec (lá o lead já estava na árvore), e bloquear seria pior — mas é interação conhecida, não
descuido.

### 3.3 O custo em consulta

`fluxo_da_conversa` já sai sem tocar o banco quando **nenhum** fluxo está ligado
(`config.algum_fluxo_ligado()`), e com algum ligado resolve `agent_profiles` por um cache de
300s (`runner._perfil_cache`). Então o motivo novo custa, no pior caso, uma consulta por
perfil por 5 minutos — não uma por job.

A checagem entra **depois** das verificações em memória e **antes** de
`is_lead_blacklisted`, que é a única outra que vai ao banco. Assim o lead que já para por
`opt_out` não paga nem a consulta de perfil nem a de blacklist.

---

## 4. Mudanças, arquivo por arquivo

| Arquivo | Mudança | Risco |
|---|---|---|
| `backend/app/follow_up/scheduler.py` | `_lead_stop_reason` ganha o motivo e os 2 params opcionais; `_stop_reason_applies` ganha a tabela de isenção; os chamadores que têm canal/conversa passam | **alto** — backstop de 6 caminhos de envio, em produção |
| `backend/tests/test_followup_x_botoes_2026_10_01.py` | **novo** | baixo |

Mitigação do risco alto: os 2 params são **opcionais com default `None`**, e sem eles o
motivo não dispara. Nenhum caminho existente muda de comportamento por omissão — só os que
passarem explicitamente.

## 5. Testes

- Lead em conversa de fluxo de botões: `standard`, `ai_reengage` e `ai_scheduled_return`
  cancelam com `cancel_reason="fluxo_de_botoes"`.
- `handoff_rescue`, `lp_welcome` e um tipo do João **não** cancelam.
- Sem `conversation`/`channel` (chamador antigo): comportamento byte-idêntico ao de hoje.
- Com todos os fluxos desligados (`algum_fluxo_ligado()` falso): o motivo não dispara **e
  não há consulta a `agent_profiles`**.
- Conversa de LLM no mesmo canal de botões: **não** cancela (a conversa vence o canal, e é
  o caso do lead que o disparo apontou para a LLM).
- Erro ao resolver o perfil: fail-open, não cancela.
- Precedência: lead com `opt_out` **e** em fluxo de botões → `cancel_reason="opt_out"`
  (analytics preservado).
- Lead em fluxo de botões **e** `ai_enabled=False` → `"fluxo_de_botoes"`, não `"ai_disabled"`.

## 6. Testes fictícios (ponta a ponta, sem tocar a Meta)

Simulação de conversa completa com dados fictícios, exercitando o que teste unitário não
cobre: a **ordem** entre os dois motores.

1. Lead fictício entra, recebe a tela de entrada, toca "Pro meu negócio", recebe N1 e **para**.
2. O scheduler roda com um job `ai_reengage` vencido para esse lead → **cancelado**
   com `fluxo_de_botoes`, nenhuma chamada de LLM, nenhuma chamada ao provedor.
3. O mesmo lead é transbordado (`T_HANDOFF`) → um `handoff_rescue` vencido **dispara**.
4. Um lead de LP no mesmo canal → `lp_welcome` **dispara**.
5. Um lead da ValerIA LLM no mesmo canal (conversa apontada para o perfil LLM) →
   `ai_reengage` **dispara** normalmente.

Dublês no provedor e no LLM; qualquer chamada real a um deles **falha o teste**.
