"""Regressões da auditoria de 17/09/2026 do /trafego (leads por campanha x Meta/Google).

Três defeitos medidos contra a produção, na janela 01-16/09/2026:
  1. 15 leads com meta_ad_id e sem ctwa_clid caíam em "Sem rastreio" — o canal do lead
     ignorava o único elo que o webhook do CTWA guarda quando o clique não traz clid.
  2. A janela do relatório era resolvida em UTC enquanto o gráfico da mesma tela usava
     America/Sao_Paulo: a tabela virava o dia às 21h de Brasília e o gráfico à meia-noite,
     e os dois discordavam (09/09 = 30 leads na tabela, 27 no gráfico).
  3. O sync de investimento rodava 1x a cada 24h ancorado no start do worker, então o dia
     corrente aparecia zerado e o último dia sincronizado ficava pela metade.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.campaigns.traffic_report import (
    _local_day,
    _resolve_window,
    derive_channel,
)

_SP = ZoneInfo("America/Sao_Paulo")


# --- 1. meta_ad_id é sinal de canal pago ---

def test_derive_channel_meta_by_meta_ad_id():
    """Lead de CTWA que chegou só com o id do anúncio ainda é Meta Ads.

    Nem todo referral do WhatsApp traz ctwa_clid; o source_id (meta_ad_id) vem sempre.
    Sem isso, 15 leads pagos da janela auditada viravam "Sem rastreio"."""
    assert derive_channel({"meta_ad_id": "120250281981040163"}) == "Meta Ads"


def test_derive_channel_meta_ad_id_ignores_empty_string():
    assert derive_channel({"meta_ad_id": "   "}) == "Sem rastreio"


def test_derive_channel_gclid_wins_over_meta_ad_id():
    """Click-id continua mandando: o gclid é sinal mais forte que o anúncio do último toque."""
    assert derive_channel({"gclid": "g", "meta_ad_id": "123"}) == "Google Ads"


def test_derive_channel_meta_ad_id_beats_organic_utm_source():
    """utm_source orgânico não apaga a prova de que o lead veio de um anúncio."""
    assert derive_channel({"meta_ad_id": "123", "utm_source": "instagram"}) == "Meta Ads"


# --- 2. um relógio só: o fuso de negócio (America/Sao_Paulo) ---

def test_resolve_window_explicit_range_uses_business_tz():
    """01/09 a 16/09 é o dia de Brasília, não o dia de Londres."""
    lo, hi = _resolve_window("30d", "2026-09-01", "2026-09-16")
    assert lo == "2026-09-01T00:00:00-03:00"
    assert hi == "2026-09-16T23:59:59.999999-03:00"


def test_resolve_window_only_from_uses_business_tz():
    lo, hi = _resolve_window("all", "2026-08-10", None)
    assert lo == "2026-08-10T00:00:00-03:00"
    assert hi is None


def test_resolve_window_preset_starts_at_local_midnight():
    """Preset vira janela de dias-calendário, não de 24h corridas a partir de agora."""
    lo, hi = _resolve_window("30d", None, None)
    assert hi is None
    assert lo.endswith("T00:00:00-03:00")


def test_resolve_window_preset_covers_n_calendar_days_including_today():
    lo, _ = _resolve_window("7d", None, None)
    hoje = datetime.now(_SP).date()
    assert datetime.fromisoformat(lo).date() == hoje - timedelta(days=6)


def test_tabela_e_grafico_concordam_sobre_o_dia_do_lead():
    """O invariante que o bug quebrava: o lead que a janela do dia 9 inclui é o mesmo
    lead que o gráfico pinta no dia 9.

    22h30 de 09/09 em Brasília = 01h30 UTC de 10/09. Na janela UTC antiga esse lead
    caía fora do dia 9 na tabela e dentro do dia 9 no gráfico."""
    criado_em = "2026-09-10T01:30:00+00:00"
    lo, hi = _resolve_window("all", "2026-09-09", "2026-09-09")
    inicio = datetime.fromisoformat(lo)
    fim = datetime.fromisoformat(hi)
    instante = datetime.fromisoformat(criado_em)

    assert inicio <= instante <= fim, "a tabela precisa incluir o lead das 22h30"
    assert _local_day(criado_em) == date(2026, 9, 9), "o gráfico precisa pintá-lo no dia 9"


def test_lead_da_madrugada_nao_entra_no_dia_anterior():
    """A outra borda: 00h30 de 10/09 em Brasília (03h30 UTC) não pertence ao dia 9."""
    criado_em = "2026-09-10T03:30:00+00:00"
    _, hi = _resolve_window("all", "2026-09-09", "2026-09-09")
    assert datetime.fromisoformat(criado_em) > datetime.fromisoformat(hi)
    assert _local_day(criado_em) == date(2026, 9, 10)


def test_resolve_window_ainda_ignora_datas_malformadas():
    lo, hi = _resolve_window("7d", "nao-e-data", "")
    assert lo is not None and hi is None


def test_resolve_window_all_continua_aberta():
    assert _resolve_window("all", None, None) == (None, None)


# --- 3. investimento do dia corrente não pode ficar zerado ---

def test_ad_spend_sync_roda_mais_de_uma_vez_por_dia():
    """Com tick de 24h ancorado no start do worker, o dia corrente aparecia com R$ 0,00
    e o último dia sincronizado ficava pela metade — inflando o ROAS da tela."""
    from app.worker.main import TASK_SPECS

    nome, _kind, _fn, intervalo = next(s for s in TASK_SPECS if s[0] == "ad-spend-sync")
    assert nome == "ad-spend-sync"
    assert intervalo <= 3 * 3600, "o gasto precisa ser reconferido pelo menos a cada 3h"
