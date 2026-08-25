# Orçamento (Proposta Comercial Bling) — design

Data: 2026-08-25
Branch: `feat/orcamento-proposta-comercial` (parte de `origin/master` = `85598b89`)

---

## 1. Objetivo

Permitir que o vendedor monte um **orçamento** no CRM, que ele nasça como
**proposta comercial no Bling**, gere um **PDF com a marca Café Canastra** para
download, e possa ser **convertido em pedido de venda** com um clique quando o
cliente aceitar.

Entradas do usuário (respostas de 25/08/2026, todas já decididas):

| # | Decisão |
|---|---|
| 1 | Aceite → **converter em venda com 1 clique**; depois de convertido o orçamento **não pode mais ser editado** |
| 2 | Nasce no Bling com situação **Rascunho** |
| 3 | **Sem validade** — o PDF não tem "válido até" e nada expira sozinho |
| 4 | "Não aprovado" é marcado **manualmente** pelo vendedor |
| 5 | Criar orçamento move o card do funil para uma **etapa nova "Proposta Enviada"**, posicionada **imediatamente antes de Fechado Ganho** (ver §6) |
| 6 | Contato inexistente no Bling é criado na hora; **razão social, CPF/CNPJ e e-mail passam a ser obrigatórios em TODA criação de contato** (inclusive no fluxo de venda que já existe) |
| 7 | Desconto **por item (%)** e **no total do pedido (R$ ou %)** |
| 8 | **Frete entra** no orçamento |
| 9 | Prazo de entrega / garantia: fora do escopo |
| 10 | Sem texto de introdução — só o cabeçalho padrão com logo e dados da empresa |
| 11 | Formas e prazos de pagamento: os mesmos já sincronizados do Bling |
| 12 | Dados da empresa no PDF: ver §7 |
| 13 | PDF leva nome e e-mail do vendedor no rodapé |
| 14 | Cláusulas fixas no rodapé do PDF: ver §7 |
| 15 | **Escopo por vendedor** — cada vendedor vê só os orçamentos dele |
| 16 | Indicadores: nº de orçamentos, valor total proposto, taxa de aprovação, ticket médio |
| 17 | **Sem sincronização** de propostas criadas direto no Bling |
| 18 | Permissão "Propostas Comerciais" no app + reautorização OAuth: o usuário faz no final |

Já decidido antes: **PDF apenas para download**, sem botão de enviar no WhatsApp.

---

## 2. A API do Bling — o que foi apurado

Fonte: spec OpenAPI oficial, não indexada, em
`https://developer.bling.com.br/build/assets/openapi-BvBfsn8J.json`
(descoberta a partir de `https://developer.bling.com.br/referencia`).
Cópia da parte relevante: `docs/reference/bling-propostas-comerciais.md`.

Servidor: `https://api.bling.com.br/Api/v3` (o mesmo que `config.API_BASE` já usa).

| Método | Rota | Observação |
|---|---|---|
| GET | `/propostas-comerciais` | filtros `situacao`, `idContato`, `dataInicial`, `dataFinal`, `pagina`, `limite` |
| POST | `/propostas-comerciais` | **obrigatórios: `itens[]` e `parcelas[]`** |
| GET | `/propostas-comerciais/{id}` | |
| PUT | `/propostas-comerciais/{id}` | |
| DELETE | `/propostas-comerciais/{id}` e `/propostas-comerciais` (lote) | |
| PATCH | `/propostas-comerciais/{id}/situacoes` | corpo `{"situacao": "..."}` |

Situações válidas (enum exato, com acento):
`Pendente`, `Aguardando`, `Não aprovado`, `Aprovado`, `Concluído`, `Rascunho`.

Corpo do POST/PUT:

```jsonc
{
  "data": "2026-08-25",              // date
  "situacao": "Rascunho",            // string
  "numero": 13,                      // integer, opcional (o Bling numera sozinho)
  "contato": { "id": 12345678 },
  "loja":    { "id": 12345678, "unidadeNegocio": { "id": 1 } },
  "vendedor":{ "id": 12345678 },
  "desconto": 10.0,                  // number PURO (ver §10, risco 1)
  "outrasDespesas": 11.0,
  "garantia": 3,                     // integer — fora do escopo
  "dataProximoContato": "2026-09-01",
  "observacoes": "…",                // sai no PDF do Bling
  "observacaoInterna": "…",
  "totalOutrosItens": 1,
  "aosCuidadosDe": "Nome do contato",
  "introducao": "…",
  "prazoEntrega": "…",               // string — fora do escopo
  "itens": [{                        // OBRIGATÓRIO
    "produto": { "id": 12345678, "descricao": "Bolo" },
    "codigo": "BLG-5",
    "unidade": "UN",
    "quantidade": 1.1,
    "desconto": 1.2,                 // percentual do item
    "valor": 3.1,                    // unitário
    "descricaoDetalhada": "…"
  }],
  "parcelas": [{                     // OBRIGATÓRIO
    "numeroDias": 10,
    "dataVencimento": "2026-09-24",
    "valor": 10.55,
    "observacoes": "…",
    "formaPagamento": { "id": 12345678 }
  }],
  "transporte": {
    "freteModalidade": 0,            // 0 CIF, 1 FOB, 2 terceiros, 3/4 próprio, 9 sem transporte
    "frete": 2.34,
    "quantidadeVolumes": 2,
    "prazoEntrega": 2,
    "pesoBruto": 2.4,
    "contato": { "id": 1, "nome": "Transportadora" }
  }
}
```

Campos `readOnly` (nunca enviar, e não confiar neles na criação):
`id`, `total`, `totalProdutos`, e `transporte.volumes.*`.

**Resposta do POST: `201 { "data": { "id": 12345678 } }` — só o id, SEM o
`numero`.** Para ter o número que vai no PDF é preciso um `GET
/propostas-comerciais/{id}` logo depois.

**Não existe endpoint de PDF de proposta comercial.** A spec inteira foi varrida:
os únicos PDFs da API do Bling são DANFE de NF-e e etiqueta de envio. Por isso o
PDF é gerado por nós (§7).

Não há webhook de proposta comercial documentado — o que casa com a decisão 17
(sem sincronização).

---

## 3. Modelo de dados

Migration nova: `supabase/migrations/20260825_quotes.sql`.

```sql
CREATE TABLE quotes (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id               uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  deal_id               uuid REFERENCES deals(id) ON DELETE SET NULL,
  conversation_id       uuid,
  created_by            text,               -- e-mail do vendedor; base do escopo
  quoted_at             date NOT NULL,
  status                text NOT NULL DEFAULT 'rascunho',
  bling_proposal_id     bigint UNIQUE,
  bling_proposal_number integer,
  bling_contact_id      bigint,
  bling_situacao        text,               -- espelho da última situação enviada
  subtotal              numeric(12,2) NOT NULL DEFAULT 0,
  discount_value        numeric(12,2) NOT NULL DEFAULT 0,   -- SEMPRE em reais
  discount_unit         text NOT NULL DEFAULT 'REAL',       -- REAL | PERCENTUAL (o que foi digitado)
  discount_input        numeric(12,3) NOT NULL DEFAULT 0,   -- o número digitado, antes de virar reais
  freight               numeric(12,2) NOT NULL DEFAULT 0,
  freight_mode          smallint,
  total                 numeric(12,2) NOT NULL DEFAULT 0,
  payment_method_id     bigint,
  payment_terms         text,               -- "30/60/90"
  notes                 text,
  internal_notes        text,
  sale_id               uuid REFERENCES sales(id) ON DELETE SET NULL,
  converted_at          timestamptz,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE quote_items (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  quote_id            uuid NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
  bling_product_id    bigint,
  codigo              text,
  descricao           text NOT NULL,
  unidade             text,
  quantidade          numeric(14,3) NOT NULL,
  valor_unitario      numeric(12,2) NOT NULL,
  desconto_percentual numeric(6,3) NOT NULL DEFAULT 0,
  total               numeric(12,2) NOT NULL,
  ordem               integer NOT NULL DEFAULT 0
);
```

`status` (nosso, não o do Bling): `rascunho`, `enviado`, `aprovado`,
`nao_aprovado`, `convertido`, `cancelado`.
Mapeamento para a situação do Bling:

| `quotes.status` | situação no Bling |
|---|---|
| `rascunho` | `Rascunho` |
| `enviado` | `Pendente` |
| `aprovado` | `Aprovado` |
| `nao_aprovado` | `Não aprovado` |
| `convertido` | `Aprovado` |
| `cancelado` | `Não aprovado` |

Por que guardar `discount_value` sempre em reais **e** `discount_unit` +
`discount_input`: o valor em reais é o que vai para o Bling e para o total; o par
unidade+entrada é o que a tela precisa reexibir na edição, para o vendedor não ver
"10" virar "57,10" ao reabrir um desconto que ele digitou como 10%.

Índices: `quotes(lead_id)`, `quotes(created_by)`, `quotes(quoted_at DESC)`,
`quotes(status)`, `quote_items(quote_id)`.
RLS: `ENABLE ROW LEVEL SECURITY` nas duas, com policy de `SELECT` para
`authenticated, service_role USING (true)` — igual a `sale_items`. O escopo real
por vendedor é aplicado na API (§8), que é como `sales` já funciona hoje.

Trigger `updated_at` reaproveitando a função que a migration do Bling já criou.

---

## 4. Backend — `backend/app/quotes/`

Módulo novo. Todo cálculo de dinheiro em `Decimal`, reaproveitando
`backend/app/bling/orders.py` (`_dec`, `_money`, `item_total`, `apply_discount`,
`build_installments`, `parse_terms`) — a divisão de parcelas TEM que ser idêntica
à da venda, senão o Bling recusa por diferença de centavo.

### `proposals.py`

```python
def quote_total(itens, *, discount_value: Decimal, freight: Decimal) -> Decimal
    # subtotal (itens já com desconto de item) - desconto de cabeçalho + frete

def resolve_discount(subtotal, *, unidade: str, valor) -> Decimal
    # PERCENTUAL -> subtotal * valor/100 ; REAL -> valor. Nunca maior que o subtotal.

def build_proposal_payload(*, contact_id, quoted_at, itens, discount_value,
                           freight, freight_mode, method_id, terms, seller_id,
                           store_id, situacao, notes, internal_notes,
                           aos_cuidados_de) -> dict

async def create_proposal(client, *, ...) -> dict
    # POST /propostas-comerciais -> {data:{id}}
    # depois GET /propostas-comerciais/{id} para capturar `numero`.
    # O GET é best-effort: falhou, grava numero=None e segue (o PDF cai no id).

async def update_proposal(client, *, proposal_id, ...) -> None    # PUT

async def set_situacao(client, *, proposal_id, situacao: str) -> None
    # PATCH /propostas-comerciais/{id}/situacoes
```

O frete entra no total **e é parcelado junto** — é o valor que o cliente vai
pagar. `outrasDespesas` não é usado; o frete viaja em `transporte.frete`.

### `pdf.py`

```python
def build_quote_pdf(quote: dict, items: list[dict], *, seller: dict | None) -> bytes
```

reportlab (`platypus`), A4, retorna os bytes. Sem I/O de rede, sem acesso a banco
— recebe tudo pronto, para ser testável direto.

### `router.py` — prefixo `/api/quotes`

| Endpoint | Corpo / resposta | Regras |
|---|---|---|
| `POST /api/quotes` | `QuoteIn` → `201 {id, bling_proposal_id, bling_proposal_number, total}` | 409 se o contato não resolver (mesmo contrato do `POST /api/bling/orders`) |
| `PUT /api/quotes/{id}` | `QuoteIn` → `200` | **409** se `status='convertido'` |
| `PATCH /api/quotes/{id}/status` | `{status}` → `200` | valida a transição; espelha no Bling |
| `POST /api/quotes/{id}/convert` | → `201 {sale_id, bling_order_id}` | **409** se já convertido |
| `GET /api/quotes/{id}/pdf` | `application/pdf` | `Content-Disposition: attachment; filename="orcamento-{numero}.pdf"` |

`QuoteIn` (espelha `OrderIn` do router do Bling, mais os campos novos):

```python
class QuoteItemIn(BaseModel):
    bling_product_id: int
    codigo: str | None = None
    descricao: str
    unidade: str | None = None
    quantidade: float
    valor_unitario: float
    desconto_percentual: float = 0

class QuoteIn(BaseModel):
    lead_id: str
    deal_id: str | None = None
    conversation_id: str | None = None
    quoted_at: str                      # YYYY-MM-DD
    created_by: str | None = None       # e-mail do vendedor
    items: list[QuoteItemIn]
    discount: dict | None = None        # {"valor": 10, "unidade": "PERCENTUAL"|"REAL"}
    freight: float = 0
    freight_mode: int | None = None
    payment: dict                       # {"method_id": int, "terms": [30,60]}
    notes: str = ""
    internal_notes: str = ""
```

Registrar o router em `backend/app/main.py` junto com os outros.

### Conversão (`POST /api/quotes/{id}/convert`)

Ordem obrigatória — a venda nasce **antes** do PATCH de situação:

1. Lê a `quotes`. Se `status = 'convertido'`, `409`.
2. Chama `app.bling.orders.create_order` com os itens e as parcelas do orçamento
   (mesma chave de idempotência que a venda já usa). Isso cria o pedido no Bling,
   grava `sales` + `sale_items` e move o deal para `fechado_ganho`.
3. `set_situacao(proposal_id, "Aprovado")`. **Se falhar, não desfaz a venda** —
   loga e devolve `201` com `{"situacao_sync": false}`.
4. `UPDATE quotes SET status='convertido', sale_id=…, converted_at=now()`.

Se o passo 3 fosse antes do 2, uma falha na criação do pedido deixaria uma
proposta marcada como aprovada sem venda nenhuma — mentira no ERP.

---

## 5. Frontend

### Rotas proxy — `frontend/src/app/api/quotes/`

Seguem o padrão de `frontend/src/app/api/bling/orders/route.ts`: repassam para o
FastAPI e **preservam o status tal qual**.

- `POST /api/quotes` e `GET /api/quotes` (o GET é local, ver abaixo)
- `PUT|GET /api/quotes/[id]`
- `PATCH /api/quotes/[id]/status`
- `POST /api/quotes/[id]/convert`
- `GET /api/quotes/[id]/pdf` — repassa o corpo binário e os headers
- `GET /api/quotes/metrics`

`GET /api/quotes` e `GET /api/quotes/metrics` consultam o Supabase direto pelo
Next (padrão de `frontend/src/app/api/sales/route.ts`), porque precisam do escopo
por vendedor e de `quote_items` embutido.

### `frontend/src/lib/quote-state.ts` — lógica pura, testada

A suíte do frontend não tem runner de DOM; tudo que pode dar errado mora aqui.

```ts
export interface QuoteDiscount { valor: number; unidade: "REAL" | "PERCENTUAL" }

export function resolveDiscount(subtotal: number, d: QuoteDiscount): number
export function quoteSubtotal(linhas: OrderLine[]): number
export function quoteTotal(subtotal: number, descontoEmReais: number, frete: number): number
export function buildQuotePayload(linhas: OrderLine[], meta: QuoteMeta): QuotePayloadResult
export function linesFromQuoteItems(items: QuoteItem[] | null): OrderLine[]
```

Reaproveita `OrderLine`, `blankLine`, `addLine`, `removeLine`, `updateLine`,
`applyProduct`, `lineTotal` de `@/lib/bling-order-state` e `itemTotal`,
`orderTotal`, `buildInstallments`, `parseTerms` de `@/lib/bling`.

**Paridade obrigatória com o backend**, com teste dedicado: `resolveDiscount` e
`quoteTotal` no TS têm que dar exatamente o mesmo resultado que
`resolve_discount` e `quote_total` no Python, incluindo o arredondamento em
centavos. É a mesma regra que `bling.ts` já documenta para as parcelas.

### `QuoteCreateModal` — `frontend/src/components/quotes/quote-create-modal.tsx`

Reaproveita `BlingOrderForm` (busca no catálogo, linhas de item, desconto por
item) e `BlingContactResolver` (409 de contato). Acrescenta:

- desconto do pedido: campo numérico + alternador `R$` / `%`
- frete: valor + modalidade (0 CIF, 1 FOB, 2 Terceiros, 3 Próprio remetente,
  4 Próprio destinatário, 9 Sem transporte)
- observações (vão para o PDF e para o Bling) e observação interna (só Bling)
- resumo à direita: subtotal, desconto, frete, total, e as parcelas calculadas

Em edição, carrega as linhas com `linesFromQuoteItems` — mesmo motivo do
`linesFromSaleItems`: o PUT no Bling substitui os itens pelo que estiver no
formulário, e nascer com uma linha em branco apagaria os itens no ERP.

### `/conversas` — aba Perfil

Em `frontend/src/components/conversas/tabs/crm-perfil-tab.tsx`, **uma seção
"Orçamentos" logo abaixo da seção "Vendas"**, no mesmo padrão visual: rótulo,
botão de ação à direita e a lista dos últimos 3.

O botão **"Fazer Orçamento"** usa contorno (não o verde sólido de "Registrar
Venda") para não competir com a ação principal. Cada orçamento da lista mostra
número, valor, situação e um atalho para o PDF.

### `/orcamento` — `frontend/src/app/(authenticated)/orcamento/page.tsx`

Espelha a estrutura de `/vendas`:

- **4 cards de indicador:** Orçamentos no período · Valor total proposto ·
  Taxa de aprovação · Ticket médio. Os quatro respeitam o filtro de vendedor,
  como foi corrigido em `/vendas` no commit `85598b89`.
- **Filtros:** período, situação, busca por cliente, vendedor (só para admin).
- **Tabela:** Nº · Cliente · Vendedor · Data · Itens · Total · Situação · ações.
- **Ações por linha:** baixar PDF, editar (some depois de convertido), marcar
  aprovado / não aprovado, converter em venda.

Item novo na sidebar (`frontend/src/components/sidebar.tsx`), logo depois de
"Vendas".

---

## 6. Etapa nova no funil

`pipeline_stages.key` só é preenchido em `fechado_ganho` e `fechado_perdido`; as
demais etapas são livres e variam por funil (funis são por usuário neste sistema).
Então a etapa nova precisa de **key própria** para o comportamento ser
determinístico em vez de adivinhado por posição.

- **key:** `proposta_enviada`
- **label:** `Proposta Enviada`
- **posição:** `order_index` da `fechado_ganho` daquele funil; a `fechado_ganho`
  e tudo depois dela desce uma casa.

> **Premissa assumida, sujeita a correção:** o funil padrão já tem uma etapa
> "Proposta" (sem key) na terceira posição. Criar outra com o mesmo rótulo
> deixaria duas colunas idênticas no Kanban, então a nova se chama **"Proposta
> Enviada"**. Se o desejado era reposicionar a "Proposta" existente em vez de
> criar uma etapa, é uma mudança pequena na migration.

A migration insere a etapa em **todo funil que tenha uma `fechado_ganho`**, e é
idempotente (não insere se já existir `key='proposta_enviada'` naquele funil).
`DEFAULT_STAGES` em `frontend/src/app/api/pipelines/route.ts` e `DEAL_STAGES` em
`frontend/src/lib/constants.ts` ganham a etapa, para funis novos já nascerem com
ela.

**Regra de movimentação:** ao criar um orçamento, o deal vai para
`proposta_enviada`. Nunca anda para trás — se já estiver em `fechado_ganho`,
`fechado_perdido` ou em qualquer etapa de `order_index` maior, não mexe.

---

## 7. O PDF

`GET /api/quotes/{id}/pdf`, gerado com reportlab no backend. A4, retrato, uma
página sempre que couber; a tabela de itens quebra para a página seguinte
repetindo o cabeçalho.

**Cabeçalho** — logo (`frontend/public/logocanastra.png`, copiado para
`backend/app/quotes/assets/logocanastra.png`) à esquerda; à direita
`ORÇAMENTO Nº {numero}` e a data. Abaixo, os dados da empresa:

```
Boaventura Cafés Especiais Ltda
CNPJ 24.252.228/0001-37
Rua Nivaldo Guerreiro Nunes 701 · Distrito Industrial · Uberlândia/MG · 38402-330
comercial@cafecanastra.com · cafecanastra.com
```

**Cliente:** razão social, CPF/CNPJ, e-mail, WhatsApp, e "A/C" quando houver.

**Itens:** Código · Descrição · Un · Qtd · Valor unit. · Desc. % · Total.

**Totais:** Subtotal · Desconto · Frete · **TOTAL** (o desconto e o frete só
aparecem quando diferentes de zero).

**Pagamento:** forma + prazos + cada parcela com vencimento e valor.

**Observações:** o texto de `notes`, quando houver. `internal_notes` **nunca**
entra no PDF.

**Rodapé:** `Vendedor: {nome} · {e-mail}` e as duas cláusulas fixas, textualmente:

> Preços sujeitos a alteração sem aviso prévio.
>
> Tributos sob a venda já incluídos (não incluído possíveis diferenças de
> alíquotas de ICMS, consulte seu contador pois depende do seu regime tributário
> e das regras de seu estado).

**Sem "válido até"** — decisão 3.

Tipografia: Helvetica (embutida no reportlab). A fonte da marca (Saans) não está
no repositório; se o `.ttf` aparecer, trocar é uma linha.

Paleta: preto `#111111` para texto, `#7b7b78` para rótulos, `#dedbd6` para
filetes — os mesmos tokens do `DESIGN.md`, para o documento não destoar do CRM.

---

## 8. Escopo por vendedor

Reaproveita `frontend/src/lib/sales/sales-scope.ts` e
`sales-scope-route.ts`, que a entrega anterior já colocou em produção. A regra
para `quotes` é mais simples que a de `sales`: **`created_by = e-mail do usuário`**,
sem a exceção de `origin='bling'` (não existe orçamento importado — decisão 17).

Admin vê tudo e ganha o filtro de vendedor. Os quatro cards de indicador
respeitam o filtro, como já foi corrigido em `/vendas`.

---

## 9. Testes

**Backend** (`backend/tests/`):

- `test_quotes_payload.py` — `build_proposal_payload`: campos obrigatórios,
  `readOnly` nunca enviados, frete em `transporte`, situação inicial `Rascunho`.
- `test_quotes_discount.py` — `resolve_discount` em R$ e em %, desconto maior que
  o subtotal, arredondamento de centavo.
- `test_quotes_total.py` — subtotal, desconto, frete; parcelas fechando exato com
  o total (a última absorve o resto), incluindo o frete.
- `test_quotes_router.py` — 409 ao editar convertido, 409 ao converter duas
  vezes, ordem venda→situação na conversão, PATCH de situação inválida.
- `test_quotes_pdf.py` — smoke: bytes começam com `%PDF`, o texto contém o CNPJ
  da empresa e as cláusulas fixas, e **não** contém `internal_notes`.
- `test_quotes_create_number.py` — POST devolve só `{data:{id}}`; o `numero` vem
  do GET seguinte; GET falhando não derruba a criação.

**Frontend** (`vitest`):

- `quote-state.test.ts` — subtotal/desconto/frete/total, `resolveDiscount` nas
  duas unidades, `linesFromQuoteItems` preservando itens na edição.
- `quote-state-parity.test.ts` — paridade explícita com os números do backend
  (mesma tabela de casos usada no teste Python).
- `bling-contact-form.test.ts` — atualizar para o e-mail obrigatório.

---

## 10. Riscos e pontos a validar em produção

1. **`desconto` do cabeçalho é um número puro na proposta comercial**, sem o par
   `{valor, unidade}` que o pedido de venda usa (`VendasDescontoDTO`). A leitura
   mais provável é que seja **em reais**, porque o campo irmão `outrasDespesas`
   claramente é. O código converte `%` para reais antes de enviar e registra o
   que foi digitado. **Precisa de uma chamada real para confirmar** — se estiver
   errado, o desconto sai multiplicado por cem ou dividido por cem no ERP.
2. **Permissão "Propostas Comerciais"** no app do Bling e **reautorização do
   OAuth**. Sem isso todos os endpoints respondem 403. Fica pronto e inerte até o
   usuário fazer (decisão 18).
3. **`reportlab`** é dependência Python nova. Wheel puro (`reportlab>=4.2,<5`),
   sem biblioteca de sistema — não muda o Dockerfile.
4. **`BLING_STORE_ID` não está definido** no `.env`. `loja` é opcional no POST, e
   o código só envia quando a variável existir.
5. **E-mail obrigatório no contato** muda um fluxo que já está em produção (o
   registro de venda). Cadastro que hoje passa sem e-mail vai passar a ser
   recusado no formulário.

---

## 11. Fora de escopo

- Envio do PDF por WhatsApp (decidido: só download).
- Sincronizar propostas criadas direto no Bling.
- Validade / expiração automática.
- Prazo de entrega e garantia nos campos do Bling.
- `outrasDespesas`, `dataProximoContato`, `introducao`, `totalOutrosItens`,
  transportadora e volumes.
- Excluir proposta no Bling (`DELETE`) — o cancelamento é feito por situação.
