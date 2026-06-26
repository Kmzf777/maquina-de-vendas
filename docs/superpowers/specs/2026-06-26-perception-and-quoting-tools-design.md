# Tools de Percepção + Orçamento Determinístico (Feature 2)

**Data:** 2026-06-26
**Feature:** Roadmap de Autonomia #2 — `consultar_relacionamento` + `calcular_orcamento`
**Status:** Design aprovado (decisões confirmadas)

---

## 1. Problema

Dois comportamentos da Valéria custam conversão:

1. **Trata cliente ativo como desconhecido:** roda o funil de lead novo (qualificação,
   fotos, pitch) com quem já compra. O sinal `lead_is_customer` existe mas é passivo — a IA
   não tem como *perguntar* "esse lead já é cliente? o que ele já comprou?" no início.
2. **Alucina matemática de preço:** ao somar pedidos, aplicar frete e checar pedido mínimo,
   o LLM erra contas e inventa condições. As regras de frete vivem como **texto estático no
   prompt** (`atacado.py`), o que polui o contexto e ainda assim não impede o erro de cálculo.

**Objetivo:** dar à IA (a) uma tool de **percepção** que consulta o relacionamento real do
lead e (b) uma tool de **orçamento determinístico** que faz o cálculo em código Python, e
**proibir** a IA de calcular preços de cabeça.

---

## 2. Estado atual (grounding)

| Peça | Onde | Papel |
|---|---|---|
| Preços de produto | tabela DB `products` (`price_formatted` TEXT, ex. `"R$ 97,70"`; `min_lot` TEXT) | **Fonte de verdade viva**, mantida por ops, cacheada 5min, injetada como `<catalogo_de_produtos>` (`agent/catalog.py`) |
| Frete + pedido mínimo | **texto estático em `atacado.py`** (seção `## FRETE`) | Regra de negócio presa no prompt — sai nesta entrega |
| Sinal de cliente | `leads.service.lead_has_active_relationship()` (consulta `sales` + `deals` ganho/tratativa) | Já existe; hoje só vira flag passiva `lead_is_customer` |
| Vendas | tabela DB `sales` (`product`, `value` numeric, `sold_at`, ...) | Fonte da "última compra" |
| Despacho de tools | `tools.execute_tool(name, args, lead_id, phone, conversation_id)` (cadeia if/elif, retorna `str`) | `lead_id` é injetado pelo runtime, **não** vem do LLM |
| Tools por stage | `tools.get_tools_for_stage(stage)` | allowlist por stage |

**Decisões confirmadas:**
- **D1 — Fonte de preço:** `calcular_orcamento` lê o preço-base do **DB `products`**
  (parseando `price_formatted`). Fonte única, zero drift. Só frete/pedido-mínimo/cálculo
  viram código.
- **D2 — Escopo:** **atacado apenas** (frete e pedido mínimo só existem definidos para
  atacado). Private Label fica para entrega futura.

### Revisão de arquitetura (blockers desta versão)

- **B1 — Paradoxo do carrinho:** orçar **um único produto** quebra a semântica do pedido
  mínimo (R$300 é do PEDIDO inteiro, não do item). → o input vira um **carrinho**
  (`list[PedidoItem]`); o subtotal global é somado ANTES de aplicar frete/mínimo.
- **B2 — Bloqueio de Uberlândia:** "sem estado → trava" é falho. Uberlândia é override de
  **cidade**. → se `estado` é nulo mas `cidade` é um override válido, o cálculo prossegue
  (flat R$15) sem exigir o estado. A trava só vale quando NÃO há nem estado nem cidade-override.
- **B3 — Gatilho da percepção:** a IA não pode depender só do `<crm_data>`. → `base.py`
  instrui a chamar `consultar_relacionamento` também em termos de recompra ("repor", "novo
  pedido", etc.) ou em qualquer suspeita de cliente antigo.
- **P1 — Overhead:** `parse_brl` roda **só** nos produtos que deram match (não na base toda).
- **P2 — Desambiguação controlada:** >1 match → devolve no máximo **TOP 5** (nunca 50 itens,
  pra não estourar o contexto do Gemini).

---

## 3. Dados de negócio extraídos (a serem movidos para código)

### Frete e pedido mínimo (de `atacado.py` → `app/agent/pricing.py`)

| Região (key) | Pedido mínimo | Frete | Frete grátis a partir de |
|---|---|---|---|
| `sul_sudeste` | R$ 300,00 | R$ 55,00 | R$ 900,00 |
| `centro_oeste` | R$ 300,00 | R$ 65,00 | R$ 1.000,00 |
| `nordeste` | R$ 300,00 | R$ 75,00 | R$ 1.200,00 |
| `norte` | R$ 300,00 | R$ 85,00 | R$ 1.500,00 |
| **Uberlândia** (cidade, override) | sem mínimo | R$ 15,00 | (sem faixa de grátis — flat) |

> A faixa de frete e o pedido mínimo são avaliados sobre o **subtotal de produtos**
> (não sobre o total com frete).

### Mapa UF → macrorregião (IBGE; `sul` e `sudeste` compartilham a faixa `sul_sudeste`)

- **Norte:** AC, AP, AM, PA, RO, RR, TO
- **Nordeste:** AL, BA, CE, MA, PB, PE, PI, RN, SE
- **Centro-Oeste:** DF, GO, MT, MS
- **Sudeste→`sul_sudeste`:** ES, MG, RJ, SP
- **Sul→`sul_sudeste`:** PR, RS, SC

Uberlândia (cidade, UF=MG) é override de cidade: frete R$15, sem pedido mínimo.

Preços de produto: **não** são copiados para cá — vêm do DB em tempo de cálculo.

---

## 4. Arquitetura proposta

Novo módulo isolado `app/agent/pricing.py` (lógica de negócio pura + Pydantic), consumido por
`tools.py`. Mantém `tools.py` enxuto e a regra comercial unit-testável sem rede.

### 4.1 `app/agent/pricing.py`

```python
FREIGHT_TABLE: dict[str, FreightRule]   # as 4 regiões acima
UF_TO_REGION: dict[str, str]            # UF → key de FREIGHT_TABLE
UBERLANDIA_FREIGHT = 15.0
MAX_DISAMBIGUATION = 5                   # P2: TOP 5 no máximo

class PedidoItem(BaseModel):            # B1: item de carrinho
    produto: str
    quantidade: int = Field(gt=0)

class OrcamentoInput(BaseModel):        # tipagem (Pydantic) — CARRINHO
    itens: list[PedidoItem] = Field(min_length=1)
    estado: str | None = None           # sigla UF (ex. "SP"); opcional
    cidade: str | None = None           # override de cidade (ex. "Uberlândia"); opcional

class LineQuote(BaseModel):            # linha resolvida do carrinho
    produto: str                        # nome do catálogo (match)
    quantidade: int
    preco_unitario: float
    subtotal_linha: float

def parse_brl(s: str) -> float           # "R$ 97,70" → 97.70  (puro)
def resolve_region(estado, cidade) -> tuple[str|None, bool]  # (region_key, is_uberlandia) (puro)
def match_products(produto, products) -> list[dict]          # match normalizado (puro)
def compute_quote(lines: list[LineQuote], region_key, is_uberlandia) -> Quote  # MATH (puro)
def format_quote(quote: Quote) -> str    # breakdown legível, item a item (puro)
```

`compute_quote` (núcleo determinístico, 100% testável — **itera o carrinho, B1**):
- `subtotal = sum(linha.subtotal_linha for linha in lines)`  ← subtotal GLOBAL do pedido
- `is_uberlandia` → `frete = 15.0`, **sem** checagem de mínimo
- senão: `abaixo_minimo = subtotal < rule.pedido_minimo`;
  `frete = 0.0 if subtotal >= rule.gratis_acima else rule.frete`
- `total = subtotal + frete`
- retorna `Quote(lines, subtotal, frete, total, frete_gratis, abaixo_minimo, pedido_minimo, region_key)`

`resolve_region` (B2): normaliza `cidade`; se for override conhecido (Uberlândia) → `(None, True)`
mesmo com `estado=None`. Senão mapeia `estado`(UF)→região. Sem estado E sem cidade-override →
`(None, False)` (o caller então pede o estado).

### 4.2 `tools.consultar_relacionamento` (percepção)

- **Sem args do LLM** — usa o `lead_id` injetado. (Schema com `properties: {}`.)
- Lógica em `leads.service.get_relationship_summary(lead_id) -> str`:
  - última venda em `sales` (order `sold_at` desc, limit 1) →
    `"CLIENTE ATIVO. Última compra: {product} (R$ {value}) em {DD/MM/YYYY}. Trate como
    reabastecimento/upsell — NÃO requalifique."`
  - senão, se `lead_has_active_relationship()` →
    `"CLIENTE ATIVO / em tratativa (sem venda detalhada registrada). NÃO rode funil de lead novo."`
  - senão → `"SEM histórico de compra — tratar como lead novo."`
  - fail-soft → string neutra ("não foi possível consultar agora").

### 4.3 `tools.calcular_orcamento` (orçamento determinístico — CARRINHO)

- Valida args com `OrcamentoInput` (Pydantic, `itens: list[PedidoItem]`) → erro de validação
  vira string clara p/ a IA.
- Busca produtos ativos do setor **atacado** UMA vez; para **cada item** do carrinho roda
  `match_products`:
  - 0 match → `"Produto '<x>' não encontrado no catálogo de atacado. Confirme o nome."`
  - >1 match → `"Para '<x>', especifique qual: <TOP 5 nomes>."` (P2: máx. 5; NUNCA chuta)
  - 1 match → `parse_brl(price_formatted)` **só nesse match** (P1) → vira `LineQuote`.
  - qualquer item irresolvido aborta o cálculo e devolve a pergunta de desambiguação.
- Resolução de região (B2): `resolve_region(estado, cidade)`.
  - `is_uberlandia=True` (mesmo sem estado) → calcula com frete flat R$15.
  - sem região E sem override → devolve subtotal global + checagem de mínimo +
    `"me confirme o estado pra eu calcular o frete"` (sem inventar frete).
  - região resolvida → `compute_quote(lines, region_key, is_uberlandia)`.
- `format_quote` → breakdown item a item + subtotal global, frete/“grátis”, total e aviso de
  pedido mínimo.
- Fail-soft: qualquer exceção → string segura instruindo a IA a encaminhar pro João.

### 4.4 Integração de schema e stages

- Adicionar `consultar_relacionamento` e `calcular_orcamento` a `TOOLS_SCHEMA` (JSON schema p/
  o Gemini; descrições fortes). `calcular_orcamento` recebe `itens` como **array de objetos**
  `{produto, quantidade}` (carrinho) + `estado`/`cidade` opcionais.
- `get_tools_for_stage`:
  - `consultar_relacionamento`: **todos** os stages comerciais (`secretaria`, `atacado`,
    `private_label`, `exportacao`, `consumo`) — pode ser cliente retornando em qualquer um.
  - `calcular_orcamento`: **`atacado`** (escopo D2).

---

## 5. Atualização dos prompts

### `atacado.py`
- **Remover** a seção `## FRETE` inteira (tabela estática) e as instruções de "monte frases
  com os valores do catálogo / como apresentar preços manualmente".
- **Adicionar** regra dura: *"Para QUALQUER pergunta de preço, valor de pedido, frete, total
  ou pedido mínimo, você DEVE chamar `calcular_orcamento` e informar EXATAMENTE o resultado.
  É PROIBIDO somar, multiplicar, estimar ou inventar qualquer valor de cabeça. Se faltar a
  quantidade ou o estado, pergunte antes de calcular."*
- O `<catalogo_de_produtos>` continua (nomes, descrições, fotos e como **fonte do preço-base**
  que a tool lê) — só deixa de ser o canal de cálculo.

### `base.py`
- Regra universal (B3): *"Chame `consultar_relacionamento` ANTES de qualificar se: o
  `<crm_data>`/`<lead_memory>` indicar que o lead pode já ser cliente; OU o lead usar termos de
  recompra ('repor', 'novo pedido', 'mais um pedido', 'de novo', 'sempre compro'); OU houver
  QUALQUER suspeita de cliente antigo. Não rode o funil de lead novo com cliente ativo."*
  + reforço de que cálculo de preço (total, frete, pedido mínimo) é SEMPRE via
  `calcular_orcamento` — proibido somar/estimar de cabeça.

---

## 6. Testes (TDD)

`app/agent/pricing.py` (puro, sem rede):
1. `parse_brl`: `"R$ 97,70"`→97.70; `"R$ 1.169,70"`→1169.70; lixo → erro tratável.
2. `resolve_region`: `"SP"`→`sul_sudeste`; `"BA"`→`nordeste`; `"GO"`→`centro_oeste`;
   `"AM"`→`norte`; `cidade="Uberlândia"` **sem estado** → `(None, True)` (B2);
   sem estado e sem cidade → `(None, False)`; UF inválida → `(None, False)`.
3. `compute_quote` — **carrinho, cálculos exatos** (B1):
   - **multi-itens**: subtotal = soma das linhas; mínimo aplicado ao subtotal GLOBAL.
   - subtotal global abaixo do mínimo → `abaixo_minimo=True`.
   - subtotal ≥ faixa → `frete=0`, `frete_gratis=True`.
   - subtotal < faixa → frete da região; total correto.
   - Uberlândia → frete 15, sem `abaixo_minimo`.
4. `match_products`: match exato/normalizado (acento/caixa); 0, 1 e >1 matches; >5 → corta no
   TOP 5 (P2).
5. `format_quote`: item a item + subtotal, frete, total e aviso de mínimo quando aplicável.

`tools` / `leads.service` (fake supabase):
6. `get_relationship_summary`: com venda → "CLIENTE ATIVO. Última compra…"; sem venda mas
   relacionamento ativo → mensagem de tratativa; nada → "lead novo"; fail-soft.
7. `execute_tool("calcular_orcamento", …)`:
   - **carrinho multi-itens** → breakdown somado correto.
   - item ambíguo → desambiguação (máx. 5).
   - `cidade="Uberlândia"` sem estado → calcula (frete 15), NÃO pede estado (B2).
   - sem estado e sem cidade → subtotal + pede estado.
   - valida via Pydantic (`itens` vazio → erro tratável).
8. `get_tools_for_stage`: `calcular_orcamento` em atacado; `consultar_relacionamento` em todos.
9. Schemas em `TOOLS_SCHEMA` bem-formados (array `itens` de objetos) para o Gemini.

Rodar a suíte completa (sem regressão em `test_agent_tools`, `test_catalog`, orchestrator).

---

## 7. Escopo / YAGNI

**Dentro:** `pricing.py`, as duas tools, `get_relationship_summary`, limpeza do `atacado.py`,
regra nos prompts, testes.

**Fora:** Private Label/exportação no `calcular_orcamento` (D2); coluna numérica de preço em
`products` (parseamos o texto por ora); proposta em PDF; pesquisa de CNPJ online; desconto por
volume (Feature 4, decisão de negócio).

---

## 8. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Drift preço código×DB | Lê do DB `products` (fonte única) — D1 |
| `price_formatted` em formato inesperado | `parse_brl` tolerante (R$, espaços, milhar `.`, decimal `,`); erro → fail-soft "confirmo com o João" |
| Match de produto errado/ambíguo | Nunca chuta: 0/≥2 matches → pede confirmação/desambiguação |
| IA ainda calcular de cabeça | Regra dura no prompt + tool obrigatória; frete sai do prompt (não há mais tabela pra ela "ler e somar") |
| Frete inventado sem região | `estado` ausente → tool pede o estado, não inventa |
| Exceção quebra o turno | Toda tool é fail-soft (retorna string segura) |
| Pedido mínimo aplicado por item (B1) | Carrinho `list[PedidoItem]`; mínimo sobre o subtotal GLOBAL |
| Cliente de Uberlândia travado pedindo estado (B2) | Override de cidade calcula sem exigir estado |
| Saída da tool estoura contexto do Gemini (P2) | Desambiguação limitada a TOP 5 |
| Parse caro na base toda (P1) | `parse_brl` só nos matches |

---

## 9. Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `backend/app/agent/pricing.py` | **novo** — Pydantic + frete/UF + cálculo puro |
| `backend/app/agent/tools.py` | +2 tools no `TOOLS_SCHEMA`, dispatch e `get_tools_for_stage` |
| `backend/app/leads/service.py` | **novo** `get_relationship_summary(lead_id)` |
| `backend/app/agent/prompts/valeria_outbound/atacado.py` | remove `## FRETE` + regras manuais de preço; add regra "use calcular_orcamento" |
| `backend/app/agent/prompts/base.py` | regra: usar `consultar_relacionamento`; preço sempre via tool |
| `backend/tests/test_pricing.py` | **novo** |
| `backend/tests/test_perception_quoting_tools.py` | **novo** |
