"""B7 (7b143561): o disparo só move deals ABERTOS do lead; card ganho/perdido fica intacto.

"Aberto" é decidido SÓ pela etapa (key fora de TERMINAL_STAGE_KEYS): deals reabertos pelo
kanban guardam closed_at antigo e mesmo assim são abertos."""

from types import SimpleNamespace

from app.broadcast.worker import TERMINAL_STAGE_KEYS, _mover_deals_do_disparo

PIPE = "pipe-1"
ALVO = "st-alvo"
STAGE_KEYS = {
    "st-alvo": "chamado_reposicao",
    "st-novo": "novo",
    "st-ganho": "fechado_ganho",
    "st-perdido": "perdido",
    "st-fperdido": "fechado_perdido",
    "st-encerrado": "encerrado",
}


class _Query:
    def __init__(self, sb, table):
        self.sb, self.table, self.op, self.payload, self.filters = sb, table, "select", None, []

    def select(self, *_a, **_k):
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def eq(self, col, val):
        self.filters.append(("eq", col, val))
        return self

    def in_(self, col, vals):
        self.filters.append(("in", col, list(vals)))
        return self

    def execute(self):
        self.sb.calls.append((self.table, self.op, self.payload, self.filters))
        if self.op != "select":
            return SimpleNamespace(data=[{"id": "x"}])
        if self.table == "deals":
            return SimpleNamespace(data=list(self.sb.deals))
        if self.table == "pipeline_stages":
            ids = next(v for k, c, v in self.filters if k == "in" and c == "id")
            return SimpleNamespace(data=[{"id": i, "key": STAGE_KEYS.get(i)} for i in ids])
        return SimpleNamespace(data=[])


class _SB:
    def __init__(self, deals):
        self.deals, self.calls = deals, []

    def table(self, name):
        return _Query(self, name)

    def ops(self, table, op):
        return [c for c in self.calls if c[0] == table and c[1] == op]


LEAD = {"id": "lead-1", "name": "Ana", "phone": "5511999"}


def test_keys_terminais():
    assert set(TERMINAL_STAGE_KEYS) == {"fechado_ganho", "fechado_perdido", "perdido", "encerrado"}


def test_so_ganho_cria_card_novo_sem_mexer_no_ganho():
    sb = _SB([{"id": "d1", "closed_at": "2026-07-01T00:00:00Z", "stage_id": "st-ganho"}])
    assert _mover_deals_do_disparo(sb, LEAD, PIPE, ALVO) is True
    assert sb.ops("deals", "update") == []
    ins = sb.ops("deals", "insert")
    assert len(ins) == 1
    assert ins[0][2] == {
        "lead_id": "lead-1", "title": "Ana - Oportunidade", "stage": "novo",
        "pipeline_id": PIPE, "stage_id": ALVO,
    }


def test_closed_at_antigo_em_etapa_nao_terminal_e_aberto_e_move():
    # deal reaberto pelo kanban: closed_at ficou, mas a etapa não é terminal → MOVE, sem INSERT
    sb = _SB([{"id": "d1", "closed_at": "2026-07-01T00:00:00Z", "stage_id": "st-novo"}])
    assert _mover_deals_do_disparo(sb, LEAD, PIPE, ALVO) is True
    ups = sb.ops("deals", "update")
    assert len(ups) == 1
    assert ups[0][2]["stage_id"] == ALVO
    assert ("in", "id", ["d1"]) in ups[0][3]
    assert sb.ops("deals", "insert") == []


def test_etapa_alvo_terminal_ja_ocupada_nao_cria_card():
    # disparo com alvo terminal (ex.: fechado_ganho) e o lead já tem deal nessa etapa → nada
    sb = _SB([{"id": "d1", "closed_at": "2026-07-01T00:00:00Z", "stage_id": "st-ganho"}])
    assert _mover_deals_do_disparo(sb, LEAD, PIPE, "st-ganho") is False
    assert sb.ops("deals", "update") == []
    assert sb.ops("deals", "insert") == []


def test_move_so_o_aberto_e_nao_cria():
    sb = _SB([
        {"id": "d-aberto", "closed_at": None, "stage_id": "st-novo"},
        {"id": "d-ganho", "closed_at": "2026-07-01T00:00:00Z", "stage_id": "st-ganho"},
    ])
    assert _mover_deals_do_disparo(sb, LEAD, PIPE, ALVO) is True
    ups = sb.ops("deals", "update")
    assert len(ups) == 1
    assert ups[0][2]["stage_id"] == ALVO
    assert ("in", "id", ["d-aberto"]) in ups[0][3]
    assert sb.ops("deals", "insert") == []


def test_aberto_ja_na_etapa_alvo_nao_faz_nada():
    sb = _SB([{"id": "d1", "closed_at": None, "stage_id": ALVO}])
    assert _mover_deals_do_disparo(sb, LEAD, PIPE, ALVO) is False
    assert sb.ops("deals", "update") == []
    assert sb.ops("deals", "insert") == []


def test_perdido_sem_closed_at_nao_move():
    for st in ("st-perdido", "st-fperdido", "st-encerrado"):
        sb = _SB([{"id": "d1", "closed_at": None, "stage_id": st}])
        assert _mover_deals_do_disparo(sb, LEAD, PIPE, ALVO) is True
        assert sb.ops("deals", "update") == []
        assert len(sb.ops("deals", "insert")) == 1


def test_sem_deal_cria_card():
    sb = _SB([])
    assert _mover_deals_do_disparo(sb, LEAD, PIPE, ALVO) is True
    assert sb.ops("deals", "update") == []
    assert len(sb.ops("deals", "insert")) == 1
