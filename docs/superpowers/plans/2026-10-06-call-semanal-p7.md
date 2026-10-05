# P7 — Preço na ValerIA de botões — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Os nós `N5` ("Clássico 250g") e `N5b` ("Suave 250g") voltam a mostrar preço: "a partir de R$ 28,70 a unidade no atacado." — o menor preço entre os SKUs que casam, quando todos são do mesmo produto-base.

**Architecture:** `preco_do_no` (`backend/app/button_flow/valeria_runner.py`) hoje corta a linha de preço com mais de 1 candidato. Passa a agrupar os candidatos por produto-base (nome sem "Moído"/"Em Grãos"/"Grãos", acento-insensível); um só produto-base → menor preço com o prefixo "a partir de"; mais de um → corta como hoje. Como o corpo do nó diz "gira em torno de {preco}", o `_resolver` passa a retirar o qualificador aprovado imediatamente antes de `{preco}` quando o valor já começa com "a partir de" — senão o lead leria "gira em torno de a partir de R$ 28,70".

**Tech Stack:** Python 3 / pytest (container `canastra-api`), `app.agent.pricing.match_products` + `parse_brl` (só leitura — `agent/pricing.py` **não** é editado).

**Spec:** `docs/superpowers/specs/2026-10-06-call-semanal-0110-design.md` (Diagnóstico item 8 e seção P7); `docs/superpowers/specs/2026-09-29-valeria-botoes-design.md` (nó N5: "preço sai do catálogo em tempo de envio, nunca do texto").

---

## Catálogo real (produção, `products`, `sector = 'Atacado'`, `is_active = true`, lido em 06/10/2026)

Relevantes para os testes (nomes e preços exatos):

| name | price_formatted |
|---|---|
| Canastra Canela — Moído 250g | R$ 28,70 |
| Canastra Clássico — Em Grãos 1kg | R$ 97,70 |
| Canastra Clássico — Em Grãos 250g | R$ 31,70 |
| Canastra Clássico — Em Grãos 500g | R$ 54,70 |
| Canastra Clássico — Moído 250g | R$ 28,70 |
| Canastra Clássico — Moído 500g | R$ 52,70 |
| Canastra Suave — Em Grãos 250g | R$ 31,70 |
| Canastra Suave — Moído 250g | R$ 28,70 |
| Granel Canastra Clássico — 2kg em grãos | R$ 169,70 |
| Granel Canastra Suave — 2kg em grãos | R$ 169,70 |
| Microlote — Em Grãos 250g | R$ 32,70 |
| Microlote — Moído 250g | R$ 32,70 |

`match_products("Clássico 250g", atacado)` → exatamente `Canastra Clássico — Moído 250g` e `Canastra Clássico — Em Grãos 250g` (os dois viram produto-base `canastra classico 250g`). Idem Suave.

## Arquivos

- Modify: `backend/app/button_flow/valeria_runner.py` — `preco_do_no` (≈ linhas 215-252), novo helper `_produto_base`, novo helper `_faixa_a_partir_de`, ajuste em `_resolver` (≈ linhas 187-212) e constantes perto de `_MARCADOR` (linha 138).
- Create: `backend/tests/test_cs_p7_preco_valeria.py` — testes do pacote.
- **Não** editar: `backend/app/agent/pricing.py`, `backend/app/button_flow/valeria_registry.py` (o corpo do N5/N5b continua "gira em torno de {preco} …", e continua certo para candidato único).

## Comando de teste (sempre com flock)

```bash
cd /root/crm-wt/cs-p7 && flock /root/crm-wt/_heavy.lock docker run --rm --user root \
  -v $PWD:/repo -w /repo/backend -e SUPABASE_URL=https://example.supabase.co \
  -e SUPABASE_SERVICE_KEY=ci-dummy canastra-api:latest sh -c \
  "pip install -q -r requirements-dev.txt >/dev/null 2>&1; python -m pytest -q -p no:cacheprovider tests/test_cs_p7_preco_valeria.py"
```

---

### Task 1: `preco_do_no` — "a partir de" para o mesmo produto-base

**Files:**
- Create: `backend/tests/test_cs_p7_preco_valeria.py`
- Modify: `backend/app/button_flow/valeria_runner.py` (imports, constantes, `preco_do_no`)

- [ ] **Step 1: Escrever os testes que falham**

`backend/tests/test_cs_p7_preco_valeria.py`:

```python
"""P7 — preço na ValerIA de botões (call de 01/10).

`{classico, 250g}` casa com DOIS SKUs ativos do atacado (Moído R$ 28,70 e Em
Grãos R$ 31,70) e o `preco_do_no` cortava a linha de preço com 2 candidatos: o
N5/N5b saíam sem preço nenhum. Decisão do dono (06/10): mostrar o MENOR preço com
"a partir de" quando os candidatos são o mesmo café em formatos diferentes.
Produtos-base diferentes continuam cortando a linha — essa é a regra Ritz.

O catálogo abaixo é cópia literal das linhas de `products` de produção
(sector "Atacado", is_active) lidas em 06/10/2026.
"""
import dataclasses
from unittest.mock import MagicMock, patch

import pytest

from app.button_flow import valeria_registry as reg
from app.button_flow import valeria_runner as runner


def _sku(nome, preco, setor="Atacado"):
    return {"sector": setor, "name": nome, "price_formatted": preco,
            "min_lot": None, "description": "", "image_urls": []}


CATALOGO = [
    _sku("Canastra Canela — Moído 250g", "R$ 28,70"),
    _sku("Canastra Clássico — Em Grãos 1kg", "R$ 97,70"),
    _sku("Canastra Clássico — Em Grãos 250g", "R$ 31,70"),
    _sku("Canastra Clássico — Em Grãos 500g", "R$ 54,70"),
    _sku("Canastra Clássico — Moído 250g", "R$ 28,70"),
    _sku("Canastra Clássico — Moído 500g", "R$ 52,70"),
    _sku("Canastra Suave — Em Grãos 250g", "R$ 31,70"),
    _sku("Canastra Suave — Moído 250g", "R$ 28,70"),
    _sku("Granel Canastra Clássico — 2kg em grãos", "R$ 169,70"),
    _sku("Granel Canastra Suave — 2kg em grãos", "R$ 169,70"),
    _sku("Microlote — Em Grãos 250g", "R$ 32,70"),
    _sku("Microlote — Moído 250g", "R$ 32,70"),
    # Mesmo nome em OUTRO setor e outro preço: o filtro de setor tem de valer.
    _sku("Canastra Clássico — Moído 250g", "R$ 39,90", setor="Varejo"),
]


@pytest.fixture
def catalogo():
    """Troca o catálogo do Supabase por uma lista fixa (o import é tardio)."""
    def _com(produtos):
        return patch("app.agent.catalog._fetch_active_products",
                     MagicMock(return_value=produtos))
    return _com


# ── preco_do_no ─────────────────────────────────────────────────────────────
def test_n5_classico_com_dois_formatos_mostra_a_partir_do_menor(catalogo):
    with catalogo(CATALOGO):
        assert runner.preco_do_no(reg.NOS["N5"]) == "a partir de R$ 28,70"


def test_n5b_suave_com_dois_formatos_mostra_a_partir_do_menor(catalogo):
    with catalogo(CATALOGO):
        assert runner.preco_do_no(reg.NOS["N5b"]) == "a partir de R$ 28,70"


def test_menor_preco_independe_da_ordem_do_catalogo(catalogo):
    with catalogo(list(reversed(CATALOGO))):
        assert runner.preco_do_no(reg.NOS["N5"]) == "a partir de R$ 28,70"


def test_candidato_unico_sai_sem_prefixo(catalogo):
    so_moido = [p for p in CATALOGO if p["name"] != "Canastra Clássico — Em Grãos 250g"]
    with catalogo(so_moido):
        assert runner.preco_do_no(reg.NOS["N5"]) == "R$ 28,70"


def test_produtos_base_diferentes_cortam_a_linha(catalogo):
    """"Moído 250g" casa Canela, Clássico, Suave e Microlote: cafés DIFERENTES.

    Cotar o menor deles seria cotar um café pelo preço de outro — a classe do
    incidente Ritz (drip cotado misturando com Microlote).
    """
    no = dataclasses.replace(reg.NOS["N5"], produto="Moído 250g")
    with catalogo(CATALOGO):
        assert runner.preco_do_no(no) == ""


def test_preco_ilegivel_corta_a_linha(catalogo):
    quebrado = [_sku("Canastra Clássico — Moído 250g", ""),
                _sku("Canastra Clássico — Em Grãos 250g", "R$ 31,70")]
    with catalogo(quebrado):
        assert runner.preco_do_no(reg.NOS["N5"]) == ""


def test_nenhum_candidato_continua_sem_preco(catalogo):
    with catalogo([_sku("Microlote — Moído 250g", "R$ 32,70")]):
        assert runner.preco_do_no(reg.NOS["N5"]) == ""


# ── produto-base ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("nome", [
    "Canastra Clássico — Moído 250g",
    "Canastra Clássico — Em Grãos 250g",
    "Canastra Classico - em graos 250g",
    "CANASTRA CLÁSSICO GRÃOS 250G",
])
def test_produto_base_ignora_formato_acento_e_pontuacao(nome):
    assert runner._produto_base(nome) == "canastra classico 250g"


def test_produto_base_distingue_cafes_diferentes():
    assert (runner._produto_base("Canastra Clássico — Moído 250g")
            != runner._produto_base("Canastra Suave — Moído 250g"))
```

- [ ] **Step 2: Rodar e ver falhar**

Rodar o comando de teste. Esperado: FAIL — `test_n5_*`/`test_n5b_*`/`test_menor_*` com `'' == 'a partir de R$ 28,70'`, e `test_produto_base_*` com `AttributeError: ... has no attribute '_produto_base'`.

- [ ] **Step 3: Implementar**

Em `backend/app/button_flow/valeria_runner.py`:

1. Imports: adicionar `import unicodedata` depois de `import re`.
2. Logo abaixo de `_MARCADOR = re.compile(r"\{[a-z_]+\}")`:

```python
# P7 (call de 01/10). O FORMATO do café (moído / em grãos) não muda o produto:
# "Canastra Clássico — Moído 250g" e "— Em Grãos 250g" são o mesmo café. Casado
# sobre o nome já sem acento e em caixa baixa (ver `_produto_base`).
_FORMATO_DO_CAFE = re.compile(r"\b(?:em\s+)?graos\b|\bmoido\b")
# Prefixo de quando o nó casa com vários formatos do MESMO café (decisão do dono,
# 06/10): mostra o menor preço, sem fingir que é o preço de todos.
PREFIXO_FAIXA = "a partir de"
```

3. Antes de `def preco_do_no`, os dois helpers:

```python
def _produto_base(nome: str) -> str:
    """O café sem o formato: "Canastra Clássico — Em Grãos 250g" -> "canastra classico 250g".

    Acento, caixa e pontuação não contam (o catálogo usa travessão; um SKU
    cadastrado com hífen não pode virar outro produto).
    """
    sem_acento = unicodedata.normalize("NFKD", nome or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c)).lower()
    return " ".join(re.findall(r"[a-z0-9]+", _FORMATO_DO_CAFE.sub(" ", sem_acento)))


def _faixa_a_partir_de(produto: str, candidatos: list[dict]) -> str:
    """"a partir de <menor preço>" se os candidatos são UM café; senão "".

    Cafés diferentes continuam sem preço: cotar o menor seria cotar um café pelo
    preço de outro (incidente Ritz). Preço ilegível também corta — melhor sem a
    linha do que um "a partir de" que não é o menor de verdade.
    """
    from app.agent.pricing import parse_brl
    bases = {_produto_base(p.get("name", "")) for p in candidatos}
    if len(bases) != 1:
        logger.info("%s produto %r casou com %d SKUs de %d cafés — entrega SEM preço",
                    _LOG, produto, len(candidatos), len(bases))
        return ""
    try:
        menor = min(candidatos,
                    key=lambda p: parse_brl(p.get("price_formatted") or ""))
    except ValueError as exc:
        logger.warning("%s preço ilegível entre os SKUs de %r — entrega SEM preço: %s",
                       _LOG, produto, exc)
        return ""
    return f"{PREFIXO_FAIXA} {menor['price_formatted'].strip()}"
```

4. Em `preco_do_no`, trocar o bloco final

```python
    if len(candidatos) != 1:
        logger.info("%s produto %r casou com %d SKUs ativos — entrega SEM preço",
                    _LOG, no.produto, len(candidatos))
        return ""
    return (candidatos[0].get("price_formatted") or "").strip()
```

por

```python
    if not candidatos:
        logger.info("%s produto %r não casou com SKU ativo — entrega SEM preço",
                    _LOG, no.produto)
        return ""
    if len(candidatos) == 1:
        return (candidatos[0].get("price_formatted") or "").strip()
    return _faixa_a_partir_de(no.produto, candidatos)
```

e acrescentar à docstring de `preco_do_no` o parágrafo:

```
    Exceção (P7, call de 01/10): vários candidatos que são o MESMO café em
    formatos diferentes ("Clássico 250g" = Moído R$ 28,70 + Em Grãos R$ 31,70)
    devolvem "a partir de <menor>" — ver `_faixa_a_partir_de`. Sem isso o N5 e
    o N5b saíam sem preço nenhum.
```

(e trocar "Match ÚNICO e DENTRO DO SETOR" por "Match ÚNICO (ou um café só) e DENTRO DO SETOR").

- [ ] **Step 4: Rodar e ver passar**

Mesmo comando. Esperado: todos PASS.

- [ ] **Step 5: Commit**

```bash
cd /root/crm-wt/cs-p7 && git add backend/app/button_flow/valeria_runner.py backend/tests/test_cs_p7_preco_valeria.py && git commit -m "feat(valeria-botoes): preço 'a partir de' quando o nó casa com formatos do mesmo café

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: o corpo não pode dizer "gira em torno de a partir de"

O corpo do N5/N5b é `gira em torno de {preco} a unidade no atacado.` Com o valor da Task 1 viraria "gira em torno de a partir de R$ 28,70". O `_resolver` retira o qualificador aprovado (lista fechada de `atacado.py`: "gira em torno de", "fica por volta de", "na faixa de", "por volta de") que precede imediatamente `{preco}` **só** quando o preço já começa com "a partir de". Candidato único continua com "gira em torno de R$ 28,70". O ajuste vale também para corpo editado na tela (`valeria_flow_content`), que passa pelo mesmo `_resolver`.

**Files:**
- Modify: `backend/tests/test_cs_p7_preco_valeria.py` (acrescentar)
- Modify: `backend/app/button_flow/valeria_runner.py` (`_resolver` e constante)

- [ ] **Step 1: Escrever os testes que falham** (acrescentar ao fim do arquivo)

```python
# ── o corpo que o lead lê ───────────────────────────────────────────────────
class ProvedorFalso:
    def __init__(self):
        self.chamadas = []

    async def send_interactive_buttons(self, to, body, buttons, image_url=None):
        self.chamadas.append(body)
        return {"messages": [{"id": "wamid.1"}]}


@pytest.fixture
def sem_foto(monkeypatch):
    monkeypatch.setattr(runner, "url_publica_da_foto", lambda _c: None)


@pytest.mark.asyncio
@pytest.mark.parametrize("no_id", ["N5", "N5b"])
async def test_corpo_com_faixa_nao_empilha_qualificador(no_id, catalogo, sem_foto):
    with catalogo(CATALOGO):
        contexto = {"preco": runner.preco_do_no(reg.NOS[no_id])}
    p = ProvedorFalso()
    await runner.enviar_no(p, "5534988861441", reg.NOS[no_id], contexto)
    corpo = p.chamadas[0]
    assert "a partir de R$ 28,70 a unidade no atacado." in corpo
    assert "gira em torno de a partir de" not in corpo
    assert "{preco}" not in corpo
    assert "gostaria de ser encaminhado ao vendedor?" in corpo


@pytest.mark.asyncio
async def test_preco_unico_mantem_o_qualificador(sem_foto):
    p = ProvedorFalso()
    await runner.enviar_no(p, "5534988861441", reg.NOS["N5"], {"preco": "R$ 28,70"})
    assert "gira em torno de R$ 28,70 a unidade no atacado." in p.chamadas[0]


@pytest.mark.parametrize("qualificador", [
    "gira em torno de", "fica por volta de", "na faixa de", "por volta de",
    "Gira em torno de",
])
def test_qualquer_qualificador_aprovado_sai_antes_da_faixa(qualificador):
    corpo = f"{qualificador} {{preco}} a unidade."
    texto = runner._resolver(corpo, {"preco": "a partir de R$ 28,70"})
    assert texto == "a partir de R$ 28,70 a unidade."


def test_qualificador_longe_do_marcador_fica():
    """Só sai o qualificador COLADO no {preco}; o resto do texto é do editor."""
    corpo = "o preço gira em torno de mercado.\nvalor: {preco}."
    texto = runner._resolver(corpo, {"preco": "a partir de R$ 28,70"})
    assert texto == "o preço gira em torno de mercado.\nvalor: a partir de R$ 28,70."
```

- [ ] **Step 2: Rodar e ver falhar**

Mesmo comando. Esperado: FAIL em `test_corpo_com_faixa_nao_empilha_qualificador[N5]`/`[N5b]` (corpo contém "gira em torno de a partir de") e em `test_qualquer_qualificador_aprovado_sai_antes_da_faixa` (5 casos). `test_preco_unico_mantem_o_qualificador` e `test_qualificador_longe_do_marcador_fica` já passam (guardas de regressão).

- [ ] **Step 3: Implementar**

Em `valeria_runner.py`, abaixo de `PREFIXO_FAIXA`:

```python
# Os qualificadores aprovados de `agent/prompts/.../atacado.py` ("Apresentacao de
# precos"). Com "a partir de" no valor, o qualificador colado ao `{preco}` sai —
# "gira em torno de a partir de R$ 28,70" não é português. Só o COLADO ao
# marcador: o resto do corpo é texto do editor e não se mexe.
_QUALIFICADOR_DO_PRECO = re.compile(
    r"\b(?:gira em torno de|fica por volta de|na faixa de|por volta de)\s+(?=\{preco\})",
    re.IGNORECASE,
)
```

Em `_resolver`, trocar

```python
    dados = {k: str(v) for k, v in (contexto or {}).items() if v}
    texto = flows.render(corpo or "", dados)
```

por

```python
    dados = {k: str(v) for k, v in (contexto or {}).items() if v}
    corpo = corpo or ""
    if dados.get("preco", "").startswith(PREFIXO_FAIXA):
        corpo = _QUALIFICADOR_DO_PRECO.sub("", corpo)
    texto = flows.render(corpo, dados)
```

e acrescentar à docstring de `_resolver`:

```
    Preço em faixa ("a partir de R$ 28,70", ver `preco_do_no`) já traz a sua
    própria ressalva: o qualificador colado ao `{preco}` sai, para o lead não
    ler "gira em torno de a partir de".
```

Nota: a frase resultante começa em minúscula ("a partir de R$ 28,70 a unidade…"), coerente com o tom em minúscula do corpo inteiro.

- [ ] **Step 4: Rodar e ver passar**

Mesmo comando. Esperado: todos PASS.

- [ ] **Step 5: Commit**

```bash
cd /root/crm-wt/cs-p7 && git add backend/app/button_flow/valeria_runner.py backend/tests/test_cs_p7_preco_valeria.py && git commit -m "fix(valeria-botoes): faixa 'a partir de' não empilha com 'gira em torno de' no corpo

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Verificação (sem commit)

- [ ] **Step 1:** Testes do pacote + fluxo de botões existente, com flock:

```bash
cd /root/crm-wt/cs-p7 && flock /root/crm-wt/_heavy.lock docker run --rm --user root \
  -v $PWD:/repo -w /repo/backend -e SUPABASE_URL=https://example.supabase.co \
  -e SUPABASE_SERVICE_KEY=ci-dummy canastra-api:latest sh -c \
  "pip install -q -r requirements-dev.txt >/dev/null 2>&1; python -m pytest -q -p no:cacheprovider tests/test_cs_p7_preco_valeria.py tests/test_*valeria*.py tests/test_button_flow*.py tests/test_botoes_pos_producao_2026_10_01.py tests/test_followup_x_botoes_e2e_2026_10_01.py"
```

Esperado: 0 failed. Qualquer falha nos testes existentes → superpowers:systematic-debugging antes de mexer.

- [ ] **Step 2:** Imprimir o corpo final do N5 e do N5b com o catálogo real (mesmo container, `python -c` com patch de `_fetch_active_products`) para o relatório.

---

## Auto-revisão

- Spec P7: >1 candidato do mesmo produto-base → menor preço com "a partir de" (Task 1); produtos-base diferentes → corta (Task 1, `test_produtos_base_diferentes_cortam_a_linha`); candidato único sem prefixo (Task 1); N5/N5b mostram "a partir de R$ 28,70" (Tasks 1 e 2).
- Desvio declarado em relação ao plano mestre: Task 2 (ajuste do qualificador no `_resolver`) não estava listada; sem ela a frase sairia "gira em torno de a partir de R$ 28,70". Fica dentro de `button_flow/*`.
- `agent/pricing.py` só é importado (`match_products`, `parse_brl`), nunca editado.
- Limite conhecido: `match_products` corta em `MAX_DISAMBIGUATION = 5`; com mais de 5 formatos de um café o "menor" seria entre os 5 primeiros. Hoje o máximo real é 2 por nó.
