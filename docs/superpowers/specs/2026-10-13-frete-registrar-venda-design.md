# Frete no "Registrar venda" — design

Cartão: "Teste 1: Na aba de registrar venda não tem o campo de frete" (BEEINSIDE CANSTRA CRM, id 1a586e44).

## Problema

Nas palavras do Rafael: "Na aba de registrar venda não tem o campo de frete."

O modal **Registrar venda** do CRM (`frontend/src/components/sales/sale-create-modal.tsx`, modo Bling via
`bling-order-form.tsx`) só tem itens, conta, forma de pagamento e prazos. O modal de **Orçamento** já tem
"Frete (R$)" + "Modalidade do frete", e o backend já sabe pôr frete no pedido de venda
(`build_order_payload(freight=, freight_mode=)` → `transporte.frete` / `transporte.fretePorConta`, somado ao total
e às parcelas por `order_net_total`). O que falta é a tela de venda e a rota `OrderIn` (POST/PUT
`/api/bling/orders`) repassarem esse valor. Resultado hoje: venda com frete gera pedido/nota e `sales.value`
abaixo do combinado.

Hoje 100% das vendas do CRM em produção passam pelo Bling (11 de 11), então o modo manual (sem Bling) fica de fora.

## Decisões (Rafael)

1. Campo igual ao do orçamento: **valor em R$ + modalidade** (opcional; mesmas opções de `FREIGHT_MODES`:
   0, 1, 2, 3, 4, 9).
2. **Guardar o frete na venda** (colunas novas em `sales`), para a edição já abrir preenchida e o PUT no Bling não
   apagar o frete.

## O que muda

### Banco (Supabase)
- Migração nova `supabase/migrations/20261013_sales_freight.sql`, só aditiva:
  `ALTER TABLE sales ADD COLUMN IF NOT EXISTS freight numeric(12,2) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS freight_mode smallint;` (mesmo tipo de `quotes`). Vendas antigas ficam com 0/null.

### Backend (`backend/app/bling/`)
- `router.py` — `OrderIn` ganha `freight: float = 0` e `freight_mode: int | None = None`, validados como no
  orçamento (negativo → recusa/0 via `normalize_freight`; modalidade fora de `MODALIDADES_FRETE` → 422).
  POST repassa para `create_order` (inclusive no caminho da fila `jobs.enqueue`); PUT repassa para `update_order`.
- `orders.py` — `update_order` aceita e repassa `freight`/`freight_mode` ao `build_order_payload`.
  `create_order` grava `freight` e `freight_mode` na linha de `sales` (o `value` já inclui o frete via
  `order_net_total`).
- `jobs.py` — o job `create_order` carrega os dois campos (kwargs já vão inteiros; conferir no teste).
- Conversão de orçamento em venda (`quotes/router.py`) já passa frete para `create_order`; com a mudança acima a
  venda convertida também passa a guardar `freight`/`freight_mode`.

### Frontend (`frontend/src/`)
- `components/sales/bling-order-form.tsx` — bloco opcional "Frete (R$)" + "Modalidade do frete" (mesmo visual e
  componentes do orçamento), ligado por prop (ex.: `freight` habilitado só no Registrar venda; o orçamento continua
  com o seu próprio campo). A previsão de parcelas e o total passam a somar o frete.
- `lib/bling-order-state.ts` — `buildOrderPayload` inclui `freight`/`freight_mode` no payload e no total/parcelas
  (frete entra depois dos itens, mesma regra do backend).
- `components/sales/sale-create-modal.tsx` — na edição, nasce com `editingSale.freight`/`freight_mode`; o que
  atualiza `sales` após o PUT também grava frete e `value` com frete.
- Rotas proxy `app/api/bling/orders/**` repassam o JSON inteiro (conferir no teste que o campo chega).
- Tipo `Sale` ganha `freight`/`freight_mode`.

## Como testar

- **Backend (pytest):** `OrderIn` com frete → `create_order` recebe frete; payload tem `transporte.frete` e
  parcelas somando frete; linha de `sales` tem `freight`, `freight_mode` e `value` com frete; `update_order` com
  frete monta o mesmo `transporte`; sem frete o payload não ganha `transporte` (regressão); modalidade inválida → 422.
- **Frontend (vitest):** form mostra os campos no Registrar venda; total/parcelas somam o frete; payload enviado
  leva `freight`/`freight_mode`; edição abre com o frete gravado.
- **Ponta a ponta na produção, depois do deploy:** registrar uma venda de teste com frete numa conta Bling,
  conferir no Bling o pedido com frete/modalidade e total certo, conferir `sales.freight`/`value` por SELECT,
  editar e ver o frete mantido. Print do modal com o campo. Combinar com o Rafael qual lead/pedido de teste usar e
  como cancelar o pedido de teste no Bling.

## Como publicar

1. Aplicar a migração na VPS (`supabase_db`, psql) **antes** do deploy — é só `ADD COLUMN IF NOT EXISTS`, não
   apaga nada.
2. Fluxo do CLAUDE.md do ValerIA: branch `agente/1a586e44`, `git pull origin master`, e
   `git push origin agente/1a586e44:master` **só com autorização do Rafael** (dispara o GitHub Actions de deploy:
   canastra_api/worker e frontend).
3. Conferir `docker service ls`/logs depois do deploy e rodar o teste ponta a ponta.

## Fora do escopo

- Modo manual (sem Bling) do Registrar venda.
- Descobrir o frete de vendas antigas (ficam com 0). Se alguém editar uma venda antiga cujo frete foi lançado à mão
  direto no Bling, o PUT continua sobrescrevendo, como já acontece hoje.
- Desconto de cabeçalho na venda e qualquer mudança no modal de orçamento.
- Cálculo automático de frete por região (`pricing.py`): o vendedor digita o valor.
