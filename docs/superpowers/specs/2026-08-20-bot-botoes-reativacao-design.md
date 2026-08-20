# Bot de Botões — Qualificação de Reativação

**Data:** 2026-08-20
**Status:** aprovado (usuário aprovou spec e plano antecipadamente)

---

## 1. Problema

A base tem ~1.208 leads inativos importados do Bling (reativação). Hoje, para
qualificá-los, é preciso disparar um template e deixar a ValerIA (LLM) conduzir a
conversa por texto livre. Isso tem três custos:

1. **Custo de token por lead** numa base grande, para uma pergunta que tem só três
   respostas possíveis.
2. **Não determinismo** — o LLM pode conduzir a mesma pergunta de formas diferentes.
3. **Não funciona no número do João** — o canal dele está em `mode='human'`, e o gate
   em `buffer/processor.py:1418` desliga qualquer resposta automática ali.

O que falta é um agente **determinístico**, que faça uma pergunta fechada por botões,
registre a resposta no CRM e se cale — e que possa ser elencado em disparos nos dois
números.

## 2. Objetivo

Criar o **Bot Reativação**: um agente de fluxo de botões, reconhecido como agente no
CRM (aparece no seletor de agente do modal de disparo), que qualifica leads inativos
perguntando se querem continuar na base ou sair.

### Não-objetivos

- Não é um construtor genérico de chatbots. O fluxo é um só, declarado em código.
- Não substitui a ValerIA. Os dois coexistem; a escolha é por disparo.
- Não há editor de fluxo na interface nesta entrega.

## 3. Fluxo de conversa

```
[Disparo — template aprovado com 3 QUICK_REPLY]
"Oi {{nome}}, faz um tempo que a gente não se fala..."

  ├─ [Quero comprar agora]      → HANDOFF (nó: encerrado)
  │     • nº ValerIA: texto de transbordo + cartão de contato do João
  │     • nº João:    "perfeito, já te chamo por aqui" (sem cartão)
  │     • tag `Reativação: Quente`, ai_enabled=false, nota no lead
  │
  ├─ [Talvez em alguns meses]   → PERGUNTA 2 (nó: aguardando_prazo)
  │     "Beleza! Quando faz sentido eu te chamar de novo?"
  │       ├─ [Daqui a 1 mês]   → tag `Reativação: 1 mês`,   recontatar_em = +1m
  │       ├─ [Daqui a 3 meses] → tag `Reativação: 3 meses`, recontatar_em = +3m
  │       └─ [Daqui a 6 meses] → tag `Reativação: 6 meses`, recontatar_em = +6m
  │     → mensagem de fechamento, nó: encerrado
  │
  └─ [Não quero mais receber]   → OPT-OUT (nó: encerrado)
        • opt_out=true, ai_enabled=false
        • deals movidos p/ pipeline Blacklist, follow-ups cancelados
        • tag `Reativação: Recusou`
        • mensagem curta de confirmação
```

**Texto livre em vez de clique:** na primeira ocorrência o bot reoferece a pergunta do
nó atual com os botões (uma única vez por conversa, marcado em `flow_state.nudged`).
Na segunda, o bot se cala, aplica a tag `Reativação: Atendimento humano` e devolve a
conversa ao vendedor. Sem LLM em nenhum dos dois casos.

**Restrição da plataforma:** a primeira mensagem tem que ser um **template aprovado com
QUICK_REPLY**, porque a janela de 24h está fechada numa base fria. O segundo nível
(1/3/6 meses) usa `interactive.button` livre, porque o clique do lead abre a janela.

### 3.1 Textos

Copy definitiva, para não ser inventada na implementação. Vive em `flows.py`.

| id | texto |
|---|---|
| `nivel1.botoes` | `Quero comprar agora` · `Talvez em alguns meses` · `Não quero mais receber` |
| `nivel2.corpo` | "Beleza! Quando faz sentido eu te chamar de novo?" |
| `nivel2.botoes` | `Daqui a 1 mês` (`prazo_1m`) · `Daqui a 3 meses` (`prazo_3m`) · `Daqui a 6 meses` (`prazo_6m`) |
| `quente.valeria` | "Perfeito! Vou te passar pro João, nosso especialista — ele te chama já já. Deixo o contato dele aqui embaixo pra agilizar." + cartão de contato |
| `quente.joao` | "Perfeito! Já te chamo por aqui pra gente resolver." |
| `prazo.fechamento` | "Combinado, {prazo}. Vou anotar aqui e te chamo nessa época. Qualquer coisa antes disso, é só me escrever!" |
| `optout.confirmacao` | "Entendido, não te mando mais nada. Obrigado pelo tempo e um abraço!" |
| `nudge` | "Pra facilitar, é só tocar numa das opções abaixo:" + os botões do nó atual |

**O nudge do nível 1 não reenvia o template.** Como o lead acabou de escrever, a janela de
24h está aberta, então o reoferecimento sai como mensagem **interativa** com os mesmos três
rótulos, agora com ids nossos (`interesse_quente`, `interesse_talvez`, `interesse_sair`).
Consequência: no nó `aguardando_interesse` o bot precisa casar **duas** formas de clique —
payload igual ao texto do botão (veio do template) ou id `interesse_*` (veio do nudge).

`{prazo}` é substituído por "daqui a 1 mês" / "daqui a 3 meses" / "daqui a 6 meses".

O corpo do template do nível 1 **não** vive em `flows.py` — ele é aprovado na Meta e
escolhido pelo operador no disparo. `flows.py` declara apenas os **rótulos dos botões**
que o template precisa ter, que é o que o preflight (4.7) verifica.

## 4. Arquitetura

### 4.1 O bot como agente do CRM

`agent_profiles` ganha uma coluna `kind text NOT NULL DEFAULT 'llm'`, com valores
`'llm'` e `'button_flow'`. O bot é uma linha:

| campo | valor |
|---|---|
| `name` | `Bot Reativação` |
| `kind` | `button_flow` |
| `prompt_key` | `bot_reativacao` |
| `model` | `''` (não usa LLM) |
| `stages` | `'{}'` |

Isso basta para o requisito "reconhecido como um agente no CRM": o endpoint
`GET /api/agent-profiles` já lista todos os perfis, e o modal de disparo
(`create-broadcast-modal.tsx`) já popula o seletor "Escolher agente específico" a
partir dele. O disparo grava `broadcasts.agent_profile_id`, e o worker
(`broadcast/worker.py:332`) já fixa esse id em `conversations.agent_profile_id`.

**Nenhum código novo é necessário para o bot aparecer e ser elencável.** A única
mudança de frontend é remover a condição que esconde o seletor de agente em canais
`mode='human'` (ver 4.5).

### 4.2 Módulo `backend/app/button_flow/`

Quatro arquivos, com uma responsabilidade cada:

| arquivo | responsabilidade | I/O |
|---|---|---|
| `flows.py` | Declaração do fluxo: nós, textos, botões, ids, efeitos. Dados puros. | nenhum |
| `engine.py` | Núcleo puro: `decidir(no_atual, evento) -> Decisao`. Sem banco, sem rede. | nenhum |
| `effects.py` | Aplica os efeitos no CRM (tags, opt-out, handoff, `recontatar_em`). | Supabase |
| `runner.py` | Orquestra: lê estado → `engine.decidir` → envia mensagem → `effects` → grava estado. | tudo |

`engine.py` é testável isoladamente com dicts, seguindo o precedente de
`app/agent/persona.py` (núcleo puro, I/O no chamador).

**Tipos do núcleo:**

```python
# evento de entrada
Clique(payload: str, titulo: str)   # msg_type == "button" ou "interactive"
Texto(conteudo: str)                # qualquer outra coisa

# saída
Decisao(
    proximo_no: str,                # "aguardando_prazo" | "encerrado" | inalterado
    mensagem: Mensagem | None,      # texto simples ou texto+botões
    efeitos: tuple[Efeito, ...],    # TAG, OPTOUT, HANDOFF, AGENDAR_RECONTATO
    marcar_nudge: bool,
)
```

### 4.3 Estado do fluxo

`conversations` ganha `flow_state jsonb DEFAULT NULL`:

```json
{
  "flow": "reativacao_v1",
  "node": "aguardando_prazo",
  "nudged": false,
  "updated_at": "2026-08-20T14:03:00Z"
}
```

Coluna em vez de Redis: o estado precisa sobreviver a um FLUSHALL (precedente do
incidente de 07/06/2026) e ficar visível numa consulta ao CRM.

O `runner` inicializa `flow_state` no **primeiro inbound** de uma conversa cujo
`agent_profile_id` aponta para um perfil `button_flow` e cujo `flow_state` é `NULL` —
o nó inicial é `aguardando_interesse`. O worker de disparo não precisa gravar nada.

### 4.4 Gate no `buffer/processor.py`

Um branch novo em `process_buffered_messages`, posicionado **antes** do gate de canal
humano (`processor.py:1418`) e depois dos gates de deduplicação/reação:

```python
# Bot de botões: agente determinístico. Roda ANTES do gate de canal humano —
# um fluxo fechado não é IA generativa e é seguro no número do vendedor.
if is_button_flow_conversation(conversation, channel):
    await run_button_flow(...)
    _update_last_msg(conversation["id"])
    return
```

Ordem deliberada: o gate fica **depois** do gate de reação isolada (uma reação não é
turno) e **antes** dos gates de `mode='human'`, `VALERIA_ENABLED`, `lead.ai_enabled` e
`ai_phone_number_ids`. Consequência explícita: o bot roda no número do João sem abrir
esse número para a ValerIA — o gate de canal humano continua intacto para o LLM.

`is_button_flow_conversation` retorna `True` quando a conversa tem
`agent_profile_id` de um perfil com `kind='button_flow'` **e** o `flow_state` não está
em `encerrado`. Uma conversa encerrada cai no fluxo normal do CRM (vendedor humano).

Duas consequências da posição escolhida, ambas desejadas:

- O registro de resposta ao disparo (`record_broadcast_reply`, `processor.py:1337`)
  acontece **antes** do gate. O clique conta como resposta nas métricas do broadcast,
  como qualquer outra mensagem.
- A resolução dinâmica de persona (`_resolve_agent_profile_id`, `processor.py:1505`)
  acontece **depois** do gate e nunca é alcançada numa conversa de bot. Isso importa:
  aquela função recomputa a persona a partir do histórico e sobrescreveria o perfil
  fixado pelo disparo — um disparo do bot é classificado como `cold_reactivation` e
  cairia em `valeria_outbound`. Com o gate antes, não há conflito.

### 4.5 Captura do payload do botão

Hoje `webhook/meta_parser.py:138-151` transforma clique em texto puro e joga fora o
identificador — sem isso não dá para distinguir clique de texto digitado.

Mudança em três pontos, seguindo o padrão já estabelecido para `location`/`contact`/
`reaction`:

1. **`meta_parser.py`** — para `msg_type == "button"` (template) e
   `interactive.button_reply` (interativa), emite `parsed_type = "button"` com
   `text = <título>` e `metadata = {"payload": <payload|id>, "title": <título>}`.
   `list_reply` continua virando texto, como hoje.
2. **`buffer/manager.py`** — `"button"` entra em `_META_TYPES`, e o clique atravessa o
   buffer como `[button: meta_b64=...]`, exatamente como reação já faz.
3. **`buffer/processor.py:2225`** — `"button"` entra na tupla de tipos decodificados em
   `_resolve_media`, devolvendo `message_type="button"` e o `metadata`.

**Nível 1 (template):** a Meta não permite payload customizado em quick-reply de
template — o payload chega igual ao texto do botão. O sinal de "foi clique, não digitação"
é o próprio `msg_type == "button"`; o casamento é por texto normalizado contra os rótulos
declarados em `flows.py`.
**Nível 2 (interativa):** nós controlamos o `id` — `prazo_1m`, `prazo_3m`, `prazo_6m` —
e o casamento é exato.

### 4.6 Envio de botões interativos

`WhatsAppProvider` ganha `send_interactive_buttons(to, body, buttons)`, com o mesmo
padrão dos métodos opcionais já existentes (`send_contact`, `send_reaction`): método
concreto na base que levanta `NotImplementedError`, implementado em `MetaCloudClient` e
no `MockProvider`. O Evolution (descontinuado) herda o default.

Payload da Meta:

```json
{"type": "interactive",
 "interactive": {"type": "button",
   "body": {"text": "..."},
   "action": {"buttons": [{"type": "reply", "reply": {"id": "prazo_1m", "title": "Daqui a 1 mês"}}]}}}
```

Limites da plataforma, validados em `flows.py` por teste: no máximo 3 botões, título de
até 20 caracteres na interativa (25 no template), ids únicos.

### 4.7 Preflight do disparo

`templates/preflight.py` já bloqueia com 400 no start do broadcast. Ganha uma checagem:
quando `broadcasts.agent_profile_id` aponta para um perfil `button_flow`, o template
selecionado precisa ter um componente `BUTTONS` com exatamente os 3 rótulos declarados
no fluxo. Sem isso, o operador consegue parear o bot com um template sem botões e o
disparo sai para 1.208 leads num fluxo que nunca vai avançar.

## 5. Efeitos no CRM

Todos os efeitos reusam funções que já existem — nenhuma regra de negócio nova é
reimplementada.

| Desfecho | Efeito | Reusa |
|---|---|---|
| Quente | tag + `ai_enabled=false` + nota no lead + cartão do João (só no nº da ValerIA) | `add_tags_to_lead`, `update_lead`, `append_lead_observation`, `provider.send_contact` |
| 1/3/6 meses | tag + `leads.metadata.recontatar_em` (ISO) | `add_tags_to_lead`, `update_lead` |
| Recusou | `opt_out=true` + `ai_enabled=false` + Blacklist + cancela follow-ups + tag | `update_lead`, `apply_optout_side_effects` |
| Texto livre 2× | tag `Reativação: Atendimento humano`, bot silencia | `add_tags_to_lead` |

`add_tags_to_lead` resolve tags por nome exato e **nunca cria tags novas** — logo a
migração precisa semear as seis tags. Sem o seed, as tags são silenciosamente ignoradas.

O handoff do branch quente é uma versão enxuta do `encaminhar_humano`: **sem** o resumo
de qualificação por LLM (não há conversa para resumir — houve um clique) e **sem** o
rescue job. Grava `metadata.handoff` e uma nota objetiva com o desfecho do clique.

## 6. Migração de banco

Arquivo: `supabase/migrations/20260820_button_flow_agent.sql`

Conteúdo:

1. `agent_profiles.kind text NOT NULL DEFAULT 'llm'` + constraint
   `CHECK (kind IN ('llm','button_flow'))`, adicionada dentro de `DO $$ ... $$` para ser
   idempotente (`ADD CONSTRAINT` não aceita `IF NOT EXISTS`).
2. `conversations.flow_state jsonb DEFAULT NULL`.
3. A linha do agente: `INSERT INTO agent_profiles (name, kind, prompt_key, model,
   base_prompt, stages) VALUES ('Bot Reativação', 'button_flow', 'bot_reativacao', '',
   '', '{}')` guardado por `WHERE NOT EXISTS (... prompt_key = 'bot_reativacao')`.
4. As **seis** tags, guardadas por `WHERE NOT EXISTS` no nome exato — `add_tags_to_lead`
   resolve por nome e nunca cria, então sem o seed as tags somem em silêncio:
   `Reativação: Quente`, `Reativação: 1 mês`, `Reativação: 3 meses`,
   `Reativação: 6 meses`, `Reativação: Recusou`, `Reativação: Atendimento humano`.

Padrão do repositório: `IF NOT EXISTS` em tudo, e a migração é aplicada **manualmente no
Supabase** — o deploy não roda migrations. Antes de a migração ser aplicada, o código
novo tem que ser inerte (nenhum perfil `button_flow` existe, logo o gate nunca dispara).

## 7. Frontend

Mudanças mínimas, todas em `create-broadcast-modal.tsx`:

1. O seletor de agente hoje some quando o canal é `mode='human'`
   (`selectedChannel?.mode !== "human"`). Passa a aparecer também nesses canais, mas
   listando **apenas** perfis `kind='button_flow'` — a ValerIA continua indisponível ali,
   o que reflete exatamente a regra do backend.
2. Perfis `button_flow` ganham um rótulo visual ("bot de botões") no seletor, para o
   operador não confundir com a ValerIA.
3. `AgentProfile` em `lib/types.ts` ganha `kind`.

A página `/conversas` não muda: as mensagens do bot são gravadas com `save_message` como
qualquer outra e aparecem no histórico normalmente.

## 8. Tratamento de erros

O princípio é o do resto do repositório: **fail-soft, nunca derrubar o turno**.

- Falha de envio da mensagem interativa → loga, **não** avança o nó. O lead pode clicar
  de novo; o estado ainda é o anterior.
- Falha de um efeito de CRM (tag, opt-out) → loga e segue. O nó avança mesmo assim: o
  lead já recebeu a resposta e não pode ficar preso.
- **Exceção deliberada:** falha ao gravar `opt_out=true` **bloqueia** o avanço e alerta,
  porque continuar disparando para quem pediu para sair é o pior desfecho possível.
- Clique num botão que pertence ao fluxo mas **não ao nó atual** — inclui o caso do lead
  tocar duas vezes no mesmo botão, e o de rolar a conversa e clicar no template de novo →
  **ignorado**: log, nenhum efeito, nenhuma mensagem, nenhum nudge. Deliberadamente não
  cai na regra de texto livre: tocar de novo num botão não é o lead se recusando a usar
  os botões.
- `flow_state` corrompido ou de uma versão antiga do fluxo (`flow != "reativacao_v1"`) →
  bot silencia e devolve ao humano.

## 9. Testes

Seguindo o padrão do repositório (`backend/tests/test_<assunto>_<data>.py`):

**Núcleo puro (`engine.py`)** — sem I/O, cobre a matriz completa:
cada um dos 3 botões do nível 1, cada um dos 3 do nível 2, texto livre no nó 1, texto
livre no nó 2, texto livre com `nudged=true`, clique fora do nó, `flow_state` inválido.

**Parser** — clique de template vira `type="button"` com payload; `button_reply` vira
`type="button"` com id; `list_reply` continua texto; texto digitado idêntico ao rótulo
do botão **não** vira clique.

**Buffer** — o clique atravessa `push_to_buffer` → `_resolve_media` preservando o payload.

**Gate do processor** — conversa `button_flow` em canal `mode='human'` roda o bot;
conversa normal em canal `mode='human'` continua bloqueada; conversa `button_flow`
`encerrado` não roda.

**Efeitos** — opt-out chama `apply_optout_side_effects`; handoff manda cartão no nº da
ValerIA e não manda no nº do João.

**Preflight** — broadcast com perfil `button_flow` e template sem botões é rejeitado com 400.

## 10. Fase 2 — re-disparo automático

Entrega **separada**, depois da Fase 1 estar em produção e validada. Escopo:

- Worker que varre `leads.metadata.recontatar_em` vencidos e cria/alimenta um broadcast
  de reativação, no modelo do `follow_up/scheduler.py`.
- Trava de segurança: teto de leads por rodada e um alerta de sistema por rodada, para
  que uma data errada não vire disparo em massa silencioso.
- Template próprio aprovado para o recontato.

Está fora da Fase 1 porque o valor da Fase 1 (qualificar a base e higienizar os opt-outs)
não depende dela, e porque disparo automático merece revisão própria.

## 11. Riscos aceitos

**Pedido de saída em texto livre não é interpretado.** Decisão explícita do usuário: um
lead que escreve "para de me mandar isso" recebe o reoferecimento dos botões, não o
opt-out imediato. Na Meta isso tende a virar *block/report*, que derruba a qualidade do
número. O gancho fica pronto: `engine.decidir` recebe o texto e basta uma regra a mais no
núcleo puro para ligar o comportamento. Recomendação registrada para revisão após o
primeiro lote.

**Rótulos duplicados entre template e código.** Os textos dos botões do nível 1 vivem no
template aprovado na Meta e também em `flows.py`. O preflight (4.7) é a proteção: um
template que divirja do fluxo bloqueia o disparo antes de ele sair.

## 12. Fora de escopo

- Editor de fluxo na interface.
- Outros fluxos de botão além do de reativação.
- Suporte a `list_reply` (listas da Meta).
- Provedor Evolution.
