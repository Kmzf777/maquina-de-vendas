# Vendas: registrar sem Bling + painel escopado por vendedor — design

Data: 24/08/2026
Antecessores: `2026-08-18-crm-bling-integracao-design.md` (a integração),
`2026-08-21-crm-bling-alinhamento-design.md` (Fases A–E, que ligaram o modo Bling)

## Por que esta spec existe

Depois que a integração subiu, o vendedor reclamou que não consegue alinhar os
pedidos do Bling com os do CRM. A empresa opera **dois CNPJs**, portanto duas
contas Bling, e o CRM está integrado a **uma** só. Pedidos lançados na outra
conta não têm como entrar no CRM pelo fluxo atual.

A Fase A da spec anterior fechou a única porta que restava. `bling-gate.ts` decide
o modo do modal e não tem saída: Bling ligado e conectado ⇒ modo Bling, sempre.
Até falha de rede ao consultar `/api/bling/status` bloqueia o registro, por uma
razão que continua válida ("venda gravada fora do ERP é permanente"). O que o
vendedor pede é exatamente a exceção que aquela regra proibiu — então esta spec
muda uma política, não só uma tela.

### O que os dados de produção mostram (24/08/2026)

```sql
SELECT origin, (sold_by IS NULL) AS sem_vendedor, count(*), min(sold_at), max(sold_at)
  FROM sales GROUP BY 1,2;
```

| origin | sem vendedor | linhas | período |
|---|---|---|---|
| `bling` | sim | 1.012 | 27/08/2025 → 21/08/2026 |
| `manual` | não | 28 | 26/05/2026 → 14/08/2026 |
| `manual` | sim | 63 | 26/06/2026 → 07/08/2026 |
| `crm` | — | **0** | — |

Três leituras, todas relevantes para o desenho:

1. **`origin` tem três valores, não dois.** A migration criou a coluna com
   `DEFAULT 'crm'` (`20260818_bling_integration.sql:146`) e logo abaixo carimbou
   todo o histórico como `'manual'` (linha 173). `'crm'` ficou reservado para
   venda criada no CRM que virou pedido no Bling.
2. **Nenhuma venda jamais foi criada pelo caminho CRM→Bling.** Zero linhas com
   `origin = 'crm'` significa que `POST /pedidos/vendas` nunca produziu venda em
   produção.
3. **Nenhuma venda entrou desde que a Fase A subiu.** A última `manual` é de
   14/08; a Fase A foi para produção por volta de 21–22/08. Com 91 vendas de
   amostra isso não prova causalidade, mas a leitura mais provável é que a
   reclamação não seja só "não consigo alinhar" e sim **"não consigo registrar"**:
   o gate exige modo Bling e, quando o pedido é do CNPJ 2, o vendedor não tem
   saída e desiste.

Por isso o Bloco 1 é a parte urgente.

## Restrição inegociável: nada pode escrever no Bling

Existem exatamente três escritas para o ERP em todo o backend:

| Onde | Chamada |
|---|---|
| `backend/app/bling/contacts.py:357` | `POST /contatos` |
| `backend/app/bling/orders.py:342` | `POST /pedidos/vendas` |
| `backend/app/bling/orders.py:212` | `PUT /pedidos/vendas/{id}` |

As três só são alcançadas por ação explícita no modal de venda. Não há trigger no
banco sobre `sales` que empurre nada para o ERP — a única trigger da migration é
`bling_jobs_set_updated_at`, sobre `bling_jobs`.

Nenhum dos três blocos abaixo chama qualquer uma das três. O Bloco 1 **remove**
uma escrita (o `POST` deixa de acontecer naquela venda); o Bloco 2 é leitura no
Supabase; o Bloco 3 é `UPDATE` local. Nenhuma requisição ao Bling é feita, nem de
leitura.

Essa restrição também é o motivo de a atribuição histórica **não** usar o
`vendedor` que vem no pedido do Bling: buscá-lo exigiria `GET /pedidos/vendas/{id}`
para cada venda órfã. Seria leitura, não escrita, mas custaria rate limit (3 req/s)
e dependeria de `bling_seller_map` estar preenchido. Com um único vendedor real, o
`UPDATE` local entrega o mesmo resultado sem tocar no ERP.

## Decisões

| # | Decisão | Alternativa recusada e por quê |
|---|---|---|
| D1 | A escapatória é **genérica**: não declara empresa nem exige motivo. | Modelar o CNPJ na venda deixaria o histórico conciliável quando o segundo Bling for integrado, mas foi recusado por custo/benefício agora. |
| D2 | **Sem fricção e sem chave global**: qualquer vendedor marca a caixa e registra. | Confirmação extra e/ou toggle em `/config` foram recusados. Risco assumido: a escapatória vira o caminho padrão e a integração eroda sem ninguém perceber, já que D1 não pede justificativa. |
| D3 | Vendedor vê as próprias vendas **mais** as de `origin = 'bling'`. | Escopo estrito esconderia do vendedor as 1.012 importadas — justamente o material que ele precisa para conferir. Resolveria o pedido literal e pioraria o problema real. |
| D4 | O painel ganha filtro de origem (Todas / CRM / Bling). | — |
| D5 | Toda venda `origin = 'manual'` passa a ser do joao, **inclusive as que já têm outro vendedor gravado**. | O usuário confirmou duas vezes que foi ele quem vendeu tudo. `Comercial2@cafecanastra.com` é conta antiga do CRM. |
| D6 | Nada escreve no Bling. | — |

## Bloco 1 — Registrar venda sem enviar ao Bling

`frontend/src/lib/bling-gate.ts` ganha a entrada `skipBling`, e a **ordem importa**:

```ts
export function blingGate({ loading, error, enabled, skipBling }: BlingGateInput): BlingGate {
  if (skipBling) return { mode: "legacy", canSubmit: true };
  if (loading)   return { mode: "loading", canSubmit: false };
  if (error)     return { mode: "error", canSubmit: false, message: /* ... */ };
  return enabled ? { mode: "bling", canSubmit: true } : { mode: "legacy", canSubmit: true };
}
```

`skipBling` precisa curto-circuitar **antes** de `error`. Hoje, quando
`/api/bling/status` falha, o modal trava por completo. Se a escapatória fosse
avaliada depois do erro, o vendedor continuaria travado justamente quando ela
seria mais útil. Nessa ordem, a mesma caixa resolve o CNPJ 2 e o deadlock de rede.

Na UI (`sale-create-modal.tsx`), uma checkbox no topo da seção Bling —
**"Registrar sem enviar ao Bling"** — visível quando o gate resolveria para
`bling` ou `error`. Marcada, o formulário troca para os campos legados (produto em
texto livre + valor) e o submit vai para `POST /api/sales`, o caminho que já
existe e funciona.

**Sem coluna nova para marcar a venda** — mas com uma correção obrigatória no
backend. `POST /api/sales` hoje **não define `origin`** e a coluna cai no
`DEFAULT 'crm'` (`20260818_bling_integration.sql:146`), que significa exatamente o
oposto do que aconteceu: "criada no CRM **e** virou pedido no Bling". A rota passa
a gravar `origin: 'manual'` explicitamente. Sem isso, a venda da escapatória
nasceria rotulada como venda integrada, e ficaria indistinguível de uma venda com
pedido no ERP a não ser pelo `bling_order_id` nulo.

Por isso o discriminador do selo é **`bling_order_id IS NULL`**, não o `origin`:
é a única condição que é verdadeira para os três casos que estão de fato fora do
Bling (venda anterior à integração, venda da escapatória, venda legada) e falsa
para os que estão dentro. Na lista isso vira o selo **"Fora do Bling"**, derivado
em `sale-display.ts`. Vendas anteriores à integração caem no mesmo balde, e está
correto que caiam: elas também estão fora do Bling.

`isEditing` mantém o comportamento atual (Fase E): editar venda com pedido no
Bling continua sendo `PUT` no ERP. A escapatória vale para **criação**.

## Bloco 2 — Painel de vendas escopado por vendedor

Hoje `GET /api/sales` e `GET /api/sales/metrics` usam `getServiceSupabase()`
(service role, ignora RLS) e **não checam sessão**. O `sold_by` atual é filtro que
o cliente manda na query string — conveniência, não segurança. O escopo tem que
ser imposto no servidor.

Função pura nova, `frontend/src/lib/sales/sales-scope.ts`. Identidade via
`getCurrentUser()` de `lib/supabase/pipeline-access.ts` (`app_metadata.role`,
`"admin" | "vendedor"`).

| Quem | Vê |
|---|---|
| `admin` | tudo |
| `vendedor` | `lower(sold_by) = lower(<e-mail dele>)` **OU** `origin = 'bling'` |

**A comparação é `lower()` dos dois lados.** O seed grava o vendedor como
`Comercial2@cafecanastra.com`, com C maiúsculo (`20260514_seed_auth_users.sql:94`).
Se `sold_by` guardar uma grafia e o login devolver outra, a regra casa zero linhas
e o painel abre vazio — falha silenciosa, sem erro em lugar nenhum.

Falha ao resolver a identidade → **401, fail-closed**, no mesmo padrão de
`pipeline-access.ts`.

Aplicado em `/api/sales`, `/api/sales/metrics` **e** `/api/sales/[id]` (GET, PATCH,
DELETE). Sem o `[id]` o escopo é cosmético: `/painel-vendas?sale_id=` é deep-link e
qualquer id abriria qualquer venda. Venda fora do escopo responde **404**, não 403
— 403 confirmaria que ela existe.

### Filtro de origem

`SalesFilters` ganha `origin?: "crm" | "bling"`, e a barra ganha um Select
**"Origem: Todas / Registradas no CRM / Vindas do Bling"**, no padrão dos filtros
existentes. "Registradas no CRM" cobre `origin IN ('crm','manual')` — os dois
valores nasceram no CRM, e a distinção entre eles não interessa ao vendedor.

O filtro **intersecta** o escopo, nunca o substitui: filtro escolhido pelo usuário
não pode alargar o que o servidor decidiu. Vale igualmente para `/api/sales/metrics`,
senão o KPI do topo discorda da lista logo abaixo.

Para `role = "vendedor"`, o filtro "Vendedor" que já existe na barra perde sentido
e é ocultado.

### Rollback

Chave de ambiente `SALES_SCOPE_BY_SELLER`, ligada por padrão, lida no servidor.
Desligada, as rotas voltam ao comportamento global sem deploy. Esse é o bloco com
maior chance de gerar reclamação nova ("sumiram minhas vendas") e o que mais se
beneficia de reversão em minutos.

## Bloco 3 — Tornar `sold_by` confiável, e atribuir o histórico

Sem este bloco, "vejo o que é meu" mente.

### 3a. O defeito dos chamadores

`sale-create-modal.tsx:137` já sabe preencher o vendedor sozinho:

```ts
const [soldBy, setSoldBy] = useState(editingSale?.sold_by ?? currentUserEmail ?? "");
```

Mas **dos quatro chamadores, só `conversas/contact-detail.tsx:281` passa
`currentUserEmail`**. `painel-vendas/page.tsx`, `deals/deal-detail-sidebar.tsx` e
`leads/lead-detail-modal.tsx` não passam: venda registrada por esses caminhos abre
com o campo vazio e grava `sold_by = NULL` se ninguém escolher no dropdown. É o
mesmo defeito, letra por letra, que a Fase A descreveu sobre `blingEnabled` —
prop existe, chamador não passa, comportamento morre em silêncio. É o que explica
as 63 linhas sem vendedor.

Correção: hook novo `frontend/src/hooks/use-current-user.ts`, no molde de
`use-bling-status.ts` (cache em memória compartilhado entre chamadores), e os
**quatro** passam a consumi-lo — inclusive `contact-detail.tsx`, que hoje mantém a
própria cópia da lógica em estado local.

### 3b. Migration `20260824_sales_sold_by_normalizacao.sql`

```sql
ALTER TABLE sales ADD COLUMN IF NOT EXISTS sold_by_source   text;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS sold_by_anterior text;

-- Guarda: e-mail errado carimbaria 91 vendas para um usuario inexistente e o
-- painel do joao abriria vazio, sem erro em lugar nenhum.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM auth.users
                  WHERE lower(email) = 'joao@cafecanastra.com') THEN
    RAISE EXCEPTION 'joao@cafecanastra.com nao existe em auth.users';
  END IF;
END $$;

UPDATE sales
   SET sold_by_anterior = sold_by,
       sold_by          = 'joao@cafecanastra.com',
       sold_by_source   = 'normalizacao_joao'
 WHERE origin = 'manual'
   AND (sold_by IS NULL OR lower(sold_by) <> 'joao@cafecanastra.com')
   AND sold_by_source IS NULL
   AND created_at < '2026-08-24';
```

O `AND sold_by_source IS NULL` torna a migration **idempotente**: rodar duas vezes
não sobrescreve `sold_by_anterior` com o valor já normalizado, que destruiria a
capacidade de desfazer.

O `AND created_at < '2026-08-24'` delimita a normalização ao passado. Sem ele,
esta migration é uma arma carregada apontada para o futuro: no dia em que um
segundo vendedor existir de fato, qualquer reexecução transferiria as vendas dele
para o joao — e a premissa "foi ele quem vendeu tudo", que é verdadeira hoje,
deixaria de ser sem que nada no SQL avisasse.

Só toca `origin = 'manual'`. As 1.012 de `origin = 'bling'` ficam sem vendedor de
propósito — não são de ninguém no CRM, e D3 as torna visíveis a todos.

**Rollback exato:**

```sql
UPDATE sales
   SET sold_by = sold_by_anterior, sold_by_anterior = NULL, sold_by_source = NULL
 WHERE sold_by_source = 'normalizacao_joao';
```

Duas colunas em vez de uma flag porque só assim se distingue "não foi tocada" de
"foi tocada e antes era NULL". Com uma flag só, desfazer significaria escolher
entre restaurar NULL em tudo (apagando o `Comercial2` das que o tinham) ou não
restaurar nada.

## Erros e casos de borda

| Situação | Comportamento |
|---|---|
| `/api/bling/status` falha **e** escapatória marcada | Registro permitido (modo legado). Destrava o deadlock atual. |
| `/api/bling/status` falha e escapatória **não** marcada | Bloqueado, como hoje. |
| Vendedor abre `?sale_id=` de venda fora do escopo | 404. |
| Sessão não resolve | 401 em todas as rotas de venda. |
| `admin` | Não afetado por escopo nem por filtro padrão. |
| `SALES_SCOPE_BY_SELLER` desligada | Todas as rotas voltam ao comportamento anterior. |

## Testes

- `bling-gate.test.ts`: `skipBling` com `error` presente → `legacy` e `canSubmit`
  (o caso que dá nome ao bloco); `skipBling` com `enabled: true` → `legacy`.
- `POST /api/sales` grava `origin = 'manual'`, não o `DEFAULT 'crm'` da coluna —
  regressão que passaria despercebida, porque nada na tela mostra o `origin` cru.
- `sales-scope.test.ts` (novo, puro): admin sem escopo; vendedor com escopo;
  comparação de e-mail insensível a maiúsculas; flag desligada devolve escopo vazio.
- Rotas: sem sessão → 401; vendedor pedindo `sale_id` alheio → 404; `origin=crm`
  como vendedor não traz venda `manual` de outro; métricas e lista concordam sob o
  mesmo filtro.
- Frontend: os quatro chamadores passam `currentUserEmail`; a checkbox troca os
  campos do formulário e o endpoint de destino.
- Migration: idempotência (rodar duas vezes preserva `sold_by_anterior`) e rollback
  restaurando NULL e não-NULL corretamente.

## Verificação obrigatória antes de implementar

Ainda não foi conferido se as 91 vendas `manual` têm contraparte entre as 1.012
importadas. O import deduplica **apenas** por `bling_order_id`
(`orders.py:_existing_sale`), e venda lançada à mão antes da integração não tem
esse campo — logo o sync de 12 meses pode ter criado uma segunda linha para o
mesmo pedido do mundo real.

```sql
SELECT c.id AS id_crm, b.id AS id_bling, c.lead_id, c.value,
       c.sold_at AS data_crm, b.sold_at AS data_bling, b.bling_order_number
  FROM sales c
  JOIN sales b
    ON b.lead_id = c.lead_id
   AND b.value   = c.value
   AND b.origin  = 'bling'
   AND abs(extract(epoch FROM b.sold_at - c.sold_at)) < 86400 * 3
 WHERE c.origin = 'manual'
 ORDER BY c.sold_at DESC;
```

Regra de decisão: **vazio** → os três blocos seguem como estão. **Com linhas** → a
deduplicação vira um quarto bloco e é tratada **antes** do Bloco 2, porque filtrar
melhor uma lista que conta a mesma venda duas vezes não resolve a dor do vendedor,
só reorganiza um total errado.

## Fora de escopo, de propósito

- Segundo CNPJ / suporte multi-conta no Bling. `config.py` é single-account e
  continua sendo.
- Motivo ou justificativa na venda avulsa (D1).
- Reconciliação automática entre venda avulsa e pedido do outro Bling.
- Preencher `sold_by` a partir do `vendedor` do pedido no Bling — descartado por
  D6 e pela existência de um vendedor único.
- Chave global para ligar/desligar a escapatória (D2).
