"""Testes da resolucao de identidade lead <-> contato Bling.

O que estes testes protegem: contato DUPLICADO no ERP do cliente. Duplicar
cadastro num ERP nao e cosmetico — a proxima nota fiscal sai no CNPJ errado.
"""
import asyncio

import pytest

import app.bling.contacts as ct
from app.bling.errors import BlingValidationError


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = {}

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def in_(self, col, vals):
        self.filters[col] = vals
        return self

    def or_(self, expr):
        self.filters["or"] = expr
        return self

    def limit(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def update(self, payload):
        self.filters["update"] = payload
        return self

    def insert(self, payload):
        self.filters["insert"] = payload
        return self

    def upsert(self, payload, on_conflict=None):
        self.filters["upsert"] = payload
        return self

    def execute(self):
        class R:
            pass
        r = R()
        r.data = self.rows
        return r


class FakeSupabase:
    """Devolve linhas por tabela; guarda o que foi escrito."""

    def __init__(self, por_tabela=None):
        self.por_tabela = por_tabela or {}
        self.queries = []

    def table(self, name):
        q = FakeQuery(self.por_tabela.get(name, []))
        q.name = name
        self.queries.append(q)
        return q


def _fake_lock(_key):
    class _Ctx:
        async def __aenter__(self):
            return True

        async def __aexit__(self, *_a):
            return False
    return _Ctx()


def test_digits_limpa_pontuacao():
    assert ct.doc_digits("29.860.598/0001-70") == "29860598000170"
    assert ct.doc_digits("123.456.789-09") == "12345678909"
    assert ct.doc_digits("") is None
    assert ct.doc_digits(None) is None


def test_documento_valido_so_com_11_ou_14_digitos():
    assert ct.is_valid_document("29860598000170") is True   # CNPJ real
    assert ct.is_valid_document("12345678909") is True      # CPF valido
    assert ct.is_valid_document("11111111111") is False     # repetido
    assert ct.is_valid_document("123") is False
    assert ct.is_valid_document("12345678901234") is False  # CNPJ com DV errado


def test_resolve_usa_o_vinculo_ja_gravado(monkeypatch):
    lead = {"id": "L1", "bling_contact_id": 999, "cnpj": "29860598000170"}
    # Instancia UNICA fora do lambda: `lambda: FakeSupabase()` construiria um objeto
    # novo a cada chamada e as escritas registradas se perderiam entre as queries.
    sb = FakeSupabase()
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.resolve(lead))

    assert out.contact_id == 999
    assert out.status == "linked"
    # Vinculo ja gravado nao consulta nada: e o caminho barato do dia a dia.
    assert sb.queries == []


def test_resolve_por_documento_vincula_sozinho(monkeypatch):
    lead = {"id": "L1", "bling_contact_id": None, "cnpj": "29.860.598/0001-70",
            "phone": "5551992696163"}
    sb = FakeSupabase({"bling_contacts": [{"id": 5845664414, "nome": "360 LTDA"}]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.resolve(lead))

    assert out.status == "linked"
    assert out.contact_id == 5845664414
    # o vinculo tem que ser PERSISTIDO — resolvido uma vez por cliente, para sempre
    assert any(q.filters.get("update", {}).get("bling_contact_id") == 5845664414
               for q in sb.queries)


def test_documento_com_dois_contatos_nao_vincula(monkeypatch):
    """Ambiguidade nunca vira palpite: devolve candidatos e para."""
    lead = {"id": "L1", "bling_contact_id": None, "cnpj": "29860598000170"}
    sb = FakeSupabase({"bling_contacts": [{"id": 1, "nome": "A"}, {"id": 2, "nome": "B"}]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.resolve(lead))

    assert out.status == "ambiguous"
    assert out.contact_id is None
    assert len(out.candidates) == 2
    assert not any("update" in q.filters for q in sb.queries)


def test_telefone_apenas_sugere_nunca_vincula(monkeypatch):
    """O telefone do lead costuma ser o do COMPRADOR; o contato do Bling e a
    EMPRESA. Casar por telefone sem confirmacao humana e chute."""
    lead = {"id": "L1", "bling_contact_id": None, "cnpj": None, "phone": "5551992696163"}
    sb = FakeSupabase({"bling_contacts": [{"id": 77, "nome": "Empresa X"}]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.resolve(lead))

    assert out.status == "suggested"
    assert out.contact_id is None
    assert out.candidates[0]["id"] == 77
    assert not any("update" in q.filters for q in sb.queries)


def test_telefone_do_lead_e_do_contato_casam_apesar_dos_formatos(monkeypatch):
    """INVARIANTE: os dois lados do casamento por telefone usam a MESMA normalizacao.

    `bling_contacts.telefone_e164`/`celular_e164` sao gravados por
    `app.bling.sync._to_e164_br`, que PREFIXA o "55" do Brasil. Se o lado do lead
    usasse `normalize_phone` puro — que NAO prefixa: "(51) 99269-6163" vira
    "51992696163" — a comparacao nunca casaria. E o pior tipo de falha: silenciosa.
    `resolve` devolveria "missing", o vendedor cadastraria de novo e o ERP ficaria
    com um contato DUPLICADO para um cliente que ja existe.

    Este teste trava a invariante: mesmo numero, formatos diferentes, tem que casar.
    """
    from app.bling.sync import map_contact

    # Como o contato chega do Bling: texto livre digitado por humano, formato local.
    espelhado = map_contact({"id": 77, "nome": "Empresa X", "telefone": "(51) 99269-6163"})
    assert espelhado["telefone_e164"] == "5551992696163"

    # Como o lead esta no CRM: E.164 sem "+". Tem que produzir a MESMA chave.
    lead_e164 = {"id": "L1", "bling_contact_id": None, "cnpj": None,
                 "phone": "5551992696163"}
    assert espelhado["telefone_e164"] in ct._phone_variants(lead_e164)

    # E um lead cujo telefone foi salvo em formato local (importacao antiga, colagem
    # manual) tambem tem que casar — a normalizacao e por comprimento, nao por origem.
    lead_local = {"id": "L1", "bling_contact_id": None, "cnpj": None,
                  "phone": "(51) 99269-6163"}
    assert espelhado["telefone_e164"] in ct._phone_variants(lead_local)

    # E de ponta a ponta: a expressao que vai ao Postgrest carrega o E.164, nao o local.
    sb = FakeSupabase({"bling_contacts": [espelhado]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.resolve(lead_local))

    assert out.status == "suggested"
    expr = next(q.filters["or"] for q in sb.queries if "or" in q.filters)
    assert "5551992696163" in expr


def test_sem_nenhum_match_devolve_missing(monkeypatch):
    lead = {"id": "L1", "bling_contact_id": None, "cnpj": None, "phone": "5511999999999"}
    sb = FakeSupabase()
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.resolve(lead))

    assert out.status == "missing"
    assert out.candidates == []


def test_create_recusa_sem_documento(monkeypatch):
    lead = {"id": "L1", "name": "Fulano", "phone": "5511999999999"}
    with pytest.raises(BlingValidationError) as exc:
        asyncio.run(ct.create_contact(None, lead, {"nome": "Fulano"}))
    assert "documento" in str(exc.value).lower()


def test_create_recheca_ao_vivo_e_vincula_em_vez_de_criar(monkeypatch):
    """O espelho pode estar minutos atrasado. Antes do POST, pergunta ao Bling."""
    lead = {"id": "L1", "name": "360 LTDA"}
    sb = FakeSupabase()
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)
    monkeypatch.setattr(ct, "_lock", _fake_lock)

    class FakeClient:
        def __init__(self):
            self.posts = []

        async def get(self, path, params=None):
            assert params["numeroDocumento"] == "29860598000170"
            return {"data": [{"id": 424242, "nome": "360 LTDA"}]}

        async def post(self, path, json=None):
            self.posts.append(json)
            return {"data": {"id": 999999}}

    client = FakeClient()
    out = asyncio.run(ct.create_contact(
        client, lead, {"nome": "360 LTDA", "numeroDocumento": "29.860.598/0001-70",
                       "tipo": "J"}))

    assert out == 424242
    assert client.posts == [], "nao pode criar quando o contato ja existe no Bling"


def test_create_faz_post_quando_realmente_nao_existe(monkeypatch):
    lead = {"id": "L1", "name": "Novo Cliente"}
    sb = FakeSupabase()
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)
    monkeypatch.setattr(ct, "_lock", _fake_lock)

    class FakeClient:
        def __init__(self):
            self.posts = []

        async def get(self, path, params=None):
            return {"data": []}

        async def post(self, path, json=None):
            self.posts.append(json)
            return {"data": {"id": 999999}}

    client = FakeClient()
    out = asyncio.run(ct.create_contact(
        client, lead, {"nome": "Novo Cliente", "numeroDocumento": "12345678909",
                       "tipo": "F", "email": "a@b.com"}))

    assert out == 999999
    enviado = client.posts[0]
    assert enviado["situacao"] == "A"
    assert enviado["numeroDocumento"] == "12345678909"
    assert enviado["tipo"] == "F"


def test_create_nao_cria_quando_o_lock_e_negado(monkeypatch):
    """Dois vendedores cadastrando o mesmo cliente ao mesmo tempo: o segundo espera.

    Se nem esperando conseguir a trava, RECUSA — seguir sem serializacao aqui
    significaria dois POST /contatos com o mesmo documento, ou seja, duplicata.
    Este e o unico lock do sistema que NAO pode ser fail-open.
    """
    def _lock_negado(_key):
        class _Ctx:
            async def __aenter__(self):
                return False

            async def __aexit__(self, *_a):
                return False
        return _Ctx()

    sb = FakeSupabase()
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)
    monkeypatch.setattr(ct, "_lock", _lock_negado)

    class FakeClient:
        def __init__(self):
            self.posts = []
            self.gets = []

        async def get(self, path, params=None):
            self.gets.append(params)
            return {"data": []}

        async def post(self, path, json=None):
            self.posts.append(json)
            return {"data": {"id": 999999}}

    client = FakeClient()
    with pytest.raises(BlingValidationError) as exc:
        asyncio.run(ct.create_contact(
            client, {"id": "L1"}, {"nome": "X", "numeroDocumento": "12345678909"}))

    assert exc.value.status == 409
    assert client.posts == []
    assert client.gets == []


def test_ensure_lead_reaproveita_lead_existente_por_documento(monkeypatch):
    contato = {"id": 55, "nome": "Empresa", "doc_digits": "29860598000170",
               "celular_e164": "5551992696163"}
    sb = FakeSupabase({"leads": [{"id": "LEAD-X"}]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.ensure_lead(contato))

    assert out == "LEAD-X"


def test_ensure_lead_cria_com_placeholder_quando_contato_nao_tem_telefone(monkeypatch):
    """leads.phone e UNIQUE NOT NULL — precisa de valor sempre."""
    contato = {"id": 55, "nome": "Sem Telefone", "doc_digits": "12345678909",
               "telefone_e164": None, "celular_e164": None}
    sb = FakeSupabase({"leads": []})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    asyncio.run(ct.ensure_lead(contato))

    inseridos = [q.filters["insert"] for q in sb.queries if "insert" in q.filters]
    assert inseridos[0]["phone"] == "bling-55"
    assert inseridos[0]["bling_contact_id"] == 55
    assert inseridos[0]["metadata"]["origem"] == "bling_webhook"
