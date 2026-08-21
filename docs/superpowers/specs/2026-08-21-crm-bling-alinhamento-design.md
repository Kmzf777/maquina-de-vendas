# Alinhamento CRM ↔ Bling — design

Data: 21/08/2026
Antecessor: `2026-08-18-crm-bling-integracao-design.md` (a integração em si)

## Por que esta spec existe

A integração de 18/08 foi mergeada, deployada e — depois da correção do índice
parcial (commit `09497172`) — funciona no sentido **ERP → CRM**: pedido criado no
Bling vira venda no CRM, com itens, valor e lead resolvido.

O sentido **CRM → Bling** nunca funcionou em produção, e não por acaso: o modal de
venda decide o modo assim,

```ts
// frontend/src/components/sales/sale-create-modal.tsx:93
const blingMode = !!blingEnabled && !isEditing;
```

e **nenhum dos quatro chamadores passa `blingEnabled`** — `painel-vendas/page.tsx`,
`deals/deal-detail-sidebar.tsx`, `conversas/contact-detail.tsx` e
`leads/lead-detail-modal.tsx`. `blingMode` é sempre `false`. As 1.568 linhas de
`sale-create-modal.tsx` + `bling-order-form.tsx` + `bling-contact-resolver.tsx`
estão implementadas e são inalcançáveis. Nenhum teste cobre esse modo.

Além disso, três superfícies que o usuário espera não existem: leads não mostram
nada sobre o vínculo com o Bling, não há tela de catálogo, e editar uma venda é
operação puramente local.

## Princípio

Com o Bling ligado e conectado, ele é a **fonte da verdade** de pedido, produto e
contato. O CRM não inventa o que o Bling deve conhecer.

A única exceção é deliberada e delimitada: uma edição que o Bling recusar pode
valer no CRM, mas a venda fica **marcada como divergente**, com o diff registrado.
Divergência silenciosa é o que a integração existe para evitar — se o CRM diz
R$ 500 e o Bling diz R$ 400, comissão e relatório passam a ter duas verdades.
Marcar torna a escolha auditável em vez de invisível.

## Fase A — Ligar o modo Bling no modal

Novo hook `frontend/src/hooks/use-bling-status.ts`, no padrão dos 16 hooks
existentes: busca `/api/bling/status` uma vez e compartilha o resultado entre os
consumidores. Os quatro chamadores passam `blingEnabled` a partir dele.

Sem o hook, cada chamador faria a própria chamada e a regra de "o que conta como
ligado" ficaria duplicada em quatro lugares — a mesma razão pela qual
`config.is_configured()` existe como fonte única no backend.

### Estados de carregamento e falha

Esta é a parte opinativa, e a razão está no bug que a fase corrige.

| Estado | Comportamento |
|---|---|
| Carregando | Modal abre com submit desabilitado. Nenhum dos dois modos é renderizado ainda. |
| `enabled: true` | Modo Bling. Produto sai do catálogo espelhado. |
| `enabled: false` | Modo legado (texto livre), como hoje. |
| Falha na chamada | Mensagem explícita e **registro bloqueado**. |

Cair no modo legado quando a chamada falha reintroduz exatamente o defeito que
esta fase conserta, só que intermitente e invisível: venda avulsa entraria no CRM
sem ninguém perceber. Falha de rede é transitória; venda gravada fora do ERP é
permanente.

`isEditing` continua forçando o modo legado nesta fase — a edição só passa a
falar com o Bling na Fase E.

## Fase B — Superfície Bling nos leads

Seção "Bling" em `lead-detail-modal.tsx`:

- **Vinculado** (`bling_contact_id` presente): selo, dados do espelho (razão
  social, CNPJ, telefone, e-mail, endereço), link para o contato no Bling, botão
  "Desvincular".
- **Sem vínculo**: botão "Vincular…", que busca em `bling_contacts` por nome ou
  documento e grava a escolha.

Backend ganha `GET /api/bling/contacts/search?q=`, sobre o **espelho** e nunca
sobre a API do Bling — o campo dispara a cada tecla, mesma razão de
`GET /api/bling/products`. Reaproveita `_termo_seguro()` para neutralizar os
caracteres que compõem a sintaxe do filtro `or` do PostgREST.

`POST /api/bling/contacts/link` já existe. O desvincular entra como
`POST /api/bling/contacts/unlink` com `lead_id` — verbo próprio em vez de `link`
com nulo, porque desvincular tem consequência diferente de vincular: a próxima
venda daquele lead volta a cair na resolução por documento, e um `null` acidental
no payload de `link` não pode ser capaz de apagar vínculo em silêncio.

Na lista de leads, selo de origem quando `channel === 'bling'` — `ensure_lead` já
grava esse valor e `metadata.origem = 'bling_webhook'`, então não há migration.

Leads vindos do ERP continuam **sem deal** (decisão D7 da spec anterior, mantida):
aparecem em `/leads` com o selo, não no Kanban.

## Fase C — Nome da situação do pedido

`sales.bling_situacao_nome` é declarada na spec anterior e consumida pelo frontend
como rótulo principal do status,

```ts
// frontend/src/lib/sale-display.ts
return { label: sale.bling_situacao_nome || "Registrada", tone: "neutral" };
```

mas **nenhuma task do plano anterior a preenche** — `grep -rn bling_situacao_nome
backend/app/` não devolve nada. Toda venda do Bling aparece como "Registrada".

A causa é uma suposição errada da spec anterior (linha 493: "`GET
/pedidos/vendas/{id}` para obter `numero` e `situacao` já resolvidos"). A API real
não resolve nada:

```json
"situacao": { "id": 6, "valor": 0 }
```

O payload do webhook idem. O nome só sai de `/situacoes/modulos/{idModulo}`, que
hoje devolve **403** — o escopo de Situações não está no aplicativo.

Desenho: nova tabela `bling_situacoes (id, nome, modulo_id, synced_at)`, no padrão
dos outros quatro espelhos (PK do Bling, `synced_at`, RLS com SELECT para
`authenticated`), alimentada por `sync_situacoes()` dentro de `sync_all`.
`upsert_from_bling` e `create_order` passam a preencher `bling_situacao_nome` por
consulta ao espelho, ao lado do `bling_situacao_id` que já gravam.

**Pré-requisito de execução:** o formato real da resposta de `/situacoes/modulos`
precisa ser observado antes de escrever o mapeamento. Codificar contra suposição
foi exatamente o que produziu este defeito. A task correspondente começa provando
a resposta, e só então escreve o parser.

## Fase D — Tela de produtos

Página nova `/produtos` (não existe hoje), somente leitura sobre `bling_products`:
código, nome, preço, unidade, saldo virtual, situação. Busca por nome/código e
filtro por situação.

O endpoint atual não serve: `GET /api/bling/products` fixa `situacao = 'A'` e tem
teto de 200 linhas, porque nasceu para um combobox. A tela precisa de um endpoint
irmão com paginação real e sem o filtro fixo.

Cuidado herdado: PostgREST corta em 1.000 linhas por padrão. Com 535 produtos hoje
isso não morde, mas a paginação tem que ser explícita para não virar truncamento
silencioso quando o catálogo crescer.

## Fase E — Editar venda reflete no Bling

`BlingClient.put()` existe (`client.py:201`) e nunca foi usado. Não há endpoint de
update no router.

Backend ganha `update_order()` em `orders.py` e `PUT /api/bling/orders/{order_id}`
no router, reaproveitando `build_order_payload`.

Duas colunas em `sales`:

```sql
ALTER TABLE sales ADD COLUMN IF NOT EXISTS bling_divergent  boolean NOT NULL DEFAULT false;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS bling_divergence jsonb;
```

`bling_divergence` guarda os campos que diferem e quando divergiram.

Fluxo da edição:

1. CRM envia a alteração ao Bling.
2. **Aceito** → grava local, `bling_divergent = false`, `bling_divergence = null`.
3. **Recusado** (4xx do Bling, tipicamente pedido já faturado) → mostra a mensagem
   original do Bling e pergunta se quer salvar só no CRM.
4. Confirmando → grava local, `bling_divergent = true`, `bling_divergence` com o
   diff e o carimbo de tempo.

Erro transitório (5xx, timeout, rate limit) **não** é recusa: cai no caminho de
retentativa já existente, sem marcar divergência. Só recusa de validação marca.
A distinção é a mesma que `TRANSIENT` já faz no `POST /orders` — repetir payload
inválido nunca conserta, e rajada de erro conta para o bloqueio de IP do Bling.

Na tabela de vendas, selo de divergência; no detalhe, o diff.

## Testes

O modo Bling do modal tem 1.568 linhas e nenhum teste. Cada fase entra por TDD:
teste que falha primeiro, código depois.

Prioridade para os caminhos que nunca rodaram contra nada:

- Fase A: os quatro estados do hook, com ênfase em **falha não cair no modo legado**.
- Fase B: busca com termo que contém vírgula/parêntese (sintaxe do `or` do
  PostgREST); desvincular.
- Fase C: situação ausente do espelho não pode quebrar a projeção do pedido.
- Fase D: paginação além da primeira página.
- Fase E: recusa de validação marca divergência; erro transitório **não** marca.

Dublês de Supabase não modelam inferência de `ON CONFLICT` — a lição do
`42P10`. Toda migration desta spec é aplicada e verificada contra o Postgres real
antes de a fase ser considerada pronta.

## Ordem de entrega

**A → C → B → D → E.**

A primeiro porque destrava o uso real. C logo depois por ser pequena e depender de
ação no painel do Bling (marcar o escopo e reconectar). E por último por ser a de
maior risco e a única que grava no ERP por um caminho novo.

## Fora de escopo

- Criar deal para lead vindo do ERP (D7 mantida).
- Sincronizar estoque em tempo real (o webhook de `product` já cobre o espelho).
- `sales.status = 'pendente_bling'`: segue caminho morto, como documentado na spec
  anterior.
