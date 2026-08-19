import asyncio
from datetime import date, timedelta

import app.bling.backfill as bf


def test_janelas_de_30_dias_cobrem_o_periodo_sem_buraco():
    janelas = bf.build_windows(date(2026, 1, 1), date(2026, 3, 2), dias=30)
    assert janelas[0] == ("2026-01-01", "2026-01-30")
    assert janelas[1] == ("2026-01-31", "2026-03-01")
    assert janelas[-1][1] == "2026-03-02"
    # sem sobreposicao nem lacuna entre janelas consecutivas
    for anterior, seguinte in zip(janelas, janelas[1:]):
        assert date.fromisoformat(seguinte[0]) == date.fromisoformat(anterior[1]) + \
            __import__("datetime").timedelta(days=1)


def test_janela_nunca_passa_de_um_ano():
    """Filtro de periodo com intervalo > 1 ano devolve 400 no Bling."""
    janelas = bf.build_windows(date(2025, 1, 1), date(2026, 8, 18), dias=30)
    for inicio, fim in janelas:
        delta = date.fromisoformat(fim) - date.fromisoformat(inicio)
        assert delta.days < 365


def test_periodo_de_um_dia_gera_uma_janela():
    assert bf.build_windows(date(2026, 8, 18), date(2026, 8, 18), dias=30) == \
        [("2026-08-18", "2026-08-18")]


def test_run_projeta_cada_pedido_e_salva_progresso(monkeypatch):
    pedidos_listados = [{"id": 1}, {"id": 2}]
    detalhes = {1: {"id": 1, "data": "2026-08-01", "total": 10.0,
                    "contato": {"id": 55}, "itens": []},
                2: {"id": 2, "data": "2026-08-02", "total": 20.0,
                    "contato": {"id": 66}, "itens": []}}

    class FakeClient:
        async def paginate(self, path, params=None, limite=100):
            for p in pedidos_listados:
                yield p

        async def get(self, path, params=None):
            oid = int(path.rsplit("/", 1)[-1])
            return {"data": detalhes[oid]}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    projetados = []

    async def fake_upsert(pedido, lead_id, event_date):
        projetados.append(pedido["id"])
        return "S"

    async def fake_lead(contact_id):
        return "LEAD-1"

    progresso = []
    monkeypatch.setattr(bf, "_new_client", lambda: FakeClient())
    monkeypatch.setattr(bf, "upsert_from_bling", fake_upsert)
    monkeypatch.setattr(bf, "_lead_for_contact", fake_lead)
    monkeypatch.setattr(bf, "_save_progress", lambda cursor: progresso.append(cursor))
    # Sem isso, _load_progress bate no Supabase real (URL fake da suite) e o
    # teste falha com erro de rede em vez de exercitar a logica do backfill.
    monkeypatch.setattr(bf, "_load_progress", lambda: None)

    out = asyncio.run(bf.run(months=1))

    assert out["pedidos"] == 2
    assert projetados == [1, 2]
    assert progresso, "o progresso tem que ser salvo para o job ser retomavel"


def test_run_retoma_da_ultima_janela_concluida(monkeypatch):
    class FakeClient:
        def __init__(self):
            self.params = []

        async def paginate(self, path, params=None, limite=100):
            self.params.append(params)
            return
            yield  # pragma: no cover

        async def get(self, path, params=None):
            return {"data": {}}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    client = FakeClient()
    monkeypatch.setattr(bf, "_new_client", lambda: client)
    monkeypatch.setattr(bf, "_save_progress", lambda cursor: None)

    # Data FIXA (nao datetime.now()): sem isso, o numero de janelas restantes
    # varia com o dia em que a suite roda, e o teste pode passar por outro
    # motivo — ou passar vacuamente — dependendo da data.
    hoje = date(2027, 1, 15)
    inicio = hoje - timedelta(days=30 * 12 - 1)
    todas = bf.build_windows(inicio, hoje)
    # Trava a premissa do teste: se `run()` mudar a formula de inicio/fim,
    # este assert falha aqui, alto e claro, em vez de invalidar silenciosamente
    # o resto do teste.
    assert len(todas) == 12

    # Simula progresso ja salvo ate o fim da 6a janela (indice 5): restam
    # exatamente as ultimas 6, nem uma a mais nem a menos.
    cursor = todas[5][1]
    restantes_esperadas = todas[6:]
    monkeypatch.setattr(bf, "_load_progress", lambda: cursor)

    out = asyncio.run(bf.run(months=12, hoje=hoje))

    # Afirma que a lista nao esta vazia ANTES de qualquer comparacao: com a
    # lista vazia, as checagens seguintes seriam vacuamente verdadeiras e o
    # teste passaria mesmo com a retomada quebrada.
    assert client.params, "nenhuma janela foi consultada — a retomada nao provou nada"

    consultadas = [(p["dataInicial"], p["dataFinal"]) for p in client.params]
    assert len(consultadas) == len(restantes_esperadas) == 6, \
        "numero de janelas consultadas tem que bater exatamente com as pendentes"
    assert consultadas == restantes_esperadas, \
        "janelas ja concluidas nao podem ser refeitas nem faltar nenhuma pendente"
    assert out["janelas"] == 6
