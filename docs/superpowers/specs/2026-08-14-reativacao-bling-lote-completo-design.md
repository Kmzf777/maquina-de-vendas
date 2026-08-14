# Importação do lote completo do Bling para o CRM — design

**Data:** 2026-08-14
**Branch:** `feat/reativacao-bling-lote-completo`
**Origem dos requisitos:** sessão de brainstorming em 2026-08-14 (4 decisões do usuário, registradas em "Decisões")
**Antecessor:** `2026-08-08-reativacao-crm-preparacao-design.md` (lote de 276 contatos, **nunca aplicado** — ver "Estado do lote anterior")

---

## Problema

A extração do Bling de 2026-08-08 tem 2.771 contatos. Apenas **293 (10,6%)** existem no
CRM. Os outros 2.478 são invisíveis para o CRM: `broadcast_leads` referencia `lead_id`,
então quem não tem lead não pode receber disparo, não aparece no Kanban e não tem
histórico para o vendedor consultar.

Dos 2.478 ausentes, **1.275 têm telefone** e somam **R$ 2.043.402 já faturados**. Os
outros 1.203 não têm telefone nenhum (66 têm e-mail) e não têm como entrar num fluxo de
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

Todas as 11 tags perdem leads. Importar mais 1.240 leva a base a 3.579 e derruba a
fração visível para ~28%.

## Escopo

Criar no CRM os leads ausentes que têm telefone, organizados num funil dedicado com
etapas por recência de compra, marcados por tag de perfil, cada um com uma nota de
briefing para o vendedor.

### Fora de escopo

- **Executar ou preparar disparo.** Nenhum registro em `broadcasts` ou `broadcast_leads`
  (decisão D3). Número, template e dono são decididos depois.
- Os 1.203 contatos sem telefone.
- **Os 51 opt-outs pendentes** e o **enriquecimento dos 293 leads já existentes** — as
  duas partes do lote de 10/08 que este não cobre (ver "Estado do lote anterior"). Ambas
  precisam de rodada própria.
- Corrigir o teto de 1.000 em `GET /api/leads`. É um defeito real e está registrado em
  "Dívida técnica descoberta", mas o desenho deste lote foi feito para não depender da
  correção.
- Alterar código de backend ou frontend.

## Universo de dados

Fonte: `leads-bling-completo-2026-08-08-br (1).csv` (2.771 contatos, separador `;`,
UTF-8 com BOM), na raiz do repositório.

| Grupo | Qtd |
|---|---|
| Contatos no CSV | 2.771 |
| Já existem no CRM (291 por telefone, 2 por e-mail) | 293 |
| Ausentes **sem** telefone (66 com e-mail) | 1.203 |
| Ausentes **com** telefone | 1.275 |
| Telefones repetidos dentro desse grupo (32 números, 35 linhas) | −35 |
| **Leads a criar** | **1.240** |

O cruzamento normalizou os telefones com a mesma regra do backend
(`backend/app/leads/service.py:32` — 55 + DDD + 9 dígitos, injetando o 9º quando falta)
e comparou contra `leads.phone` **e** `leads.wa_id`, com e-mail como segundo critério.
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
mesmos 2.771 contatos, e os que ainda não existem no CRM estão dentro dos 1.240. Mas
**não cobre duas partes** do lote anterior, que continuam pendentes:

1. **Os 51 opt-outs detectados.** São contatos que disseram "não tenho interesse" /
   "parar mensagens" em disparos anteriores e seguem com `opt_out = false` — hoje a base
   inteira tem só 20 leads marcados. Eles **já existem** no CRM (por isso não estão nos
   1.240) e continuam elegíveis para receber mensagem. É um risco vivo, independente
   deste lote.
2. **O enriquecimento conservador dos leads que já existem** (D5 do lote anterior:
   preencher só campos vazios de `cnpj`, `razao_social`, `nome_fantasia`, `endereco`,
   `email` e adicionar briefing). Vale para os 293 já presentes no CRM.

A curadoria manual do lote anterior **não conflita com este lote**, verificado
telefone a telefone: as 10 `DUPLICATAS_EXCLUIDAS` e as 4 de `MOTIVOS_EXCLUSAO` estão
**todas** entre os 293 que já existem no CRM, portanto **nenhuma cai nos 1.240**. O
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
funil inteiro" no disparo nunca devolverá os 1.240, porque o corte de 1.000 se aplica à
consulta de `deals` do funil. **A seleção tem que ser sempre por etapa.** A maior etapa
tem 692 leads, abaixo do teto, então cada etapa é integralmente selecionável.

Efeito colateral favorável: como funil e etapa filtram server-side, o conjunto já chega
ao cliente com ≤692 linhas — e aí o filtro de tag, que roda depois, passa a operar sobre
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
canal, nem template. `assigned_to` fica vazio e o funil fica sem dono (`owner_user_id = NULL`),
como "Valeria - Importação Leads Frios". Número, template e responsável são decididos
quando a campanha for montada.

**D4 — Gravação por SQL gerado.** Adaptar `scripts/reativacao/generate_sql.py`, que já
produz `preparar.sql` + `rollback.sql` em transação única com blocos `RAISE EXCEPTION`
conferindo cada contagem. Descartadas: a importação pela UI (o `name` viria da razão
social do Bling — o problema que o lote anterior resolveu com a coluna `saudacao` — e não
haveria briefing, tag, metadata nem rollback) e um script via PostgREST (sem transação
multi-statement, e o banco não tem backup).

## Estrutura

### Funil

`Reativação Bling` — `owner_user_id = NULL`, `is_universal = false`, `order_index` após os
existentes.

### Etapas

Todas com `is_protected = false`, `order_index` na ordem abaixo (quente → frio):

| `key` | `label` | Leads | Já faturaram |
|---|---|---|---|
| `ativo_0_3m` | Ativo (0-3m) | 76 | R$ 355.797 |
| `inativo_3_6m` | Inativo 3-6m | 67 | R$ 154.532 |
| `inativo_6_12m` | Inativo 6-12m | 71 | R$ 54.363 |
| `inativo_12_24m` | Inativo 12-24m | 62 | R$ 72.310 |
| `inativo_24_36m` | Inativo 24-36m | 101 | R$ 171.940 |
| `inativo_36m_mais` | Inativo 36m+ | 692 | R$ 1.190.500 |
| `pedido_sem_faturar` | Pedido sem faturar | 63 | — |
| `lead_sem_compra` | Nunca comprou | 108 | — |
| | **Total** | **1.240** | **R$ 1.999.442** |

### Tags

| Tag | Qtd | Estado |
|---|---|---|
| `Reativação Bling 08/26` | 1.240 | nova (UUID hardcoded, como o lote anterior) |
| `B2B` | 730 | já existe (`2249642b-…`) |
| `E-commerce` | 299 | nova |
| `Sem vendedor` | 211 | nova |
| `Débito vencido` | 182 | nova |

`B2B` = tem vendedor humano nomeado no Bling. `E-commerce` = origem Tray, WooCommerce ou
Licitação. `Sem vendedor` = campo `vendedor` vazio. Os IDs numéricos do Bling no campo
`vendedor` (199 contatos) contam como `B2B` — são vendedores humanos cujo nome não foi
resolvido na extração.

A tag `Já é Cliente` foi deliberadamente **descartada** deste lote: seriam 1.064 leads,
exatamente o complemento das duas últimas etapas. Redundante com a estrutura.

### Campos do lead

`phone` normalizado (55+DDD+9); `name` via `escolher_saudacao(nome_crm=None, nome_bling)`
de `transform.py`, que remove código/CNPJ do início e sufixos empresariais — nenhum dos
1.240 fica sem nome; `company` / `razao_social` com o nome legal do Bling; `nome_fantasia`,
`cnpj` (620 PJ), `email` (968), `endereco`, `telefone_comercial` quando existirem;
`stage='pending'`, `status='imported'`, `assigned_to = NULL`, `opt_out = false`.

`metadata`: `origem='reativacao_bling'`, `lote='reativacao_bling_2026-08-14'`, `id_bling`,
`segmento`, `vendedor_anterior`, `total_gasto`, `ultima_compra`, `criado_por_lote=true`.
As duas primeiras chaves juntas são o que o rollback usa — nunca `lote` sozinho.

### Deal

Um por lead, na etapa do seu segmento. `title = "<name> - Reativação Bling"`, `value = 0`,
`stage = "novo"`, `assigned_to = NULL`.

## Regras de conteúdo do briefing

Uma nota por lead em `lead_notes`, `author = 'Sistema — Reativação Bling'`, reaproveitando
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

## Critérios de aceitação

1. `pg_dump` gerado, com tamanho reportado, antes de qualquer escrita.
2. `select count(*) from leads where metadata->>'origem'='reativacao_bling' and metadata->>'lote'='reativacao_bling_2026-08-14'` = **1.240**.
3. `select count(*) from lead_notes where author='Sistema — Reativação Bling'` = **1.240**.
4. `select count(*) from deals where pipeline_id=<funil>` = **1.240**, distribuídos pelas
   8 etapas exatamente conforme a tabela de "Etapas".
5. `select count(*) from pipeline_stages where pipeline_id=<funil>` = **8**.
6. Vínculos em `lead_tags`: 1.240 do lote + 730 `B2B` + 299 `E-commerce` + 211
   `Sem vendedor` + 182 `Débito vencido` = **2.662**.
7. Zero registros criados em `broadcasts` ou `broadcast_leads`.
8. Nenhum dos 2.339 leads pré-existentes é alterado (comparação com snapshot pré-execução).
9. Rodar o script duas vezes não cria lead, nota, deal nem vínculo de tag duplicado.
10. `rollback.sql` existe e devolve o banco ao estado do snapshot, incluindo remoção do
    funil e das 8 etapas.
11. Cada etapa, consultada por `pipeline_id` + `stage_id`, devolve o total esperado sem
    truncar (todas ≤ 692, abaixo do teto de 1.000).

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
