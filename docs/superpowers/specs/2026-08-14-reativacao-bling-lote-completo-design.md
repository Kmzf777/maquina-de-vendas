# Importação do lote completo do Bling + aviso de inadimplentes no disparo — design

**Data:** 2026-08-14
**Branch:** `feat/reativacao-bling-lote-completo`
**Origem dos requisitos:** sessão de brainstorming em 2026-08-14 (5 decisões do usuário, registradas em "Decisões")

**Duas entregas, caminhos de deploy diferentes:**

| | Parte 1 — Dados | Parte 2 — Aviso na UI |
|---|---|---|
| O que é | 1.208 leads, funil, etapas, tags, briefings | banner de inadimplentes no modal de disparo |
| Como vai ao ar | `preparar.sql` aplicado via `psql` na VPS | commit → push para `master` → GitHub Actions |
| Depende de | — | da tag `Débito vencido` criada na Parte 1 |

A Parte 2 é inócua enquanto a Parte 1 não roda: sem nenhum lead com a tag, o banner
simplesmente nunca aparece. As duas podem subir em qualquer ordem.
**Antecessor:** `2026-08-08-reativacao-crm-preparacao-design.md` (lote de 276 contatos, **nunca aplicado** — ver "Estado do lote anterior")

---

## Problema

A extração do Bling de 2026-08-08 tem 2.771 contatos. Apenas **288 (10,4%)** existem no
CRM. Os outros 2.483 são invisíveis para o CRM: `broadcast_leads` referencia `lead_id`,
então quem não tem lead não pode receber disparo, não aparece no Kanban e não tem
histórico para o vendedor consultar.

Dos 2.483 ausentes, **1.241 têm telefone utilizável** e somam **R$ 1.951.716 já faturados**. Os
outros 1.242 não têm telefone nenhum ou têm número malformado (66 têm e-mail) e não têm como entrar num fluxo de
WhatsApp.

Existe um segundo problema, descoberto ao investigar como o disparo seleciona público:
**a marcação por tag não funciona em escala hoje.** `GET /api/leads` não tem `.limit()`
nem paginação, o PostgREST corta em 1.000 linhas, e o filtro de tag do modal de disparo
roda **no cliente, depois do corte**. Com 2.339 leads na base isso já quebra:

| Tag | No banco | Selecionável no disparo |
|---|---|---|
| B2B | 271 | 29 |
| Marca Própria | 256 | 31 |
| Revenda | 184 | 16 |
| Já é Cliente | 19 | 2 |

Todas as 11 tags perdem leads. Importar mais 1.208 leva a base a 3.557 e derruba a
fração visível para ~28%.

## Escopo

**Parte 1.** Criar no CRM os leads ausentes que têm telefone, organizados num funil
dedicado com etapas por recência de compra, marcados por tag de perfil, cada um com uma
nota de briefing para o vendedor.

**Parte 2.** Avisar, no modal de criação de disparo, quando houver leads com débito
vencido entre os selecionados — mostrando quais são e oferecendo desmarcá-los.

### Fora de escopo

- **Executar ou preparar disparo.** Nenhum registro em `broadcasts` ou `broadcast_leads`
  (decisão D3). Número, template e dono são decididos depois.
- Os 1.242 contatos sem telefone utilizável.
- **Os 51 opt-outs pendentes** e o **enriquecimento dos 288 leads já existentes** — as
  duas partes do lote de 10/08 que este não cobre (ver "Estado do lote anterior"). Ambas
  precisam de rodada própria.
- Corrigir o teto de 1.000 em `GET /api/leads`. É um defeito real e está registrado em
  "Dívida técnica descoberta", mas o desenho deste lote foi feito para não depender da
  correção.
- **O aviso na aba CSV do disparo.** Naquele caminho o modal envia o arquivo direto para
  `POST /api/broadcasts/{id}/import` e nunca vê os leads (que são criados no backend), então
  não há o que checar no cliente. O aviso vale só para a aba CRM.
- Alterar código de backend.

## Universo de dados

Fonte: `leads-bling-completo-2026-08-08-br (1).csv` (2.771 contatos, separador `;`,
UTF-8 com BOM), na raiz do repositório.

| Grupo | Qtd |
|---|---|
| Contatos no CSV | 2.771 |
| Já existem no CRM | 288 |
| Ausentes sem telefone utilizável (66 com e-mail) | 1.242 |
| Ausentes **com** telefone | 1.241 |
| Telefones repetidos dentro desse grupo | −33 |
| **Leads a criar** | **1.208** |

O cruzamento normalizou os telefones com a mesma regra do backend
(55 + DDD + 9 dígitos) e comparou contra `leads.phone` **e** `leads.wa_id`, com e-mail como
segundo critério. O 9º dígito é injetado **apenas em celular** (assinante começando em 6-9):
injetá-lo num fixo fabricaria um número de outra pessoa — ver "Normalização de telefone".
`leads.cnpj` está vazio em todos os 2.339 leads do CRM, então cruzar por CNPJ não é
possível — um cliente cadastrado no CRM com telefone diferente do que consta no Bling
conta como ausente.

**Verificação contra falso-negativo:** 20 dos "ausentes" foram sorteados e buscados
diretamente no PostgREST por sufixo do número (`phone.like` / `wa_id.like`), sem passar
pela normalização local. Nenhum apareceu.

## Estado do lote anterior

O lote `reativacao_bling_2026-08-10` (276 contatos curados da mesma extração) tem spec,
runbook, `generate_sql.py` com rollback e testes — tudo mergeado. **Nunca foi aplicado
ao banco:**

- `leads` com `metadata->>'lote' = 'reativacao_bling_2026-08-10'`: **0**
- `leads` com `metadata->>'origem' = 'reativacao_bling'`: **0**
- tag `9f1c7a52-4b3e-4d81-9a6f-2c8e5b0d7a41` ("Reativação 10/08"): **não existe**
- `lead_notes` começando com `REATIVA`: **0**

Este lote **cobre a criação de leads** daquele — os 276 são um subconjunto curado dos
mesmos 2.771 contatos, e os que ainda não existem no CRM estão dentro dos 1.208. Mas
**não cobre duas partes** do lote anterior, que continuam pendentes:

1. **Os 51 opt-outs detectados.** São contatos que disseram "não tenho interesse" /
   "parar mensagens" em disparos anteriores e seguem com `opt_out = false` — hoje a base
   inteira tem só 20 leads marcados. Eles **já existem** no CRM (por isso não estão nos
   1.208) e continuam elegíveis para receber mensagem. É um risco vivo, independente
   deste lote.
2. **O enriquecimento conservador dos leads que já existem** (D5 do lote anterior:
   preencher só campos vazios de `cnpj`, `razao_social`, `nome_fantasia`, `endereco`,
   `email` e adicionar briefing). Vale para os 288 já presentes no CRM.

A curadoria manual do lote anterior **não conflita com este lote**, verificado
telefone a telefone: as 10 `DUPLICATAS_EXCLUIDAS` e as 4 de `MOTIVOS_EXCLUSAO` estão
**todas** entre os 288 que já existem no CRM, portanto **nenhuma cai nos 1.208**. O
script deste lote não precisa carregar essas constantes — mas elas continuam válidas para
a rodada futura de enriquecimento dos leads existentes.

## Restrições do ambiente

Verificado contra a produção (Supabase self-hosted, `https://supabase.canastrainteligencia.com`)
em 2026-08-14:

- **Teto de 1.000 linhas do PostgREST**, confirmado: `GET /rest/v1/leads?select=id` sem
  `limit` devolve 1.000 de 2.339.
- `GET /api/leads` (`frontend/src/app/api/leads/route.ts`) não pagina e ordena por
  `last_msg_at desc nullsfirst=false`. Só 10 dos 2.339 leads têm `last_msg_at`.
- O filtro de **funil/etapa é server-side** (`.eq("pipeline_id")` / `.eq("stage_id")` sobre
  `deals`); o de **tag e busca é client-side**, aplicado depois do corte.
- Base atual: 2.339 leads, 2.606 deals, 869 vínculos em `lead_tags`, 11 tags, 10 funis.
  Maior funil: "Valeria - Importação Leads Frios", 943 deals.
- `pipelines` tem `owner_user_id` e `is_universal`. Só os 4 funis do João têm dono; os da
  Valeria e do Arthur estão com `owner_user_id = NULL`.
- `pipeline_stages`: `id, pipeline_id, label, key, dot_color, order_index, is_protected,
  conversion_event, conversion_value`.
- `deals`: `lead_id, title, value, stage, category, pipeline_id, stage_id, assigned_to, …`.
  Convenção de título (`frontend/src/lib/import-deals.ts:33`): `"<nome ou telefone> - <funil>"`,
  `value = 0`, `stage = "novo"`.
- `lead_notes`: `lead_id, author, content, created_at`.
- `leads.phone` é NOT NULL com índice UNIQUE (`leads_phone_key`); a unicidade é da string
  exata, então `11981154002` e `5511981154002` coexistem.
- Defaults de `leads`: `stage='pending'`, `status='imported'`, `channel='evolution'`,
  `metadata='{}'`, `human_control=false`.
- Só um usuário aparece em `assigned_to`: João (`1c3c78ed-…`), 393 leads.
- Três canais ativos: `NUMERO ARTHUR` (mode `human`), `NUMERO JOÃO` (`human`),
  `NUMERO VALERIA` (`ai`).
- O banco **não tem backup automático** (`archive_mode = off`, sem cron), fato herdado do
  levantamento de 08/08 e não corrigido desde então.

## Decisões

**D1 — Funil único, etapa por recência.** Um funil `Reativação Bling` com 8 etapas, uma
por `segmento_reativacao`. O usuário escolheu esta forma sabendo do custo: filtrar "o
funil inteiro" no disparo nunca devolverá os 1.208, porque o corte de 1.000 se aplica à
consulta de `deals` do funil. **A seleção tem que ser sempre por etapa.** A maior etapa
tem 665 leads, abaixo do teto, então cada etapa é integralmente selecionável.

Efeito colateral favorável: como funil e etapa filtram server-side, o conjunto já chega
ao cliente com ≤665 linhas — e aí o filtro de tag, que roda depois, passa a operar sobre
o conjunto completo. **Tag combinada com etapa é confiável; tag sozinha não é.**

**D2 — Inadimplentes entram normalmente.** Os 182 contatos com título vencido
(R$ 227.638 antes do dedup, mediana de 190 dias de atraso, 106 acima de 180 dias) entram
nas etapas de recência como qualquer outro. Foi levantado que eles se concentram
justamente nos segmentos mais recentes — 55 dos 77 `ativo_0_3m`, 60 dos 68 `inativo_3_6m`,
72 dos 76 `inativo_6_12m` — e que 84% dos segmentos recentes com débito tem tanto cara de
título não baixado no Bling quanto de inadimplência real. O usuário decidiu incluí-los
mesmo assim. Mitigação adotada: tag `Débito vencido` e a linha de débito no briefing, para
que quem monta o disparo possa excluí-los conscientemente e o vendedor saiba antes de
falar.

**D3 — Sem disparo nesta etapa.** Nenhum registro em `broadcasts`/`broadcast_leads`, nem
canal, nem template. `assigned_to` dos leads fica vazio. **O funil, porém, precisa de dono** — ver
"Visibilidade do funil".

**D4 — Gravação por SQL gerado.** Adaptar `scripts/reativacao/generate_sql.py`, que já
produz `preparar.sql` + `rollback.sql` em transação única com blocos `RAISE EXCEPTION`
conferindo cada contagem. Descartadas: a importação pela UI (o `name` viria da razão
social do Bling — o problema que o lote anterior resolveu com a coluna `saudacao` — e não
haveria briefing, tag, metadata nem rollback) e um script via PostgREST (sem transação
multi-statement, e o banco não tem backup).

**D5 — A tag `Débito vencido` é fixa e o disparo avisa sobre ela.** A tag deixa de ser um
rótulo qualquer e vira contrato: UUID hardcoded, protegida contra rename e exclusão na
API, e lida pelo modal de disparo. Quando houver leads com ela entre os selecionados, o
modal mostra um banner com a lista e um botão para desmarcá-los. **Não bloqueia a criação
do disparo** — travar contradiria D2, que decidiu incluir os inadimplentes na base; o
papel do aviso é garantir que a inclusão num disparo específico seja consciente, não
impedi-la.

## Estrutura

### Funil

`Reativação Bling` — `owner_user_id` = João (`1c3c78ed-…`), `is_universal = false`,
`order_index` após os existentes.

**Visibilidade do funil (corrigido em 2026-08-17, depois de aplicado).** A regra em
`frontend/src/lib/supabase/pipeline-access.ts` e na policy `deals_select` é *admin OU
`owner_user_id = auth.uid()` OU `is_universal`*. O funil nasceu com `owner_user_id = NULL`
e `is_universal = false`, o que o tornou — e aos 1.208 cards — **invisível para todo
vendedor**; só admin enxergava. O João reportou o funil faltando.

O engano foi tomar `Valeria - …` e `Arthur - Exportação` como precedente de "NULL funciona":
esses funis são administrativos de fato (o Arthur é `admin`, o único `vendedor` real é o
João), então ninguém tinha notado. Hoje `pipelines` está assim:

| Configuração | Quem enxerga |
|---|---|
| `owner_user_id = <uid>` | o dono + admins |
| `is_universal = true` | todos os vendedores + admins |
| ambos vazios | **só admins** |

Dono resolve para um vendedor; `is_universal = true` é o caminho se a carteira tiver que
ser trabalhada por vários. Dono também concede gestão da estrutura (renomear, mexer nas
etapas, excluir); `is_universal` concede só escrita de deals.

### Etapas

Todas com `is_protected = false`, `order_index` na ordem abaixo (quente → frio):

| `key` | `label` | Leads | Já faturaram |
|---|---|---|---|
| `ativo_0_3m` | Ativo (0-3m) | 75 | R$ 355.577 |
| `inativo_3_6m` | Inativo 3-6m | 68 | R$ 156.182 |
| `inativo_6_12m` | Inativo 6-12m | 71 | R$ 54.363 |
| `inativo_12_24m` | Inativo 12-24m | 63 | R$ 72.664 |
| `inativo_24_36m` | Inativo 24-36m | 101 | R$ 172.780 |
| `inativo_36m_mais` | Inativo 36m+ | 665 | R$ 1.140.151 |
| `pedido_sem_faturar` | Pedido sem faturar | 62 | — |
| `lead_sem_compra` | Nunca comprou | 103 | — |
| | **Total** | **1.208** | **R$ 1.951.716** |

### Tags

| Tag | Qtd | UUID | Estado |
|---|---|---|---|
| `Reativação Bling 08/26` | 1.208 | `7c4e2a19-3f68-4b02-9d5a-1e8f6c0b3d47` | nova, hardcoded |
| `B2B` | 706 | `2249642b-e4f2-420e-8482-d07b325a28c8` | já existe |
| `E-commerce` | 298 | gerado no insert | nova |
| `Sem vendedor` | 204 | gerado no insert | nova |
| `Débito vencido` | 182 | `3d1b8e6c-7a24-4f95-b8d1-5c0e9a47f210` | nova, **fixa** (D5) |

Os UUIDs hardcoded existem por dois motivos distintos: o do lote deixa o `INSERT`
idempotente e dá ao rollback um alvo preciso; o de `Débito vencido` é referenciado pelo
código do frontend (ver Parte 2), então precisa ser estável entre ambientes.

`B2B` = tem vendedor humano nomeado no Bling. `E-commerce` = origem Tray, WooCommerce ou
Licitação. `Sem vendedor` = campo `vendedor` vazio. Os IDs numéricos do Bling no campo
`vendedor` (199 contatos) contam como `B2B` — são vendedores humanos cujo nome não foi
resolvido na extração.

A tag `Já é Cliente` foi deliberadamente **descartada** deste lote: seriam 1.064 leads,
exatamente o complemento das duas últimas etapas. Redundante com a estrutura.

### Normalização de telefone

O 9º dígito é injetado **apenas quando o assinante começa em 6-9** (faixa móvel do plano de
numeração brasileiro). Fixos começam em 2-5 e ficam com 12 dígitos.

Injetar o 9 num fixo produz um celular válido que muito provavelmente pertence a **outra
pessoa**: `(68) 3302-0386` do Poder Judiciário viraria `68 9 3302-0386`. Como este lote
alimenta disparo de template, isso mandaria marketing para estranhos. São **241 fixos**
entre os 1.208.

Isso **diverge** de `backend/app/leads/service.py::normalize_phone` e de
`frontend/src/lib/phone.ts::normalizePhoneBR`, que injetam o 9 em qualquer número de 12
dígitos começando com 55. Os dois têm o mesmo defeito; corrigi-los afeta a base inteira e
é trabalho separado, registrado em "Dívida técnica descoberta".

O custo de preservar 12 dígitos: se um desses fixos for número de WhatsApp Business, o
webhook gravará a forma de 13 dígitos e criará um segundo lead. É um risco menor que
mandar marketing para estranho, mas existe. `whatsapp_tipo` fica em `metadata` para
permitir filtrar os 241 na hora de montar o disparo.

### Campos do lead

`phone` normalizado (55+DDD+9); `name` via `escolher_saudacao(nome_crm=None, nome_bling)`
de `transform.py`, que remove código/CNPJ do início e sufixos empresariais — nenhum dos
1.208 fica sem nome; `company` / `razao_social` com o nome legal do Bling; `nome_fantasia`,
`cnpj`, `email`, `endereco`, `telefone_comercial` quando existirem;
`stage='pending'`, `status='imported'`, `assigned_to = NULL`, `opt_out = false`.

`metadata`: `origem='reativacao_bling'`, `lote='reativacao_bling_2026-08-14'`, `id_bling`,
`segmento`, `vendedor_anterior`, `total_gasto`, `ultima_compra`, `criado_por_lote=true`.
As duas primeiras chaves juntas são o que o rollback usa — nunca `lote` sozinho.

Nos 182 com débito, `metadata` recebe também `valor_vencido` (número), `titulos_vencidos`
(inteiro) e `dias_atraso_max` (inteiro). São o que o banner da Parte 2 exibe. Ficam em
`metadata` e não em colunas próprias porque `GET /api/leads` faz `select=*` — o dado chega
ao modal sem consulta adicional nem migração de schema.

### Deal

Um por lead, na etapa do seu segmento. `title = "<name> - Reativação Bling"`, `value = 0`,
`stage = "novo"`, `assigned_to = NULL`.

## Regras de conteúdo do briefing

O `author` **precisa ser diferente** do usado pelo lote de 10/08 (`Sistema — Reativação
Bling`, em `generate_sql.py:20`). Com a string repetida, o bloco de verificação contaria as
notas dos dois lotes e — pior — o `DELETE` do rollback apagaria as notas do outro lote, que
não têm `criado_por_lote` para protegê-las. O sufixo também diz ao vendedor de qual
importação veio a nota.

Uma nota por lead em `lead_notes`, `author = 'Sistema — Reativação Bling 08/26'`, reaproveitando
`montar_briefing()` de `transform.py`. Estrutura:

```
REATIVAÇÃO BLING 14/08/2026 — lote reativacao_bling_2026-08-14

CLIENTE INATIVO há 1.109 dias (última compra: 26/07/2023)
Histórico: 140 pedidos · R$ 404.082,26 · ticket médio R$ 3.207,00
Comprava: Café Canastra Clássico Moído 250g (1.190 un)
PERFIL: granel/volume — não abordar como reposição de varejo

Cadastro: CNPJ 29.860.598/0001-70 · Lajeado/RS
NF-e emitidas: 139 · Orçamentos: 0 · Sem débito em aberto
Vendedor anterior: João Brás Vasconcelos dos Reis
id_bling 5845664414
```

Variações obrigatórias:

- **Nunca comprou** (108): substituir o bloco de histórico por
  `LEAD SEM COMPRA — cadastrado no Bling, nunca faturou`.
- **Pedido sem faturar** (63): `PEDIDO EM ABERTO — cadastrado, pedido nunca faturado`.
- **Perfil atípico:** linha `PERFIL:` só quando `classificar_perfil()` retornar rótulo
  (cápsula, café verde/industrial, drip, granel/volume, kit/presente); omitida no café
  torrado convencional.
- **Débito vencido** (182): trocar "Sem débito em aberto" por
  `DÉBITO VENCIDO: R$ X (N títulos, máx N dias de atraso) — confirmar com o financeiro
  antes de abordar`.
- Sem a linha `ICP` do lote anterior: aquele score vinha do CSV master enriquecido com
  BrasilAPI, que não faz parte desta entrada.

## Parte 2 — Aviso de inadimplentes no modal de disparo

### Por que dá para fazer sem consulta nova

`GET /api/leads` já devolve `*, lead_tags(tag_id, tags(*))`. O modal, portanto, tem em
`leads` tanto as tags quanto o `metadata` de cada lead. O aviso é cálculo local sobre
estado que já está carregado — nenhuma rota nova, nenhum round-trip.

### A tag como contrato

`TAG_DEBITO_VENCIDO_ID = "3d1b8e6c-7a24-4f95-b8d1-5c0e9a47f210"` em
`frontend/src/lib/constants.ts` (onde já vive `DEAL_CATEGORIES`), e repetido em
`scripts/reativacao/generate_sql.py`. A duplicação é deliberada — os dois lados precisam
concordar e não compartilham runtime —, e é responsabilidade do plano manter um comentário
cruzado em cada lado.

`PUT` e `DELETE` em `frontend/src/app/api/tags/[id]/route.ts` passam a devolver **409** para
esse ID, com mensagem explicando que o modal de disparo depende da tag. Sem isso, "tag
fixa" seria só convenção: hoje qualquer um renomeia ou apaga uma tag pela UI e o aviso
sumiria em silêncio — que é exatamente o modo de falha mais perigoso de um alerta.

### Componentes

- **`frontend/src/lib/inadimplentes.ts`** — função pura
  `findInadimplentes(leads, selectedIds)` → `{ leads: Lead[]; totalVencido: number }`.
  Filtra os selecionados que têm `lead_tags` com `tag_id === TAG_DEBITO_VENCIDO_ID`, soma
  `metadata.valor_vencido`. Tolera `metadata` ausente, `valor_vencido` string, `null` ou
  lixo (trata como 0) — leads tagueados à mão depois não terão essas chaves.
- **`frontend/src/components/campaigns/inadimplentes-warning.tsx`** — o banner.
  Props: `leads`, `selectedLeadIds`, `onDeselect(ids)`, `variant: "selection" | "review"`.
  Componente separado porque `create-broadcast-modal.tsx` já tem ~1.250 linhas; enfiar mais
  UI lá dentro piora um arquivo que já está grande demais.

### Comportamento

Não renderiza nada quando não há inadimplente selecionado.

O modal tem **6 passos** (`Configuração, Template, Leads, Ação, Agendamento, Revisão`); os
dois pontos de inserção são o **passo 3 (Leads)** e o **passo 6 (Revisão)**.

**`variant="selection"`** (passo 3, acima da tabela): `⚠ N dos M selecionados têm débito
vencido`, os 3 primeiros com nome, telefone, valor e dias de atraso, um `+N outros` que
expande a lista inteira, e o botão **`Desmarcar os N`**, que chama `onDeselect` com os ids
e remove todos de uma vez.

**`variant="review"`** (passo 6, logo abaixo da linha "Leads: N leads do CRM"): uma linha
compacta com a contagem e o total vencido. Sem botão. **Não desabilita o botão de criar o
disparo** (D5).

O `Lead` do modal é uma interface **local** (`create-broadcast-modal.tsx:20`), não a de
`@/lib/types` — ela já declara `lead_tags`, mas **não** `metadata`. Precisa ganhar o campo.

Leads com a tag mas sem `valor_vencido` no metadata aparecem na lista com nome e telefone,
sem a parte monetária, e contam na contagem — nunca somem do aviso por falta de dado.

### Testes

`findInadimplentes` é função pura e ganha testes em `frontend/src/lib/inadimplentes.test.ts`,
seguindo o padrão de `phone.test.ts` e `stats-mappers.test.ts` (vitest): nenhum
selecionado; nenhum com a tag; alguns com a tag; `metadata` ausente; `valor_vencido` como
string com vírgula decimal; lead com a tag mas não selecionado (não pode contar).

## Critérios de aceitação

### Parte 1 — Dados

1. `pg_dump` gerado, com tamanho reportado, antes de qualquer escrita.
2. `select count(*) from leads where metadata->>'origem'='reativacao_bling' and metadata->>'lote'='reativacao_bling_2026-08-14'` = **1.208**.
3. `select count(*) from lead_notes where author='Sistema — Reativação Bling 08/26'` = **1.208**.
4. `select count(*) from deals where pipeline_id=<funil>` = **1.208**, distribuídos pelas
   8 etapas exatamente conforme a tabela de "Etapas".
5. `select count(*) from pipeline_stages where pipeline_id=<funil>` = **8**.
6. Vínculos em `lead_tags`: 1.208 do lote + 706 `B2B` + 298 `E-commerce` + 204
   `Sem vendedor` + 182 `Débito vencido` = **2.598**.
7. Zero registros criados em `broadcasts` ou `broadcast_leads`.
8. Nenhum dos 2.339 leads pré-existentes é alterado (comparação com snapshot pré-execução).
9. Rodar o script duas vezes não cria lead, nota, deal nem vínculo de tag duplicado.
10. `rollback.sql` existe e devolve o banco ao estado do snapshot, incluindo remoção do
    funil e das 8 etapas.
11. Cada etapa, consultada por `pipeline_id` + `stage_id`, devolve o total esperado sem
    truncar (todas ≤ 665, abaixo do teto de 1.000).
12. A tag `Débito vencido` existe com o UUID `3d1b8e6c-7a24-4f95-b8d1-5c0e9a47f210` e tem
    exatamente 182 vínculos, e os 182 leads têm `valor_vencido`, `titulos_vencidos` e
    `dias_atraso_max` em `metadata`.

### Parte 2 — Aviso na UI

13. Sem inadimplente entre os selecionados, o modal fica **idêntico ao de hoje** — nenhum
    espaço reservado, nenhuma borda a mais.
14. Com inadimplentes selecionados, o banner aparece no passo 3 (Leads) com a contagem
    correta e os 3 primeiros nomes; `+N outros` expande para a lista completa.
15. `Desmarcar os N` remove todos os inadimplentes da seleção numa ação, e o banner
    desaparece.
16. O passo 6 (Revisão) mostra contagem e total vencido, e o botão de criar o disparo
    **continua habilitado**.
17. Um lead com a tag mas sem `metadata.valor_vencido` aparece na lista (nome e telefone) e
    conta na contagem, sem quebrar a soma.
18. `PUT` e `DELETE` em `/api/tags/3d1b8e6c-…` devolvem 409; outras tags seguem editáveis e
    removíveis.
19. `findInadimplentes` tem testes cobrindo os seis casos listados em "Testes", e a suíte do
    frontend passa inteira.

## Dívida técnica descoberta

Não faz parte deste escopo, mas foi verificado nesta sessão e deve ser registrado:

1. **`GET /api/leads` não pagina.** Devolve no máximo 1.000 de 2.339 leads, e o filtro de
   tag do modal de disparo roda no cliente sobre esse recorte. Efeito: a seleção por tag
   sem filtro de funil/etapa é silenciosamente incompleta — a UI não avisa que truncou.
   Corrigir exige paginação e mover o filtro de tag para o servidor.
2. **`leads.cnpj` está vazio nos 2.339 leads.** Impede cruzar CRM e Bling por documento,
   que é a chave mais confiável que existe entre os dois sistemas.
3. **188 duplicatas lógicas na base** (mesma pessoa com e sem prefixo `55`), levantadas na
   auditoria de 08/08 e ainda não mescladas.
4. **Banco sem backup automático**, aberto desde jul/2026.
5. **`normalize_phone` (backend) e `normalizePhoneBR` (frontend) injetam o 9º dígito em
   fixos**, fabricando celulares de terceiros. Afeta toda criação de lead a partir de
   número de 12 dígitos, não só este lote. Corrigir exige varrer a base por telefones já
   corrompidos, além de mudar as duas funções.
