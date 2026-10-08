from unittest.mock import MagicMock

from app.db.paginacao import paginar


def _paginas(paginas, ranges):
    class _P:
        def range(self, a, b):
            ranges.append((a, b))
            return self

        def execute(self):
            return MagicMock(data=paginas[len(ranges) - 1])
    return _P


def test_paginar_segue_ate_a_pagina_incompleta():
    ranges = []
    P = _paginas([[{"i": n} for n in range(1000)], [{"i": n} for n in range(1000)], [{"i": 1}]], ranges)
    rows = paginar(lambda: P())
    assert len(rows) == 2001
    assert ranges == [(0, 999), (1000, 1999), (2000, 2999)]


def test_paginar_pagina_vazia_e_none():
    ranges = []
    P = _paginas([None], ranges)
    assert paginar(lambda: P()) == []
    assert ranges == [(0, 999)]


def test_paginar_tamanho_de_pagina():
    ranges = []
    P = _paginas([[{"i": 1}, {"i": 2}], [{"i": 3}]], ranges)
    assert len(paginar(lambda: P(), page=2)) == 3
    assert ranges == [(0, 1), (2, 3)]
