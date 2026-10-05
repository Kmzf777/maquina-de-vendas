# P1 — Bling e identidade — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fechar as quatro pontas do Bling que a call de 01/10 expôs: busca manual por CNPJ com
máscara, CNPJ/razão/e-mail voltando para o lead no vínculo, venda via Bling criando o card de
Reposição, e o script que mescla os 270 leads `bling-*` já duplicados.

**Architecture:** As três primeiras tarefas são mudanças cirúrgicas em `backend/app/bling/`
(router, contacts, orders, webhook_processor), cada uma com testes unitários novos em
`backend/tests/test_cs_p1_*.py` usando dublês do supabase-py no padrão dos testes
existentes. A mesclagem é um script **só stdlib** (`scripts/bling/mesclar_leads_duplicados.py`)
que fala com o Postgres via `psql` em subprocesso — roda no host da VPS, onde não há venv do
backend nem driver de Postgres no container. Lógica pura (pareamento, gêmeas, SQL) é testada
por unidade; o SQL de verdade é testado num Postgres 17 descartável com o esquema de produção.

**Tech Stack:** FastAPI + supabase-py, pytest (container `canastra-api`), Python 3.12 stdlib +
`psql` para o script, Postgres 17 descartável (`crm-scratch-pg`).

**Spec:** `docs/superpowers/specs/2026-10-06-call-semanal-0110-design.md` (Diagnóstico 2, 4, 7 e
seção P1). Plano mestre: `docs/superpowers/plans/2026-10-06-call-semanal-0110.md` (Regras de
execução e seção P1 — obrigatórias).

---

## Regras de execução (resumo do plano mestre)

- Todo pytest/docker dentro de `flock /root/crm-wt/_heavy.lock`. Sem suíte completa.
- Comando de teste backend (troque `<arquivos>`):
  ```bash
  cd /root/crm-wt/cs-p1 && flock /root/crm-wt/_heavy.lock docker run --rm --user root \
    -v $PWD:/repo -w /repo/backend -e SUPABASE_URL=https://example.supabase.co \
    -e SUPABASE_SERVICE_KEY=ci-dummy canastra-api:latest sh -c \
    "pip install -q -r requirements-dev.txt >/dev/null 2>&1; python -m pytest -q -p no:cacheprovider <arquivos>"
  ```
- Produção: **somente leitura**. O script roda em produção só em dry-run.
- Commits pequenos em `feat/cs-p1`, nunca push.

## Fatos do código e do banco que o plano usa (conferidos em 06/10)

- `router._query_contacts` (`router.py:200-213`) faz `nome/fantasia/doc_digits ilike %termo%`;
  `_termo_seguro` não tira `.`, `/`, `-` → CNPJ com máscara nunca casa com `doc_digits`.
- Vínculos gravados em `lead_bling_contacts`: `contacts.resolve` (ramo documento),
  `contacts.create_contact`, `contacts.link` (vínculo manual, chamado por
  `POST /api/bling/contacts/link`), `contacts.ensure_lead` (webhook: ramos documento e celular).
- `orders.create_order` move o deal para ganho (`_move_deal_to_won`, devolve bool) mas não
  chama `ensure_reposicao_deal`. `ensure_reposicao_deal(lead_id, deal_id)` é **fail-closed**:
  sem `deal_id`, ou com deal de funil fora do mapa (`reposicao_pipeline_para`), não cria nada.
  Venda do webhook entra **sem deal** (decisão D7) → precisa achar o deal de origem do lead
  (o mais recente num funil mapeado: João Atacado / João Private Label).
- `webhook_processor._handle_order` chama `upsert_from_bling`; o backfill também, mas o backfill
  **não** pode criar cards (só o webhook ganha o gancho, e só para venda nova com
  `sold_at >= now()-7d`).
- Produção: **270** candidatos (`phone like 'bling-%'` = 261, + 9 `channel='bling'` com
  `metadata.origem='bling_webhook'` e telefone real); todos têm `lead_bling_contacts`
  (21 com contato nas duas contas).
- Tabelas-base com `lead_id` em produção (21): `broadcast_leads`, `campaign_enrollments`,
  `campaign_execution_log`, `conversations`, `conversion_events`, `deals`, `follow_up_jobs`,
  `follow_up_jobs_incidente_20261003`, `lead_bling_contacts`, `lead_daily_sends`,
  `lead_events`, `lead_notes`, `lead_qualification_scores`, `lead_seller_feelings`,
  `lead_tags`, `lp_email_jobs`, `messages`, `messages_archive`, `quotes`, `sales`,
  `token_usage`. (`valeria_score_*` são views — fora.) `lp_email_jobs`, `token_usage` e
  `follow_up_jobs` têm FK **sem** cascade → precisam ser movidas antes do `delete`.
- Índices únicos com `lead_id`: `broadcast_leads(broadcast_id, lead_id)`,
  `lead_bling_contacts(lead_id, account)`, `conversations(lead_id, channel_id)`,
  `follow_up_jobs` parcial `(lead_id, job_type, coalesce(metadata->>'deal_id',''), sequence)`
  em `pending|processing` e `joao\_%`, `lead_tags(lead_id, tag_id)`,
  `lead_daily_sends(lead_id, date)`, `campaign_enrollments` parcial `(campaign_id, lead_id)`
  em `active|paused`, `lead_seller_feelings(lead_id, user_id)`,
  `lead_qualification_scores(lead_id)`.
- `lead_events` em produção ainda **não** tem `occurred_at/source/dedupe_key` (P0 não aplicado).
  O `--aplicar` exige o P0 e aborta sem ele; o dry-run não precisa.
- Casos reais: Jovens/Iago — dup `8b915450…` (`bling-18410375514`, contato secundária com
  `telefone_e164=5543999565650`) × lead `eb8ffb98…` "Hiago Angelucci" (`5543999565650`);
  venda bling R$ 60 `sold_at 2026-09-25 12:00` × manual R$ 60 `sold_at 2026-09-24 15:00`
  (criadas a 15 s). Serginho — dup `966977d1…` (contato `5566997222209`) × lead `7c8638ee…`
  "Serginho Sinop". Velho Hank — dup `289d5f93…`, contato `5551996473918` casa com o lead
  `8a082d51…` "Luiz Felipe" (lista fria de maio).

## Arquivos

| Arquivo | Responsabilidade |
|---|---|
| Modify `backend/app/bling/router.py` | `_documento_do_termo` + ramo `doc_digits.eq` em `_query_contacts` |
| Modify `backend/app/bling/contacts.py` | `_preencher_lead_com_contato`, `_preencher_pelo_espelho`; chamadas em `resolve`, `link`, `create_contact`, `ensure_lead` |
| Modify `backend/app/bling/orders.py` | `venda_recente`, `_deal_de_origem_do_lead`, `garantir_reposicao_apos_venda`; gancho no `create_order` |
| Modify `backend/app/bling/webhook_processor.py` | `_venda_ja_existia`; gancho de reposição no `_handle_order` |
| Create `scripts/bling/mesclar_leads_duplicados.py` | Script de mesclagem (stdlib + psql) |
| Create `backend/tests/test_cs_p1_busca_documento.py` | Task 1 |
| Create `backend/tests/test_cs_p1_preenche_lead.py` | Task 2 |
| Create `backend/tests/test_cs_p1_reposicao.py` | Task 3 |
| Create `backend/tests/test_cs_p1_mesclagem.py` | Task 4 (unidade, roda no container) |
| Create `backend/tests/test_cs_p1_mesclagem_pg.py` | Task 4 (integração; pula sem `CS_P1_PG_URL`) |

---

### Task 1: Busca manual aceita CPF/CNPJ com máscara

**Files:**
- Modify: `backend/app/bling/router.py` (logo após `_termo_seguro`; e `_query_contacts`)
- Test: `backend/tests/test_cs_p1_busca_documento.py`

- [ ] **Step 1: Teste falhando**

```python
"""P1.3 — busca manual de contato Bling aceita CPF/CNPJ digitado com máscara.

Caso Vida Natural (call de 01/10): o vendedor colou o CNPJ formatado e nada voltou, porque
`doc_digits` só tem dígitos e o termo ia cru para o `ilike`.
"""
import app.bling.router as br


class _Q:
    def __init__(self):
        self.eqs = {}
        self.ors = []

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.eqs[col] = val
        return self

    def or_(self, expr):
        self.ors.append(expr)
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        class R:
            data = []
        return R()


def _rodar(monkeypatch, termo):
    q = _Q()
    monkeypatch.setattr(br, "get_supabase", lambda: type("SB", (), {"table": lambda self, n: q})())
    br._query_contacts(termo, 20, "default")
    return q


def test_cnpj_com_mascara_vira_filtro_exato_em_doc_digits(monkeypatch):
    q = _rodar(monkeypatch, "12.345.678/0001-90")
    assert q.eqs["doc_digits"] == "12345678000190"
    assert q.eqs["account"] == "default"
    assert q.ors == [], "documento nao pode cair no ilike de nome"


def test_cpf_com_mascara_vira_filtro_exato(monkeypatch):
    q = _rodar(monkeypatch, " 123.456.789-09 ")
    assert q.eqs["doc_digits"] == "12345678909"


def test_cnpj_so_digitos_tambem_usa_filtro_exato(monkeypatch):
    q = _rodar(monkeypatch, "12345678000190")
    assert q.eqs["doc_digits"] == "12345678000190"


def test_nome_continua_no_ilike(monkeypatch):
    q = _rodar(monkeypatch, "Vida Natural")
    assert "doc_digits" not in q.eqs
    assert q.ors == ["nome.ilike.%Vida Natural%,fantasia.ilike.%Vida Natural%,"
                     "doc_digits.ilike.%Vida Natural%"]


def test_numero_que_nao_e_documento_continua_no_ilike(monkeypatch):
    # 8 digitos: pedaco de CNPJ ou telefone — nao e documento inteiro.
    q = _rodar(monkeypatch, "12.345.678")
    assert "doc_digits" not in q.eqs
    assert len(q.ors) == 1


def test_texto_com_letras_e_11_digitos_nao_e_documento():
    assert br._documento_do_termo("Loja 123.456.789-09") is None
    assert br._documento_do_termo("") is None
    assert br._documento_do_termo(None) is None
```

- [ ] **Step 2: Rodar e ver falhar** — comando de teste com `tests/test_cs_p1_busca_documento.py`.
  Esperado: FAIL (`AttributeError: _documento_do_termo` / `KeyError: 'doc_digits'`).

- [ ] **Step 3: Implementação** — em `router.py`, depois de `_termo_seguro`:

```python
# So digitos e a pontuacao de mascara de CPF/CNPJ (ponto, barra, hifen, espaco).
_TERMO_DE_DOCUMENTO_RE = re.compile(r"[\d\s./-]+")


def _documento_do_termo(q: str | None) -> str | None:
    """O termo e um CPF/CNPJ inteiro (com ou sem mascara)? Devolve so os digitos.

    Caso Vida Natural (call de 01/10): o vendedor colou "12.345.678/0001-90" e a busca
    nao achou nada, porque `doc_digits` guarda so digitos e o termo ia cru para o
    `ilike`. Termo com letra nunca e documento; 11 ou 14 digitos sim.
    """
    if not q or not _TERMO_DE_DOCUMENTO_RE.fullmatch(q.strip()):
        return None
    digitos = "".join(ch for ch in q if ch.isdigit())
    return digitos if len(digitos) in (11, 14) else None
```

e em `_query_contacts`, o ramo `elif q:` vira:

```python
    elif q:
        doc = _documento_do_termo(q)
        if doc:
            # Documento inteiro: igualdade exata no indice, nao ilike.
            query = query.eq("doc_digits", doc)
        else:
            alvo = f"%{_termo_seguro(q)}%"
            query = query.or_(f"nome.ilike.{alvo},fantasia.ilike.{alvo},doc_digits.ilike.{alvo}")
```

- [ ] **Step 4: Rodar e ver passar** — `tests/test_cs_p1_busca_documento.py tests/test_bling_router.py`. Esperado: PASS.
- [ ] **Step 5: Commit** — `feat(bling): busca de contato aceita CPF/CNPJ com mascara`.

---

### Task 2: CNPJ, razão social e e-mail voltam para o lead no vínculo

**Files:**
- Modify: `backend/app/bling/contacts.py` (helpers após `_link`; `resolve`, `link`, `create_contact`, `ensure_lead`)
- Test: `backend/tests/test_cs_p1_preenche_lead.py`

Regra: grava `cnpj` (só dígitos, e só se o documento for válido), `razao_social` (= `nome` do
contato) e `email` **somente nos campos vazios** do lead (`null` ou só espaço). Fail-soft: o
vínculo já foi gravado; falha no preenchimento só loga.

- [ ] **Step 1: Teste falhando**

```python
"""P1.2 — vincular contato Bling devolve CNPJ/razao/e-mail ao lead (so onde esta vazio).

Caso Vida Natural: o contato foi vinculado pelo modal e o CNPJ nunca voltou para o lead, entao
a proxima resolucao automatica (que so olha `leads.cnpj`) continuava sem achar nada.
"""
import asyncio

import app.bling.contacts as ct

CNPJ = "29860598000170"  # valido (mesmo dos testes de contacts)


class _Q:
    def __init__(self, sb, tabela):
        self.sb, self.tabela = sb, tabela
        self.filtros = {}
        self.payload = None
        self.op = "select"

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.filtros[col] = val
        return self

    def limit(self, *_a, **_k):
        return self

    def maybe_single(self):
        self.filtros["_single"] = True
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def upsert(self, payload, on_conflict=None):
        self.op, self.payload = "upsert", payload
        return self

    def execute(self):
        self.sb.log.append((self.tabela, self.op, dict(self.filtros), self.payload))
        if self.op != "select":
            return type("R", (), {"data": [self.payload]})()
        linhas = self.sb.linhas.get(self.tabela, [])
        if self.filtros.get("_single"):
            linhas = linhas[0] if linhas else None
        return type("R", (), {"data": linhas})()


class _SB:
    def __init__(self, linhas):
        self.linhas = linhas
        self.log = []

    def table(self, nome):
        return _Q(self, nome)

    def updates(self, tabela):
        return [p for (t, op, _f, p) in self.log if t == tabela and op == "update"]


CONTATO = {"id": 77, "nome": "Vida Natural Produtos LTDA", "doc_digits": CNPJ,
           "email": "compras@vidanatural.com.br"}


def test_lead_sem_cnpj_recebe_documento_razao_e_email(monkeypatch):
    sb = _SB({"leads": [{"cnpj": None, "razao_social": "", "email": None}]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    patch = ct._preencher_lead_com_contato("L1", CONTATO)

    assert patch == {"cnpj": CNPJ, "razao_social": "Vida Natural Produtos LTDA",
                     "email": "compras@vidanatural.com.br"}
    assert sb.updates("leads") == [patch]


def test_lead_com_cnpj_fica_intocado(monkeypatch):
    sb = _SB({"leads": [{"cnpj": "11.222.333/0001-81", "razao_social": "Outra",
                         "email": "x@y.com"}]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    assert ct._preencher_lead_com_contato("L1", CONTATO) == {}
    assert sb.updates("leads") == []


def test_so_os_campos_vazios_sao_preenchidos(monkeypatch):
    sb = _SB({"leads": [{"cnpj": None, "razao_social": "Ja Tem", "email": "  "}]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    patch = ct._preencher_lead_com_contato("L1", CONTATO)

    assert patch == {"cnpj": CNPJ, "email": "compras@vidanatural.com.br"}


def test_documento_invalido_nao_vai_para_o_lead(monkeypatch):
    sb = _SB({"leads": [{"cnpj": None, "razao_social": None, "email": None}]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    patch = ct._preencher_lead_com_contato("L1", {**CONTATO, "doc_digits": "00000000000"})

    assert "cnpj" not in patch


def test_falha_no_preenchimento_nao_propaga(monkeypatch):
    def quebra():
        raise RuntimeError("supabase fora")
    monkeypatch.setattr(ct, "get_supabase", quebra)
    assert ct._preencher_lead_com_contato("L1", CONTATO) == {}


def test_vinculo_manual_preenche_a_partir_do_espelho(monkeypatch):
    sb = _SB({"bling_contacts": [CONTATO],
              "leads": [{"cnpj": None, "razao_social": None, "email": None}]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    asyncio.run(ct.link("L1", 77, "secundaria"))

    assert any(t == "lead_bling_contacts" and op == "upsert" for (t, op, _f, _p) in sb.log)
    leitura = [f for (t, op, f, _p) in sb.log if t == "bling_contacts"]
    assert leitura and leitura[0]["id"] == 77 and leitura[0]["account"] == "secundaria"
    assert sb.updates("leads") == [{"cnpj": CNPJ, "razao_social": "Vida Natural Produtos LTDA",
                                    "email": "compras@vidanatural.com.br"}]


def test_resolve_por_documento_preenche_razao_e_email(monkeypatch):
    sb = _SB({"bling_contacts": [CONTATO],
              "leads": [{"cnpj": CNPJ, "razao_social": None, "email": None}]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.resolve({"id": "L1", "cnpj": CNPJ}, "default"))

    assert out.status == "linked"
    assert sb.updates("leads") == [{"razao_social": "Vida Natural Produtos LTDA",
                                    "email": "compras@vidanatural.com.br"}]


def test_create_contact_que_acha_por_documento_preenche_o_lead(monkeypatch):
    sb = _SB({"leads": [{"cnpj": None, "razao_social": None, "email": None}]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    def lock(_k):
        class _C:
            async def __aenter__(self):
                return True

            async def __aexit__(self, *_a):
                return False
        return _C()
    monkeypatch.setattr(ct, "_lock", lock)

    class Cliente:
        async def get(self, path, params=None):
            return {"data": [{"id": 77, "numeroDocumento": "29.860.598/0001-70"}]}

        async def post(self, *_a, **_k):
            raise AssertionError("nao pode criar")

    out = asyncio.run(ct.create_contact(
        Cliente(), {"id": "L1", "name": "Vida"},
        {"nome": "Vida Natural Produtos LTDA", "numeroDocumento": "29.860.598/0001-70",
         "email": "compras@vidanatural.com.br"}))

    assert out == 77
    assert sb.updates("leads") == [{"cnpj": CNPJ, "razao_social": "Vida Natural Produtos LTDA",
                                    "email": "compras@vidanatural.com.br"}]


def test_ensure_lead_por_celular_preenche_o_lead_achado(monkeypatch):
    """Caso Jovens/Iago: o lead do Hiago e achado pelo celular e passa a ter o CNPJ."""
    sb = _SB({"leads": [{"id": "HIAGO", "cnpj": None, "razao_social": None, "email": None}]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)
    monkeypatch.setattr(ct, "_lead_por_contato", lambda *_a: None)
    monkeypatch.setattr(ct, "_contato_do_lead", lambda *_a: None)

    contato = {"id": 18410375514, "nome": "Jovens Com Uma Missao", "doc_digits": "06132231000135",
               "telefone_e164": "5543999565650", "email": None}
    # o documento do contato nao casa com nenhum lead: o fake devolve a mesma linha para
    # qualquer select em leads, entao forcamos o ramo do celular tirando o documento da busca
    original = ct._find_lead
    monkeypatch.setattr(ct, "_find_lead",
                        lambda col, val: None if col == "cnpj" else original(col, val))

    lead_id = asyncio.run(ct.ensure_lead(contato, "secundaria"))

    assert lead_id == "HIAGO"
    assert sb.updates("leads") == [{"cnpj": "06132231000135",
                                    "razao_social": "Jovens Com Uma Missao"}]
```

- [ ] **Step 2: Rodar e ver falhar.** Esperado: FAIL (`_preencher_lead_com_contato` não existe).

- [ ] **Step 3: Implementação** — em `contacts.py`, logo após `_link`:

```python
# Campos que o vinculo devolve ao lead. So entram onde o lead esta VAZIO: o que o vendedor
# digitou no CRM nunca e sobrescrito pelo ERP.
def _vazio(valor) -> bool:
    return valor is None or not str(valor).strip()


def _preencher_lead_com_contato(lead_id: str, contato: dict) -> dict:
    """Devolve ao lead o documento, a razao social e o e-mail do contato Bling vinculado.

    Caso Vida Natural (call de 01/10): o contato foi escolhido no modal, o vinculo foi
    gravado, mas `leads.cnpj` continuou vazio — e a resolucao automatica (`resolve`) so
    olha `leads.cnpj`. Toda via que grava `lead_bling_contacts` chama isto.

    `contato` e uma linha do espelho (`doc_digits`, `nome`, `email`) ou o que o modal
    mandou (`numeroDocumento`). Documento invalido nao sobe (mesma regra do `resolve`).

    Fail-soft: o vinculo ja foi gravado e e o que importa para a venda; uma falha aqui
    so deixa o lead como estava. Devolve o que foi gravado (vazio se nada).
    """
    try:
        doc = doc_digits(contato.get("doc_digits") or contato.get("numeroDocumento"))
        do_contato = {
            "cnpj": doc if is_valid_document(doc) else None,
            "razao_social": (contato.get("nome") or "").strip() or None,
            "email": (contato.get("email") or "").strip() or None,
        }
        do_contato = {k: v for k, v in do_contato.items() if v}
        if not do_contato:
            return {}
        sb = get_supabase()
        res = (sb.table("leads").select("cnpj, razao_social, email")
               .eq("id", lead_id).limit(1).execute())
        linhas = getattr(res, "data", None) or []
        if not linhas:
            return {}
        atual = linhas[0]
        patch = {k: v for k, v in do_contato.items() if _vazio(atual.get(k))}
        if patch:
            sb.table("leads").update(patch).eq("id", lead_id).execute()
        return patch
    except Exception:
        logger.warning("[BLING] vinculo do lead %s gravado, mas o preenchimento a partir "
                       "do contato falhou", lead_id, exc_info=True)
        return {}


def _preencher_pelo_espelho(lead_id: str, contact_id: int, account: str) -> dict:
    """Le o contato no espelho (NESTA conta) e preenche o lead. Fail-soft."""
    try:
        res = (get_supabase().table("bling_contacts").select(_CONTACT_COLS)
               .eq("id", contact_id).eq("account", account).limit(1).execute())
        linhas = getattr(res, "data", None) or []
    except Exception:
        logger.warning("[BLING] espelho do contato %s (conta %s) indisponivel para "
                       "preencher o lead %s", contact_id, account, lead_id, exc_info=True)
        return {}
    return _preencher_lead_com_contato(lead_id, linhas[0]) if linhas else {}
```

Chamadas:

1. `resolve`, ramo documento, depois do `try/except` do `_link` e antes do
   `return Resolution("linked", contact_id, reason="documento")`:
   ```python
            await asyncio.to_thread(_preencher_lead_com_contato, lead["id"], achados[0])
   ```
2. `link`:
   ```python
    await asyncio.to_thread(_link, lead_id, contact_id, account)
    await asyncio.to_thread(_preencher_pelo_espelho, lead_id, contact_id, account)
   ```
3. `create_contact`, depois do `try/except` do `_link` e antes do `return contact_id`:
   ```python
        await asyncio.to_thread(_preencher_lead_com_contato, lead["id"], {
            "doc_digits": doc, "nome": dados.get("nome"), "email": dados.get("email"),
        })
   ```
4. `ensure_lead`, nos dois pontos onde `_link` é chamado para um lead **já existente** (ramo
   documento e ramo celular), logo depois do `_link`:
   ```python
                await asyncio.to_thread(_preencher_lead_com_contato, achado["id"], contato)
   ```

- [ ] **Step 4: Rodar e ver passar** — `tests/test_cs_p1_preenche_lead.py tests/test_bling_contacts.py tests/test_bling_router.py`.
- [ ] **Step 5: Commit** — `feat(bling): vinculo com contato devolve CNPJ, razao e e-mail ao lead`.

---

### Task 3: Venda via Bling cria o card de Reposição

**Files:**
- Modify: `backend/app/bling/orders.py` (helpers antes de `create_order`; bloco do deal no fim de `create_order`)
- Modify: `backend/app/bling/webhook_processor.py` (`_handle_order`)
- Test: `backend/tests/test_cs_p1_reposicao.py`

Regras:
- `create_order`: deal informado e movido para ganho → `ensure_reposicao_deal(lead, deal)`. Sem
  deal → deal de origem do lead (o mais recente num funil mapeado por
  `reposicao_pipeline_para`); sem nenhum → não cria (fail-closed). Deal informado que **não**
  foi movido → não cria.
- Webhook: só venda **nova** (não havia linha em `sales`), com lead, e
  `sold_at >= now() - 7 dias` → deal de origem do lead → `ensure_reposicao_deal`.
  Backfill nunca chama.
- Qualquer exceção é logada e não desfaz a venda nem falha o evento.

- [ ] **Step 1: Teste falhando**

```python
"""P1.4 — venda registrada pelo CRM via Bling (e venda nova do webhook) cria a Reposicao.

Diagnostico 7 da call de 01/10: `create_order` nao dispara `sale_created`, entao o card de
Reposicao nunca nascia e a cadencia de reposicao/kit (P6) ficava sem card.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import app.bling.orders as orders
import app.bling.webhook_processor as wp
import app.leads.reposicao as reposicao


class _Q:
    def __init__(self, sb, tabela):
        self.sb, self.tabela = sb, tabela

    def __getattr__(self, _nome):
        return lambda *_a, **_k: self

    def execute(self):
        return type("R", (), {"data": self.sb.linhas.get(self.tabela, [{"id": "SALE-1"}])})()


class _SB:
    def __init__(self, linhas=None):
        self.linhas = linhas or {}

    def table(self, nome):
        return _Q(self, nome)


class _Cliente:
    async def post(self, path, json=None):
        return {"data": {"id": 999}}

    async def get(self, path, params=None):
        return {"data": {"id": 999, "numero": 1, "situacao": {"id": 6}}}


def _conta(_account):
    return orders.config.BlingAccount(key="default", label="default", client_id="",
                                      client_secret="", store_id=None, situacao_id=None)


def _criar(monkeypatch, deal_id, movido=True, origem=None, ensure=None):
    chamadas = []
    monkeypatch.setattr(orders, "get_supabase", lambda: _SB())
    monkeypatch.setattr(orders.config, "account", _conta)
    monkeypatch.setattr(orders, "_move_deal_to_won", lambda _d: movido)
    monkeypatch.setattr(orders, "_deal_de_origem_do_lead", lambda _l: origem)
    monkeypatch.setattr(reposicao, "ensure_reposicao_deal",
                        ensure or (lambda lead_id, deal_id=None: chamadas.append((lead_id, deal_id))))
    out = asyncio.run(orders.create_order(
        _Cliente(), lead_id="L1", deal_id=deal_id, contact_id=5, sold_at="2026-10-06",
        sold_by=None, itens=[{"bling_product_id": 1, "descricao": "Kit", "quantidade": 1,
                              "valor_unitario": 60, "desconto_percentual": 0}],
        payment={"method_id": 1, "terms": [0]}, seller_id=None))
    return out, chamadas


def test_create_order_cria_reposicao_depois_de_mover_o_deal(monkeypatch):
    out, chamadas = _criar(monkeypatch, "D1")
    assert out["bling_order_id"] == 999
    assert chamadas == [("L1", "D1")]


def test_create_order_sem_deal_usa_o_deal_de_origem_do_lead(monkeypatch):
    _out, chamadas = _criar(monkeypatch, None, origem="D-ATACADO")
    assert chamadas == [("L1", "D-ATACADO")]


def test_create_order_sem_deal_e_sem_origem_nao_cria(monkeypatch):
    _out, chamadas = _criar(monkeypatch, None, origem=None)
    assert chamadas == []


def test_create_order_deal_nao_movido_nao_cria(monkeypatch):
    _out, chamadas = _criar(monkeypatch, "D1", movido=False)
    assert chamadas == []


def test_create_order_excecao_na_reposicao_nao_desfaz_a_venda(monkeypatch):
    def explode(lead_id, deal_id=None):
        raise RuntimeError("funil fora")
    out, _ = _criar(monkeypatch, "D1", ensure=explode)
    assert out["sale_id"] == "SALE-1"


def test_deal_de_origem_e_o_mais_recente_de_funil_mapeado(monkeypatch):
    atacado = "9706a14a-3d9a-413b-bceb-26838fc2cc45"
    sb = _SB({"deals": [
        {"id": "D-VALERIA", "pipeline_id": "outro", "created_at": "2026-10-01T00:00:00+00:00"},
        {"id": "D-VELHO", "pipeline_id": atacado, "created_at": "2026-08-01T00:00:00+00:00"},
        {"id": "D-NOVO", "pipeline_id": atacado, "created_at": "2026-09-01T00:00:00+00:00"},
    ]})
    monkeypatch.setattr(orders, "get_supabase", lambda: sb)
    assert orders._deal_de_origem_do_lead("L1") == "D-NOVO"


def test_venda_recente_janela_de_7_dias():
    agora = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
    assert orders.venda_recente("2026-09-29T12:00:00+00:00", agora)
    assert not orders.venda_recente("2026-09-29T11:59:59+00:00", agora)
    assert not orders.venda_recente(None, agora)
    assert not orders.venda_recente("lixo", agora)


# ---------- webhook ----------

def _pedido(dias_atras):
    data = (datetime.now(timezone.utc) - timedelta(days=dias_atras)).date().isoformat()
    return {"id": 555, "data": data, "total": 60, "contato": {"id": 9}}


def _handle(monkeypatch, pedido, ja_existia=False, garantir=None, lead="L1"):
    chamadas = []

    class Cli:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def get(self, _p):
            return {"data": pedido}

    async def nada(*_a, **_k):
        return None

    async def lead_fn(*_a):
        return lead

    monkeypatch.setattr(wp, "_new_client", lambda a: Cli())
    monkeypatch.setattr(wp, "_last_event_date", nada)
    monkeypatch.setattr(wp, "_contact_row", lambda a, c: {"id": 9})
    monkeypatch.setattr(wp, "_resolve_lead", lead_fn)
    monkeypatch.setattr(wp, "upsert_from_bling", nada)
    monkeypatch.setattr(wp, "_venda_ja_existia", lambda a, o: ja_existia)
    monkeypatch.setattr(wp, "garantir_reposicao_apos_venda",
                        garantir or (lambda lead_id, deal_id=None: chamadas.append(lead_id)))
    evento = {"event_id": "E1", "event": "order.created", "account": "default"}
    status = asyncio.run(wp._handle_order(evento, {"data": {"id": 555}}))
    return status, chamadas


def test_webhook_venda_nova_e_recente_cria_reposicao(monkeypatch):
    status, chamadas = _handle(monkeypatch, _pedido(1))
    assert status == "done"
    assert chamadas == ["L1"]


def test_webhook_venda_antiga_nao_cria(monkeypatch):
    _s, chamadas = _handle(monkeypatch, _pedido(10))
    assert chamadas == []


def test_webhook_venda_ja_existente_nao_cria(monkeypatch):
    _s, chamadas = _handle(monkeypatch, _pedido(1), ja_existia=True)
    assert chamadas == []


def test_webhook_sem_lead_nao_cria(monkeypatch):
    _s, chamadas = _handle(monkeypatch, _pedido(1), lead=None)
    assert chamadas == []


def test_webhook_excecao_na_reposicao_nao_falha_o_evento(monkeypatch):
    def explode(*_a, **_k):
        raise RuntimeError("x")
    status, _ = _handle(monkeypatch, _pedido(1), garantir=explode)
    assert status == "done"
```

- [ ] **Step 2: Rodar e ver falhar.** Esperado: FAIL (`_deal_de_origem_do_lead` / `venda_recente` não existem).

- [ ] **Step 3: Implementação em `orders.py`** — antes de `_find_order_by_key`:

```python
# Venda do webhook so cria card de Reposicao se for recente: o backfill historico e um
# order.created atrasado nao podem abrir cards em massa para vendas de meses atras.
JANELA_REPOSICAO_WEBHOOK = timedelta(days=7)


def venda_recente(sold_at_iso: str | None, agora: datetime | None = None) -> bool:
    """`sold_at` (ISO) esta dentro da janela de 7 dias? Data ilegivel → False (fail-closed)."""
    if not sold_at_iso:
        return False
    try:
        quando = datetime.fromisoformat(str(sold_at_iso).replace("Z", "+00:00"))
    except ValueError:
        return False
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=timezone.utc)
    agora = agora or datetime.now(timezone.utc)
    return quando >= agora - JANELA_REPOSICAO_WEBHOOK


def _deal_de_origem_do_lead(lead_id: str) -> str | None:
    """Deal mais recente do lead num funil que TEM reposicao mapeada (Atacado/Private Label).

    Venda do Bling entra sem deal (D7) e `ensure_reposicao_deal` e fail-closed sem deal:
    o destino da Reposicao depende do funil de ORIGEM. Sem nenhum deal mapeado → None, e
    nada e criado (criar no funil errado ja extraviou 19 cards em 09/2026).
    Ordena em Python para nao depender de `.order` (lead tem poucos deals).
    """
    from app.leads.reposicao import reposicao_pipeline_para
    res = (get_supabase().table("deals").select("id, pipeline_id, created_at")
           .eq("lead_id", lead_id).limit(200).execute())
    linhas = getattr(res, "data", None) or []
    linhas = sorted(linhas, key=lambda d: str(d.get("created_at") or ""), reverse=True)
    for deal in linhas:
        if reposicao_pipeline_para(deal.get("pipeline_id")):
            return deal.get("id")
    return None


def garantir_reposicao_apos_venda(lead_id: str | None, deal_id: str | None = None) -> None:
    """Chama `ensure_reposicao_deal` para a venda (spec P1.4). Nunca levanta.

    `deal_id` e o card que a venda fechou; sem ele, usa o deal de origem do lead. Falha
    aqui e logada e NAO desfaz a venda: o pedido ja existe no ERP.
    """
    if not lead_id:
        return
    try:
        from app.leads import reposicao
        origem = deal_id or _deal_de_origem_do_lead(lead_id)
        if not origem:
            logger.info("[BLING] venda do lead %s sem deal de funil mapeado — "
                        "Reposicao nao criada (fail-closed)", lead_id)
            return
        reposicao.ensure_reposicao_deal(lead_id, deal_id=origem)
    except Exception:
        logger.exception("[BLING] falha ao garantir a Reposicao do lead %s (venda mantida)",
                         lead_id)
```

E o bloco do deal no fim de `create_order` passa a ser:

```python
    movido = False
    if deal_id:
        try:
            movido = bool(await asyncio.to_thread(_move_deal_to_won, deal_id))
        except Exception:
            # (comentario existente mantido)
            logger.exception("[BLING] pedido %s criado, mas falhou ao mover o "
                             "deal %s para Fechado Ganho", order_id, deal_id)

    # Reposicao (spec P1.4): o POST /api/sales cria o card via `sale_created`; este
    # caminho nao emite o evento, entao chama direto. Deal informado so conta se foi
    # MOVIDO para ganho; sem deal, vale o deal de origem do lead. Nunca levanta.
    if movido or not deal_id:
        await asyncio.to_thread(garantir_reposicao_apos_venda, lead_id,
                                deal_id if movido else None)
```

**Em `webhook_processor.py`:** importar `garantir_reposicao_apos_venda`, `venda_recente` e
`_sold_at_iso` de `app.bling.orders`; novo helper:

```python
def _venda_ja_existia(account: str, order_id: int) -> bool:
    """Ja ha linha em `sales` para este pedido? Erro de leitura → True (nao cria card)."""
    try:
        res = (get_supabase().table("sales").select("id")
               .eq("bling_account", account).eq("bling_order_id", order_id)
               .limit(1).execute())
        return bool(getattr(res, "data", None))
    except Exception:
        logger.warning("[BLING WEBHOOK] nao consegui checar se o pedido %s ja existia — "
                       "Reposicao nao sera criada", order_id, exc_info=True)
        return True
```

e em `_handle_order`, trocando a última linha (`await upsert_from_bling(...)`):

```python
    # Reposicao (spec P1.4): so venda NOVA e RECENTE. A checagem de existencia vem antes
    # do upsert (depois dele a linha sempre existe). Pedido criado pelo CRM ja passou
    # por `create_order`, que cuidou do card — por isso "ja existia" nao cria.
    nova_e_recente = False
    if lead_id and venda_recente(_sold_at_iso(pedido, event_date)):
        nova_e_recente = not await asyncio.to_thread(_venda_ja_existia, account, order_id)

    await upsert_from_bling(pedido, lead_id=lead_id, event_date=event_date, account=account)

    if nova_e_recente:
        try:
            await asyncio.to_thread(garantir_reposicao_apos_venda, lead_id, None)
        except Exception:
            logger.exception("[BLING WEBHOOK] Reposicao do lead %s falhou (venda mantida)",
                             lead_id)
    return "done"
```

- [ ] **Step 4: Rodar e ver passar** — `tests/test_cs_p1_reposicao.py tests/test_bling_orders.py tests/test_bling_webhook_processor.py tests/test_bling_jobs.py`.
- [ ] **Step 5: Commit** — `feat(bling): venda via Bling cria o card de Reposicao`.

---

### Task 4: Script de mesclagem dos leads `bling-*` duplicados

**Files:**
- Create: `scripts/bling/mesclar_leads_duplicados.py`
- Test: `backend/tests/test_cs_p1_mesclagem.py` (unidade, container)
- Test: `backend/tests/test_cs_p1_mesclagem_pg.py` (integração, host + Postgres descartável)

Decisões de desenho:
- **Só stdlib + `psql`** (`--psql "<comando>"` ou env `MESCLAR_PSQL`). O container
  `canastra-api` não tem driver Postgres; o host tem `psql`. Leitura via
  `select coalesce(json_agg(t),'[]') from (…) t`; escrita via um `psql -v ON_ERROR_STOP=1` por
  par com `begin … commit` (erro → rollback só daquele par, registrado em `aplicados.csv`).
- Chaves de celular: cópia fiel de `_celular_br`/`_chaves_de_celular` de
  `app/bling/contacts.py` (o script não importa `app` — precisa de redis/supabase); um teste de
  paridade garante que as duas não divergem.
- Documento para pareamento: 11 ou 14 dígitos, não repetitivo (`00000000000` fora).
- Sobrevivente nunca é outro candidato. 0 achados → órfão; >1 → ambíguo (não mescla).
- Tabelas: conjunto `TABELAS_COBERTAS` = `SO_MOVER` ∪ `COLISAO`; tabela-base com `lead_id` no
  banco fora do conjunto → aborta antes de tudo (dry-run inclusive). Em `COLISAO`, a linha do
  duplicado que colidiria com uma do sobrevivente é apagada (sobrevivente vence) e entra no
  backup; `conversations` colidindo em `(lead_id, channel_id)` faz o par inteiro dar rollback.
- Campos copiados só se vazios no sobrevivente: `cnpj`, `razao_social`, `nome_fantasia`, `email`.
- Evento `lead_events` `mesclagem` (`source='sistema'`, `dedupe_key='mesclagem:<dup>'`,
  metadata com snapshot do duplicado e o motivo). `--aplicar` exige as colunas do P0.
- Gêmeas: par (venda do duplicado, venda do sobrevivente), nenhuma cancelada, uma `bling` e a
  outra `manual|crm`, mesmo valor (±0,005), `|Δ sold_at| ≤ 1 dia`. Só relata.
- Saída: `pares.csv`, `ambiguos.csv`, `orfaos.csv`, `gemeas.csv`, `backup.json`
  (`aplicados.csv` no `--aplicar`) e contagens em JSON no stdout.

- [ ] **Step 1: Testes de unidade falhando** — `backend/tests/test_cs_p1_mesclagem.py`:

```python
"""P1.1 — mesclagem dos leads `bling-*` duplicados: pareamento, gemeas e SQL.

Casos reais da call de 01/10: Jovens/Iago (celular no campo `telefone` do Bling), Serginho
(celular antigo sem o 9), ambiguo (celular e documento apontando para leads diferentes).
"""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "bling" / "mesclar_leads_duplicados.py"
_spec = importlib.util.spec_from_file_location("mesclar_leads_duplicados", SCRIPT)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

DUP = "8b915450-bf36-4bd6-be1b-fde35858f9ed"
HIAGO = "eb8ffb98-fbb2-4847-997c-89b7a0c04ac7"
OUTRO = "11111111-1111-1111-1111-111111111111"


def _cand(id_=DUP, **contato):
    base = {"account": "secundaria", "id": 18410375514, "nome": "Jovens Com Uma Missao",
            "doc_digits": None, "telefone_e164": None, "celular_e164": None}
    return {"id": id_, "phone": "bling-18410375514", "name": "Jovens", "contatos": [{**base, **contato}]}


def test_chaves_iguais_as_do_modulo_de_contatos():
    from app.bling.contacts import _chaves_de_celular
    casos = [
        {"telefone_e164": "5543999565650", "celular_e164": None},
        {"telefone_e164": "556697222209", "celular_e164": None},
        {"telefone_e164": "554332221111", "celular_e164": None},
        {"telefone_e164": None, "celular_e164": "554332221111"},
        {"telefone_e164": "5511987654321", "celular_e164": "5511912345678"},
        {"telefone_e164": None, "celular_e164": None},
    ]
    for c in casos:
        assert m.chaves_de_celular(c) == _chaves_de_celular(c), c


def test_jovens_iago_celular_no_campo_telefone_pareia():
    r = m.parear([_cand(telefone_e164="5543999565650", doc_digits="06132231000135")],
                 [{"id": HIAGO, "phone": "5543999565650", "name": "Hiago Angelucci", "cnpj": None}])
    assert [(p["duplicado"], p["sobrevivente"]) for p in r["pares"]] == [(DUP, HIAGO)]
    assert "celular:5543999565650" in r["pares"][0]["motivo"]
    assert r["ambiguos"] == [] and r["orfaos"] == []


def test_serginho_celular_antigo_sem_o_9_pareia():
    r = m.parear([_cand(telefone_e164="556697222209")],
                 [{"id": HIAGO, "phone": "5566997222209", "name": "Serginho Sinop", "cnpj": None}])
    assert len(r["pares"]) == 1


def test_lead_legado_sem_o_9_tambem_pareia():
    r = m.parear([_cand(celular_e164="5566997222209")],
                 [{"id": HIAGO, "phone": "556697222209", "name": "Serginho", "cnpj": None}])
    assert len(r["pares"]) == 1


def test_documento_pareia_mesmo_com_mascara_no_lead():
    r = m.parear([_cand(doc_digits="06132231000135")],
                 [{"id": HIAGO, "phone": "5543999565650", "name": "X", "cnpj": "06.132.231/0001-35"}])
    assert r["pares"][0]["motivo"] == "documento:06132231000135"


def test_celular_e_documento_em_leads_diferentes_e_ambiguo():
    r = m.parear([_cand(telefone_e164="5543999565650", doc_digits="06132231000135")],
                 [{"id": HIAGO, "phone": "5543999565650", "name": "Hiago", "cnpj": None},
                  {"id": OUTRO, "phone": "5511900000000", "name": "Jocum", "cnpj": "06132231000135"}])
    assert r["pares"] == []
    assert r["ambiguos"][0]["duplicado"] == DUP
    assert sorted(r["ambiguos"][0]["opcoes"]) == sorted([HIAGO, OUTRO])


def test_sem_achado_e_orfao_e_fixo_nao_conta():
    r = m.parear([_cand(telefone_e164="554332221111")],
                 [{"id": HIAGO, "phone": "554332221111", "name": "Fixo", "cnpj": None}])
    assert r["pares"] == [] and [o["duplicado"] for o in r["orfaos"]] == [DUP]


def test_outro_candidato_nunca_e_sobrevivente():
    outro_dup = _cand(id_=OUTRO, telefone_e164="5543999565650")
    outro_dup["phone"] = "5543999565650"
    r = m.parear([_cand(telefone_e164="5543999565650"), outro_dup],
                 [{"id": OUTRO, "phone": "5543999565650", "name": "Bling 2", "cnpj": None}])
    assert r["pares"] == []
    assert len(r["orfaos"]) == 2


def test_documento_lixo_nao_pareia():
    r = m.parear([_cand(doc_digits="00000000000")],
                 [{"id": HIAGO, "phone": "x", "name": "Lixo", "cnpj": "000.000.000-00"}])
    assert r["pares"] == []


def _venda(id_, lead, valor, origin, sold_at, status="registrada"):
    return {"id": id_, "lead_id": lead, "value": valor, "origin": origin,
            "status": status, "sold_at": sold_at}


PAR = [{"duplicado": DUP, "sobrevivente": HIAGO}]


def test_gemeas_iago_60_bling_e_60_manual():
    g = m.vendas_gemeas(PAR, [
        _venda("VB", DUP, 60, "bling", "2026-09-25T12:00:00+00:00"),
        _venda("VM", HIAGO, "60.00", "manual", "2026-09-24T15:00:00+00:00"),
    ])
    assert len(g) == 1
    assert (g[0]["venda_bling"], g[0]["venda_outra"]) == ("VB", "VM")
    assert g[0]["diferenca_horas"] == 21.0


@pytest.mark.parametrize("outra", [
    _venda("VM", HIAGO, 61, "manual", "2026-09-24T15:00:00+00:00"),
    _venda("VM", HIAGO, 60, "manual", "2026-09-23T11:00:00+00:00"),
    _venda("VM", HIAGO, 60, "manual", "2026-09-24T15:00:00+00:00", status="cancelada"),
    _venda("VM", HIAGO, 60, "bling", "2026-09-24T15:00:00+00:00"),
])
def test_nao_e_gemea(outra):
    assert m.vendas_gemeas(PAR, [_venda("VB", DUP, 60, "bling", "2026-09-25T12:00:00+00:00"),
                                 outra]) == []


def test_gemea_detectada_nos_dois_sentidos():
    g = m.vendas_gemeas(PAR, [
        _venda("VC", DUP, 90, "crm", "2026-09-23T12:00:00+00:00"),
        _venda("VB", HIAGO, 90, "bling", "2026-09-23T12:00:00+00:00"),
    ])
    assert [(x["venda_bling"], x["venda_outra"]) for x in g] == [("VB", "VC")]


def test_tabela_com_lead_id_nao_coberta_aborta():
    with pytest.raises(m.TabelaNaoCoberta) as exc:
        m.verificar_cobertura(m.TABELAS_COBERTAS | {"tabela_nova"})
    assert "tabela_nova" in str(exc.value)
    m.verificar_cobertura(set(m.TABELAS_COBERTAS))


def test_sql_do_par_move_tudo_e_apaga_o_duplicado():
    sql = m.sql_mesclar_par(DUP, HIAGO, {"sales", "messages", "lead_bling_contacts"}, "celular:1")
    assert sql.startswith("begin;") and sql.rstrip().endswith("commit;")
    assert f"update public.sales set lead_id = '{HIAGO}' where lead_id = '{DUP}';" in sql
    assert "delete from public.lead_bling_contacts d using public.lead_bling_contacts s" in sql
    assert "'mesclagem'" in sql and f"'mesclagem:{DUP}'" in sql
    assert f"delete from public.leads where id = '{DUP}';" in sql
    # tabela que nao existe no banco nao entra no SQL
    assert "public.deals" not in sql
    # o sobrevivente recebe cnpj/razao/fantasia/email so se vazios
    assert "coalesce(btrim(s.cnpj), '') = ''" in sql


def test_sql_recusa_id_que_nao_e_uuid():
    with pytest.raises(ValueError):
        m.sql_mesclar_par("x'; drop table leads; --", HIAGO, {"sales"}, "m")


def test_motivo_com_aspas_e_escapado():
    sql = m.sql_mesclar_par(DUP, HIAGO, set(), "nome d'agua")
    assert "nome d''agua" in sql
```

- [ ] **Step 2: Rodar e ver falhar** — `tests/test_cs_p1_mesclagem.py`. Esperado: FAIL (script não existe → `FileNotFoundError` no import).

- [ ] **Step 3: Implementar o script** `scripts/bling/mesclar_leads_duplicados.py`:

```python
#!/usr/bin/env python3
"""Mescla os leads `bling-*` duplicados no lead verdadeiro (spec 2026-10-06, P1.1).

POR QUE EXISTE: ate o fix `ba9cb923`, o webhook do Bling so olhava o campo `celular` do
contato. Quando o celular estava em `telefone` (o comum) ou no formato antigo sem o 9, o
`ensure_lead` nao achava o cliente e criava um lead `bling-<id>` com a venda — que caia
"sem origem" no /trafego (Jovens/Iago, Antonio Sergio). O fix impede NOVAS duplicatas; este
script junta as que ja existem.

REGRAS:
  - Candidato: `phone like 'bling-%'` OU `channel='bling'` com `metadata.origem='bling_webhook'`.
  - Par: chaves de celular do contato vinculado (com e sem o 9, mesmas de
    `app/bling/contacts._chaves_de_celular`) contra `leads.phone`, e `doc_digits` contra os
    digitos de `leads.cnpj`. Sobrevivente = o lead NAO-Bling. Mais de um possivel → ambiguo,
    nao mescla. Nenhum → orfao.
  - Move todas as linhas com `lead_id` (lista conferida contra information_schema — tabela
    nao coberta ABORTA), copia cnpj/razao_social/nome_fantasia/email so onde o sobrevivente
    esta vazio, grava `lead_events` 'mesclagem' e apaga o duplicado.
  - Vendas gemeas (mesmo valor, sold_at a <= 1 dia, uma bling e outra manual/crm): so relata.

USO (dry-run e o padrao — so le):
  python3 scripts/bling/mesclar_leads_duplicados.py \\
      --psql "docker exec -i $(docker ps -q -f name=supabase_db | head -1) psql -U postgres -d postgres" \\
      --saida /root/mesclagem-dryrun
  ... --aplicar     # executa, uma transacao por par — SO com OK do Rafael, depois do P0

Saida: pares.csv, ambiguos.csv, orfaos.csv, gemeas.csv, backup.json (+ aplicados.csv) e as
contagens em JSON no stdout. So stdlib: roda no host da VPS (psql), sem o venv do backend.
"""
import argparse
import csv
import json
import os
import shlex
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Chaves de celular — COPIA FIEL de app/bling/contacts.py (_celular_br e
# _chaves_de_celular). O script nao importa `app` (precisa de redis/supabase).
# tests/test_cs_p1_mesclagem.py compara as duas implementacoes.
# ---------------------------------------------------------------------------


def celular_br(e164):
    if not e164 or not e164.startswith("55"):
        return None
    if len(e164) == 13 and e164[4] == "9":
        return e164
    if len(e164) == 12 and e164[4] in "6789":
        return e164[:4] + "9" + e164[4:]
    return None


def chaves_de_celular(contato):
    chaves = []
    for campo in ("celular_e164", "telefone_e164"):
        bruto = contato.get(campo)
        celular = celular_br(bruto)
        if celular:
            candidatos = [celular, celular[:4] + celular[5:]]
        elif campo == "celular_e164" and bruto:
            candidatos = [bruto]
        else:
            candidatos = []
        for c in candidatos:
            if c not in chaves:
                chaves.append(c)
    return chaves


def doc_para_par(valor):
    """Digitos de CPF/CNPJ que servem de chave: 11 ou 14, nao repetitivos (lixo de importacao fora)."""
    d = "".join(ch for ch in str(valor or "") if ch.isdigit())
    if len(d) in (11, 14) and len(set(d)) > 1:
        return d
    return None


# ---------------------------------------------------------------------------
# Pareamento
# ---------------------------------------------------------------------------


def parear(candidatos, leads):
    """candidatos: [{id, phone, name, contatos: [{account, id, nome, doc_digits,
    telefone_e164, celular_e164}]}]; leads: linhas de `leads` que casaram alguma chave
    ({id, phone, name, cnpj}). Devolve {pares, ambiguos, orfaos}."""
    ids_candidatos = {c["id"] for c in candidatos}
    por_phone, por_doc, info = {}, {}, {}
    for lead in leads:
        if lead["id"] in ids_candidatos:
            continue
        info[lead["id"]] = lead
        if lead.get("phone"):
            por_phone.setdefault(lead["phone"], set()).add(lead["id"])
        d = doc_para_par(lead.get("cnpj"))
        if d:
            por_doc.setdefault(d, set()).add(lead["id"])

    pares, ambiguos, orfaos = [], [], []
    for cand in candidatos:
        achados = {}
        for contato in cand.get("contatos") or []:
            for chave in chaves_de_celular(contato):
                for lid in por_phone.get(chave, ()):
                    achados.setdefault(lid, set()).add(f"celular:{chave}")
            d = doc_para_par(contato.get("doc_digits"))
            if d:
                for lid in por_doc.get(d, ()):
                    achados.setdefault(lid, set()).add(f"documento:{d}")
        base = {"duplicado": cand["id"], "duplicado_nome": cand.get("name"),
                "duplicado_phone": cand.get("phone")}
        if len(achados) == 1:
            (lid, motivos), = achados.items()
            pares.append({**base, "sobrevivente": lid,
                          "sobrevivente_nome": info[lid].get("name"),
                          "sobrevivente_phone": info[lid].get("phone"),
                          "motivo": ";".join(sorted(motivos))})
        elif achados:
            ambiguos.append({**base, "opcoes": sorted(achados),
                             "motivo": ";".join(f"{lid}={'|'.join(sorted(mv))}"
                                                for lid, mv in sorted(achados.items()))})
        else:
            orfaos.append(base)
    return {"pares": pares, "ambiguos": ambiguos, "orfaos": orfaos}


# ---------------------------------------------------------------------------
# Vendas gemeas
# ---------------------------------------------------------------------------

_JANELA_GEMEAS = timedelta(days=1)


def _quando(valor):
    return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))


def vendas_gemeas(pares, vendas):
    """A mesma venda lancada duas vezes: uma pelo Bling (no duplicado ou no sobrevivente) e
    outra manual/crm, mesmo valor, sold_at a <= 1 dia. Canceladas nao contam. So relata."""
    por_lead = {}
    for v in vendas:
        if v.get("status") == "cancelada":
            continue
        por_lead.setdefault(v["lead_id"], []).append(v)
    saida = []
    for par in pares:
        do_dup = por_lead.get(par["duplicado"], [])
        do_sob = por_lead.get(par["sobrevivente"], [])
        for a in do_dup:
            for b in do_sob:
                origens = {a.get("origin"), b.get("origin")}
                if "bling" not in origens or not origens & {"manual", "crm"} or len(origens) != 2:
                    continue
                if abs(float(a["value"]) - float(b["value"])) >= 0.005:
                    continue
                delta = abs(_quando(a["sold_at"]) - _quando(b["sold_at"]))
                if delta > _JANELA_GEMEAS:
                    continue
                bling, outra = (a, b) if a.get("origin") == "bling" else (b, a)
                saida.append({
                    "sobrevivente": par["sobrevivente"], "duplicado": par["duplicado"],
                    "valor": float(bling["value"]),
                    "venda_bling": bling["id"], "sold_at_bling": bling["sold_at"],
                    "venda_outra": outra["id"], "origin_outra": outra.get("origin"),
                    "sold_at_outra": outra["sold_at"],
                    "diferenca_horas": round(delta.total_seconds() / 3600, 2),
                })
    return saida


# ---------------------------------------------------------------------------
# Tabelas com lead_id
# ---------------------------------------------------------------------------

# So mover: nenhuma unicidade envolvendo lead_id (ou, em `conversations`, colisao em
# (lead_id, channel_id) derruba a transacao do par inteiro — preferivel a fundir conversas).
SO_MOVER = (
    "sales", "deals", "quotes", "lead_notes", "lead_events", "conversations", "messages",
    "messages_archive", "conversion_events", "campaign_execution_log", "lp_email_jobs",
    "token_usage", "follow_up_jobs_incidente_20261003",
)

# Com unicidade: a linha do duplicado que colidiria com uma do sobrevivente e APAGADA (o
# sobrevivente vence; a linha vai para o backup) e o resto e movido. `d` = duplicado,
# `s` = sobrevivente.
COLISAO = {
    "lead_bling_contacts": "s.account = d.account",
    "lead_tags": "s.tag_id = d.tag_id",
    "lead_daily_sends": "s.date = d.date",
    "lead_seller_feelings": "s.user_id = d.user_id",
    "lead_qualification_scores": "true",
    "broadcast_leads": "s.broadcast_id = d.broadcast_id",
    "campaign_enrollments": ("s.campaign_id = d.campaign_id"
                             " and s.status in ('active', 'paused')"
                             " and d.status in ('active', 'paused')"),
    "follow_up_jobs": ("s.job_type = d.job_type and s.sequence is not distinct from d.sequence"
                       " and coalesce(s.metadata->>'deal_id', '') = coalesce(d.metadata->>'deal_id', '')"
                       " and s.status in ('pending', 'processing')"
                       " and d.status in ('pending', 'processing')"
                       r" and d.job_type like 'joao\_%'"),
}

TABELAS_COBERTAS = frozenset(SO_MOVER) | frozenset(COLISAO)


class TabelaNaoCoberta(RuntimeError):
    pass


def verificar_cobertura(tabelas_no_banco):
    faltando = sorted(set(tabelas_no_banco) - TABELAS_COBERTAS)
    if faltando:
        raise TabelaNaoCoberta(
            "tabela(s) com lead_id que o script nao sabe mesclar: " + ", ".join(faltando)
            + " — inclua em SO_MOVER ou COLISAO antes de rodar")


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------


def _uuid(valor):
    return str(uuid.UUID(str(valor)))


def _texto(valor):
    return "'" + str(valor).replace("'", "''") + "'"


CAMPOS_COPIADOS = ("cnpj", "razao_social", "nome_fantasia", "email")


def sql_mesclar_par(duplicado, sobrevivente, tabelas, motivo):
    """SQL de UM par, numa transacao. `tabelas` = tabelas com lead_id que existem no banco."""
    d, s = _uuid(duplicado), _uuid(sobrevivente)
    linhas = [
        "begin;",
        "do $$ begin",
        f"  if (select count(*) from public.leads where id in ('{d}', '{s}')) <> 2 then",
        f"    raise exception 'par {d} -> {s}: um dos leads nao existe mais';",
        "  end if;",
        "end $$;",
    ]
    for tabela in sorted(set(tabelas) & TABELAS_COBERTAS):
        if tabela in COLISAO:
            linhas.append(
                f"delete from public.{tabela} d using public.{tabela} s"
                f" where d.lead_id = '{d}' and s.lead_id = '{s}' and ({COLISAO[tabela]});")
        linhas.append(f"update public.{tabela} set lead_id = '{s}' where lead_id = '{d}';")
    sets = ",\n  ".join(
        f"{c} = case when coalesce(btrim(s.{c}), '') = '' then d.{c} else s.{c} end"
        for c in CAMPOS_COPIADOS)
    linhas.append(f"update public.leads s set\n  {sets}\nfrom public.leads d"
                  f" where s.id = '{s}' and d.id = '{d}';")
    linhas.append(
        "insert into public.lead_events"
        " (lead_id, event_type, old_value, new_value, metadata, occurred_at, source, dedupe_key)\n"
        f"select '{s}', 'mesclagem', '{d}', '{s}',"
        " jsonb_build_object('duplicado', jsonb_build_object('id', d.id, 'phone', d.phone,"
        " 'name', d.name, 'cnpj', d.cnpj, 'razao_social', d.razao_social, 'email', d.email,"
        " 'channel', d.channel, 'created_at', d.created_at, 'metadata', d.metadata),"
        f" 'motivo', {_texto(motivo)}),"
        f" now(), 'sistema', 'mesclagem:{d}'\n"
        f"from public.leads d where d.id = '{d}'\non conflict do nothing;")
    linhas.append(f"delete from public.leads where id = '{d}';")
    linhas.append("commit;")
    return "\n".join(linhas) + "\n"


# ---------------------------------------------------------------------------
# Banco (psql em subprocesso)
# ---------------------------------------------------------------------------


class Psql:
    def __init__(self, comando):
        self.base = shlex.split(comando)

    def _rodar(self, sql):
        proc = subprocess.run(self.base + ["-X", "-q", "-At", "-v", "ON_ERROR_STOP=1"],
                              input=sql, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or f"psql saiu com {proc.returncode}")
        return proc.stdout

    def linhas(self, sql):
        saida = self._rodar(f"select coalesce(json_agg(t), '[]'::json) from ({sql}) t;")
        return json.loads(saida.strip() or "[]")

    def executar(self, sql):
        self._rodar(sql)


Q_TABELAS = """
select c.table_name from information_schema.columns c
join information_schema.tables t using (table_schema, table_name)
where c.table_schema = 'public' and c.column_name = 'lead_id' and t.table_type = 'BASE TABLE'
"""

Q_COLUNAS_P0 = """
select column_name from information_schema.columns
where table_schema = 'public' and table_name = 'lead_events'
  and column_name in ('occurred_at', 'source', 'dedupe_key')
"""

Q_CANDIDATOS = """
select l.id, l.phone, l.name, l.cnpj, l.created_at,
       coalesce((select json_agg(json_build_object(
                   'account', bc.account, 'id', bc.id, 'nome', bc.nome,
                   'doc_digits', bc.doc_digits, 'telefone_e164', bc.telefone_e164,
                   'celular_e164', bc.celular_e164) order by bc.account)
                 from public.lead_bling_contacts lbc
                 join public.bling_contacts bc
                   on bc.account = lbc.account and bc.id = lbc.bling_contact_id
                 where lbc.lead_id = l.id), '[]'::json) as contatos
from public.leads l
where l.phone like 'bling-%'
   or (l.channel = 'bling' and l.metadata->>'origem' = 'bling_webhook')
order by l.created_at, l.id
"""


def _array_texto(valores):
    # So digitos chegam aqui (filtrados em `coletar_chaves`) — o literal e seguro.
    return "'{" + ",".join(sorted(valores)) + "}'::text[]"


def coletar_chaves(candidatos):
    chaves, docs = set(), set()
    for cand in candidatos:
        for contato in cand.get("contatos") or []:
            chaves.update(c for c in chaves_de_celular(contato) if c.isdigit())
            d = doc_para_par(contato.get("doc_digits"))
            if d:
                docs.add(d)
    return chaves, docs


def q_leads(chaves, docs):
    return ("select id, phone, name, cnpj from public.leads"
            f" where phone = any({_array_texto(chaves)})"
            rf" or regexp_replace(coalesce(cnpj, ''), '\D', '', 'g') = any({_array_texto(docs)})")


def q_vendas(ids):
    lista = ",".join(_uuid(i) for i in sorted(ids))
    return ("select id, lead_id, value, origin, status, sold_at from public.sales"
            f" where lead_id = any('{{{lista}}}'::uuid[])")


def q_backup(ids, tabelas):
    lista = ",".join(_uuid(i) for i in sorted(ids))
    extras = "".join(
        f", coalesce((select json_agg(to_jsonb(x)) from public.{t} x where x.lead_id = l.id),"
        f" '[]'::json) as {t}"
        for t in sorted(set(tabelas) & set(COLISAO)))
    return (f"select to_jsonb(l) as lead{extras} from public.leads l"
            f" where l.id = any('{{{lista}}}'::uuid[])")


# ---------------------------------------------------------------------------
# Execucao
# ---------------------------------------------------------------------------


def _csv(caminho, linhas, campos):
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        for linha in linhas:
            w.writerow({k: ("|".join(v) if isinstance(v, list) else v) for k, v in linha.items()})


def executar(db, saida, aplicar=False, limite=None):
    saida = Path(saida)
    saida.mkdir(parents=True, exist_ok=True)

    tabelas = {r["table_name"] for r in db.linhas(Q_TABELAS)}
    verificar_cobertura(tabelas)

    candidatos = db.linhas(Q_CANDIDATOS)
    chaves, docs = coletar_chaves(candidatos)
    leads = db.linhas(q_leads(chaves, docs)) if (chaves or docs) else []
    r = parear(candidatos, leads)
    pares = r["pares"]

    ids = {p["duplicado"] for p in pares} | {p["sobrevivente"] for p in pares}
    vendas = db.linhas(q_vendas(ids)) if ids else []
    gemeas = vendas_gemeas(pares, vendas)
    backup = db.linhas(q_backup({p["duplicado"] for p in pares}, tabelas)) if pares else []

    base = ["duplicado", "duplicado_nome", "duplicado_phone"]
    _csv(saida / "pares.csv", pares,
         base + ["sobrevivente", "sobrevivente_nome", "sobrevivente_phone", "motivo"])
    _csv(saida / "ambiguos.csv", r["ambiguos"], base + ["opcoes", "motivo"])
    _csv(saida / "orfaos.csv", r["orfaos"], base)
    _csv(saida / "gemeas.csv", gemeas,
         ["sobrevivente", "duplicado", "valor", "venda_bling", "sold_at_bling",
          "venda_outra", "origin_outra", "sold_at_outra", "diferenca_horas"])
    (saida / "backup.json").write_text(json.dumps(backup, ensure_ascii=False, indent=1),
                                       encoding="utf-8")

    aplicados = []
    if aplicar:
        if len(db.linhas(Q_COLUNAS_P0)) != 3:
            raise SystemExit("lead_events sem occurred_at/source/dedupe_key: aplique "
                             "supabase/migrations/20261006_call_semanal_base.sql antes do --aplicar")
        for par in pares[:limite] if limite else pares:
            try:
                db.executar(sql_mesclar_par(par["duplicado"], par["sobrevivente"], tabelas,
                                            par["motivo"]))
                aplicados.append({**par, "resultado": "ok", "erro": ""})
            except RuntimeError as exc:
                aplicados.append({**par, "resultado": "erro", "erro": str(exc)})
        _csv(saida / "aplicados.csv", aplicados,
             ["duplicado", "sobrevivente", "motivo", "resultado", "erro"])

    contagens = {
        "candidatos": len(candidatos), "pares": len(pares),
        "ambiguos": len(r["ambiguos"]), "orfaos": len(r["orfaos"]),
        "gemeas": len(gemeas), "vendas_do_duplicado_movidas": sum(
            1 for v in vendas if v["lead_id"] in {p["duplicado"] for p in pares}),
        "aplicados_ok": sum(1 for a in aplicados if a["resultado"] == "ok"),
        "aplicados_erro": sum(1 for a in aplicados if a["resultado"] == "erro"),
        "modo": "aplicar" if aplicar else "dry-run",
    }
    return {"contagens": contagens, "gemeas": gemeas, "aplicados": aplicados, **r}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--psql", default=os.environ.get("MESCLAR_PSQL"),
                    help="comando psql completo (ou env MESCLAR_PSQL)")
    ap.add_argument("--saida", default=None, help="pasta dos CSVs (default ./mesclagem-<data>)")
    ap.add_argument("--aplicar", action="store_true",
                    help="EXECUTA a mesclagem (uma transacao por par). Sem isto, so le.")
    ap.add_argument("--limite", type=int, default=None, help="aplica so os N primeiros pares")
    args = ap.parse_args(argv)
    if not args.psql:
        ap.error("informe --psql ou a env MESCLAR_PSQL")
    saida = args.saida or f"mesclagem-{datetime.now():%Y%m%d-%H%M%S}"
    resultado = executar(Psql(args.psql), saida, aplicar=args.aplicar, limite=args.limite)
    print(json.dumps(resultado["contagens"], ensure_ascii=False))
    print(f"arquivos em {Path(saida).resolve()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Rodar unidade e ver passar** — `tests/test_cs_p1_mesclagem.py`. Esperado: PASS.

- [ ] **Step 5: Teste de integração** — `backend/tests/test_cs_p1_mesclagem_pg.py`:

```python
"""P1.1 — mesclagem de verdade num Postgres 17 com o esquema de producao + P0.

Pula sem `CS_P1_PG_URL` (ex.: postgresql://postgres:scratch@127.0.0.1:55432) ou sem `psql`.
Roda no HOST (o container canastra-api nao tem psql):
  CS_P1_PG_URL=... <venv>/bin/python -m pytest --noconftest backend/tests/test_cs_p1_mesclagem_pg.py
"""
import csv
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

URL = os.environ.get("CS_P1_PG_URL")
pytestmark = pytest.mark.skipif(not URL or not shutil.which("psql"),
                                reason="sem CS_P1_PG_URL/psql")

RAIZ = Path(__file__).resolve().parents[2]
SCRIPT = RAIZ / "scripts" / "bling" / "mesclar_leads_duplicados.py"
P0 = RAIZ / "supabase" / "migrations" / "20261006_call_semanal_base.sql"
BANCO = "p1_mesclagem"

DUP = "8b915450-bf36-4bd6-be1b-fde35858f9ed"
SOB = "eb8ffb98-fbb2-4847-997c-89b7a0c04ac7"

SEED = f"""
insert into public.channels (id, name, phone, provider)
  values ('00000000-0000-0000-0000-0000000000c1', 'Joao', '553491461669', 'meta');
insert into public.leads (id, phone, name, channel, created_at)
  values ('{SOB}', '5543999565650', 'Hiago Angelucci', 'meta', '2026-09-22 10:00+00');
insert into public.leads (id, phone, name, channel, cnpj, razao_social, email, metadata, created_at)
  values ('{DUP}', 'bling-18410375514', 'Jovens Com Uma Missao', 'bling', '06132231000135',
          'Jovens Com Uma Missao Jocum', 'jocum@exemplo.org',
          '{{"origem": "bling_webhook", "id_bling": "18410375514"}}', '2026-09-25 15:53+00');
insert into public.bling_contacts (account, id, nome, doc_digits, telefone_e164)
  values ('secundaria', 18410375514, 'Jovens Com Uma Missao', '06132231000135', '5543999565650');
insert into public.lead_bling_contacts (lead_id, account, bling_contact_id)
  values ('{DUP}', 'secundaria', 18410375514);
insert into public.sales (id, lead_id, product, value, origin, status, sold_at)
  values ('00000000-0000-0000-0000-00000000b001', '{DUP}', 'Kit', 60, 'bling', 'registrada', '2026-09-25 12:00+00'),
         ('00000000-0000-0000-0000-00000000a001', '{SOB}', 'Kit', 60, 'manual', 'registrada', '2026-09-24 15:00+00');
insert into public.conversations (id, lead_id, channel_id)
  values ('00000000-0000-0000-0000-0000000000f1', '{SOB}', '00000000-0000-0000-0000-0000000000c1');
insert into public.messages (lead_id, conversation_id, role, content)
  values ('{SOB}', '00000000-0000-0000-0000-0000000000f1', 'user', 'quero o kit'),
         ('{DUP}', null, 'user', 'mensagem presa no duplicado');
"""


def _psql(banco, sql):
    out = subprocess.run(["psql", f"{URL}/{banco}", "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1"],
                         input=sql, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


@pytest.fixture()
def banco():
    _psql("postgres", f"drop database if exists {BANCO};")
    _psql("postgres", f"create database {BANCO} template crm_schema;")
    _psql(BANCO, P0.read_text(encoding="utf-8"))
    _psql(BANCO, SEED)
    yield f"psql {URL}/{BANCO}"
    _psql("postgres", f"drop database if exists {BANCO};")


def _script():
    spec = importlib.util.spec_from_file_location("mesclar_pg", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_dry_run_nao_escreve_e_relata(banco, tmp_path):
    m = _script()
    r = m.executar(m.Psql(banco), tmp_path)
    assert r["contagens"]["pares"] == 1 and r["contagens"]["gemeas"] == 1
    assert _psql(BANCO, f"select count(*) from public.leads where id = '{DUP}'") == "1"
    pares = list(csv.DictReader(open(tmp_path / "pares.csv", encoding="utf-8")))
    assert pares[0]["sobrevivente"] == SOB
    backup = json.loads((tmp_path / "backup.json").read_text(encoding="utf-8"))
    assert backup[0]["lead"]["id"] == DUP
    assert backup[0]["lead_bling_contacts"][0]["bling_contact_id"] == 18410375514


def test_aplicar_move_tudo_para_o_sobrevivente(banco, tmp_path):
    m = _script()
    r = m.executar(m.Psql(banco), tmp_path, aplicar=True)
    assert r["contagens"]["aplicados_ok"] == 1, r["aplicados"]

    q = lambda sql: _psql(BANCO, sql)  # noqa: E731
    assert q(f"select count(*) from public.leads where id = '{DUP}'") == "0"
    assert q(f"select count(*) from public.sales where lead_id = '{SOB}'") == "2"
    assert q(f"select count(*) from public.messages where lead_id = '{SOB}'") == "2"
    assert q(f"select account||':'||bling_contact_id from public.lead_bling_contacts"
             f" where lead_id = '{SOB}'") == "secundaria:18410375514"
    assert q(f"select cnpj||'|'||razao_social||'|'||email from public.leads where id = '{SOB}'") \
        == "06132231000135|Jovens Com Uma Missao Jocum|jocum@exemplo.org"
    assert q(f"select name from public.leads where id = '{SOB}'") == "Hiago Angelucci"
    assert q(f"select event_type||'|'||source||'|'||dedupe_key||'|'||(metadata->'duplicado'->>'phone')"
             f" from public.lead_events where lead_id = '{SOB}' and event_type = 'mesclagem'") \
        == f"mesclagem|sistema|mesclagem:{DUP}|bling-18410375514"

    # segunda rodada: nada mais a mesclar
    r2 = m.executar(m.Psql(banco), tmp_path / "2", aplicar=True)
    assert r2["contagens"]["pares"] == 0 and r2["contagens"]["candidatos"] == 0


def test_par_com_erro_faz_rollback_so_dele(banco, tmp_path):
    # conversa do duplicado no MESMO canal: (lead_id, channel_id) colide → rollback do par
    _psql(BANCO, f"insert into public.conversations (lead_id, channel_id) values"
                 f" ('{DUP}', '00000000-0000-0000-0000-0000000000c1');")
    m = _script()
    r = m.executar(m.Psql(banco), tmp_path, aplicar=True)
    assert r["contagens"]["aplicados_erro"] == 1
    assert _psql(BANCO, f"select count(*) from public.leads where id = '{DUP}'") == "1"
    assert _psql(BANCO, f"select count(*) from public.sales where lead_id = '{DUP}'") == "1"
```

- [ ] **Step 6: Rodar a integração no host** (Postgres descartável; precisa só de `pytest` num venv
  do scratchpad):
  ```bash
  python3 -m venv $SCRATCH/venv && $SCRATCH/venv/bin/pip install -q pytest
  cd /root/crm-wt/cs-p1 && flock /root/crm-wt/_heavy.lock env \
    CS_P1_PG_URL=postgresql://postgres:scratch@127.0.0.1:55432 \
    $SCRATCH/venv/bin/python -m pytest --noconftest -q -p no:cacheprovider \
    backend/tests/test_cs_p1_mesclagem_pg.py
  ```
  Esperado: 3 passed. (Ajustar o SEED às colunas reais se alguma NOT NULL faltar.)

- [ ] **Step 7: Commit** — `feat(bling): script de mesclagem dos leads bling-* duplicados`.

- [ ] **Step 8: Dry-run contra produção (somente leitura)**:
  ```bash
  cd /root/crm-wt/cs-p1 && python3 scripts/bling/mesclar_leads_duplicados.py \
    --psql "docker exec -i $(docker ps -q -f name=supabase_db | head -1) psql -U postgres -d postgres" \
    --saida $SCRATCH/mesclagem-dryrun
  ```
  Conferir nos CSVs: Jovens/Iago (`8b915450…` → `eb8ffb98…`, gêmea R$ 60), Serginho
  (`966977d1…` → `7c8638ee…`), Velho Hank (`289d5f93…` → `8a082d51…` "Luiz Felipe", ou órfão) e
  anexar as contagens ao relatório.

---

### Task 5: Verificação final

- [ ] Rodar (com flock) `tests/test_cs_p1_*.py tests/test_bling_*.py` no container e a
  integração no host; colar a saída exata no relatório.
- [ ] `git log --oneline feat/call-semanal-0110..feat/cs-p1` para o relatório.

## Fora do pacote (reportar, não editar)

- `frontend/src/components/sales/bling-contact-resolver.tsx` / `lead-bling-section.tsx`: nada
  precisa mudar — o write-back acontece no backend.
- `backend/app/leads/reposicao.py`: só chamado.
