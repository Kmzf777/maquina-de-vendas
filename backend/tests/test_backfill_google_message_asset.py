"""Backfill one-off dos leads antigos que chegaram pelo botão WhatsApp do anúncio Google."""
from __future__ import annotations

import copy
import json
import re
from types import SimpleNamespace

from scripts import backfill_google_message_asset as bf

TEXTO = "Olá, encontrei vocês pelo Google e gostaria de obter mais informações."


def _like_regex(pattern: str) -> re.Pattern:
    parts = [re.escape(p) for p in pattern.split("%")]
    return re.compile("^" + ".*".join(parts) + "$", re.IGNORECASE | re.DOTALL)


class _Query:
    def __init__(self, sb: "FakeSB", table: str):
        self.sb = sb
        self.table = table
        self.filters: list = []
        self.order_key: str | None = None
        self.order_desc = False
        self.limit_n: int | None = None
        self.range_: tuple[int, int] | None = None
        self.update_payload: dict | None = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, col, value):
        self.filters.append(lambda r: r.get(col) == value)
        return self

    def ilike(self, col, pattern):
        rx = _like_regex(pattern)
        self.filters.append(lambda r: r.get(col) is not None and bool(rx.match(str(r.get(col)))))
        return self

    def is_(self, col, value):
        expected = None if value == "null" else value
        self.filters.append(lambda r: r.get(col) is expected)
        return self

    def order(self, col, desc=False):
        self.order_key, self.order_desc = col, desc
        return self

    def limit(self, n):
        self.limit_n = n
        return self

    def range(self, start, end):
        self.range_ = (start, end)
        self.sb.ranges.append((self.table, self.order_key, start, end))
        return self

    def update(self, payload):
        self.update_payload = dict(payload)
        return self

    def _matching(self):
        rows = [r for r in self.sb.tables.setdefault(self.table, []) if all(f(r) for f in self.filters)]
        if self.order_key:
            rows.sort(key=lambda r: r.get(self.order_key) or "", reverse=self.order_desc)
        return rows

    def execute(self):
        rows = self._matching()
        if self.update_payload is not None:
            self.sb.updates.append((self.table, self.update_payload, [r["id"] for r in rows]))
            for r in rows:
                r.update(self.update_payload)
            return SimpleNamespace(data=copy.deepcopy(rows))
        if self.range_:
            rows = rows[self.range_[0]: self.range_[1] + 1]
        if self.limit_n is not None:
            rows = rows[: self.limit_n]
        return SimpleNamespace(data=copy.deepcopy(rows))


class FakeSB:
    def __init__(self, tables: dict[str, list[dict]]):
        self.tables = tables
        self.updates: list = []
        self.ranges: list = []  # (table, order_key no momento do range, start, end)

    def table(self, name):
        return _Query(self, name)


def _lead(id_, **extra):
    base = {
        "id": id_, "phone": f"55349999{id_[-4:]:0>4}", "name": f"Lead {id_}",
        "gclid": None, "fbclid": None, "ctwa_clid": None, "meta_ad_id": None,
        "utm_source": None, "utm_medium": None, "utm_campaign": None, "traffic_type": None,
    }
    base.update(extra)
    return base


def _fixture() -> FakeSB:
    leads = [
        _lead("lead-a"),                       # 1a msg = texto -> candidato
        _lead("lead-b"),                       # 1a msg = "Oi", 2a = texto -> não
        _lead("lead-c", gclid="abc123"),       # tem gclid -> não
        _lead("lead-d"),                       # sem mensagem do botão -> não
    ]
    messages = [
        {"id": "m1", "lead_id": "lead-a", "role": "user", "content": TEXTO, "created_at": "2026-01-01T10:00:00Z"},
        {"id": "m2", "lead_id": "lead-a", "role": "assistant", "content": "Oi!", "created_at": "2026-01-01T10:01:00Z"},
        {"id": "m3", "lead_id": "lead-b", "role": "user", "content": "Oi", "created_at": "2026-01-02T10:00:00Z"},
        {"id": "m4", "lead_id": "lead-b", "role": "user", "content": TEXTO, "created_at": "2026-01-02T10:05:00Z"},
        {"id": "m5", "lead_id": "lead-c", "role": "user", "content": TEXTO, "created_at": "2026-01-03T10:00:00Z"},
        {"id": "m6", "lead_id": "lead-d", "role": "user", "content": "Quero café", "created_at": "2026-01-04T10:00:00Z"},
        {"id": "m7", "lead_id": None, "role": "user", "content": TEXTO, "created_at": "2026-01-05T10:00:00Z"},
    ]
    return FakeSB({"leads": leads, "messages": messages})


def _lead_row(sb, id_):
    return next(r for r in sb.tables["leads"] if r["id"] == id_)


def test_lead_sem_atribuicao_com_primeira_msg_do_botao_e_candidato():
    sb = _fixture()
    ids = [c["id"] for c in bf.find_candidates(sb)]
    assert ids == ["lead-a"]
    c = bf.find_candidates(sb)[0]
    assert set(c) == {"id", "phone", "name"}


def test_texto_do_botao_so_na_segunda_msg_nao_e_candidato():
    sb = _fixture()
    assert "lead-b" not in [c["id"] for c in bf.find_candidates(sb)]


def test_lead_com_gclid_nao_e_candidato():
    sb = _fixture()
    assert "lead-c" not in [c["id"] for c in bf.find_candidates(sb)]


def test_find_candidates_pagina_ate_pagina_curta():
    sb = _fixture()
    for i in range(1500):
        sb.tables["messages"].append(
            {"id": f"x{i}", "lead_id": "lead-a", "role": "user", "content": TEXTO,
             "created_at": f"2026-02-01T00:00:{i % 60:02d}Z"}
        )
    sb.tables["leads"].append(_lead("lead-e"))
    sb.tables["messages"].append(
        {"id": "late", "lead_id": "lead-e", "role": "user", "content": TEXTO, "created_at": "2026-03-01T00:00:00Z"}
    )
    assert [c["id"] for c in bf.find_candidates(sb)] == ["lead-a", "lead-e"]


def test_apply_grava_so_nos_candidatos_e_json_com_os_ids(tmp_path):
    sb = _fixture()
    candidates = bf.find_candidates(sb)
    path = bf.apply(sb, candidates, tmp_path)

    assert path.parent == tmp_path
    assert path.name.startswith("backfill_google_message_asset_") and path.suffix == ".json"
    assert json.loads(path.read_text(encoding="utf-8")) == {"lead_ids": ["lead-a"]}

    a = _lead_row(sb, "lead-a")
    assert (a["utm_source"], a["utm_medium"], a["utm_campaign"], a["traffic_type"]) == (
        "google", "cpc", "WhatsApp do Google", "paid")
    for other in ("lead-b", "lead-c", "lead-d"):
        r = _lead_row(sb, other)
        assert (r["utm_source"], r["utm_medium"], r["traffic_type"]) == (None, None, None)
    assert [u for u in sb.updates if u[2]] == [
        ("leads", {"utm_source": "google", "utm_medium": "cpc", "utm_campaign": "WhatsApp do Google",
                   "traffic_type": "paid"}, ["lead-a"])
    ]


def test_apply_nao_sobrescreve_lead_que_ganhou_utm_no_meio_tempo(tmp_path):
    sb = _fixture()
    candidates = bf.find_candidates(sb)
    _lead_row(sb, "lead-a")["utm_source"] = "facebook"
    path = bf.apply(sb, candidates, tmp_path)
    assert _lead_row(sb, "lead-a")["utm_source"] == "facebook"
    assert _lead_row(sb, "lead-a")["traffic_type"] is None
    # não gravado -> fora do JSON, para o revert nunca tocar nele
    assert json.loads(path.read_text(encoding="utf-8")) == {"lead_ids": []}


def test_revert_limpa_so_ids_do_json_que_ainda_sao_google_cpc(tmp_path):
    sb = _fixture()
    for id_ in ("lead-a", "lead-b"):
        _lead_row(sb, id_).update(utm_source="google", utm_medium="cpc", utm_campaign="WhatsApp do Google",
                                  traffic_type="paid")
    # lead-b mudou depois do backfill (não é mais google/cpc)
    _lead_row(sb, "lead-b").update(utm_source="facebook", utm_medium="paid_social")
    # lead-d é google/cpc mas NÃO está no JSON
    _lead_row(sb, "lead-d").update(utm_source="google", utm_medium="cpc", traffic_type="paid")

    path = tmp_path / "backfill.json"
    path.write_text(json.dumps({"lead_ids": ["lead-a", "lead-b"]}), encoding="utf-8")

    count = bf.revert(sb, path)

    a = _lead_row(sb, "lead-a")
    assert (a["utm_source"], a["utm_medium"], a["utm_campaign"], a["traffic_type"]) == (None, None, None, None)
    b = _lead_row(sb, "lead-b")
    assert (b["utm_source"], b["utm_medium"], b["traffic_type"]) == ("facebook", "paid_social", "paid")
    d = _lead_row(sb, "lead-d")
    assert (d["utm_source"], d["utm_medium"], d["traffic_type"]) == ("google", "cpc", "paid")
    assert count == 1  # só lead-a de fato revertido


def test_dry_run_nao_grava_e_avisa(capsys):
    sb = _fixture()
    bf.main([], sb=sb)
    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    assert sb.updates == []
    assert "Lead lead-a" in out
    phone = _lead_row(sb, "lead-a")["phone"]
    assert phone not in out
    assert phone[-4:] in out


def test_main_apply_grava_e_mostra_caminho(tmp_path, capsys):
    sb = _fixture()
    bf.main(["--apply", "--out-dir", str(tmp_path)], sb=sb)
    out = capsys.readouterr().out
    files = list(tmp_path.glob("backfill_google_message_asset_*.json"))
    assert len(files) == 1
    assert str(files[0]) in out
    assert _lead_row(sb, "lead-a")["utm_source"] == "google"


def test_main_apply_imprime_so_os_realmente_gravados(tmp_path, capsys, monkeypatch):
    sb = _fixture()
    real_find = bf.find_candidates

    def find_e_lead_muda(sb_):
        cands = real_find(sb_)
        _lead_row(sb_, "lead-a")["utm_source"] = "facebook"  # alguém gravou no meio tempo
        return cands

    monkeypatch.setattr(bf, "find_candidates", find_e_lead_muda)
    bf.main(["--apply", "--out-dir", str(tmp_path)], sb=sb)
    out = capsys.readouterr().out
    assert "Aplicado em 0 leads" in out


def test_paginacao_ordena_por_id_antes_do_range():
    sb = _fixture()
    bf.find_candidates(sb)
    assert sb.ranges and all(r[:2] == ("messages", "id") for r in sb.ranges)
