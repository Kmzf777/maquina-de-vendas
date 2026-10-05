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
    leitura = [f for (t, _op, f, _p) in sb.log if t == "bling_contacts"]
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
    # O fake devolve a mesma linha para qualquer select em leads; forcamos o ramo do
    # celular fazendo a busca por documento nao achar nada.
    original = ct._find_lead
    monkeypatch.setattr(ct, "_find_lead",
                        lambda col, val: None if col == "cnpj" else original(col, val))

    lead_id = asyncio.run(ct.ensure_lead(contato, "secundaria"))

    assert lead_id == "HIAGO"
    assert sb.updates("leads") == [{"cnpj": "06132231000135",
                                    "razao_social": "Jovens Com Uma Missao"}]
