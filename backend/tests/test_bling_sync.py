import asyncio
import re
from datetime import datetime

import app.bling.sync as sync


class FakeTable:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def upsert(self, rows, on_conflict=None):
        self.store.setdefault(self.name, []).extend(rows)
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        class R:
            pass
        r = R()
        r.data = self.store.get("row_" + self.name)
        return r


class FakeSupabase:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return FakeTable(self.store, name)


class FakeClient:
    def __init__(self, por_path, get_responses=None):
        self.por_path = por_path
        self.params = {}
        self.get_responses = get_responses or {}
        self.get_calls = []

    async def paginate(self, path, params=None, limite=100):
        self.params[path] = params
        for item in self.por_path.get(path, []):
            yield item

    async def get(self, path, params=None):
        self.get_calls.append(path)
        return self.get_responses.get(path, {"data": []})


class FakeSupabaseCountingBatches:
    """Registra CADA chamada a upsert() como um lote separado — todos os fixtures
    acima tem 1 item so, entao o buffer/flush por batch_size nunca estoura; sem
    isso, trocar o loop por um unico upsert(list(...)) passaria despercebido."""
    def __init__(self):
        self.batches: list[list[dict]] = []

    def table(self, _name):
        return self

    def upsert(self, rows, on_conflict=None):
        self.batches.append(list(rows))
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        class R:
            data = None
        return R()


def test_contato_normaliza_telefone_com_a_funcao_do_crm():
    """O casamento lead <-> contato depende de a normalizacao ser a MESMA dos dois
    lados. O Bling guarda '(51) 99269-6163'; leads.phone guarda '5551992696163'."""
    bruto = {
        "id": 5845664414, "nome": "360 IMP E DISTRIBUIDORA LTDA",
        "fantasia": "360 ALIMENTOS", "tipo": "J",
        "numeroDocumento": "29.860.598/0001-70",
        "telefone": "(51) 99269-6163", "celular": "51 3714-1000",
        "email": "adm@projetos360.com.br", "situacao": "A",
    }
    row = sync.map_contact(bruto)
    assert row["doc_digits"] == "29860598000170"
    assert row["telefone_e164"] == "5551992696163"
    assert row["celular_e164"] == "555137141000"
    assert row["email"] == "adm@projetos360.com.br"


def test_to_e164_br_celular_local_ganha_o_55():
    assert sync._to_e164_br("(51) 99269-6163") == "5551992696163"


def test_to_e164_br_fixo_local_ganha_o_55():
    assert sync._to_e164_br("51 3714-1000") == "555137141000"


def test_to_e164_br_e_idempotente_quando_ja_tem_ddi_com_mais():
    """Texto livre digitado por humano: nada impede o "+55" ja vir no campo. Se
    prefixassemos de novo sem checar, '5551992696163' viraria '555551992696163'
    — nao casa com nada, e a Task 8 cria um contato NOVO e DUPLICADO no Bling
    para um cliente que ja existe."""
    assert sync._to_e164_br("+55 51 99269-6163") == "5551992696163"


def test_to_e164_br_e_idempotente_quando_ja_tem_ddi_sem_mais():
    assert sync._to_e164_br("55 51 99269-6163") == "5551992696163"


def test_to_e164_br_fixo_com_ddi_nao_ganha_9_espurio():
    """Bug real: '+55 34 3232-1000' tem 12 digitos comecando com 55 — o MESMO
    formato que um celular local sem o 9o digito. Se _to_e164_br delegasse pra
    normalize_phone depois de ja ter o DDI misturado no texto, ela nao teria
    como distinguir os dois casos e inseriria um 9 espurio no fixo, fazendo
    duas grafias do MESMO numero (com e sem DDI) produzirem valores diferentes
    — o que quebra o casamento da Task 8 silenciosamente."""
    esperado = sync._to_e164_br("(34) 3232-1000")
    assert esperado == "553432321000"
    assert sync._to_e164_br("+55 34 3232-1000") == esperado
    assert sync._to_e164_br("55 34 3232-1000") == esperado


def test_to_e164_br_vazio_none_e_lixo_viram_none():
    assert sync._to_e164_br("") is None
    assert sync._to_e164_br(None) is None
    assert sync._to_e164_br("abc") is None
    assert sync._to_e164_br("123") is None


def test_to_e164_br_numero_absurdo_vira_none():
    """20 digitos nao encaixa em local (10/11) nem em DDI+local (12/13). Melhor
    'sem telefone' do que uma chave de casamento errada."""
    assert sync._to_e164_br("11111111112222222222") is None


def test_to_e164_br_bate_com_normalize_phone_do_leads_phone():
    """A invariante que faz a Task 8 funcionar: para o MESMO numero, o valor que
    _to_e164_br produz a partir do formato do Bling tem que ser IGUAL ao valor
    que normalize_phone produz a partir do formato que o CRM grava em
    leads.phone (o JID do WhatsApp, que ja vem com o DDI). Se essa igualdade
    quebrar, o casamento lead <-> contato falha silenciosamente e a integracao
    duplica o contato no ERP do cliente."""
    formato_bling = "(51) 99269-6163"
    formato_crm = "5551992696163"  # como chega via webhook do WhatsApp, com DDI
    assert sync._to_e164_br(formato_bling) == sync.normalize_phone(formato_crm)


def test_contato_sem_documento_fica_com_doc_digits_nulo():
    row = sync.map_contact({"id": 1, "nome": "X", "tipo": "F"})
    assert row["doc_digits"] is None


def test_contato_extrai_endereco_para_jsonb():
    bruto = {
        "id": 2, "nome": "Y", "tipo": "J",
        "endereco": {"geral": {"endereco": "Rua A", "numero": "255", "bairro": "Centro",
                               "municipio": "Uberlandia", "uf": "MG", "cep": "38400084"}},
    }
    row = sync.map_contact(bruto)
    assert row["endereco"]["municipio"] == "Uberlandia"
    assert row["endereco"]["cep"] == "38400084"


def test_to_bling_datetime_converte_iso_com_timezone_para_formato_bling():
    """O Bling rejeita (400) qualquer coisa que nao seja 'Y-m-d H:i:s' exato:
    sem 'T', sem offset, sem microssegundos. margin_hours=0 isola o teste do
    formato puro, sem misturar com a margem de seguranca (testada a parte)."""
    resultado = sync.to_bling_datetime("2026-08-19T23:46:59.734435+00:00", margin_hours=0)
    assert resultado == "2026-08-19 23:46:59"
    assert "T" not in resultado
    assert "+" not in resultado
    assert "." not in resultado


def test_to_bling_datetime_aplica_margem_de_seguranca():
    """A margem tem que empurrar o resultado para TRAS do instante de entrada
    -- nunca para frente. Reprocessar e inofensivo (upsert on_conflict=id);
    perder registro por a janela comecar tarde demais nao e."""
    entrada = "2026-08-19T23:46:59+00:00"
    resultado = sync.to_bling_datetime(entrada)
    dt_resultado = datetime.strptime(resultado, "%Y-%m-%d %H:%M:%S")
    dt_entrada = datetime.fromisoformat(entrada).replace(tzinfo=None)
    assert dt_resultado < dt_entrada


def test_to_bling_datetime_entrada_invalida_ou_vazia_vira_none():
    """None sinaliza pro chamador cair no caminho `full` (criterio=Todos) em
    vez de mandar uma string invalida ao Bling e levar 400."""
    assert sync.to_bling_datetime(None) is None
    assert sync.to_bling_datetime("") is None
    assert sync.to_bling_datetime("lixo") is None


def test_sync_contacts_incremental_usa_data_alteracao(monkeypatch):
    store = {"row_bling_sync_state": {"last_sync_at": "2026-08-17T00:00:00+00:00"}}
    client = FakeClient({"/contatos": [{"id": 1, "nome": "A", "tipo": "J"}]})
    monkeypatch.setattr(sync, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(sync, "_save_sync_state", lambda *a, **k: None)

    n = asyncio.run(sync.sync_contacts(client))

    assert n == 1
    # Convertido para o formato do Bling ('Y-m-d H:i:s', sem T/offset) com a
    # margem de seguranca de 6h subtraida -- NAO e mais o ISO 8601 cru.
    assert client.params["/contatos"]["dataAlteracaoInicial"] == "2026-08-16 18:00:00"


def test_sync_contacts_manda_data_alteracao_ja_formatada_para_o_bling(monkeypatch):
    """Este e o teste que pega a regressao de verdade: o formato NO FIO que o
    Bling recusou com 400 em producao era o ISO 8601 cru (com 'T', offset e
    microssegundos). Aqui garantimos que o que sai no parametro HTTP bate
    exatamente com 'Y-m-d H:i:s', o formato que o Bling exige."""
    store = {"row_bling_sync_state": {"last_sync_at": "2026-08-19T23:46:59.734435+00:00"}}
    client = FakeClient({"/contatos": [{"id": 1, "nome": "A", "tipo": "J"}]})
    monkeypatch.setattr(sync, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(sync, "_save_sync_state", lambda *a, **k: None)

    asyncio.run(sync.sync_contacts(client))

    enviado = client.params["/contatos"]["dataAlteracaoInicial"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", enviado)


def test_sync_contacts_completo_usa_criterio_1_todos(monkeypatch):
    """criterio=3 (default do Bling) traz so os 'ultimos incluidos' — no primeiro
    sync isso deixaria a base incompleta silenciosamente."""
    store = {}
    client = FakeClient({"/contatos": [{"id": 1, "nome": "A", "tipo": "J"}]})
    monkeypatch.setattr(sync, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(sync, "_save_sync_state", lambda *a, **k: None)

    asyncio.run(sync.sync_contacts(client))

    assert client.params["/contatos"]["criterio"] == 1


def test_sync_contacts_estoura_batch_size_em_varios_upserts(monkeypatch):
    """batch_size pequeno (3) com 7 contatos: tem que sair em mais de uma
    chamada de upsert (prova que o buffer realmente flusha em lotes), e o total
    gravado tem que bater com os 7 contatos, sem perder nem duplicar nenhum."""
    fake = FakeSupabaseCountingBatches()
    contatos = [{"id": i, "nome": f"Contato {i}", "tipo": "F"} for i in range(1, 8)]
    client = FakeClient({"/contatos": contatos})
    monkeypatch.setattr(sync, "get_supabase", lambda: fake)
    monkeypatch.setattr(sync, "_save_sync_state", lambda *a, **k: None)

    n = asyncio.run(sync.sync_contacts(client, batch_size=3))

    assert n == 7
    assert len(fake.batches) > 1
    assert sum(len(b) for b in fake.batches) == 7


def test_sync_payment_methods_e_sellers(monkeypatch):
    store = {}
    client = FakeClient({
        "/formas-pagamentos": [{"id": 45, "descricao": "Boleto", "tipoPagamento": 15,
                                "situacao": 1, "padrao": 1, "finalidade": 2}],
        "/vendedores": [{"id": 7, "contato": {"nome": "Joao Bras"}, "situacao": "A"}],
    })
    monkeypatch.setattr(sync, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(sync, "_save_sync_state", lambda *a, **k: None)

    asyncio.run(sync.sync_payment_methods(client))
    asyncio.run(sync.sync_sellers(client))

    assert store["bling_payment_methods"][0]["descricao"] == "Boleto"
    assert store["bling_sellers"][0]["nome"] == "Joao Bras"


def test_sync_situacoes_mapeia_id_nome_cor_modulo_id(monkeypatch):
    """Forma real da API (verificada em producao, escopo recem-concedido):
    GET /situacoes/modulos devolve o(s) modulo(s); GET /situacoes/modulos/{id}
    devolve as situacoes daquele modulo, com `nome` e `cor` — o nome que o
    pedido e o webhook NUNCA trazem (so mandam `{id, valor}`)."""
    store = {}
    client = FakeClient({}, get_responses={
        "/situacoes/modulos": {"data": [
            {"id": 98310, "nome": "Vendas", "descricao": "Pedidos de Venda",
             "criarSituacoes": True},
        ]},
        "/situacoes/modulos/98310": {"data": [
            {"id": 6, "nome": "Em aberto", "cor": "#E9DC40", "idHerdado": 0},
            {"id": 9, "nome": "Atendido", "cor": "#3FB57A", "idHerdado": 0},
        ]},
    })
    monkeypatch.setattr(sync, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(sync, "_save_sync_state", lambda *a, **k: None)

    n = asyncio.run(sync.sync_situacoes(client))

    assert n == 2
    rows = {r["id"]: r for r in store["bling_situacoes"]}
    assert rows[6]["nome"] == "Em aberto"
    assert rows[6]["cor"] == "#E9DC40"
    assert rows[6]["modulo_id"] == 98310
    assert rows[9]["nome"] == "Atendido"
    assert rows[9]["cor"] == "#3FB57A"
    assert rows[9]["modulo_id"] == 98310
    # idHerdado NAO e guardado — sem uso hoje (YAGNI).
    assert "idHerdado" not in rows[6]


def test_sync_situacoes_modulo_sem_situacoes_nao_quebra(monkeypatch):
    store = {}
    client = FakeClient({}, get_responses={
        "/situacoes/modulos": {"data": [
            {"id": 98310, "nome": "Vendas", "descricao": "Pedidos de Venda"},
        ]},
        "/situacoes/modulos/98310": {"data": []},
    })
    monkeypatch.setattr(sync, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(sync, "_save_sync_state", lambda *a, **k: None)

    n = asyncio.run(sync.sync_situacoes(client))

    assert n == 0


def test_sync_all_inclui_situacoes(monkeypatch):
    """sync_all passa a rodar sync_situacoes e devolver a contagem no dict de
    retorno, no mesmo padrao dos outros syncs."""
    async def fake_products(client, *, full=False):
        return 1

    async def fake_contacts(client):
        return 2

    async def fake_payment_methods(client):
        return 3

    async def fake_sellers(client):
        return 4

    async def fake_situacoes(client):
        return 9

    class FakeBlingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr(sync, "sync_products", fake_products)
    monkeypatch.setattr(sync, "sync_contacts", fake_contacts)
    monkeypatch.setattr(sync, "sync_payment_methods", fake_payment_methods)
    monkeypatch.setattr(sync, "sync_sellers", fake_sellers)
    monkeypatch.setattr(sync, "sync_situacoes", fake_situacoes)
    monkeypatch.setattr("app.bling.client.BlingClient", FakeBlingClient)

    resultado = asyncio.run(sync.sync_all())

    assert resultado["situacoes"] == 9


def test_tick_nao_faz_nada_quando_desabilitado(monkeypatch):
    monkeypatch.setattr(sync.config, "enabled", lambda: False)
    chamou = []
    monkeypatch.setattr(sync, "sync_all", lambda *a, **k: chamou.append(True))
    asyncio.run(sync.bling_sync_tick())
    assert chamou == []


def test_tick_engole_excecao_de_sync_all_sem_derrubar_o_worker(monkeypatch):
    """O tick e chamado a cada 24h dentro do mesmo loop que roda broadcasts,
    followups etc. — se sync_all levantar (Bling fora do ar, token revogado,
    rate limit estourado) e a excecao vazasse, o worker inteiro morreria."""
    monkeypatch.setattr(sync.config, "enabled", lambda: True)

    async def sync_all_com_falha(*_a, **_k):
        raise RuntimeError("Bling fora do ar")

    monkeypatch.setattr(sync, "sync_all", sync_all_com_falha)

    asyncio.run(sync.bling_sync_tick())  # nao pode levantar


def test_worker_registra_o_tick_de_sync():
    from app.worker.main import TASK_SPECS
    spec = next(s for s in TASK_SPECS if s[0] == "bling-sync")
    assert spec[1] == "periodic"
    assert callable(spec[2])
    assert spec[3] == 86400
