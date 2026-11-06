"""F2 (06/11/2026): Check 5 no horário do vendedor, texto com a espera e escalonamento
só para quem já é falha.

Caso real: 04/11 às 10h20 o watchdog avisou e ESCALOU (WhatsApp do admin) 10 conversas
"sem resposta há mais de 20min" com mensagens da noite anterior e da madrugada. O João
respondeu as 10 entre 10h32 e 10h38. Os 20 min já contavam em minutos úteis desde 19/10
(7b143561), então a fila inteira da madrugada vencia junta às 10h20.

Relatório: Canastra-Content-Creator/relatorios/crm-sem-resposta-falso-2026-11.md.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.watchdog import service as W
from app.watchdog.service import check_handoff_sla

from tests.test_watchdog_checks_2026_07_02 import _iso
from tests.test_watchdog_handoff_sla_2026_07_03 import _fake_db

SP = ZoneInfo("America/Sao_Paulo")
JOAO = "user-joao"


def _sp(y, m, d, hh, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=SP).astimezone(timezone.utc)


def _seed_conv(fake, conv_id, *, customer, name="Lead", assigned_to=JOAO, metadata=None):
    fake.tables["conversations"].append({
        "id": conv_id,
        "lead_id": f"lead-{conv_id}",
        "last_customer_message_at": _iso(customer),
        "last_seller_response_at": None,
        "channels": {"mode": "human"},
        "leads": {"name": name, "assigned_to": assigned_to, "metadata": metadata or {}},
    })


def _seed_cfg(fake, user_id, ini, fim, dias=(1, 2, 3, 4, 5)):
    fake.tables.setdefault("sla_seller_config", []).append({
        "user_id": user_id, "window_start_minute": ini, "window_end_minute": fim,
        "active_weekdays": list(dias), "active": True,
    })


def _alerts(fake, tipo):
    return [a for a in fake.tables["system_alerts"] if a["type"] == tipo]


def _fila_da_madrugada(fake, n=10):
    # Terça 03/11 21:00 em diante e quarta 04/11 de madrugada (como Cesar e Jorge).
    for i in range(n):
        hora = _sp(2026, 11, 3, 21, i) if i % 2 else _sp(2026, 11, 4, 8, 40 - i)
        _seed_conv(fake, f"conv-{i}", customer=hora, name=f"Lead{i} Sobrenome")


def test_fila_da_madrugada_as_10h20_nao_alerta_ainda(monkeypatch):
    fake = _fake_db(monkeypatch)
    _fila_da_madrugada(fake)
    assert check_handoff_sla(_sp(2026, 11, 4, 10, 20)) == 0
    assert fake.tables["system_alerts"] == []


def test_fila_da_madrugada_as_10h25_avisa_mas_nao_escala(monkeypatch):
    """Passou de 20 min úteis: banner no CRM, com o texto honesto. Não é falha (2 h)."""
    fake = _fake_db(monkeypatch)
    _fila_da_madrugada(fake)

    assert check_handoff_sla(_sp(2026, 11, 4, 10, 25)) == 10
    assert _alerts(fake, "handoff_sla_escalation") == []
    breach = _alerts(fake, "handoff_sla_breach")
    assert len(breach) == 1
    texto = breach[0]["message"]
    assert "Lead0: lead escreveu às 08:40 e espera há 25 min úteis" in texto
    assert "Lead2: lead escreveu às 08:38 e espera há 25 min úteis" in texto
    assert "e mais 7" in texto
    assert breach[0]["metadata"]["minutos_uteis"]["conv-0"] == 25


def test_fila_que_passou_de_2h_uteis_escala(monkeypatch):
    fake = _fake_db(monkeypatch)
    _fila_da_madrugada(fake, n=W.HANDOFF_SLA_ESCALATION_THRESHOLD)

    check_handoff_sla(_sp(2026, 11, 4, 12, 1))  # 121 min úteis desde as 10h

    esc = _alerts(fake, "handoff_sla_escalation")
    assert len(esc) == 1
    assert esc[0]["severity"] == "critical"
    assert esc[0]["metadata"]["count"] == W.HANDOFF_SLA_ESCALATION_THRESHOLD
    assert "espera há 121 min úteis" in esc[0]["message"]


def test_antes_do_horario_do_vendedor_nao_cobra(monkeypatch):
    """Às 9h o check roda (janela larga 8h–20h), mas o João só começa às 10h."""
    fake = _fake_db(monkeypatch)
    _seed_conv(fake, "conv-1", customer=_sp(2026, 11, 3, 14, 0))  # ontem, venceu ontem
    assert check_handoff_sla(_sp(2026, 11, 4, 9, 0)) == 0
    assert fake.tables["system_alerts"] == []


def test_depois_do_horario_do_vendedor_nao_cobra(monkeypatch):
    fake = _fake_db(monkeypatch)
    _seed_conv(fake, "conv-1", customer=_sp(2026, 11, 4, 14, 0))
    assert check_handoff_sla(_sp(2026, 11, 4, 15, 0)) == 1  # dentro: 60 min úteis
    fake.tables["system_alerts"].clear()
    assert check_handoff_sla(_sp(2026, 11, 4, 17, 0)) == 0  # 17h: o João já saiu


def test_janela_propria_do_vendedor_vale(monkeypatch):
    """Vendedor configurado das 9h às 18h é cobrado às 17h."""
    fake = _fake_db(monkeypatch)
    _seed_cfg(fake, JOAO, 540, 1080)
    _seed_conv(fake, "conv-1", customer=_sp(2026, 11, 4, 14, 0))
    assert check_handoff_sla(_sp(2026, 11, 4, 17, 0)) == 1


def test_lead_do_repasse_dos_botoes_usa_o_vendedor_do_carimbo(monkeypatch):
    """O repasse dos botões não grava `assigned_to`: a janela vem de
    `metadata.handoff.vendedor_id` (João das 9h às 18h)."""
    fake = _fake_db(monkeypatch)
    _seed_cfg(fake, JOAO, 540, 1080)
    _seed_conv(fake, "conv-1", customer=_sp(2026, 11, 4, 14, 0), assigned_to=None,
               metadata={"handoff": {"vendedor_id": JOAO}})
    assert check_handoff_sla(_sp(2026, 11, 4, 17, 0)) == 1


def test_sabado_nao_cobra(monkeypatch):
    fake = _fake_db(monkeypatch)
    _seed_conv(fake, "conv-1", customer=_sp(2026, 11, 6, 14, 0))  # sexta
    assert check_handoff_sla(_sp(2026, 11, 7, 11, 0)) == 0  # sábado


def test_mensagem_de_outro_dia_traz_a_data(monkeypatch):
    fake = _fake_db(monkeypatch)
    _seed_conv(fake, "conv-1", customer=_sp(2026, 11, 3, 21, 1), name="Cesar")
    assert check_handoff_sla(_sp(2026, 11, 4, 10, 25)) == 1
    assert ("Cesar: lead escreveu às 21:01 de 03/11 e espera há 25 min úteis"
            in _alerts(fake, "handoff_sla_breach")[0]["message"])
