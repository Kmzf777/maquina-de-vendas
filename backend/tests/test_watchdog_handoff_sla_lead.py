"""Check 5 `handoff_sla_breach` — SLA pós-repasse por LEAD e no horário do vendedor
(cartão 7b143561, B6).

Dois furos do check antigo:
  1. Olhava só a conversa do canal humano. O vendedor costuma responder em OUTRA
     conversa do mesmo lead (71% das respostas estão na conversa do JOÃO, enquanto o
     marcador do repasse está na da VALERIA) → alerta falso.
  2. Media os 20 min em tempo corrido (08h–20h). A regra D4 conta no horário do
     vendedor (`sla_seller_config` + `sla_overrides`; padrão 10h–16h seg–sex), a mesma
     de `analytics.vw_resposta_closer` e de `frontend/src/lib/business-hours.ts`.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.watchdog import service as W
from app.watchdog.service import _carregar_cfg_sla, _minutos_uteis, check_handoff_sla

from tests.test_watchdog_checks_2026_07_02 import _iso
from tests.test_watchdog_handoff_sla_2026_07_03 import _fake_db

SP = ZoneInfo("America/Sao_Paulo")
VENDEDOR = "user-joao"


def _sp(y, m, d, hh, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=SP).astimezone(timezone.utc)


def _seed_conv(fake, conv_id, lead_id, *, mode="human", customer=None, seller=None,
               name="Lead", assigned_to=VENDEDOR):
    fake.tables["conversations"].append({
        "id": conv_id,
        "lead_id": lead_id,
        "last_customer_message_at": _iso(customer) if customer else None,
        "last_seller_response_at": _iso(seller) if seller else None,
        "channels": {"mode": mode},
        "leads": {"name": name, "assigned_to": assigned_to},
    })


def _seed_cfg(fake, user_id, ini, fim, dias=(1, 2, 3, 4, 5), active=True):
    fake.tables.setdefault("sla_seller_config", []).append({
        "user_id": user_id,
        "window_start_minute": ini,
        "window_end_minute": fim,
        "active_weekdays": list(dias),
        "active": active,
    })


# ── (a) resposta em outra conversa do lead ──────────────────────────────────────

def test_resposta_em_outra_conversa_do_lead_nao_viola(monkeypatch):
    fake = _fake_db(monkeypatch)
    now = _sp(2026, 10, 15, 10, 30)  # quinta
    _seed_conv(fake, "conv-valeria", "lead-1", customer=_sp(2026, 10, 15, 10, 0))
    _seed_conv(fake, "conv-joao", "lead-1", mode="ai", seller=_sp(2026, 10, 15, 10, 5))

    assert check_handoff_sla(now) == 0
    assert fake.tables["system_alerts"] == []


def test_resposta_em_outra_conversa_anterior_ao_cliente_ainda_viola(monkeypatch):
    """Controle de (a): a resposta na outra conversa veio ANTES da msg do cliente."""
    fake = _fake_db(monkeypatch)
    now = _sp(2026, 10, 15, 10, 30)
    _seed_conv(fake, "conv-valeria", "lead-1", customer=_sp(2026, 10, 15, 10, 0), name="Ana")
    _seed_conv(fake, "conv-joao", "lead-1", mode="ai", seller=_sp(2026, 10, 15, 9, 55))

    assert check_handoff_sla(now) == 1
    assert fake.tables["system_alerts"][0]["metadata"]["conversation_ids"] == ["conv-valeria"]


def test_resposta_de_outro_lead_nao_conta(monkeypatch):
    fake = _fake_db(monkeypatch)
    now = _sp(2026, 10, 15, 10, 30)
    _seed_conv(fake, "conv-a", "lead-1", customer=_sp(2026, 10, 15, 10, 0))
    _seed_conv(fake, "conv-b", "lead-2", mode="ai", seller=_sp(2026, 10, 15, 10, 5))

    assert check_handoff_sla(now) == 1


# ── (b) horário padrão 10h–16h seg–sex ─────────────────────────────────────────

def test_sexta_1550_segunda_1005_padrao_15_min_uteis_nao_viola(monkeypatch):
    fake = _fake_db(monkeypatch)
    _seed_conv(fake, "conv-1", "lead-1", customer=_sp(2026, 10, 16, 15, 50))

    assert check_handoff_sla(_sp(2026, 10, 19, 10, 5)) == 0
    assert fake.tables["system_alerts"] == []


def test_sexta_1550_segunda_1015_padrao_25_min_uteis_viola(monkeypatch):
    fake = _fake_db(monkeypatch)
    _seed_conv(fake, "conv-1", "lead-1", customer=_sp(2026, 10, 16, 15, 50), name="Bia")

    assert check_handoff_sla(_sp(2026, 10, 19, 10, 15)) == 1
    assert fake.tables["system_alerts"][0]["metadata"]["conversation_ids"] == ["conv-1"]


def test_lead_sem_vendedor_usa_padrao(monkeypatch):
    fake = _fake_db(monkeypatch)
    _seed_conv(fake, "conv-1", "lead-1", customer=_sp(2026, 10, 16, 15, 50), assigned_to=None)

    assert check_handoff_sla(_sp(2026, 10, 19, 10, 5)) == 0
    assert check_handoff_sla(_sp(2026, 10, 19, 10, 15)) == 1


# ── (c) horário do vendedor (sla_seller_config) ────────────────────────────────

def test_config_do_vendedor_540_1080_sexta_1750_segunda_0905_nao_viola(monkeypatch):
    fake = _fake_db(monkeypatch)
    _seed_cfg(fake, VENDEDOR, 540, 1080)
    _seed_conv(fake, "conv-1", "lead-1", customer=_sp(2026, 10, 16, 17, 50))

    assert check_handoff_sla(_sp(2026, 10, 19, 9, 5)) == 0


def test_config_do_vendedor_540_1080_sexta_1750_segunda_0915_viola(monkeypatch):
    fake = _fake_db(monkeypatch)
    _seed_cfg(fake, VENDEDOR, 540, 1080)
    _seed_conv(fake, "conv-1", "lead-1", customer=_sp(2026, 10, 16, 17, 50))

    assert check_handoff_sla(_sp(2026, 10, 19, 9, 15)) == 1


def test_config_inativa_cai_no_padrao(monkeypatch):
    """Config inativa é ignorada: padrão 10h–16h → sexta 17:50 → segunda 9:15 = 0 min."""
    fake = _fake_db(monkeypatch)
    _seed_cfg(fake, VENDEDOR, 540, 1080, active=False)
    _seed_conv(fake, "conv-1", "lead-1", customer=_sp(2026, 10, 16, 17, 50))

    assert check_handoff_sla(_sp(2026, 10, 19, 9, 15)) == 0


def test_folga_do_vendedor_em_sla_overrides_zera_o_dia(monkeypatch):
    """Vendedor de folga na segunda: msg de sexta 15:50 não vence na segunda 10:15."""
    fake = _fake_db(monkeypatch)
    fake.tables["sla_overrides"] = [
        {"user_id": VENDEDOR, "start_date": "2026-10-19", "end_date": "2026-10-19"},
    ]
    _seed_conv(fake, "conv-1", "lead-1", customer=_sp(2026, 10, 16, 15, 50))

    assert check_handoff_sla(_sp(2026, 10, 19, 10, 15)) == 0


def test_folga_de_outro_vendedor_nao_afeta(monkeypatch):
    fake = _fake_db(monkeypatch)
    fake.tables["sla_overrides"] = [
        {"user_id": "user-outro", "start_date": "2026-10-19", "end_date": "2026-10-19"},
    ]
    _seed_conv(fake, "conv-1", "lead-1", customer=_sp(2026, 10, 16, 15, 50))

    assert check_handoff_sla(_sp(2026, 10, 19, 10, 15)) == 1


def test_falha_ao_ler_config_cai_no_padrao_e_ainda_alerta(monkeypatch):
    fake = _fake_db(monkeypatch)
    real_table = fake.table

    class _Boom:
        def __getattr__(self, _n):
            return self

        def __call__(self, *a, **k):
            return self

        def execute(self):
            raise RuntimeError("sla_seller_config indisponível")

    def _table(name):
        if name in ("sla_seller_config", "sla_overrides"):
            return _Boom()
        return real_table(name)

    fake.table = _table
    _seed_conv(fake, "conv-1", "lead-1", customer=_sp(2026, 10, 16, 15, 50))

    assert check_handoff_sla(_sp(2026, 10, 19, 10, 15)) == 1


# ── Lookback: conta a partir de quando a violação COMEÇOU ──────────────────────

def test_violacao_que_comecou_ha_mais_de_24h_e_ignorada(monkeypatch):
    """Msg de quarta 10:00 → venceu quarta 10:20; na sexta 11:00 a violação tem 2 dias."""
    fake = _fake_db(monkeypatch)
    _seed_conv(fake, "conv-1", "lead-1", customer=_sp(2026, 10, 14, 10, 0))

    assert check_handoff_sla(_sp(2026, 10, 16, 11, 0)) == 0


def test_query_de_candidatas_busca_fim_de_semana(monkeypatch):
    fake = _fake_db(monkeypatch)
    now = _sp(2026, 10, 19, 10, 15)
    _seed_conv(fake, "conv-1", "lead-1", customer=_sp(2026, 10, 16, 15, 50))

    check_handoff_sla(now)

    cand = [c for c in fake.calls if c["table"] == "conversations" and c["not_is_null"]]
    assert len(cand) == 1
    floor = datetime.fromisoformat(dict(cand[0]["gte"])["last_customer_message_at"])
    assert floor == now - timedelta(hours=W.HANDOFF_SLA_FETCH_LOOKBACK_HOURS)
    assert floor <= _sp(2026, 10, 16, 15, 50)


# ── _minutos_uteis (função pura) ───────────────────────────────────────────────

PADRAO = {"ini": 600, "fim": 960, "dias": [1, 2, 3, 4, 5]}


def test_minutos_uteis_caso_canonico_do_frontend():
    """Mesmo caso de business-hours.ts: sexta 15:55 → segunda 10:10 = 15 min."""
    assert _minutos_uteis(_sp(2026, 10, 16, 15, 55), _sp(2026, 10, 19, 10, 10), PADRAO) == 15


def test_minutos_uteis_inicio_depois_do_fim_e_zero():
    assert _minutos_uteis(_sp(2026, 10, 19, 11, 0), _sp(2026, 10, 19, 10, 0), PADRAO) == 0


def test_minutos_uteis_dias_segue_dow_do_postgres_domingo_zero():
    so_domingo = {"ini": 600, "fim": 960, "dias": [0]}
    # 18/10/2026 é domingo
    assert _minutos_uteis(_sp(2026, 10, 18, 9, 0), _sp(2026, 10, 18, 11, 0), so_domingo) == 60
    assert _minutos_uteis(_sp(2026, 10, 19, 9, 0), _sp(2026, 10, 19, 11, 0), so_domingo) == 0


def test_minutos_uteis_sabado_e_seis():
    so_sabado = {"ini": 600, "fim": 960, "dias": [6]}
    assert _minutos_uteis(_sp(2026, 10, 17, 10, 0), _sp(2026, 10, 17, 10, 30), so_sabado) == 30


def test_minutos_uteis_datas_excluidas():
    cfg = {**PADRAO, "excluidas": {"2026-10-19"}}
    assert _minutos_uteis(_sp(2026, 10, 16, 15, 50), _sp(2026, 10, 20, 10, 5), cfg) == 15


def test_minutos_uteis_usa_fuso_de_sao_paulo():
    """13:30 UTC = 10:30 em SP → 30 min desde as 10:00 locais."""
    ini = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)   # 09:00 SP
    fim = datetime(2026, 10, 19, 13, 30, tzinfo=timezone.utc)  # 10:30 SP
    assert _minutos_uteis(ini, fim, PADRAO) == 30


# ── _carregar_cfg_sla ───────────────────────────────────────────────────────────

def _cfg_row(user_id, dias, updated_at, ini=600, fim=960):
    return {
        "user_id": user_id, "window_start_minute": ini, "window_end_minute": fim,
        "active_weekdays": dias, "active": True, "updated_at": updated_at,
    }


def test_cfg_active_weekdays_vazio_e_zero_dias_nao_o_padrao(monkeypatch):
    """Igual ao COALESCE do SQL: [] é "nenhum dia útil"; só NULL cai no padrão."""
    fake = _fake_db(monkeypatch)
    fake.tables["sla_seller_config"] = [_cfg_row(VENDEDOR, [], "2026-10-01T00:00:00+00:00")]
    cfg = _carregar_cfg_sla(fake, [VENDEDOR])
    assert cfg[VENDEDOR]["dias"] == []


def test_cfg_active_weekdays_null_cai_no_padrao(monkeypatch):
    fake = _fake_db(monkeypatch)
    fake.tables["sla_seller_config"] = [_cfg_row(VENDEDOR, None, "2026-10-01T00:00:00+00:00")]
    cfg = _carregar_cfg_sla(fake, [VENDEDOR])
    assert cfg[VENDEDOR]["dias"] == W.SLA_DEFAULT_CFG["dias"]


def test_cfg_varias_ativas_usa_a_de_updated_at_mais_recente(monkeypatch):
    fake = _fake_db(monkeypatch)
    fake.tables["sla_seller_config"] = [
        _cfg_row(VENDEDOR, [1, 2, 3], "2026-10-10T00:00:00+00:00", ini=540, fim=1080),
        _cfg_row(VENDEDOR, [4, 5], "2026-09-01T00:00:00+00:00", ini=600, fim=960),
    ]
    cfg = _carregar_cfg_sla(fake, [VENDEDOR])
    assert (cfg[VENDEDOR]["ini"], cfg[VENDEDOR]["fim"], cfg[VENDEDOR]["dias"]) == (540, 1080, [1, 2, 3])
    fake.tables["sla_seller_config"].reverse()
    cfg = _carregar_cfg_sla(fake, [VENDEDOR])
    assert (cfg[VENDEDOR]["ini"], cfg[VENDEDOR]["fim"], cfg[VENDEDOR]["dias"]) == (540, 1080, [1, 2, 3])
