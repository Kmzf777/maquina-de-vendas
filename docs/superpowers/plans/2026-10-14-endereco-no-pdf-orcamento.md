# Endereço do cliente no PDF de orçamento — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O PDF de orçamento passa a imprimir a linha "ENDEREÇO" do cliente, lida ao vivo da ficha do contato no Bling (fallback: `leads.endereco`).

**Architecture:** `pdf.py` ganha a função pura `formatar_endereco(geral)` e a linha no bloco do cliente. `router.py` ganha `_ficha_do_contato` (GET no Bling) e `_endereco_do_cliente` (vínculo na conta do orçamento → Bling com timeout de 5 s → fallback), e coloca `lead_endereco` no dicionário entregue ao PDF. Nenhuma falha impede o download.

**Tech Stack:** Python 3.12, FastAPI, reportlab, pytest (asyncio auto), Supabase (PostgREST), API Bling v3.

Spec: `docs/superpowers/specs/2026-10-14-endereco-no-pdf-orcamento-design.md`

Rodar testes sempre de `backend/`: `python -m pytest <arquivos> -q`.

---

### Task 1: `formatar_endereco` e linha ENDEREÇO no PDF

**Files:**
- Modify: `backend/app/quotes/pdf.py` (imports; nova função perto de `_documento`; `_cliente` ~linha 364)
- Test: `backend/tests/test_quotes_pdf.py` (acrescentar no fim)

- [ ] **Step 1: testes que falham** — acrescentar ao fim de `tests/test_quotes_pdf.py`:

```python
# ---------------------------------------------------------------------------
# endereço do cliente
# ---------------------------------------------------------------------------

def test_formatar_endereco_completo():
    from app.quotes.pdf import formatar_endereco

    assert formatar_endereco({
        "endereco": "Rua Júlio de Castilho", "numero": "123",
        "complemento": "Sala 2", "bairro": "Centro", "municipio": "Uberlândia",
        "uf": "MG", "cep": "38400000",
    }) == ("Rua Júlio de Castilho, 123 - Sala 2 · Centro · Uberlândia/MG · "
           "CEP 38400-000")


def test_formatar_endereco_omite_partes_vazias():
    from app.quotes.pdf import formatar_endereco

    assert formatar_endereco({
        "endereco": "Av. Brasil", "numero": "", "complemento": None,
        "bairro": "", "municipio": "Patos de Minas", "uf": "MG", "cep": "",
    }) == "Av. Brasil · Patos de Minas/MG"


def test_formatar_endereco_cep_ja_mascarado_ou_estranho():
    from app.quotes.pdf import formatar_endereco

    assert formatar_endereco({"endereco": "Rua A", "cep": "38.400-000"}) == \
        "Rua A · CEP 38400-000"
    # Contagem de dígitos desconhecida volta crua — melhor cru que deformado.
    assert formatar_endereco({"endereco": "Rua A", "cep": "1234"}) == \
        "Rua A · CEP 1234"


def test_formatar_endereco_sem_rua_nem_cidade_e_none():
    from app.quotes.pdf import formatar_endereco

    assert formatar_endereco({}) is None
    assert formatar_endereco(None) is None
    assert formatar_endereco({"endereco": "", "municipio": "", "cep": "38400000",
                              "bairro": "Centro"}) is None


def test_endereco_do_cliente_sai_no_pdf():
    texto = pdf_text(_build(lead_endereco="Rua das Flores, 10 · Centro · Uberlândia/MG"))
    assert "ENDEREÇO" in texto
    assert "Rua das Flores, 10" in texto
    assert "Uberlândia/MG" in texto


def test_sem_endereco_a_linha_some():
    texto = pdf_text(_build(lead_endereco=None))
    assert "ENDEREÇO" not in texto
```

- [ ] **Step 2: rodar e ver falhar**

Run: `python -m pytest tests/test_quotes_pdf.py -q -k "endereco"`
Expected: FAIL (`ImportError: cannot import name 'formatar_endereco'` e "ENDEREÇO" ausente).

- [ ] **Step 3: implementar** em `app/quotes/pdf.py`:

Adicionar `import re` junto dos imports da stdlib (ordem alfabética: depois de `import os`).

Logo depois da função `_documento`, acrescentar:

```python
def formatar_endereco(geral: dict | None) -> str | None:
    """Endereço do cliente numa linha, a partir de `endereco.geral` do Bling.

    Partes vazias somem (nada de ", -" pendurado). Sem rua e sem cidade não há
    endereço que valha imprimir: devolve None e a linha some do PDF, como as
    demais do bloco do cliente.
    """
    g = geral or {}

    def campo(chave: str) -> str:
        return str(g.get(chave) or "").strip()

    rua, numero, complemento = campo("endereco"), campo("numero"), campo("complemento")
    bairro, cidade, uf = campo("bairro"), campo("municipio"), campo("uf")
    if not rua and not cidade:
        return None

    linha = rua
    if numero:
        linha = f"{linha}, {numero}" if linha else numero
    if complemento:
        linha = f"{linha} - {complemento}" if linha else complemento

    local = "/".join(p for p in (cidade, uf) if p)

    cep_cru = campo("cep")
    digitos = re.sub(r"\D", "", cep_cru)
    if len(digitos) == 8:
        cep = f"CEP {digitos[:5]}-{digitos[5:]}"
    else:
        cep = f"CEP {cep_cru}" if cep_cru else ""

    return " · ".join(p for p in (linha, bairro, local, cep) if p)
```

Em `_cliente`, inserir a linha do endereço logo depois de CPF/CNPJ:

```python
    linhas = [
        ("CLIENTE", quote.get("lead_nome")),
        ("CPF/CNPJ", _documento(quote.get("lead_documento"))),
        ("ENDEREÇO", quote.get("lead_endereco")),
        ("E-MAIL", quote.get("lead_email")),
        ("WHATSAPP", _telefone(quote.get("lead_telefone"))),
        ("A/C", quote.get("aos_cuidados_de")),
    ]
```

A largura da coluna do rótulo (24 mm) comporta "ENDEREÇO" em 7 pt; o valor é `Paragraph`, então quebra linha sozinho.

- [ ] **Step 4: rodar e ver passar**

Run: `python -m pytest tests/test_quotes_pdf.py -q`
Expected: todos PASS.

- [ ] **Step 5: commit**

```bash
git add backend/app/quotes/pdf.py backend/tests/test_quotes_pdf.py
git commit -m "feat(orcamento): linha ENDERECO do cliente no PDF"
```

---

### Task 2: router busca o endereço no Bling (depende da Task 1)

**Files:**
- Modify: `backend/app/quotes/router.py` (import de `formatar_endereco`; `_load_lead_para_pdf` ~linha 209; novas funções antes de `quote_pdf_endpoint`; `quote_pdf_endpoint` ~linha 883)
- Test: `backend/tests/test_quotes_router.py` (fixture `db` + testes novos no bloco do PDF)

- [ ] **Step 1: neutralizar o I/O novo na fixture `db`** — em `tests/test_quotes_router.py`, dentro da fixture `db`, logo depois da linha `monkeypatch.setattr(qr, "_load_lead_para_pdf", lambda _id: dict(LEAD))`, acrescentar:

```python
    # O PDF consulta o vínculo do contato e a ficha no Bling. Sem vínculo por
    # padrão: os testes que exercitam o endereço trocam estes dois dubles.
    monkeypatch.setattr(qr.contacts, "_contato_do_lead", lambda _lead, _account: None)

    async def _sem_bling(_contato, _account):
        raise AssertionError("teste não deveria chamar o Bling")
    monkeypatch.setattr(qr, "_ficha_do_contato", _sem_bling)
```

(Isso só passa a funcionar depois do Step 3 — `qr._ficha_do_contato` ainda não existe; `monkeypatch.setattr` falha com AttributeError, e é a falha esperada no Step 2.)

- [ ] **Step 2: testes que falham** — acrescentar logo depois de `test_pdf_recebe_o_que_precisa_e_nada_da_observacao_interna`:

```python
def _captura_pdf(monkeypatch) -> dict:
    capturado = {}

    def fake_pdf(quote, items, *, seller=None):
        capturado["quote"] = quote
        return b"%PDF-fake"

    monkeypatch.setattr(qr, "build_quote_pdf", fake_pdf)
    return capturado


FICHA_BLING = {"data": {"id": 555, "endereco": {"geral": {
    "endereco": "Rua Júlio de Castilho", "numero": "45", "complemento": "",
    "bairro": "Centro", "municipio": "Uberlândia", "uf": "MG", "cep": "38400000",
}}}}


async def test_pdf_traz_endereco_da_ficha_do_bling_na_conta_do_orcamento(db, monkeypatch):
    capturado = _captura_pdf(monkeypatch)
    chamadas = []

    def vinculo(lead_id, account):
        chamadas.append(("vinculo", lead_id, account))
        return 555

    async def ficha(contato_id, account):
        chamadas.append(("ficha", contato_id, account))
        return FICHA_BLING

    monkeypatch.setattr(qr.contacts, "_contato_do_lead", vinculo)
    monkeypatch.setattr(qr, "_ficha_do_contato", ficha)
    monkeypatch.setattr(qr, "_load_quote",
                        lambda _id: {**QUOTE_RASCUNHO, "bling_account": "secundaria"})

    resp = await qr.quote_pdf_endpoint("Q1")

    assert resp.status_code == 200
    assert capturado["quote"]["lead_endereco"] == (
        "Rua Júlio de Castilho, 45 · Centro · Uberlândia/MG · CEP 38400-000")
    # A conta do PRÓPRIO orçamento: o mesmo lead pode ter contato nas duas.
    assert chamadas == [("vinculo", "L1", "secundaria"), ("ficha", 555, "secundaria")]


async def test_pdf_cai_no_endereco_do_lead_quando_o_bling_falha(db, monkeypatch):
    capturado = _captura_pdf(monkeypatch)
    monkeypatch.setattr(qr, "_load_lead_para_pdf",
                        lambda _id: {**LEAD, "endereco": "Rua do Lead, 9"})
    monkeypatch.setattr(qr.contacts, "_contato_do_lead", lambda _l, _a: 555)

    async def bling_fora(_c, _a):
        raise BlingServerError("bling fora", status=503)
    monkeypatch.setattr(qr, "_ficha_do_contato", bling_fora)
    monkeypatch.setattr(qr, "_load_quote", lambda _id: dict(QUOTE_RASCUNHO))

    resp = await qr.quote_pdf_endpoint("Q1")

    assert resp.status_code == 200
    assert capturado["quote"]["lead_endereco"] == "Rua do Lead, 9"


async def test_pdf_cai_no_endereco_do_lead_quando_o_bling_demora(db, monkeypatch):
    capturado = _captura_pdf(monkeypatch)
    monkeypatch.setattr(qr, "BLING_ENDERECO_TIMEOUT", 0.05)
    monkeypatch.setattr(qr, "_load_lead_para_pdf",
                        lambda _id: {**LEAD, "endereco": "Rua do Lead, 9"})
    monkeypatch.setattr(qr.contacts, "_contato_do_lead", lambda _l, _a: 555)

    async def bling_lento(_c, _a):
        await asyncio.sleep(5)
        return FICHA_BLING
    monkeypatch.setattr(qr, "_ficha_do_contato", bling_lento)
    monkeypatch.setattr(qr, "_load_quote", lambda _id: dict(QUOTE_RASCUNHO))

    resp = await qr.quote_pdf_endpoint("Q1")

    assert resp.status_code == 200
    assert capturado["quote"]["lead_endereco"] == "Rua do Lead, 9"


async def test_pdf_cai_no_endereco_do_lead_quando_a_ficha_vem_sem_endereco(db, monkeypatch):
    capturado = _captura_pdf(monkeypatch)
    monkeypatch.setattr(qr, "_load_lead_para_pdf",
                        lambda _id: {**LEAD, "endereco": "Rua do Lead, 9"})
    monkeypatch.setattr(qr.contacts, "_contato_do_lead", lambda _l, _a: 555)

    async def ficha_vazia(_c, _a):
        return {"data": {"id": 555, "endereco": {"geral": {"endereco": "", "municipio": ""}}}}
    monkeypatch.setattr(qr, "_ficha_do_contato", ficha_vazia)
    monkeypatch.setattr(qr, "_load_quote", lambda _id: dict(QUOTE_RASCUNHO))

    await qr.quote_pdf_endpoint("Q1")

    assert capturado["quote"]["lead_endereco"] == "Rua do Lead, 9"


async def test_pdf_sem_vinculo_e_sem_endereco_sai_sem_a_linha(db, monkeypatch):
    capturado = _captura_pdf(monkeypatch)
    monkeypatch.setattr(qr, "_load_quote", lambda _id: dict(QUOTE_RASCUNHO))

    resp = await qr.quote_pdf_endpoint("Q1")

    assert resp.status_code == 200
    assert capturado["quote"]["lead_endereco"] is None


async def test_pdf_sai_mesmo_com_falha_ao_ler_o_vinculo(db, monkeypatch):
    capturado = _captura_pdf(monkeypatch)

    def vinculo_quebrado(_l, _a):
        raise RuntimeError("supabase fora")
    monkeypatch.setattr(qr.contacts, "_contato_do_lead", vinculo_quebrado)
    monkeypatch.setattr(qr, "_load_quote", lambda _id: dict(QUOTE_RASCUNHO))

    resp = await qr.quote_pdf_endpoint("Q1")

    assert resp.status_code == 200
    assert capturado["quote"]["lead_endereco"] is None
```

Se `asyncio` não estiver importado no topo do arquivo de teste, acrescentar `import asyncio`. Conferir a assinatura de `BlingServerError` em `app/bling/errors.py` e ajustar o construtor do teste se for diferente (o que importa é ser uma exceção do Bling).

Run: `python -m pytest tests/test_quotes_router.py -q`
Expected: FAIL (AttributeError em `qr._ficha_do_contato` na fixture).

- [ ] **Step 3: implementar** em `app/quotes/router.py`:

Import: `from app.quotes.pdf import build_quote_pdf` vira
`from app.quotes.pdf import build_quote_pdf, formatar_endereco`.

`_load_lead_para_pdf`: o select passa a ser
`"id, name, razao_social, cnpj, email, phone, telefone_comercial, endereco"`.

Antes de `@router.get("/{quote_id}/pdf")`, acrescentar:

```python
# Teto para a consulta da ficha no Bling durante o download. O vendedor está
# esperando o arquivo; endereço atrasado não pode virar PDF atrasado.
BLING_ENDERECO_TIMEOUT = 5.0


async def _ficha_do_contato(contato_id: int, account: str) -> dict:
    """Ficha completa do contato no Bling. A listagem (e por isso o espelho
    `bling_contacts`) não traz `endereco`; só o GET por id traz."""
    async with BlingClient(account=account) as client:
        return await client.get(f"/contatos/{contato_id}")


async def _endereco_do_cliente(lead: dict, account: str) -> str | None:
    """Endereço impresso no PDF: ficha do Bling na conta do orçamento, com
    `leads.endereco` como reserva.

    Qualquer falha (sem vínculo, Bling fora, timeout, ficha sem endereço) cai
    na reserva — e na falta dela a linha some. Nunca levanta: o download do
    PDF não pode depender do Bling estar de pé.
    """
    reserva = (lead.get("endereco") or "").strip() or None
    lead_id = lead.get("id")
    if not lead_id:
        return reserva
    try:
        contato_id = await asyncio.to_thread(contacts._contato_do_lead, lead_id, account)
        if contato_id:
            ficha = await asyncio.wait_for(_ficha_do_contato(contato_id, account),
                                           BLING_ENDERECO_TIMEOUT)
            geral = (((ficha or {}).get("data") or {}).get("endereco") or {}).get("geral")
            formatado = formatar_endereco(geral)
            if formatado:
                return formatado
    except Exception:
        logger.warning("[QUOTES] endereco do lead %s nao veio do Bling (conta %s); "
                       "PDF usa o do CRM, se houver", lead_id, account, exc_info=True)
    return reserva
```

Em `quote_pdf_endpoint`, logo depois da linha `seller = await asyncio.to_thread(_seller_for, ...)`:

```python
    endereco = await _endereco_do_cliente(lead, conta_do_pdf)
```

E no dicionário `dados`, depois de `"lead_documento": lead.get("cnpj"),`:

```python
        "lead_endereco": endereco,
```

- [ ] **Step 4: rodar e ver passar**

Run: `python -m pytest tests/test_quotes_router.py tests/test_quotes_pdf.py -q`
Expected: todos PASS.

- [ ] **Step 5: suíte inteira**

Run: `python -m pytest -q`
Expected: tudo verde (anotar falhas pré-existentes, se houver, comparando com `origin/master`).

- [ ] **Step 6: commit**

```bash
git add backend/app/quotes/router.py backend/tests/test_quotes_router.py
git commit -m "feat(orcamento): PDF busca o endereco do cliente na ficha do Bling"
```

---

### Task 3: teste em modo teste na VPS (controlador, sem publicar)

- [ ] Empacotar `backend/` do branch (`git archive agente/9adfe0f1 backend`) e copiar para `/tmp/teste-9adfe0f1` na VPS.
- [ ] `docker build -t canastra-api:teste-9adfe0f1 /tmp/teste-9adfe0f1/backend` (não toca `canastra-api:latest`).
- [ ] `docker run --rm` com a env do `canastra_api` (arquivo temporário em `/tmp`, apagado no fim, nunca impresso) e a mesma rede, executando um script que chama `quote_pdf_endpoint(<id do orçamento mais recente>)` e grava o PDF em volume `/tmp/teste-9adfe0f1/out`. Única ação externa: GET no Bling.
- [ ] Copiar o PDF para o PC, converter a 1ª página em PNG (PyMuPDF), recortar o bloco do cliente, olhar o PNG.
- [ ] Limpar: `docker rmi canastra-api:teste-9adfe0f1`, `rm -rf /tmp/teste-9adfe0f1`.
