"""B11 (7b143561): closer = lead da coorte com evento lead_events 'repasse' (D3).

Etapa de deal não importa mais: 'perdido' sem repasse não é closer, e os funis do João
(sem key 'qualificado') contam normalmente."""

from types import SimpleNamespace

import app.campaigns.traffic_report as tr


class _Q:
    """Dublê de builder PostgREST que APLICA eq/in_ e range (como o banco faria)."""

    def __init__(self, sb, table):
        self.sb, self.table, self.filters, self._range = sb, table, [], None

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.filters.append(lambda r, c=col, v=val: r.get(c) == v)
        return self

    def in_(self, col, vals):
        vals = set(vals)
        self.filters.append(lambda r, c=col: r.get(c) in vals)
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        self.sb.tables_lidas.append(self.table)
        rows = [r for r in self.sb.tables.get(self.table, []) if all(f(r) for f in self.filters)]
        if self._range:
            rows = rows[self._range[0]:self._range[1] + 1]
        return SimpleNamespace(data=rows)


class _SB:
    def __init__(self, tables):
        self.tables, self.tables_lidas = tables, []

    def table(self, name):
        return _Q(self, name)


def _sb():
    return _SB({
        "lead_events": [
            {"id": "e1", "lead_id": "A", "event_type": "repasse"},
            {"id": "e2", "lead_id": "C", "event_type": "repasse"},
            {"id": "e3", "lead_id": "C", "event_type": "repasse"},  # 2º repasse não duplica
            {"id": "e4", "lead_id": "B", "event_type": "etapa"},  # outro evento não conta
            {"id": "e5", "lead_id": "J", "event_type": "repasse"},  # funil do João
            {"id": "e6", "lead_id": "FORA", "event_type": "repasse"},  # fora da coorte
        ],
        # B parado em 'perdido' (order_index alto) e sem repasse: antes contava, agora não.
        "deals": [
            {"id": "d1", "lead_id": "B", "stage_id": "s-perdido", "pipeline_id": "p1"},
            {"id": "d2", "lead_id": "J", "stage_id": "j-novo", "pipeline_id": "p-joao"},
        ],
        "pipeline_stages": [
            {"id": "s-qual", "pipeline_id": "p1", "key": "qualificado", "order_index": 1},
            {"id": "s-perdido", "pipeline_id": "p1", "key": "perdido", "order_index": 9},
            {"id": "j-novo", "pipeline_id": "p-joao", "key": "novo", "order_index": 0},
        ],
    })


def test_closer_e_quem_tem_evento_repasse():
    assert tr._closer_ids(_sb(), ["A", "B", "C"]) == {"A", "C"}


def test_perdido_sem_repasse_nao_e_closer():
    assert tr._closer_ids(_sb(), ["B"]) == set()


def test_funil_do_joao_com_repasse_conta():
    assert tr._closer_ids(_sb(), ["J"]) == {"J"}


def test_mantem_a_coorte():
    assert "FORA" not in tr._closer_ids(_sb(), ["A", "B", "C", "J"])


def test_le_so_lead_events():
    sb = _sb()
    tr._closer_ids(sb, ["A", "B"])
    assert set(sb.tables_lidas) == {"lead_events"}


def test_coorte_vazia():
    assert tr._closer_ids(_sb(), []) == set()


def test_constante_de_etapa_saiu():
    assert not hasattr(tr, "_CLOSER_STAGE_KEY")
