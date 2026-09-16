"""Testes da resolucao de identidade lead <-> contato Bling.

O que estes testes protegem: contato DUPLICADO no ERP do cliente, e venda lancada
no cadastro errado. Nenhum dos dois erros aparece na tela — aparece na nota fiscal.
"""
import asyncio

import pytest

import app.bling.contacts as ct
from app.bling.errors import BlingValidationError


class FakeQuery:
    def __init__(self, tabela, resolver):
        self.name = tabela
        self._resolver = resolver
        self.filters = {}
        self._single = False

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
        # Marca a chamada em vez de so devolver self: o supabase-py real colapsa
        # o resultado para UM registro (ou None) em vez de uma lista, e
        # `_contato_do_lead`/`_lead_por_contato` (novas em contacts.py) dependem
        # exatamente desse formato. Sem simular o colapso aqui, o double devolve
        # a lista crua do resolver e `linha.get(...)` quebra com AttributeError.
        self._single = True
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
        dados = self._resolver(self.name, self.filters)
        if self._single:
            dados = dados[0] if dados else None
        r.data = dados
        return r


class FakeSupabase:
    """Devolve linhas por tabela; guarda o que foi escrito.

    Cada valor de `por_tabela` e uma lista (mesma resposta para qualquer query) ou
    um callable(filters) -> list, para o teste discriminar POR FILTRO.

    O callable existe por um motivo concreto: um fake que devolve a mesma linha
    para qualquer consulta em `leads` faz o PRIMEIRO `_find_lead` de `ensure_lead`
    acertar sempre, e os ramos seguintes nunca executam. O teste fica verde sem
    exercitar o codigo que diz testar — apagar o ramo inteiro nao quebraria nada.
    """

    def __init__(self, por_tabela=None):
        self.por_tabela = por_tabela or {}
        self.queries = []

    def table(self, name):
        q = FakeQuery(name, self._resolve)
        self.queries.append(q)
        return q

    def _resolve(self, tabela, filters):
        regra = self.por_tabela.get(tabela, [])
        if callable(regra):
            return regra(filters) or []
        return regra


class FakeUniqueViolation(Exception):
    """Imita o APIError do supabase-py para violacao de UNIQUE (SQLSTATE 23505)."""

    def __init__(self):
        super().__init__('duplicate key value violates unique constraint '
                         '"lead_bling_contacts_account_contact_key"')
        self.code = "23505"


def _fake_lock(_key):
    class _Ctx:
        async def __aenter__(self):
            return True

        async def __aexit__(self, *_a):
            return False
    return _Ctx()


# ==========================================================================
# Documento
# ==========================================================================
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


def test_digito_verificador_e_conferido_de_verdade():
    """Casos que SO o calculo do DV separa — comprimento e repeticao nao pegam.

    Sem eles a validacao inteira pode ser trocada por `len(set(d)) != 1` e a suite
    fica verde: os outros casos sao todos discriminados por comprimento ou por
    digito repetido. E o DV e justamente a defesa contra o erro que importa aqui —
    documento digitado errado nao acha o contato existente e cria um duplicado.
    """
    # CPF valido, mas com UM dos dois digitos verificadores trocado.
    assert ct.is_valid_document("12345678919") is False  # DV1 errado (0 -> 1)
    assert ct.is_valid_document("12345678900") is False  # DV2 errado (9 -> 0)
    # CNPJ valido com so o primeiro DV trocado (7 -> 6); o segundo continua certo.
    assert ct.is_valid_document("29860598000160") is False
    # E a contraprova: os originais passam.
    assert ct.is_valid_document("12345678909") is True
    assert ct.is_valid_document("29860598000170") is True


# ==========================================================================
# resolve
# ==========================================================================
def test_resolve_usa_o_vinculo_ja_gravado(monkeypatch):
    lead = {"id": "L1", "cnpj": "29860598000170"}
    # Instancia UNICA fora do lambda: `lambda: FakeSupabase()` construiria um objeto
    # novo a cada chamada e as escritas registradas se perderiam entre as queries.
    sb = FakeSupabase({"lead_bling_contacts": [{"bling_contact_id": 999}]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.resolve(lead, "default"))

    assert out.contact_id == 999
    assert out.status == "linked"
    # Vinculo ja gravado nao chega a olhar o espelho de contatos: e o caminho
    # barato do dia a dia. So consulta `lead_bling_contacts`.
    assert not any(q.name == "bling_contacts" for q in sb.queries)


def test_resolve_por_documento_vincula_sozinho(monkeypatch):
    lead = {"id": "L1", "cnpj": "29.860.598/0001-70", "phone": "5551992696163"}
    sb = FakeSupabase({"bling_contacts": [{"id": 5845664414, "nome": "360 LTDA"}]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.resolve(lead))

    assert out.status == "linked"
    assert out.contact_id == 5845664414
    # o vinculo tem que ser PERSISTIDO em lead_bling_contacts — resolvido uma vez
    # por cliente NESTA conta, para sempre
    assert any(q.name == "lead_bling_contacts" and
               q.filters.get("upsert", {}).get("bling_contact_id") == 5845664414
               for q in sb.queries)


def test_resolve_ignora_documento_invalido(monkeypatch):
    """I1: `cnpj` lixo nao pode virar chave de vinculo automatico.

    O ramo do documento e o unico que vincula sozinho E grava. Numa base importada
    de ERP (os 1.208 leads da reativacao) o campo vem com placeholder e digitacao
    errada — e lixo casa contra um `doc_digits` igualmente lixo no espelho,
    produzindo um vinculo permanente nascido de nada. Documento invalido nao pode
    nem chegar a consultar o espelho.
    """
    lead = {"id": "L1", "cnpj": "00000000000", "phone": "5551992696163"}
    sb = FakeSupabase({"bling_contacts": [{"id": 77, "nome": "Empresa X"}]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.resolve(lead))

    assert out.status == "suggested", "documento invalido nunca vincula"
    assert out.reason == "telefone"
    assert not any("upsert" in q.filters for q in sb.queries)
    assert not any("doc_digits" in q.filters for q in sb.queries), \
        "nem chega a consultar o espelho por um documento invalido"


def test_documento_com_dois_contatos_nao_vincula(monkeypatch):
    """Ambiguidade nunca vira palpite: devolve candidatos e para."""
    lead = {"id": "L1", "cnpj": "29860598000170"}
    sb = FakeSupabase({"bling_contacts": [{"id": 1, "nome": "A"}, {"id": 2, "nome": "B"}]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.resolve(lead))

    assert out.status == "ambiguous"
    assert out.contact_id is None
    assert len(out.candidates) == 2
    assert not any("upsert" in q.filters for q in sb.queries)


def test_resolve_devolve_ambiguous_quando_o_contato_ja_tem_dono(monkeypatch):
    """I5: dois leads com o mesmo CNPJ e plausivel; 500 opaco nao e resposta.

    `lead_bling_contacts` tem UNIQUE em (account, bling_contact_id). `resolve(A)`
    ja vinculou A ao contato C nesta conta; agora `resolve(B)` acha o mesmo C por
    documento e o Postgres recusa o upsert (23505). Sem tratamento o vendedor ve
    erro sem diagnostico. Com tratamento cai na mesma porta que qualquer outra
    ambiguidade: decide o humano.
    """
    def lead_bling_contacts(filters):
        if "upsert" in filters:
            raise FakeUniqueViolation()
        return []

    lead = {"id": "LEAD-B", "cnpj": "29860598000170"}
    sb = FakeSupabase({"bling_contacts": [{"id": 5845664414, "nome": "360 LTDA"}],
                       "lead_bling_contacts": lead_bling_contacts})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.resolve(lead))

    assert out.status == "ambiguous"
    assert out.contact_id is None
    assert out.reason == "contato_ja_vinculado"
    assert out.candidates[0]["id"] == 5845664414


def test_resolve_nao_engole_erro_que_nao_seja_de_unicidade(monkeypatch):
    """O catch do 23505 e cirurgico: qualquer outra falha continua subindo.

    Transformar "Supabase fora do ar" em `ambiguous` esconderia incidente atras de
    uma tela de escolha de candidato.
    """
    def lead_bling_contacts(filters):
        if "upsert" in filters:
            raise RuntimeError("conexao recusada")
        return []

    lead = {"id": "L1", "cnpj": "29860598000170"}
    sb = FakeSupabase({"bling_contacts": [{"id": 1, "nome": "A"}],
                       "lead_bling_contacts": lead_bling_contacts})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    with pytest.raises(RuntimeError):
        asyncio.run(ct.resolve(lead))


def test_telefone_apenas_sugere_nunca_vincula(monkeypatch):
    """O telefone do lead costuma ser o do COMPRADOR; o contato do Bling e a
    EMPRESA. Casar por telefone sem confirmacao humana e chute."""
    lead = {"id": "L1", "cnpj": None, "phone": "5551992696163"}
    sb = FakeSupabase({"bling_contacts": [{"id": 77, "nome": "Empresa X"}]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.resolve(lead))

    assert out.status == "suggested"
    assert out.contact_id is None
    assert out.candidates[0]["id"] == 77
    assert not any("upsert" in q.filters for q in sb.queries)


def test_email_apenas_sugere_nunca_vincula(monkeypatch):
    """A outra metade da invariante central — e a que estava 100% descoberta.

    E-mail corporativo e compartilhado (contato@, financeiro@, o e-mail do
    contador). Vale exatamente o mesmo que o telefone: sugere, nunca vincula.
    Sem este teste, fazer o ramo de e-mail devolver "linked" e chamar `_link`
    passa despercebido pela suite inteira.
    """
    lead = {"id": "L1", "cnpj": None, "phone": None,
            "email": "  Contato@Empresa.com  "}
    sb = FakeSupabase({"bling_contacts": [{"id": 88, "nome": "Empresa X"}]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.resolve(lead))

    assert out.status == "suggested"
    assert out.reason == "email"
    assert out.contact_id is None
    assert out.candidates[0]["id"] == 88
    assert not any("upsert" in q.filters for q in sb.queries)
    # e casado normalizado (trim + lower): o cadastro digitado com maiuscula no
    # Bling nunca casaria com o do CRM se comparassemos o texto cru.
    assert any(q.filters.get("email") == "contato@empresa.com" for q in sb.queries)


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
    lead_e164 = {"id": "L1", "cnpj": None, "phone": "5551992696163"}
    assert espelhado["telefone_e164"] in ct._phone_variants(lead_e164)

    # E um lead cujo telefone foi salvo em formato local (importacao antiga, colagem
    # manual) tambem tem que casar — a normalizacao e por comprimento, nao por origem.
    lead_local = {"id": "L1", "cnpj": None, "phone": "(51) 99269-6163"}
    assert espelhado["telefone_e164"] in ct._phone_variants(lead_local)

    # E de ponta a ponta: a expressao que vai ao Postgrest carrega o E.164, nao o local.
    sb = FakeSupabase({"bling_contacts": [espelhado]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.resolve(lead_local))

    assert out.status == "suggested"
    expr = next(q.filters["or"] for q in sb.queries if "or" in q.filters)
    assert "5551992696163" in expr


def test_sem_nenhum_match_devolve_missing(monkeypatch):
    lead = {"id": "L1", "cnpj": None, "phone": "5511999999999"}
    sb = FakeSupabase()
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.resolve(lead))

    assert out.status == "missing"
    assert out.candidates == []


# ==========================================================================
# create_contact
# ==========================================================================
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
            # Resposta FIEL a real: o contato do Bling TRAZ o documento, formatado.
            # Um fake sem esse campo nao pressionaria a reconferencia do lado do CRM.
            return {"data": [{"id": 424242, "nome": "360 LTDA",
                              "numeroDocumento": "29.860.598/0001-70"}]}

        async def post(self, path, json=None):
            self.posts.append(json)
            return {"data": {"id": 999999}}

    client = FakeClient()
    out = asyncio.run(ct.create_contact(
        client, lead, {"nome": "360 LTDA", "numeroDocumento": "29.860.598/0001-70",
                       "tipo": "J"}))

    assert out == 424242
    assert client.posts == [], "nao pode criar quando o contato ja existe no Bling"
    # E o vinculo precisa ficar GRAVADO em lead_bling_contacts: sem isso a proxima
    # venda refaz tudo.
    assert any(q.name == "lead_bling_contacts" and
               q.filters.get("upsert", {}).get("bling_contact_id") == 424242
               for q in sb.queries)


def test_create_ignora_contato_que_nao_tem_o_documento_pedido(monkeypatch):
    """I3: nao confia no filtro do servidor.

    Se o Bling ignorar `numeroDocumento` — parametro desconhecido, e REST costuma
    devolver a colecao inteira em vez de erro — `data[0]` seria um contato QUALQUER
    da conta, e vinculariamos o cliente a ele. Falha silenciosa e catastrofica, no
    ponto exato que existe para impedir duplicata. A resposta e reconferida item a
    item; nao sobrando ninguem, cria de verdade.
    """
    lead = {"id": "L1", "name": "Novo Cliente"}
    sb = FakeSupabase()
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)
    monkeypatch.setattr(ct, "_lock", _fake_lock)

    class FakeClient:
        def __init__(self):
            self.posts = []

        async def get(self, path, params=None):
            # Filtro ignorado: volta o primeiro contato da conta, de outro cliente.
            return {"data": [{"id": 1, "nome": "Primeiro Contato Da Conta",
                              "numeroDocumento": "11.222.333/0001-81"}]}

        async def post(self, path, json=None):
            self.posts.append(json)
            return {"data": {"id": 999999}}

    client = FakeClient()
    out = asyncio.run(ct.create_contact(
        client, lead, {"nome": "Novo Cliente", "numeroDocumento": "12345678909",
                       "tipo": "F"}))

    assert out == 999999, "documento nao confere: e outro cliente, tem que criar"
    assert client.posts[0]["numeroDocumento"] == "12345678909"
    assert not any(q.name == "lead_bling_contacts" and
                   q.filters.get("upsert", {}).get("bling_contact_id") == 1
                   for q in sb.queries)


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


def test_create_devolve_409_quando_o_contato_ja_e_de_outro_lead(monkeypatch):
    """I5: aqui a falta de tratamento e pior que no `resolve`.

    O contato JA existe no Bling, entao toda tentativa futura repete
    GET -> acha -> `_link` -> 23505: laco de falha permanente, sem mensagem que
    permita ao vendedor entender o que fazer. Vira 409 com instrucao.
    """
    def lead_bling_contacts(filters):
        if "upsert" in filters:
            raise FakeUniqueViolation()
        return []

    sb = FakeSupabase({"lead_bling_contacts": lead_bling_contacts})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)
    monkeypatch.setattr(ct, "_lock", _fake_lock)

    class FakeClient:
        def __init__(self):
            self.posts = []

        async def get(self, path, params=None):
            return {"data": [{"id": 424242, "nome": "360 LTDA",
                              "numeroDocumento": "12345678909"}]}

        async def post(self, path, json=None):
            self.posts.append(json)
            return {"data": {"id": 999999}}

    client = FakeClient()
    with pytest.raises(BlingValidationError) as exc:
        asyncio.run(ct.create_contact(
            client, {"id": "L1"}, {"nome": "X", "numeroDocumento": "12345678909"}))

    assert exc.value.status == 409
    assert "outro lead" in str(exc.value).lower()
    assert client.posts == []


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


# ==========================================================================
# ensure_lead (caminho inverso: contato do Bling sem lead no CRM)
# ==========================================================================
def test_ensure_lead_reaproveita_lead_existente_por_documento(monkeypatch):
    """O reaproveitamento tem que vir do RAMO DO DOCUMENTO, nao do primeiro acaso.

    O fake responde POR FILTRO: a busca de `_lead_por_contato` (em
    `lead_bling_contacts`) nao acha nada, so a busca por `cnpj` (em `leads`) acha.
    Com um fake que devolve a mesma linha para qualquer query em `leads`, a
    primeira chamada ja retornaria e este ramo nunca rodaria — apagar o ramo
    inteiro do codigo deixaria o teste verde.
    """
    contato = {"id": 55, "nome": "Empresa", "doc_digits": "29860598000170",
               "celular_e164": "5551992696163"}

    def leads(filters):
        if filters.get("cnpj") == "29860598000170":
            return [{"id": "LEAD-X", "cnpj": "29860598000170"}]
        return []

    sb = FakeSupabase({"leads": leads})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.ensure_lead(contato))

    assert out == "LEAD-X"
    # achou por documento e o lead ainda nao tinha vinculo NESTA conta: PODE gravar
    assert any(q.name == "lead_bling_contacts" and
               q.filters.get("upsert", {}).get("bling_contact_id") == 55
               for q in sb.queries)


def test_ensure_lead_nao_sobrescreve_vinculo_existente_no_ramo_do_documento(monkeypatch):
    """C1, ramo 2: o lead achado por documento ja pertence a outro contato.

    Acontece quando o ERP tem documento duplicado. `_link` e UPDATE incondicional:
    sem a guarda, o lead trocaria de dono silenciosamente.
    """
    contato = {"id": 200, "nome": "Empresa (2o cadastro)",
               "doc_digits": "29860598000170", "celular_e164": None}

    def leads(filters):
        if filters.get("cnpj") == "29860598000170":
            return [{"id": "LEAD-X", "cnpj": "29860598000170"}]
        return []

    def lead_bling_contacts(filters):
        if filters.get("lead_id") == "LEAD-X":
            return [{"bling_contact_id": 100}]
        return []

    sb = FakeSupabase({"leads": leads, "lead_bling_contacts": lead_bling_contacts})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.ensure_lead(contato))

    assert out == "LEAD-X", "reaproveita o lead (nao duplica) sem regravar o vinculo"
    assert not any(q.name == "lead_bling_contacts" and "upsert" in q.filters
                   for q in sb.queries)


def test_ensure_lead_nao_sobrescreve_vinculo_existente_no_ramo_do_telefone(monkeypatch):
    """C1: um palpite de telefone NUNCA substitui um vinculo ja estabelecido.

    Cenario sem humano no meio: o lead L foi vinculado ao contato 100 por documento
    (deterministico). Chega o webhook do contato 200, sem documento, cujo celular
    casa com o telefone de L. Se `_link` rodar, L passa a apontar para 200 e a
    proxima venda de L sai no cadastro errado — nota fiscal no CNPJ errado.

    O indice UNIQUE nao protege disso: ele impede dois leads apontarem para o mesmo
    contato, nao um lead trocar de contato.
    """
    contato = {"id": 200, "nome": "Outro", "doc_digits": None,
               "celular_e164": "5551992696163"}

    def leads(filters):
        if filters.get("phone") == "5551992696163":
            return [{"id": "LEAD-L", "cnpj": "29860598000170"}]
        return []

    def lead_bling_contacts(filters):
        if filters.get("lead_id") == "LEAD-L":
            return [{"bling_contact_id": 100}]
        return []

    sb = FakeSupabase({"leads": leads, "lead_bling_contacts": lead_bling_contacts})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.ensure_lead(contato))

    assert out == "LEAD-L", "devolve o lead (nao duplica), mas sem regravar o vinculo"
    assert not any(q.name == "lead_bling_contacts" and "upsert" in q.filters
                   for q in sb.queries)


def test_ensure_lead_recusa_vinculo_por_telefone_com_documento_divergente(monkeypatch):
    """C1: documentos diferentes sao clientes diferentes, por mais que o telefone bata.

    Numero compartilhado — matriz, escritorio do contador, celular do socio que
    responde por duas empresas — e comum na base real. O lead ainda e reaproveitado
    (senao o insert estouraria o UNIQUE de `leads.phone`), mas sem gravar vinculo.
    """
    contato = {"id": 200, "nome": "Empresa B", "doc_digits": "11222333000181",
               "celular_e164": "5551992696163"}

    def leads(filters):
        if filters.get("phone") == "5551992696163":
            # cnpj do lead vem FORMATADO: a comparacao tem que ser por digitos
            return [{"id": "LEAD-A", "cnpj": "29.860.598/0001-70"}]
        return []

    sb = FakeSupabase({"leads": leads})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.ensure_lead(contato))

    assert out == "LEAD-A"
    assert not any(q.name == "lead_bling_contacts" and "upsert" in q.filters
                   for q in sb.queries)


def test_ensure_lead_vincula_por_celular_quando_nada_impede(monkeypatch):
    """Contraprova das duas recusas acima: sem vinculo previo e sem documento
    divergente, o celular VINCULA (a assimetria com `resolve` e proposital)."""
    contato = {"id": 200, "nome": "Empresa", "doc_digits": "29860598000170",
               "celular_e164": "5551992696163"}

    def leads(filters):
        if filters.get("phone") == "5551992696163":
            return [{"id": "LEAD-A", "cnpj": None}]
        return []

    sb = FakeSupabase({"leads": leads})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.ensure_lead(contato))

    assert out == "LEAD-A"
    assert any(q.name == "lead_bling_contacts" and
               q.filters.get("upsert", {}).get("bling_contact_id") == 200
               for q in sb.queries)


def test_ensure_lead_nao_usa_fixo_como_chave_de_vinculo(monkeypatch):
    """I2: fixo de empresa e compartilhado entre varios contatos do Bling.

    Como neste caminho o telefone GRAVA vinculo, aceitar o fixo prenderia leads
    distintos ao mesmo cadastro. So o celular serve de chave. O fixo continua no
    espelho (`bling_contacts.telefone_e164`), entao nada se perde. Em
    `_query_by_phones` o fixo pode entrar, porque la o resultado so sugere.
    """
    contato = {"id": 55, "nome": "Empresa", "doc_digits": None,
               "telefone_e164": "5551133334444", "celular_e164": None}
    sb = FakeSupabase({"leads": []})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    asyncio.run(ct.ensure_lead(contato))

    assert not any(q.filters.get("phone") == "5551133334444" for q in sb.queries), \
        "o fixo nao pode virar chave de busca de lead"
    inseridos = [q.filters["insert"] for q in sb.queries if "insert" in q.filters]
    assert inseridos[0]["phone"] == "bling-55", \
        "sem celular, placeholder — o fixo nao vira nem chave nem telefone do lead"


def test_ensure_lead_cria_com_placeholder_quando_contato_nao_tem_telefone(monkeypatch):
    """leads.phone e UNIQUE NOT NULL — precisa de valor sempre."""
    contato = {"id": 55, "nome": "Sem Telefone", "doc_digits": "12345678909",
               "telefone_e164": None, "celular_e164": None}

    def leads(filters):
        if "insert" in filters:
            return [{"id": "LEAD-NOVO"}]
        return []

    sb = FakeSupabase({"leads": leads})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.ensure_lead(contato))

    assert out == "LEAD-NOVO"
    inseridos = [q.filters["insert"] for q in sb.queries if "insert" in q.filters]
    assert inseridos[0]["phone"] == "bling-55"
    assert "bling_contact_id" not in inseridos[0], \
        "o vinculo agora mora em lead_bling_contacts, nao mais numa coluna do lead"
    assert inseridos[0]["metadata"]["origem"] == "bling_webhook"
    # apos o insert, o vinculo do lead recem-criado tem que ser gravado a parte
    assert any(q.name == "lead_bling_contacts" and
               q.filters.get("upsert") == {"lead_id": "LEAD-NOVO", "account": "default",
                                            "bling_contact_id": 55}
               for q in sb.queries)


# ==========================================================================
# Segunda conta Bling: o vinculo passa a ser por (lead, conta)
# ==========================================================================
async def test_vincula_lead_por_conta(monkeypatch):
    from app.bling import contacts
    gravado = {}

    def fake_link(lead_id, contact_id, account):
        gravado.update({"lead_id": lead_id, "account": account,
                        "contact_id": contact_id})

    monkeypatch.setattr(contacts, "_link", fake_link)
    await contacts.link("lead-1", 999, "secundaria")
    assert gravado == {"lead_id": "lead-1", "account": "secundaria",
                       "contact_id": 999}


async def test_mesmo_lead_pode_ter_contato_nas_duas_contas(monkeypatch):
    """O caso 'alguns clientes em comum': o mesmo cliente existe nos dois CNPJs
    com IDs diferentes, e o lead precisa apontar para os dois ao mesmo tempo."""
    from app.bling import contacts
    gravadas = []

    def fake_link(lead_id, contact_id, account):
        gravadas.append((lead_id, account, contact_id))

    monkeypatch.setattr(contacts, "_link", fake_link)
    await contacts.link("lead-1", 111, "default")
    await contacts.link("lead-1", 222, "secundaria")
    assert gravadas == [("lead-1", "default", 111),
                        ("lead-1", "secundaria", 222)]


async def test_resolve_ignora_vinculo_de_outra_conta(monkeypatch):
    """REGRESSAO DA ARMADILHA: um lead vinculado na conta 1 deve continuar
    resolvivel na conta 2, senao o cliente em comum nunca e vinculado la."""
    from app.bling import contacts

    monkeypatch.setattr(contacts, "_contato_do_lead",
                        lambda lead_id, account: 111 if account == "default" else None)
    monkeypatch.setattr(contacts, "_query_by_doc",
                        lambda doc, account: [{"id": 222}])
    gravado = {}
    monkeypatch.setattr(contacts, "_link",
                        lambda lead_id, contact_id, account: gravado.update(
                            {"contact_id": contact_id, "account": account}))

    lead = {"id": "lead-1", "cnpj": "11222333000181"}
    r = await contacts.resolve(lead, "secundaria")
    assert r.status == "linked"
    assert gravado == {"contact_id": 222, "account": "secundaria"}


def test_pode_vincular_por_telefone_olha_so_a_conta_corrente():
    """Mesma armadilha do outro lado: ter contato na conta 1 nao pode BLOQUEAR
    o vinculo por telefone na conta 2."""
    from app.bling import contacts
    assert contacts._pode_vincular_por_telefone(
        {"cnpj": None}, None, contato_da_conta=None) is True
    assert contacts._pode_vincular_por_telefone(
        {"cnpj": None}, None, contato_da_conta=111) is False


def test_espelho_de_contato_usa_chave_composta(monkeypatch):
    from app.bling import contacts
    capturado = {}

    class FakeTable:
        def upsert(self, row, on_conflict=None):
            capturado["row"] = row
            capturado["on_conflict"] = on_conflict
            return self
        def execute(self):
            class R: data = [{}]
            return R()

    class FakeSupa:
        def table(self, _n): return FakeTable()

    monkeypatch.setattr(contacts, "get_supabase", lambda: FakeSupa())
    contacts._upsert_mirror({"id": 5, "nome": "X"}, "secundaria")
    assert capturado["on_conflict"] == "account,id"
    assert capturado["row"]["account"] == "secundaria"
