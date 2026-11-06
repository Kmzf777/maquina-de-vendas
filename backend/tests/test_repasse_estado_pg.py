"""Migration 20261106_repasse_estado_resposta (frente F2) contra um Postgres DE VERDADE.

Cobre a coluna `estado` de `vw_repasse_resposta` (definição comum F2/F6 do consolidado de
06/11/2026): vendedor_respondeu, lead_nao_respondeu, em_aberto, vendedor_nao_respondeu e
sem_contato, mais `espera_desde`, `minutos_uteis_espera` e `fora_do_crm`.

Sem `REPASSE_PSQL` os testes pulam (igual a test_repasse_sla_pg.py). Rodado em 06/11/2026 num
Postgres 16 local descartável (pip `pgserver`) com um schema mínimo + 20261019 + 20261106:

    REPASSE_PSQL='psql -h 127.0.0.1 -p 55432 -U postgres' python -m pytest tests/test_repasse_estado_pg.py

Datas: `now()` é o relógio real, então os casos usam 2020 (espera já passou de 2 h úteis) ou
2030 (futuro: 0 min úteis, ainda em aberto). 2020-01-06 é segunda; 2030-06-11 é terça.
"""
from __future__ import annotations

from tests.test_repasse_sla_pg import MARCADOR, _precisa_pg, _psql

LEAD = "f2f2f2f2-0000-0000-0000-000000000001"
CH_VALERIA = "f2f2f2f2-0000-0000-0000-0000000000a1"
CH_JOAO = "f2f2f2f2-0000-0000-0000-0000000000b1"
CONV_VALERIA = "f2f2f2f2-0000-0000-0000-00000000c0a1"
CONV_JOAO = "f2f2f2f2-0000-0000-0000-00000000c0b1"
ARTHUR = "f2f2f2f2-0000-0000-0000-0000000000f9"


def _msg(conv: str, role: str, sent_by: str | None, ts: str, *, tipo: str | None = None,
         conteudo: str = "oi") -> str:
    sb = "null" if sent_by is None else f"'{sent_by}'"
    mt = "null" if tipo is None else f"'{tipo}'"
    c = conteudo.replace("'", "''")
    return ("insert into public.messages (lead_id, conversation_id, role, content, sent_by, "
            f"message_type, created_at) values ('{LEAD}', '{conv}', '{role}', '{c}', {sb}, {mt}, '{ts}');\n")


def _repasse(ts: str) -> str:
    return _msg(CONV_VALERIA, "system", "agent", ts, conteudo=MARCADOR)


def _estado(corpo: str, *, assigned_to: str | None = None) -> list[str]:
    """Semeia lead + canal da Valéria (ai) + canal do João (human), roda o corpo e devolve
    `estado|espera_desde|minutos_uteis_espera|fora_do_crm` do lead. Tudo em ROLLBACK."""
    at = "null" if assigned_to is None else f"'{assigned_to}'"
    out = _psql(f"""
begin;
insert into public.channels (id, name, phone, provider, mode) values
  ('{CH_VALERIA}', 'F2 Valeria', '5599700000901', 'meta_cloud', 'ai'),
  ('{CH_JOAO}', 'F2 Joao', '5599700000902', 'meta_cloud', 'human');
insert into public.leads (id, phone, name, assigned_to) values ('{LEAD}', '5599700000001', 'Teste F2', {at});
insert into public.conversations (id, lead_id, channel_id) values
  ('{CONV_VALERIA}', '{LEAD}', '{CH_VALERIA}'), ('{CONV_JOAO}', '{LEAD}', '{CH_JOAO}');
{corpo}
select estado || '|' || coalesce(espera_desde::text, '') || '|' || coalesce(minutos_uteis_espera::text, '')
       || '|' || fora_do_crm
  from public.vw_repasse_resposta where lead_id = '{LEAD}';
rollback;
""")
    linhas = [l for l in out.strip().splitlines() if l.strip()]
    return linhas[-1].split("|")


@_precisa_pg
def test_vendedor_respondeu():
    e = _estado(_repasse("2020-01-06 10:00-03")
                + _msg(CONV_JOAO, "user", None, "2020-01-06 10:10-03")
                + _msg(CONV_JOAO, "assistant", "seller", "2020-01-06 10:20-03"))
    assert e[0] == "vendedor_respondeu"
    assert e[1] == "" and e[2] == ""


@_precisa_pg
def test_reacao_do_vendedor_nao_conta():
    e = _estado(_repasse("2020-01-06 10:00-03")
                + _msg(CONV_JOAO, "user", None, "2020-01-06 10:10-03")
                + _msg(CONV_JOAO, "assistant", "seller", "2020-01-06 10:20-03", tipo="reaction"))
    assert e[0] == "vendedor_nao_respondeu"
    assert e[1].startswith("2020-01-06 13:10")  # 10:10-03 em UTC


@_precisa_pg
def test_contato_automatico_sem_resposta_do_lead():
    e = _estado(_repasse("2020-01-06 10:00-03")
                + _msg(CONV_JOAO, "assistant", "followup", "2020-01-06 10:15-03",
                       conteudo="Olá! Aqui é o João"))
    assert e[0] == "lead_nao_respondeu"


@_precisa_pg
def test_reacao_do_lead_ao_contato_nao_e_mensagem():
    e = _estado(_repasse("2020-01-06 10:00-03")
                + _msg(CONV_JOAO, "assistant", "followup", "2020-01-06 10:15-03")
                + _msg(CONV_JOAO, "user", None, "2020-01-06 10:16-03", tipo="reaction"))
    assert e[0] == "lead_nao_respondeu"


@_precisa_pg
def test_lead_escreveu_e_ainda_nao_passou_o_prazo():
    e = _estado(_repasse("2030-06-11 10:00-03")
                + _msg(CONV_JOAO, "assistant", "followup", "2030-06-11 10:15-03")
                + _msg(CONV_JOAO, "user", None, "2030-06-11 10:30-03"))
    assert e[0] == "em_aberto"
    assert e[1].startswith("2030-06-11 13:30")
    assert float(e[2]) == 0


@_precisa_pg
def test_lead_escreveu_e_passou_de_2h_uteis():
    e = _estado(_repasse("2020-01-06 10:00-03")
                + _msg(CONV_JOAO, "user", None, "2020-01-06 10:30-03"))
    assert e[0] == "vendedor_nao_respondeu"
    assert float(e[2]) >= 120


@_precisa_pg
def test_espera_comeca_depois_da_ultima_mensagem_nossa():
    """Lead escreveu, recebeu o contato automático e escreveu de novo: conta da 2ª."""
    e = _estado(_repasse("2030-06-11 10:00-03")
                + _msg(CONV_JOAO, "user", None, "2030-06-11 10:05-03")
                + _msg(CONV_JOAO, "assistant", "followup", "2030-06-11 10:15-03")
                + _msg(CONV_JOAO, "user", None, "2030-06-11 11:00-03")
                + _msg(CONV_JOAO, "user", None, "2030-06-11 11:30-03"))
    assert e[0] == "em_aberto"
    assert e[1].startswith("2030-06-11 14:00")


@_precisa_pg
def test_mensagem_antes_do_repasse_nao_conta():
    e = _estado(_msg(CONV_JOAO, "user", None, "2020-01-06 09:00-03")
                + _repasse("2020-01-06 10:00-03"))
    assert e[0] == "sem_contato"


@_precisa_pg
def test_lead_que_so_escreveu_no_numero_da_valeria_e_sem_contato():
    """O caso dos 25 (Valmir, Jussano): repasse dos botões sem contato automático."""
    e = _estado(_repasse("2020-01-06 10:00-03")
                + _msg(CONV_VALERIA, "assistant", "valeria_botoes", "2020-01-06 10:00:05-03")
                + _msg(CONV_VALERIA, "user", None, "2020-01-07 16:43-03",
                       conteudo="Olá, boa tarde tudo bem"))
    assert e[0] == "sem_contato"


@_precisa_pg
def test_contato_automatico_agendado_e_em_aberto():
    e = _estado(_repasse("2030-06-11 21:00-03")
                + "insert into public.follow_up_jobs (lead_id, job_type, status, created_at) "
                  f"values ('{LEAD}', 'handoff_rescue', 'pending', '2030-06-11 21:00:01-03');\n")
    assert e[0] == "em_aberto"
    assert e[1] == ""


@_precisa_pg
def test_rescue_cancelado_nao_segura_em_aberto():
    e = _estado(_repasse("2020-01-06 10:00-03")
                + "insert into public.follow_up_jobs (lead_id, job_type, status, created_at) "
                  f"values ('{LEAD}', 'handoff_rescue', 'cancelled', '2020-01-06 10:00:01-03');\n")
    assert e[0] == "sem_contato"


@_precisa_pg
def test_vendedor_fora_do_crm():
    e = _estado(f"insert into public.vendedores (id, nome, atende_no_crm) values ('{ARTHUR}', 'Arthur', false);\n"
                + _repasse("2020-01-06 10:00-03"), assigned_to=ARTHUR)
    assert e[0] == "sem_contato"
    assert e[3] == "true"


@_precisa_pg
def test_colunas_antigas_no_mesmo_lugar():
    cols = _psql("select string_agg(column_name, ',' order by ordinal_position) "
                 "from information_schema.columns where table_schema = 'public' "
                 "and table_name = 'vw_repasse_resposta';").strip().splitlines()[-1]
    assert cols == ("lead_id,repasse_em,vendedor_id,primeira_resposta_em,minutos_uteis,"
                    "minutos_uteis_em_aberto,respondeu,estado,espera_desde,minutos_uteis_espera,"
                    "fora_do_crm")
