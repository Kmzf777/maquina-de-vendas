# Plano de Implementação — Tools de Percepção + Orçamento Determinístico (Feature 2)

Spec: `docs/superpowers/specs/2026-06-26-perception-and-quoting-tools-design.md` (LER para detalhes).

## Orientação

Backend FastAPI em `backend/`. Testes com pytest (`asyncio_mode = auto`), rodar de `backend/`:
`python -m pytest tests/<arquivo> -q`. Fakes de Supabase: ver `tests/test_cold_funnel_reflex_2026_06_25.py`
(padrão `_Query`/`FakeSupabase`) e `tests/test_agent_summary.py` (LLM mock). TDD obrigatório:
escrever teste, ver falhar (RED), implementar (GREEN).

## Global Constraints (vinculантes — o reviewer usa como lente)

- **Frete (valores EXATOS, sobre o subtotal GLOBAL de produtos):**
  - sul_sudeste: pedido mínimo R$300, frete R$55, grátis ≥ R$900
  - centro_oeste: pedido mínimo R$300, frete R$65, grátis ≥ R$1000
  - nordeste: pedido mínimo R$300, frete R$75, grátis ≥ R$1200
  - norte: pedido mínimo R$300, frete R$85, grátis ≥ R$1500
  - Uberlândia (override de cidade): frete flat R$15, SEM pedido mínimo, sem faixa de grátis.
- **UF→região (IBGE):** Norte=AC,AP,AM,PA,RO,RR,TO; Nordeste=AL,BA,CE,MA,PB,PE,PI,RN,SE;
  Centro-Oeste=DF,GO,MT,MS; Sudeste(→sul_sudeste)=ES,MG,RJ,SP; Sul(→sul_sudeste)=PR,RS,SC.
- **D1:** preço-base SEMPRE lido do DB `products` (parse de `price_formatted`), NUNCA hardcoded.
- **D2:** escopo atacado apenas.
- **B1:** input de orçamento é CARRINHO (`list[PedidoItem]`); mínimo aplicado ao subtotal global.
- **B2:** Uberlândia calcula sem exigir estado.
- **P1:** `parse_brl` só nos produtos que deram match.
- **P2:** desambiguação devolve no máximo TOP 5.
- **Fail-soft:** toda tool/serviço retorna string segura em erro, nunca levanta para o runtime.
- Tools retornam `str`. `lead_id` é injetado pelo `execute_tool`, não vem do LLM.

---

## Task 1 — `app/agent/pricing.py` (lógica pura + Pydantic) + testes

**Objetivo:** módulo isolado, sem rede, com a matemática determinística do orçamento.

**Arquivos:** criar `backend/app/agent/pricing.py`, `backend/tests/test_pricing.py`.

**API (ver spec §4.1):**
- `FREIGHT_TABLE`, `UF_TO_REGION`, `UBERLANDIA_FREIGHT=15.0`, `MAX_DISAMBIGUATION=5`.
- Pydantic: `PedidoItem(produto: str, quantidade: int>0)`, `OrcamentoInput(itens: list[PedidoItem] min 1, estado: str|None, cidade: str|None)`, `LineQuote(produto, quantidade, preco_unitario, subtotal_linha)`, `Quote(lines, subtotal, frete, total, frete_gratis, abaixo_minimo, pedido_minimo, region_key)`.
- `parse_brl(s)->float`: `"R$ 97,70"`→97.70, `"R$ 1.169,70"`→1169.70; valor inválido → `ValueError`.
- `resolve_region(estado, cidade)->tuple[str|None,bool]`: cidade Uberlândia (normalizada) → `(None, True)` mesmo sem estado; senão UF→região; inválido/ausente → `(None, False)`.
- `match_products(produto, products)->list[dict]`: match por substring normalizada (sem acento, caixa baixa); corta no TOP 5.
- `compute_quote(lines: list[LineQuote], region_key, is_uberlandia)->Quote`: subtotal = soma das linhas; Uberlândia→frete 15 sem mínimo; senão abaixo_minimo se subtotal<mínimo, frete grátis se subtotal≥faixa senão frete da região; total=subtotal+frete.
- `format_quote(quote)->str`: breakdown item a item + subtotal, frete (ou "grátis"), total, aviso de mínimo quando aplicável.

**Testes (ver spec §6 itens 1-5):** parse_brl (3 casos), resolve_region (SP/BA/GO/AM/Uberlândia-sem-estado/inválido), compute_quote (carrinho multi-item somando subtotal global; abaixo do mínimo; frete grátis na faixa; frete cobrado; Uberlândia flat), match_products (0/1/>1/>5→top5), format_quote (contém subtotal/frete/total/aviso).

**Aceite:** `python -m pytest tests/test_pricing.py -q` verde; nenhum preço de produto hardcoded.

---

## Task 2 — `leads.service.get_relationship_summary(lead_id)` + testes

**Objetivo:** resumo do relacionamento p/ a tool de percepção.

**Arquivos:** editar `backend/app/leads/service.py`; criar `backend/tests/test_relationship_summary.py`.

**API (ver spec §4.2):** `get_relationship_summary(lead_id: str) -> str`:
- última venda em `sales` (select product,value,sold_at; order sold_at desc; limit 1) → `"CLIENTE ATIVO. Última compra: {product} (R$ {value}) em {DD/MM/YYYY}. Trate como reabastecimento/upsell — NÃO requalifique."`
- senão, se `lead_has_active_relationship(lead_id)` → `"CLIENTE ATIVO / em tratativa (sem venda detalhada registrada). NÃO rode funil de lead novo."`
- senão → `"SEM histórico de compra — tratar como lead novo."`
- fail-soft: exceção → `"Não foi possível consultar o relacionamento agora."`

**Testes (spec §6 item 6):** com venda; sem venda mas relacionamento ativo (mock `lead_has_active_relationship`); nada; fail-soft (supabase levanta). Usar fake supabase + patch.

**Aceite:** `python -m pytest tests/test_relationship_summary.py -q` verde.

---

## Task 3 — Wire das tools em `app/agent/tools.py` + testes

**Depende de:** Task 1 (`pricing`) e Task 2 (`get_relationship_summary`).

**Objetivo:** expor `consultar_relacionamento` e `calcular_orcamento` ao agente.

**Arquivos:** editar `backend/app/agent/tools.py`; criar `backend/tests/test_perception_quoting_tools.py`.

**Mudanças:**
- `TOOLS_SCHEMA`: +`consultar_relacionamento` (sem params: `properties:{}`, `required:[]`) e
  +`calcular_orcamento` (`itens`: array de objetos `{produto:string, quantidade:integer}` required; `estado`:string opcional; `cidade`:string opcional). Descrições fortes: orçamento é OBRIGATÓRIO p/ qualquer preço/total/frete; nunca calcular de cabeça.
- `execute_tool`: branch `consultar_relacionamento` → `get_relationship_summary(lead_id)`.
  branch `calcular_orcamento` → valida `OrcamentoInput`; busca produtos ativos setor atacado UMA vez (reutilizar leitura de `products`, ex. via `catalog._fetch_active_products` filtrando sector atacado OU query direta); por item: `match_products` (0→msg não encontrado; >1→desambiguação TOP5; 1→`parse_brl` só no match → LineQuote); `resolve_region`; se região/uberlandia → `compute_quote`+`format_quote`; se sem região e sem override → subtotal global + pedir estado; fail-soft.
- `get_tools_for_stage`: `consultar_relacionamento` em TODOS os stages comerciais (secretaria, atacado, private_label, exportacao, consumo); `calcular_orcamento` só em `atacado`.

**Testes (spec §6 itens 7-9):** carrinho multi-item (breakdown somado correto); item ambíguo→desambiguação (≤5); Uberlândia sem estado→calcula sem pedir estado; sem estado e sem cidade→pede estado; Pydantic inválido (itens vazio)→string de erro; `get_tools_for_stage` (calcular_orcamento só atacado; consultar_relacionamento em todos); schemas bem-formados. Mockar a busca de produtos e `get_relationship_summary`.

**Aceite:** `python -m pytest tests/test_perception_quoting_tools.py -q` verde; suíte `test_agent_tools.py` sem regressão.

---

## Task 4 — Prompts: limpar `atacado.py`, atualizar `base.py` + testes

**Depende de:** Task 3 (nomes das tools existem).

**Objetivo:** remover a tabela de frete suja do prompt e instruir o uso obrigatório das tools.

**Arquivos:** editar `backend/app/agent/prompts/valeria_outbound/atacado.py` e
`backend/app/agent/prompts/base.py`; criar/editar testes (`tests/test_prompt_feature2.py`).

**Mudanças (ver spec §5):**
- `atacado.py`: REMOVER a seção `## FRETE` inteira (tabela Sul/Sudeste/Centro-Oeste/Nordeste/Norte) e as instruções de "COMO APRESENTAR PREÇOS"/montar frases de preço manualmente. ADICIONAR regra dura: qualquer preço/total/frete/pedido mínimo → chamar `calcular_orcamento` e informar EXATAMENTE o resultado; proibido somar/multiplicar/estimar de cabeça; faltando quantidade ou estado, perguntar antes. Manter o resto (catálogo, etapas, objeções).
- `base.py`: regra (B3) instruindo a chamar `consultar_relacionamento` ANTES de qualificar quando crm_data/lead_memory sugerir cliente, OU termos de recompra ("repor","novo pedido","mais um pedido","de novo","sempre compro"), OU qualquer suspeita de cliente antigo; + reforço preço sempre via tool.

**Testes:** atacado prompt NÃO contém mais a tabela de frete (ex.: assert "frete gratis acima" not in prompt / "R$55" not in); contém instrução de usar `calcular_orcamento`. base_prompt contém "consultar_relacionamento" e termos de recompra. Não quebrar `test_base_prompt.py`.

**Aceite:** `python -m pytest tests/test_prompt_feature2.py tests/test_base_prompt.py -q` verde; suíte completa sem regressão.
