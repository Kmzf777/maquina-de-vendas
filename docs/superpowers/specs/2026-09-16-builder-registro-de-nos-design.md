# Builder de cadências: registro de nós como contrato único

**Data:** 2026-09-16
**Branch:** `feat/builder-registro-nos` (a partir de `origin/master` = `c1c55de4`)

---

## 1. O problema, medido

O builder de `/campanhas` foi desenvolvido e **nunca usado**. Medição em produção
(16/09/2026):

```
16 campanhas | 0 ativas | 0 matrículas em toda a história
```

As únicas campanhas feitas à mão são `Tiburcio-Miranda-2`, `cadencia` e
`Cadencia Teste deletar` — lixo de teste, todas em `draft`. Não há nada a preservar.

Isso importa porque o builder **não é o contrato**. Quem executa é
`backend/app/automation/engine.py`. E toda falha encontrada é da mesma família:
**o inspector escreve uma chave, o motor lê outra.**

### 1.1 Cinco dos doze gatilhos nunca casam

O campo "Filtro de stage" (`inspector.tsx:161-190`) é populado de `allStages` e grava
`s.label` — o **rótulo da coluna de Kanban** ("Em conversa"). O motor compara com outra
coisa, e com coisas **diferentes entre si**:

| Gatilho | Motor compara com | Onde | Inspector grava | |
|---|---|---|---|---|
| `stage_stagnation` | `leads.stage` | `triggers.py` `q.eq("stage", stage)` | rótulo | ❌ |
| `no_sale_in_stage` | `leads.stage` | RPC `get_leads_no_sale_in_stage` | rótulo | ❌ |
| `no_message` (c/ filtro) | `leads.stage` | `q.eq("stage", stage_filter)` | rótulo | ❌ |
| `stage_enter` | `leads.stage` | `_passes_filter` vs `data.stage` | rótulo | ❌ |
| `deal_stage_enter` | `pipeline_stages.key` | `_passes_filter` vs `newStageKey` | rótulo | ❌ |
| `deal_stage_stagnation` | `stage_id` (uuid) | RPC | `stage_id` | ✅ |
| `keyword_received`, `repurchase_window`, `sale_created`, `tag_added`, `deal_closed_lost`, `post_broadcast` | — | — | — | ✅ |

`leads.stage` é o **segmento do lead** (`novo`/`qualificado`/`respondeu`/`ja_chamado`),
não a coluna do Kanban. Um único `<select>` serve dois vocabulários distintos e está
errado para ambos.

Pior: `stage_stagnation` e `no_sale_in_stage` **pulam o gatilho inteiro** quando
`stage_filter` é vazio (`if not stage: continue`), e `getDefaultConfig` não escreve esse
campo. Campanha ativa, silenciosa, sem um único log de erro.

### 1.2 A ação `create_deal` cria no funil errado por construção

```python
# engine.py::_execute_action
create_deal(enrollment["lead_id"], title, cfg.get("category"))
```

Sem `pipeline_id`, sem `stage_key`, sem `dedupe_open`. E o inspector só oferece
**título** — não há campo de categoria, funil ou etapa. Então `category` é sempre `None`,
a resolução cai no fallback **"(4) primeiro pipeline"** de
`leads/service.py::create_deal`, a etapa vira a primeira coluna não protegida, e **o card
é duplicado a cada execução do nó**.

É o mesmo mecanismo que espalhou 19 cards de reposição em "Valéria - Importação Leads
Frios".

### 1.3 Quatro formas de a cadência morrer em silêncio

- **Condição com ramo solto** — `engine.py:537`: `next = yes if result else no`; nulo →
  `_complete()`. O fluxo acaba sem erro.
- **Apagar um nó do meio** — FK é `ON DELETE SET NULL`; o antecessor fica sem
  `next_node_id` e a matrícula completa na próxima execução.
- **`on_reply` do nó vence o do gatilho** (`worker.py::_apply_reply_policy`), e só é
  editável em `send`/`send_text`. Marcar num toque mata o `reset` do gatilho.
- **Template não aprovado** não impede inscrição, só envio: a campanha inscreve, não
  manda nada e caminha até a ação final.

### 1.4 Controles inertes

- `replied_only` do `post_broadcast`: o inspector oferece o toggle; `broadcast/worker.py`
  envia `"replied_only": False` fixo; `_passes_filter` não lê. **Não faz nada.**
- `final_actions` do nó `end`: o motor executa (`_execute_end`), o inspector não edita.
- 8 das 9 condições não estão na paleta (existem só no `<select>` do inspector).

### 1.5 Ativação: 1 trava contra 7

`/api/campaigns/[id]/activate` valida **uma** coisa: o gatilho tem `next_node_id`. O
`PATCH` é pior — `update({ ...body })` deixa passar `{status:"active"}` sem validação
nenhuma. A aba Esteiras (`esteiras_router.py`) valida sete, entre elas template aprovado.

### 1.6 Duas APIs paralelas

```
Aba Esteiras → Next (proxy) → FastAPI esteiras_router.py     ← 7 travas
Builder      → Next (Supabase direto)                         ← 1 trava
               FastAPI campaigns/router.py                     ← ninguém chama
```

---

## 2. O princípio

> **O motor é o contrato. O builder é uma view sobre ele.**

Consertar os cinco gatilhos um a um não impede o sexto, e criar/personalizar nós é
requisito declarado. Portanto o contrato vira **dado declarado num lugar só**, e todos os
consumidores derivam dele.

---

## 3. O registro de nós

`backend/app/campaigns/node_registry.py` — **novo**, sem dependência do motor (para não
criar ciclo de import) e sem I/O.

```python
VOCABULARIOS = {
    "texto", "texto_longo", "numero", "booleano",
    "segmento_lead",       # leads.stage           — novo/qualificado/respondeu/...
    "etapa_key",           # pipeline_stages.key   — fechado_ganho/respondeu/...
    "etapa_id",            # pipeline_stages.id    (uuid)
    "funil_id",            # pipelines.id          (uuid)
    "canal_id",            # channels.id           (uuid)
    "template",            # message_templates.name — exige APROVADO para ativar
    "tag",                 # tags.name
    "usuario_id", "lista_usuario_id", "lista_texto",
    "operador",            # eq/ne/gt/gte/lt/lte
    "politica_resposta",   # pause/cancel/reset
    "severidade",          # info/warning/critical
}

@dataclass(frozen=True)
class Campo:
    chave: str
    vocab: str
    rotulo: str
    obrigatorio: bool = False     # obrigatório para ATIVAR, não para salvar
    default: Any = None
    ajuda: str = ""

@dataclass(frozen=True)
class TipoDeNo:
    tipo: str                      # trigger|send|send_text|wait|condition|action|end
    subtipo: str | None
    rotulo: str
    icone: str
    campos: tuple[Campo, ...]
    requer_um_de: tuple[tuple[str, ...], ...] = ()   # ao menos uma chave do grupo
    na_paleta: bool = True

REGISTRO: dict[tuple[str, str | None], TipoDeNo]
```

**Regra de ouro:** `obrigatorio=True` significa *"sem isto a campanha não pode ser
ativada"*, nunca *"sem isto não salva"*. Salvar rascunho incompleto é legítimo — é assim
que se monta uma cadência.

### 3.1 O conteúdo do registro

Derivado do que o motor **de fato lê**. Casos que mudam em relação a hoje estão marcados.

**Gatilhos**

| subtipo | campos (vocabulário) | obrigatórios |
|---|---|---|
| `no_message` | `days`(numero), `stage_filter`(**segmento_lead**) | days |
| `stage_stagnation` | `stage_filter`(**segmento_lead**), `days`(numero) | **stage_filter**, days |
| `no_sale_in_stage` | `stage_filter`(**segmento_lead**), `days`(numero) | **stage_filter**, days |
| `stage_enter` | `stage_filter`(**segmento_lead**) | — |
| `deal_stage_enter` | `stage_filter`(**etapa_key**) | — |
| `deal_stage_stagnation` | `stage_id`(etapa_id), `stage_key`(etapa_key), `pipeline_id`(**funil_id**), `stage_days`, `silence_days`, `last_speaker`, `limit`, `on_reply`(**politica_resposta**) | `requer_um_de=(("stage_id","stage_key"),)` |
| `keyword_received` | `keywords`(lista_texto) | keywords |
| `repurchase_window` | `days`(numero) | days |
| `sale_created` | `min_value`(numero), `product_filter`(texto) | — |
| `tag_added` | `tag_name`(tag) | — |
| `deal_closed_lost` | — | — |
| `post_broadcast` | — | — |

`replied_only` **sai do registro e da tela**: não é lido por ninguém.

**Ações**

| subtipo | campos | obrigatórios |
|---|---|---|
| `move_stage` | `stage`(**segmento_lead**) | stage |
| `move_deal_stage` / `mark_deal_won` | `stage_id`(etapa_id) | stage_id |
| `mark_deal_lost` | `stage_id`(etapa_id), `lost_reason`(texto) | stage_id |
| `add_tag` / `remove_tag` | `tag_name`(tag) | tag_name |
| `create_deal` | `title_template`(texto), `pipeline_id`(**funil_id**), `stage_key`(**etapa_key**), `category`(texto), `dedupe_open`(booleano) | **pipeline_id** |
| `assign_to` | `user_id`(usuario_id) | user_id |
| `assign_round_robin` | `user_ids`(lista_usuario_id) | user_ids |
| `add_note` | `note_template`(texto_longo) | note_template |
| `alert_seller` | `severity`(severidade), `title`(texto), `message_template`(texto_longo) | title |
| `activate_agent` / `deactivate_agent` | — | — |

**Condições** (as 9, todas na paleta): `replied_recently`(days), `in_stage`(**segmento_lead**),
`has_deal`, `has_tag`(tag), `sale_count`/`total_spend`/`last_sale_value`/`deal_value`/
`repurchase_days` (`operator`+`value`).

**Demais nós**

| tipo | campos | obrigatórios |
|---|---|---|
| `send` | `template_name`(**template**), `template_language`, `template_variables`, `channel_id`(canal_id), `on_reply`(politica_resposta) | template_name |
| `send_text` | `message_text`(texto_longo), `channel_id`, `on_reply` | message_text |
| `wait` | `days`, `hours`, `send_start_hour`, `send_end_hour`, `skip_weekends` | — |
| `end` | `label`(texto) | — |

`final_actions` fica **fora**: é redundante com pôr nós de ação antes do `end`, e manter
uma segunda forma de executar ação dobraria a superfície de validação. O motor continua
executando o campo se existir (compatibilidade), mas a tela não o cria.

### 3.2 Os consumidores

| Consumidor | O que deriva |
|---|---|
| **Motor** | teste prova que toda chave lida por `engine.py`/`triggers.py` está declarada |
| **Inspector** | renderiza o campo e escolhe a lista de opções pelo **vocabulário** |
| **Defaults** | `getDefaultConfig` gerado do registro, não escrito à mão |
| **Validação** | obrigatórios e formato |
| **Nó novo** | uma entrada + um handler no motor |

Exposto por `GET /api/campaigns/node-schema` (FastAPI), consumido pelo inspector.

---

## 4. Validação na ativação

`backend/app/campaigns/validation.py` — **novo**. Função pura sobre
`(campanha, nós, templates_aprovados)` devolvendo `list[Problema]`.

```python
@dataclass(frozen=True)
class Problema:
    no_id: str | None
    codigo: str          # 'campo_obrigatorio' | 'template_nao_aprovado' | ...
    mensagem: str        # texto para a tela, em português
```

**Regras de campo** (do registro): todo `obrigatorio` preenchido; `requer_um_de`
satisfeito; valor bate com o vocabulário (uuid é uuid, número é número).

**Regras de grafo:**

1. Exatamente **um** nó `trigger`.
2. O `trigger` tem `next_node_id`.
3. Todo nó é **alcançável** a partir do gatilho.
4. `condition` tem **os dois** ramos (`yes_node_id` e `no_node_id`).
5. Todo nó que não é `end` tem saída — pega a cadeia cortada por exclusão de nó.
6. **Sem ciclo** (DFS sobre next/yes/no).

**Regras de campanha:**

7. `channel_id` preenchido na campanha, ou em **todos** os nós de envio.
8. Todo `send` aponta para template **aprovado** (§5).

**Fail-open** só na consulta a `message_templates` (timeout de banco não pode travar a
operação); tudo o mais é fail-closed.

Onde roda: `POST /api/campaigns/{id}/activate` no **FastAPI**
(`backend/app/campaigns/router.py`). A rota Next vira **proxy**, seguindo o padrão que
`/api/automation/[...path]/route.ts` já usa. O `PATCH` do Next deixa de aceitar `status`.

---

## 5. Templates: livre para escolher, travado para ativar

Hoje o não aprovado aparece no `<optgroup>` "Aguardando aprovação" com `disabled`
(`inspector.tsx:266-270`) — o oposto do desejado.

- **Tira o `disabled`.** Qualquer template da WABA é selecionável.
- O nó mostra um selo de pendência quando o template escolhido não está aprovado.
- **A ativação recusa**, listando nome e status de cada um que falta.
- Comparação de status normalizada (`.lower() == "approved"`) — o sync local grava
  minúsculo, a Meta devolve `APPROVED`.

Motivo de ser na ativação e não na seleção: montar a cadência e submeter os templates
são trabalhos paralelos. Travar a seleção obriga a ordem inversa e foi o que deixou as
esteiras do João impossíveis de montar antes dos templates existirem.

---

## 6. `on_reply` no lugar certo

- O campo passa a existir **no gatilho** (política da esteira inteira).
- Nos nós `send`/`send_text` ele vira **override explícito**, com rótulo dizendo que
  vence o do gatilho — hoje vence em silêncio.
- Default do nó: **ausente** (herda do gatilho). `getDefaultConfig` para de gravar
  `"pause"` em todo nó novo, que é o que mataria um gatilho `reset`.

---

## 7. Conformidade das esteiras do João

Único bloco específico do vendedor; o resto vale para qualquer campanha.

**7.1 `dedupe_open` devolve o card sem mover.**
`leads/service.py::create_deal` com `dedupe_open=True` faz `return existing` — o card é
reaproveitado **onde está**, sem ir para `stage_key`. Como os cards de reposição já
existem em "Já chamado", "Cliente Ativo" nunca recebe ninguém e a esteira de Reposição
aponta para uma etapa que permanece vazia.

Correção: quando `stage_key` é informado e o card reaproveitado está em **outra** etapa
do mesmo funil, **mover** para a etapa pedida (e atualizar `entered_stage_at`, que é o
relógio do gatilho). Sem `stage_key`, comportamento atual.

**7.2 Os 19 cards no funil errado.** Script SQL de correção, revisável antes de aplicar,
movendo os cards de título `Reposição` que estão em "Valéria - Importação Leads Frios"
para o funil de reposição da origem. Fica em `scripts/`, **não é aplicado** por este
trabalho.

---

## 8. Aposentar a aba Esteiras

Depois de §3–§6 em produção: apagar `esteiras_router.py`, `esteiras-tab.tsx`,
`esteiras-tab.test.tsx`, as rotas `frontend/src/app/api/automation/esteiras/**` e o item
`"esteiras"` de `VALID_TABS`. O seed genérico `esteiras.py` **fica** — as 4 esteiras são
campanhas normais e continuam visíveis no builder.

As 3 campanhas de teste (`Tiburcio-Miranda-2`, `cadencia`, `Cadencia Teste deletar`) são
apagadas por script, não por migration.

---

## 9. Não-objetivos

- **Portabilidade / multi-tenant.** Copiar o CRM para outra empresa é fork do git com
  adaptação total. UUID cravado em seed não é problema a resolver aqui.
- **Mudar o desenho das esteiras do João.** Prazos, número de toques e textos ficam como
  a reunião de 10/09 decidiu.
- **Ativar qualquer campanha.** Tudo continua em `draft`.
- **Aplicar o SQL dos 19 cards.**
- **Condição de janela de 24h** (`send_text` grátis). É outro projeto.

---

## 10. Como se prova

- **Registro completo:** teste varre `engine.py` e `triggers.py` por `cfg.get("...")` e
  falha se alguma chave não estiver no registro. É o teste que impede a próxima
  divergência.
- **Vocabulário correto:** para cada gatilho com `stage_filter`, teste afirma o
  vocabulário esperado (`segmento_lead` vs `etapa_key`) e casa com o que o motor compara.
- **Validação:** um teste por regra, cada um provado por **injeção** — monta o grafo
  violando a regra e exige que a ativação recuse.
- **Defaults:** teste afirma que `getDefaultConfig` de todo subtipo devolve exatamente os
  defaults do registro.
- **Templates:** ativação com template pendente recusa e nomeia o pendente; com todos
  aprovados, passa.
- **Suíte inteira verde** (backend + frontend + `tsc` + `next build`).
