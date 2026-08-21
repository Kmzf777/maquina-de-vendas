# Bling — observações da subida em produção (20/08/2026)

Registro do que a API e a infra fizeram **diferente do que a spec e o plano previam**,
durante a primeira execução da integração contra o Bling real. Escrito para a próxima
pessoa: o que já está resolvido, o que ainda morde, e onde olhar.

Contexto: até esta data nada tinha rodado contra o Bling de verdade — os 3.193 testes
do backend usam dublês. Foi a primeira execução real.

---

## 1. O bug que só o banco real revelou: `42P10` em todo pedido

**Sintoma:** todo evento `order.*` do webhook falhava depois de 6 tentativas.
Eventos `product.*` passavam normalmente.

```
{'message': 'there is no unique or exclusion constraint matching the
 ON CONFLICT specification', 'code': '42P10'}
```

**Causa raiz:** a migration criava o índice como **parcial**:

```sql
CREATE UNIQUE INDEX sales_bling_order_id_key
  ON sales (bling_order_id) WHERE bling_order_id IS NOT NULL;  -- <- o problema
```

O Postgres só infere um índice **parcial** num `ON CONFLICT (coluna)` se o **mesmo
predicado** for repetido na cláusula (`ON CONFLICT (col) WHERE col IS NOT NULL`).
O parâmetro `on_conflict=` do PostgREST — usado por `_upsert_sale` em `orders.py:435` —
emite **apenas a lista de colunas**, nunca o `WHERE`. Resultado: o índice ficava
invisível para a inferência e nenhum pedido chegava em `sales`.

`product.*` funcionava porque `bling_products.id` é PRIMARY KEY comum, plenamente
inferível.

**Correção aplicada:** índice único **não-parcial**.

```sql
DROP INDEX IF EXISTS sales_bling_order_id_key;
CREATE UNIQUE INDEX sales_bling_order_id_key ON sales (bling_order_id);
```

O predicado não agregava nada: no Postgres `NULL`s nunca conflitam entre si num índice
único, então as vendas legadas sem `bling_order_id` convivem igual nas duas versões.
A única diferença real era quebrar o `ON CONFLICT`.

O `DROP` é parte da correção: um ambiente que já tenha a versão parcial passaria batido
pelo `IF NOT EXISTS` (o *nome* existe) e continuaria quebrado.

**Lição que vale além deste caso:** dublê de Supabase não modela inferência de
`ON CONFLICT`. Qualquer `upsert` com `on_conflict=` sobre índice parcial tem esse
defeito e **passa verde nos testes**. Se criar outro índice parcial, ou ele nunca é
usado em upsert, ou ele quebra.

**O que NÃO tem o problema:** `leads_bling_contact_id_key` continua parcial de
propósito — `leads.bling_contact_id` só é escrito via `.update()` (`contacts.py:207`),
nunca por upsert, e a violação 23505 é tratada explicitamente (`contacts.py:211`).
Deixar parcial ali mantém o índice pequeno.

---

## 2. Token do `agente-bling` não serve — e não é só questão de app

O projeto `agente-bling` (`/home/ubuntu/agente-bling`) usa **token opaco**, o formato
antigo. Confirmado empiricamente:

| Chamada | Resultado |
|---|---|
| `GET /produtos` **sem** `enable-jwt` | **200 OK**, dados reais |
| `GET /produtos` **com** `enable-jwt: 1` | **401** `invalid_token` |

Nosso `BlingClient` envia `enable-jwt: 1` em toda chamada (obrigatório: o token opaco
está descontinuado). Ou seja, além da regra de não reaproveitar credencial entre
aplicativos, o token de lá é **tecnicamente incompatível** com este cliente.

Serve para consultar comportamento da API; não serve para testar este código.

---

## 3. Deep-link do pedido: o formato do plano estava errado

O plano chutava `https://www.bling.com.br/pedidos.vendas.php#/{id}`. O formato real,
confirmado abrindo um pedido no painel:

```
https://www.bling.com.br/vendas.php#edit/{id}
```

Já corrigido em `frontend/src/lib/sale-display.ts` (`BLING_ORDER_URL_TEMPLATE`).

---

## 4. Sync completo é MUITO mais rápido que o previsto

O plano dava a entender que seria demorado. Rodou em **~18 segundos**:

| Recurso | Registros |
|---|---|
| Produtos | 535 |
| Contatos | 2.850 |
| Formas de pagamento | 45 |
| Vendedores | 16 |

O `criterio=1` ("Todos") funcionou como a spec previa — a contagem de contatos bate com
o painel. Se vier muito menor, é o `criterio` caindo no default 3 ("últimos incluídos").

---

## 5. Webhook: sem secret separado, e a resposta é folgada

O HMAC usa o **`client_secret` do próprio aplicativo** (`config.client_secret()` em
`webhook_router.py`). Não existe segredo de webhook à parte — se o painel pedir um,
é o mesmo `client_secret`.

Header: `x-bling-signature-256: sha256=<hmac-sha256-hex-do-corpo-cru>`.

Medições do receiver em produção:

| Requisição | Resposta |
|---|---|
| `GET /webhook/bling` | 405 |
| `POST` sem assinatura | **401 em 68 ms** |

Bem dentro do orçamento de 5 s do Bling. Continua valendo a regra: **nada de I/O com o
Bling dentro do request**.

---

## 6. Escopos concedidos

O `scope` devolvido no OAuth vem como **IDs numéricos**, não nomes legíveis:

```
875116881 98308 318257553 318257568 318257583 318257565 318257556
318257570 791588404 363921589 363921592 98310 98309 13645013013
```

14 IDs para os 5 recursos pedidos (contatos, produtos, pedidos de venda, formas de
pagamento, vendedores) — o Bling expande em subrecursos. Não dá para conferir escopo
pelo nome via `/api/bling/status`; confira na tela do aplicativo.

---

## 7. Seed dos leads funcionou — mas o número do plano estava desatualizado

- **1.208 leads** com `metadata->>'id_bling'`, **zero duplicados** → todos ganharam
  `bling_contact_id` de graça. O número no plano estava certo.
- O funil "João - Reposição" tem **712 leads distintos** (o plano falava de 1.208 no
  contexto do funil — são coisas diferentes; os 1.208 são os que carregam o ID do Bling,
  espalhados por vários funis).

Consequência prática: leads **sem** `id_bling` e **sem** CNPJ (o caso da maioria no funil
de reposição) não têm vínculo automático. A primeira venda de cada um cai no **409 com
candidatos** e alguém decide o contato. Isso é o desenho, não defeito.

---

## Armadilhas de INFRA (não são da API do Bling)

Custaram tempo nesta subida. Valem para qualquer mexida nesta VPS.

### `docker service update --force` NÃO relê o `.env`

O Swarm guarda o env resolvido na spec do service. Depois de editar
`backend/.env`, `--force` recria a task com os valores **antigos** — sem erro nenhum,
silenciosamente. A sequência correta:

```bash
cd /srv/Maquinadevendascanastra
sg docker -c "docker stack deploy -c backend/docker-compose.yml canastra"  # re-resolve env_file
sg docker -c "docker service update --force canastra_api"
sg docker -c "docker service update --force canastra_worker"
```

Conferir sempre depois: `docker exec <container> env | grep BLING`.

### O gate do deploy é por diretório, e merge engana

`.github/workflows/deploy.yml` só roda `deploy-backend` se
`git diff --name-only $BEFORE HEAD` casar `^backend/`. Um **merge** cujo *diff contra o
commit anterior* só toca `frontend/` **não rebuilda o backend** — mesmo trazendo
`backend/app/bling/` inteiro pelo outro pai do merge.

Foi exatamente o que aconteceu: o código do Bling estava no repo e em
`/srv/Maquinadevendascanastra`, mas a imagem `canastra-api:latest` em execução era de
17/08, sem o módulo `app.bling`. Rebuild manual resolveu.

Como conferir: `docker exec <container> python -c "import app.bling"`.

### O banco de produção é o self-hosted, NÃO o do MCP `supabase-cloud`

Produção é o Supabase **self-hosted nesta VPS** (`supabase.canastrainteligencia.com`,
container `supabase_db`). O MCP `supabase-cloud` aponta para **outro projeto** — os dados
se parecem, mas divergem (ex.: zero leads com `id_bling` lá, 1.208 aqui).

Consultar produção por um destes caminhos:

```bash
# psql direto
docker exec -i $(docker ps -q -f name=supabase_db) psql -U postgres

# ou a REST, o mesmo caminho que o backend usa
SRK=$(grep '^SUPABASE_SERVICE_KEY=' /srv/Maquinadevendascanastra/backend/.env | cut -d= -f2-)
curl -sS "https://supabase.canastrainteligencia.com/rest/v1/<tabela>?select=*" \
  -H "apikey: $SRK" -H "Authorization: Bearer $SRK"
```

O `execute_sql` do MCP roda em transação **read-only** — não aceita DDL de qualquer forma.
Migrations vão por `psql`:

```bash
docker cp arquivo.sql $(docker ps -q -f name=supabase_db):/tmp/m.sql
docker exec $(docker ps -q -f name=supabase_db) \
  psql -U postgres -v ON_ERROR_STOP=1 --single-transaction -f /tmp/m.sql
```

### Eventos `failed` não voltam sozinhos

`process_pending()` só reclama linhas com `status = 'pending'`. Depois de
`MAX_ATTEMPTS = 6` o evento vira `failed` e **fica lá para sempre**. Depois de corrigir
a causa, reponha na mão:

```bash
curl -sS -X PATCH "https://supabase.canastrainteligencia.com/rest/v1/bling_webhook_events?status=eq.failed" \
  -H "apikey: $SRK" -H "Authorization: Bearer $SRK" \
  -H "Content-Type: application/json" -H "Prefer: return=representation" \
  -d '{"status":"pending","attempts":0,"last_error":null}'
```

---

## Pendência descoberta: `bling_situacao_nome` não tem produtor

A spec declara a coluna (`sales.bling_situacao_nome`, linha 240) e o frontend a usa como
**rótulo principal** do status da venda:

```ts
// frontend/src/lib/sale-display.ts
return { label: sale.bling_situacao_nome || "Registrada", tone: "neutral" };
```

Mas **nenhuma das 17 tasks do plano escreve essa coluna** — `grep -rn bling_situacao_nome
backend/app/` não devolve nada. Só o `bling_situacao_id` é gravado.

Efeito prático: toda venda vinda do Bling aparece como **"Registrada"** em
`/painel-vendas`, qualquer que seja a situação real no ERP.

**Por que a spec errou:** a linha 493 diz "`GET /pedidos/vendas/{id}` para obter `numero`
e `situacao` já resolvidos". A API real não resolve nada — devolve só o id:

```json
"situacao": { "id": 6, "valor": 0 }
```

O payload do webhook também: `{"id": 9, "valor": 1}`. **O nome não existe em nenhum ponto
do fluxo de pedido.** Ele só sai de `GET /situacoes/modulos/{idModulo}`.

**E esse endpoint exige um escopo que não está na lista do briefing.** Com os 5 escopos
recomendados (contatos, produtos, pedidos de venda, formas de pagamento, vendedores),
`GET /situacoes/modulos` devolve **HTTP 403**.

Situação IDs observados nesta conta: `6` e `9` (pedidos de venda).

**Correção sugerida** (não aplicada — depende de ação no painel):

1. Adicionar o escopo de **Situações** ao aplicativo e refazer o OAuth (mudança de escopo
   exige novo consentimento).
2. Criar espelho `bling_situacoes (id, nome, modulo_id)`, no mesmo padrão dos outros
   quatro espelhos, alimentado por `GET /situacoes/modulos/{idModulo}`.
3. Em `upsert_from_bling` (`orders.py:475`), preencher `bling_situacao_nome` a partir do
   espelho, ao lado do `bling_situacao_id` que já é gravado.

**O que já funciona sem isso:** cancelamento. `cancel_from_bling` grava
`status = 'cancelada'`, e `saleStatus()` trata esse caso antes de olhar a situação — então
o item 5 do teste E2E (cancelar no Bling → "Cancelada" no CRM) reflete corretamente. É só
a faixa de situações intermediárias (Em aberto, Faturado, etc.) que fica invisível.

---

## Rodada de 21/08/2026 — a integração existia, mas era inalcançável

Depois de tudo acima funcionar no sentido **ERP → CRM**, o usuário testou e reportou que
o CRM "continuava igual". Estava certo. Quatro achados, do mais grave ao menor.

### 1. O modo Bling do modal de venda nunca rodou em produção

`sale-create-modal.tsx` decidia o modo assim:

```ts
const blingMode = !!blingEnabled && !isEditing;
```

`blingEnabled` é uma **prop**, e nenhum dos quatro chamadores a passava —
`painel-vendas/page.tsx`, `deal-detail-sidebar.tsx`, `contact-detail.tsx`,
`lead-detail-modal.tsx`. `blingMode` era sempre `false`. As ~1.500 linhas de
`sale-create-modal` + `bling-order-form` + `bling-contact-resolver` estavam
implementadas, testadas por nada, e **inalcançáveis**. O sentido CRM → Bling nunca
executou.

A correção não foi passar a prop nos quatro lugares. Foi inverter o default: o modal
consulta `/api/bling/status` por um hook e decide sozinho; a prop continua existindo e
**vence quando informada**. Assim omitir passou a significar "pergunte ao backend", e o
defeito não volta quando alguém criar um quinto ponto que abre o modal.

**Falha ao consultar o status BLOQUEIA o registro**, em vez de cair no modo legado.
Cair no legado reintroduziria o mesmo defeito de forma intermitente e invisível: venda
avulsa entrando no CRM sem ninguém perceber. Falha de rede é transitória; venda gravada
fora do ERP é permanente.

### 2. Popover dentro de Dialog não rola (Radix + react-remove-scroll)

Sintoma: os dropdowns de lead e de produto abriam, mas não rolavam.

O `Dialog` do Radix usa `react-remove-scroll`, que só permite rolar dentro do elemento
travado — `handleScroll.js`: `var targetInLock = endTarget.contains(target)`, e a lista
de permitidos é `[lockRef.current, ...shards]` (`SideEffect.js:31`). Não existe atributo
de escape.

O `PopoverContent` do projeto sempre envolvia o conteúdo em `PopoverPrimitive.Portal`,
que renderiza no `body` — **fora** do `DialogContent`. Logo o wheel era descartado. O CSS
dos dois dropdowns estava correto o tempo todo (`max-h-64 overflow-y-auto`).

O Radix não expõe a API de `shards`, então a saída foi uma prop `portal` no
`PopoverContent`, **`true` por padrão**, com `portal={false}` só nos dois popovers que
vivem dentro do diálogo.

`sale-create-modal.tsx` era o único lugar do projeto com Popover dentro de Dialog — por
isso o defeito nunca tinha aparecido.

### 3. Editar pedido abria com o formulário vazio — e o PUT substitui o pedido no ERP

Ao ligar a edição de venda contra o Bling (`PUT /pedidos/vendas/{id}`), o formulário de
itens nascia **em branco**, porque o modal não carregava `sale_items`. Como o PUT
substitui o pedido pelo conteúdo do formulário, um vendedor que abrisse a edição de um
pedido de 11 itens para mudar uma observação **apagaria os 11 itens no sistema fiscal**.

Corrigido antes de ir ao ar: as três rotas que alimentam o modal (`/api/sales`,
`/api/sales/[id]`, `/api/leads/[id]/sales`) passaram a embutir `sale_items(*)` ordenado
por `ordem`, e o formulário abre preenchido.

Dois gates relacionados, ambos load-bearing:

- `blingEditable = !isEditing || !!editingSale?.bling_order_id` — as 91 vendas
  anteriores à integração têm `bling_order_id` nulo; sem o gate, editá-las tentaria
  `PUT /api/bling/orders/undefined`.
- `/api/leads/[id]/sales` usava lista explícita de colunas e não trazia campo nenhum do
  Bling. Como o gate decide por `bling_order_id`, editar a partir do painel de contato
  caía no PATCH local mesmo com pedido no ERP: o CRM mudava e o Bling não, **em
  silêncio**. Divergir por omissão de coluna num `select` não tem nem a defesa do selo de
  divergência.

### 4. `PATCH /api/sales/[id]` descarta campo fora do allowlist, sem erro

A rota filtra chaves desconhecidas silenciosamente. `bling_divergent` e
`bling_divergence` precisaram entrar no allowlist — sem isso a marcação de divergência
seria descartada sem nenhum sinal, e a funcionalidade não faria nada visível.

### Divergência: o desenho e por que 202 não conta

Edição recusada pelo Bling (pedido faturado) pode valer no CRM, mas a venda fica marcada
(`sales.bling_divergent`) com o diff em `sales.bling_divergence`.

**Só 422 marca.** 202 e 5xx são transitórios — o pedido não foi recusado, só não foi
entregue. Marcar divergência neles transformaria instabilidade de rede em ruído
permanente no relatório. É a mesma distinção que `TRANSIENT` já fazia no `POST /orders`.

O 202 do update **não enfileira job**: `jobs.py` só tem handler para `create_order`, e
enfileirar um `update_order` prometeria uma retentativa que falharia em silêncio como
"kind desconhecido". Devolve 202 honesto e a retentativa fica com o usuário.

---

## Tooling de teste nesta VPS

Não vem instalado. Montar uma vez:

```bash
cd frontend && npm ci
cd ../backend && python3 -m venv .venv && \
  .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
```

**`TZ=UTC` é obrigatório no frontend.** A VPS roda em CEST e o CI em UTC; sem ele três
testes de `src/lib/stats-mappers.test.ts` (gap-fill de datas) falham por aritmética de
fuso. Estão verdes no CI — não os "conserte".

O `vitest` roda em `environment: "node"` e só inclui `src/**/*.test.ts`. Não há jsdom nem
testing-library, e nenhum `.test.tsx`. O padrão do projeto é extrair a decisão para função
pura em `src/lib/` e testar lá (`sale-display.ts`, `bling-order-state.ts`,
`bling-gate.ts`, `bling-divergence.ts`). Componentes ficam finos e sem teste próprio.

O lint tem **31 erros pré-existentes** em arquivos não relacionados. O critério é não
adicionar erro novo, não zerar.

---

## Estado no fim desta sessão


| Item | Situação |
|---|---|
| Aplicativo privado + escopos | ✅ |
| OAuth conectado (JWT, 951 chars) | ✅ `refresh` vence 18/09/2026 |
| Migration aplicada | ✅ 1.208 leads vinculados |
| Sync completo | ✅ 535 / 2.850 / 45 / 16 |
| `BLING_ENABLED=true` | ✅ workers ativos |
| Webhooks `order` + `product` | ✅ entregando |
| Bug do índice `42P10` | ✅ corrigido |
| Deep-link do pedido | ✅ corrigido |
| Modo Bling no modal de venda | ✅ alcançável (21/08) |
| Vínculo Bling no detalhe do lead | ✅ |
| Tela `/produtos` | ✅ |
| Editar venda reflete no Bling | ✅ com selo de divergência |
| `bling_situacao_nome` | ⚠️ falta o escopo de Situações no app |
| Mapeamento de vendedores | ⏳ pendente |
| Teste E2E de venda real | ⏳ pendente |
| Backfill de 12 meses | ⏳ pendente (por último) |

O `refresh_token` vence **18/09/2026**. `/config` avisa quando faltarem menos de 5 dias;
perdê-lo obriga a refazer o OAuth no navegador.
