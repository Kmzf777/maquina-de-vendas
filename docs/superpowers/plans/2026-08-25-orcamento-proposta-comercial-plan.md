# Orçamento (Proposta Comercial Bling) — plano de implementação

Spec: `docs/superpowers/specs/2026-08-25-orcamento-proposta-comercial-design.md`
Referência da API: `docs/reference/bling-propostas-comerciais.openapi.json`
Branch: `feat/orcamento-proposta-comercial`

Execução em duas ondas de subagentes, com propriedade de arquivo exclusiva por
tarefa — nenhum arquivo é editado por duas tarefas da mesma onda.

**Regra para toda tarefa de frontend:** invocar a skill `frontend-design` antes
de escrever qualquer componente, e usar os primitivos shadcn que já existem em
`frontend/src/components/ui/`.

**Regra para toda tarefa:** TDD — teste antes da implementação. A suíte do
frontend é de lógica pura (não há runner de DOM): tudo que pode dar errado mora
em `src/lib` e é testado lá; componente é casca de renderização.

---

## Onda 1 — sem dependências entre si

### T1. Migration + etapa nova do funil

**Arquivos:** `supabase/migrations/20260825_quotes.sql` (novo),
`frontend/src/app/api/pipelines/route.ts`, `frontend/src/lib/constants.ts`

1. Tabelas `quotes` e `quote_items` conforme §3 da spec, com índices, RLS e
   trigger de `updated_at`.
2. Etapa nova em todo funil que tenha `fechado_ganho`: `key='proposta_enviada'`,
   label `'Proposta Enviada'`, `order_index` da `fechado_ganho`; a
   `fechado_ganho` e as posteriores descem uma casa. Idempotente: não insere se
   já houver `key='proposta_enviada'` naquele funil.
3. `DEFAULT_STAGES` e `DEAL_STAGES` ganham a etapa na posição correta.
4. A migration **não** é aplicada por deploy — fica pendente para o usuário rodar
   no Supabase. Registrar isso no cabeçalho do arquivo, como as migrations
   anteriores fazem.

### T2. PDF do orçamento

**Arquivos:** `backend/app/quotes/__init__.py`, `backend/app/quotes/pdf.py`,
`backend/app/quotes/assets/logocanastra.png`, `backend/requirements.txt`,
`backend/tests/test_quotes_pdf.py`

1. `reportlab>=4.2,<5` em `requirements.txt`.
2. Copiar `frontend/public/logocanastra.png` para os assets do backend.
3. `build_quote_pdf(quote, items, *, seller) -> bytes` conforme §7 da spec. Sem
   rede, sem banco — recebe dicionários prontos.
4. Testes: bytes começam com `%PDF`; o texto extraído contém o CNPJ da empresa,
   as duas cláusulas fixas e o nome do vendedor; **não** contém `internal_notes`;
   desconto e frete só aparecem quando diferentes de zero.

### T3. Lógica pura do orçamento no frontend

**Arquivos:** `frontend/src/lib/quote-state.ts`,
`frontend/src/lib/quote-state.test.ts`,
`frontend/src/lib/quote-state-parity.test.ts`,
`frontend/src/lib/types.ts` (só acrescentar `Quote` e `QuoteItem`)

Conforme §5 da spec. Reaproveita `bling-order-state.ts` e `bling.ts` — não
duplicar cálculo de item nem de parcela. A tabela de casos do teste de paridade
tem que ser a mesma usada em `backend/tests/test_quotes_total.py` (T5); combinar
os valores agora e deixá-los comentados no topo dos dois arquivos.

### T4. E-mail obrigatório na criação de contato Bling

**Arquivos:** `frontend/src/lib/bling-contact-form.ts`,
`frontend/src/lib/bling-contact-form.test.ts`,
`frontend/src/components/sales/bling-contact-resolver.tsx`

1. `email` passa a ser obrigatório em `buildContactPayload`, com validação de
   formato, e o erro entra em `errors.email`.
2. O formulário marca o campo como obrigatório e exibe o erro.
3. Vale para **todo** fluxo que cria contato, inclusive o registro de venda que
   já está em produção — é o pedido explícito do usuário (decisão 6).
4. Invocar `frontend-design` antes de mexer no componente.

---

## Onda 2 — depende da onda 1

### T5. Backend: propostas comerciais + router

**Depende de:** T1 (esquema), T2 (assinatura de `build_quote_pdf`)
**Arquivos:** `backend/app/quotes/proposals.py`, `backend/app/quotes/router.py`,
`backend/app/main.py`, `backend/tests/test_quotes_payload.py`,
`backend/tests/test_quotes_discount.py`, `backend/tests/test_quotes_total.py`,
`backend/tests/test_quotes_router.py`,
`backend/tests/test_quotes_create_number.py`

Conforme §4 da spec. Pontos que não podem escapar:

- Dinheiro em `Decimal`; reaproveitar `app/bling/orders.py` para item, desconto e
  parcelas. Nada de reimplementar divisão de parcela.
- O `201` do POST devolve **só `{data:{id}}`**; o `numero` vem de um `GET`
  seguinte, best-effort.
- Frete entra no total e é parcelado junto.
- Conversão: venda **antes** do PATCH de situação; falha no PATCH não desfaz a
  venda, devolve `situacao_sync: false`.
- `409` ao editar convertido e ao converter duas vezes.
- Só envia `loja` quando `BLING_STORE_ID` existir.
- Campos `readOnly` (`id`, `total`, `totalProdutos`) nunca vão no corpo.

### T6. Frontend: página `/orcamento` + rotas proxy + sidebar

**Depende de:** T3 (lib), T5 (contrato da API)
**Arquivos:** `frontend/src/app/(authenticated)/orcamento/page.tsx`,
`frontend/src/app/api/quotes/**`, `frontend/src/components/quotes/quotes-table.tsx`,
`quotes-filters.tsx`, `quotes-metrics-cards.tsx`,
`frontend/src/hooks/use-quotes.ts`, `frontend/src/components/sidebar.tsx`,
`frontend/src/lib/quotes/quotes-scope.ts` + teste

Conforme §5 e §8 da spec. Espelhar a estrutura de `/vendas` e reaproveitar
`sales-scope.ts` como modelo do escopo (a regra de `quotes` é só
`created_by = e-mail`, sem a exceção de `origin='bling'`). Os quatro cards de
indicador respeitam o filtro de vendedor. Invocar `frontend-design` e usar
shadcn.

### T7. Frontend: modal de orçamento + entrada em `/conversas`

**Depende de:** T3 (lib), T5 (contrato da API)
**Arquivos:** `frontend/src/components/quotes/quote-create-modal.tsx`,
`frontend/src/components/conversas/tabs/crm-perfil-tab.tsx`,
`frontend/src/components/conversas/contact-detail.tsx`,
`frontend/src/hooks/use-lead-quotes.ts`

Conforme §5 da spec. Reaproveitar `BlingOrderForm` e `BlingContactResolver` em
vez de recriar a montagem de itens. Seção "Orçamentos" logo abaixo de "Vendas" na
aba Perfil, com o botão **"Fazer Orçamento"** em contorno. Invocar
`frontend-design` e usar shadcn.

---

## Fechamento (eu, depois das ondas)

1. `cd frontend && npm test && npm run type-check && npm run lint`
2. `cd backend && python -m pytest`
3. Revisar as costuras entre as tarefas (contrato da API, paridade de números).
4. Commit por tarefa, mensagem em português, sem PR (fluxo do `CLAUDE.md`).
5. **Não dar push** — o push vai para `master` e dispara deploy de produção.
   Depende de: migration `20260825_quotes.sql` aplicada no Supabase, permissão
   "Propostas Comerciais" liberada no app do Bling e OAuth reautorizado.

---

## Pendências do usuário (não são código)

1. Aplicar `supabase/migrations/20260825_quotes.sql` no Supabase.
2. Liberar a permissão **Propostas Comerciais** no app do Bling e refazer o OAuth.
3. Confirmar se `desconto` na proposta comercial é em reais (risco 1 da spec) —
   validar com uma proposta real depois do item 2.
4. Confirmar o rótulo da etapa nova: **"Proposta Enviada"** (premissa da §6).
