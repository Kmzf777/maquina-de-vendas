# Preços da ValerIA editáveis em /produtos — Design

Data: 23/09/2026 · Status: aprovado pelo usuário

## Problema

A ValerIA oferta preços da tabela `products` (Supabase), injetada no prompt como
`<catalogo_de_produtos>` por `backend/app/agent/catalog.py` e lida também pela tool
`calcular_orcamento`. Nenhuma tela edita essa tabela: ela foi semeada por script em
18/06/2026. Trocar um preço exige SQL em produção.

A auditoria de 23/09/2026 também mostrou que o exemplo `R$23,90` em
`prompts/base.py` vaza como preço real (3 leads, último em 17/09). Se o modal existir
mas o prompt continuar com um preço de exemplo, a ValerIA não "segue o modal".

## Escopo

Dentro:
- Botão **"Preços da ValerIA"** em /produtos, visível só para admin.
- Modal com os itens ATIVOS de `products` (hoje 32: Atacado 26, Private Label 6),
  agrupados por setor, com um campo de preço por item.
- Salvar grava `products.price_formatted` e `updated_at`.
- A ValerIA passa a usar o valor novo em até 60 s.
- Tirar o preço de exemplo (`R$23,90`) dos prompts.

Fora (decisão do usuário): lote mínimo, ativar/desativar, criar/remover item,
frete, pedido mínimo, Kit Amostra, histórico de alterações.

## Arquitetura (abordagem A)

```
/produtos (admin) ──botão──> ValeriaPrecosModal
      │ GET/PATCH
      ▼
/api/admin/valeria-catalog  (requireAdmin + service role)
      │ grava price_formatted "R$ 1.234,56"
      ▼
Supabase products ──(TTL 60s)──> catalog.py ──> prompt + calcular_orcamento
```

O CRM grava direto no banco. O backend não ganha endpoint: o cache em memória de
`catalog.py` cai de 300 s para 60 s. Como o catálogo está no prefixo estático do
prompt, uma troca de preço só invalida o context cache uma vez.

A rota fica sob `/api/admin/`, que já está no `matcher` do `proxy.ts` e em
`ADMIN_API_PREFIXES`. Não precisa de rota nova de primeiro nível.

## Contrato da API

`GET /api/admin/valeria-catalog`
- 200 `{ data: CatalogItem[] }`, só `is_active = true`, ordenado por `sector`, `name`.
- `CatalogItem = { id: string; sector: string; name: string; preco: number | null; price_formatted: string | null }`.
  `preco` é o `price_formatted` convertido para número. Se o texto não puder ser
  convertido, vem `null` (a linha aparece com o campo vazio).

`PATCH /api/admin/valeria-catalog`
- Body `{ itens: { id: string; preco: number }[] }`.
- 400 quando: `itens` vazio ou não é array; `id` repetido; `preco` não finito, ≤ 0,
  > 99.999 ou com mais de 2 casas decimais.
- 404 quando algum `id` não existe ou está inativo (nada é gravado).
- Grava tudo num único `upsert` (uma instrução só: tudo ou nada), repetindo as
  colunas lidas da linha para satisfazer NOT NULL e trocando só `price_formatted` e
  `updated_at`.
- 200 `{ data: CatalogItem[] }` com os itens atualizados.
- 401/403 via `requireAdmin`.

## Formato do preço

Canônico: `R$ ` + milhar com `.` + decimal com `,` + sempre 2 casas, com espaço
ASCII comum (NÃO `Intl`/`toLocaleString`, que insere U+00A0). Exemplos: `R$ 28,70`,
`R$ 1.169,70`. É o formato que já existe no banco e o que `pricing.parse_brl` lê.

Entrada no modal aceita `28,70`, `28.70`, `28,7`, `1.169,70`, `1169,70` e `R$ 28,70`.

## Interface

- Botão no cabeçalho de /produtos, à direita do título, só para `role === "admin"`
  (`useCurrentRole`).
- Modal: título "Preços da ValerIA", subtítulo explicando que são os valores que a
  ValerIA oferece. Uma seção por setor, e em cada linha o nome e um input em R$.
- Linha alterada fica destacada. Input inválido fica vermelho e bloqueia o Salvar.
- Rodapé: "A ValerIA passa a usar os novos valores em até 1 minuto" · Cancelar ·
  "Salvar (N)", desabilitado quando N = 0.
- Erro ao salvar: o modal continua aberto, mantém as edições e mostra a mensagem.
  Sucesso: fecha e mostra uma confirmação.
- Visual segue a paleta existente da página (`#faf9f6`, `#dedbd6`, `#111111`, `#7b7b78`).

## Backend

- `catalog.py`: `_CACHE_TTL_SECONDS = 60` (comentário atualizado: o preço agora é
  editado pelo CRM).
- `prompts/base.py` (linhas 771, 772, 779, 783, 1081) e `prompts/voice_card.py:52`:
  trocar `23,90` por um marcador que não é preço (`R$XX,XX`), mantendo a regra que
  cada exemplo ensina (R$ maiúsculo, formato da frase).

## Testes

- Frontend (vitest, arquivos `.test.ts` em ambiente node):
  - lib de formatação/parse: casos canônicos, milhar, entrada com ponto ou vírgula,
    lixo → `null`, ida e volta.
  - rota: 401/403 repassados, 400 para cada validação, 404 para id inexistente,
    PATCH grava o formato canônico e só as colunas esperadas.
  - diff do modal: detecta só linhas alteradas e as inválidas.
- Backend (pytest):
  - TTL = 60.
  - Nenhum arquivo em `app/agent/prompts/` contém `23,90`.
  - As suítes existentes de prompt/catálogo continuam verdes.
