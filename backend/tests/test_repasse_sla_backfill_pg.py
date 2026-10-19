"""Backfills R1, R2 e R3 do cartão 7b143561 (scripts/repasse_sla/) contra um Postgres DE VERDADE.

Para cada script: escreve o esperado, a 2ª execução não muda nada, o teto aborta sem escrever
nada e o rollback volta ao estado anterior.

Diferente de test_repasse_sla_pg.py, aqui os scripts fazem COMMIT (eles têm BEGIN/COMMIT
próprios). Por isso só rodam no Postgres DESCARTÁVEL (nunca em produção): cada teste semeia
dados com commit, ids `7b143561-bf..` e nome 'Backfill 7b143561', e `_limpar()` apaga tudo
antes e depois (incluindo os eventos source='backfill' e as tabelas de backup).

    REPASSE_PSQL='ssh -i ~/.ssh/agente_crm -o BatchMode=yes root@173.249.15.11 \\
      docker exec -i crm-scratch-pg-7b143561 psql -U postgres -h localhost -d postgres' \\
      python backend/tests/test_repasse_sla_backfill_pg.py

Proteção extra: `_limpar()` recusa rodar se achar mais de 50 leads que não são da semente
(sinal de que REPASSE_PSQL aponta para um banco com dados reais).
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

try:
    import pytest
except ImportError:  # host sem pytest: o runner do __main__ cuida
    pytest = None

PSQL = os.environ.get("REPASSE_PSQL", "")
SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "repasse_sla"

NOME = "Backfill 7b143561"
MARCADOR = "[encaminhar_humano] Lead encaminhado ao vendedor João (atacado)"
VEND = "7b143561-bf00-0000-0000-0000000000f1"


def _id(grupo: str, n: int) -> str:
    """uuid determinístico: grupo 'a1' (lead), 'c1' (conversa), 'e1' (mensagem)..."""
    return f"7b143561-bf{grupo}-0000-0000-{n:012d}"


def _precisa_pg(fn):
    if pytest is None:
        return fn
    return pytest.mark.skipif(not PSQL, reason="sem REPASSE_PSQL (Postgres descartável)")(fn)


def _rodar(sql: str) -> tuple[int, str, str]:
    r = subprocess.run(
        shlex.split(PSQL) + ["-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"],
        input=sql, text=True, capture_output=True, encoding="utf-8",
    )
    return r.returncode, r.stdout, r.stderr


def _psql(sql: str) -> str:
    rc, out, err = _rodar(sql)
    if rc != 0:
        raise AssertionError(err.strip() or out.strip())
    return out


def _linhas(sql: str) -> list[str]:
    return [x.strip() for x in _psql(sql).splitlines() if x.strip()]


def _script(nome: str, prefixo: str = "") -> tuple[int, str, str]:
    return _rodar(prefixo + (SCRIPTS / nome).read_text(encoding="utf-8"))


def _ok(nome: str, prefixo: str = "") -> str:
    rc, out, err = _script(nome, prefixo)
    assert rc == 0, f"{nome} falhou: {err}"
    return err  # os NOTICE vão para o stderr


def _aborta(nome: str, trecho: str, prefixo: str = "") -> str:
    rc, out, err = _script(nome, prefixo)
    assert rc != 0, f"{nome} deveria abortar; saída: {err}"
    assert trecho in err, err
    return err


def _limpar() -> None:
    estranhos = _psql(f"select count(*) from public.leads where coalesce(name, '') <> '{NOME}';").strip()
    if int(estranhos.splitlines()[-1]) > 50:
        raise RuntimeError("REPASSE_PSQL parece apontar para um banco com dados reais — abortado")
    _psql(f"""
delete from public.lead_events where event_type = 'repasse' and source = 'backfill';
delete from public.leads where name = '{NOME}';
delete from public.broadcasts where name = '{NOME}';
delete from public.pipelines where name = '{NOME}';
drop table if exists public.backup_r2_first_response_20261019;
drop table if exists public.backup_r3_deals_20261019;
""")


def _com_limpeza(fn):
    def wrapper():
        _limpar()
        try:
            fn()
        finally:
            _limpar()
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return _precisa_pg(wrapper)


def _lead(n: int, *, assigned: str | None = None, handoff: str | None = None, fr: str | None = None) -> str:
    lid = _id("a1", n)
    meta = "'{}'::jsonb" if handoff is None else f"jsonb_build_object('handoff', {handoff})"
    a = "null" if assigned is None else f"'{assigned}'"
    f = "null" if fr is None else f"'{fr}'"
    return (f"insert into public.leads (id, phone, name, assigned_to, metadata, first_response_at)"
            f" values ('{lid}', '55997{n:08d}', '{NOME}', {a}, {meta}, {f});\n"
            f"insert into public.conversations (id, lead_id) values ('{_id('c1', n)}', '{lid}');\n")


def _msg(lead_n: int, msg_n: int, role: str, sent_by: str | None, ts: str, *,
         conteudo: str = "oi", tipo: str | None = None) -> str:
    sb = "null" if sent_by is None else f"'{sent_by}'"
    mt = "null" if tipo is None else f"'{tipo}'"
    c = conteudo.replace("'", "''")
    return (f"insert into public.messages (id, lead_id, conversation_id, role, content, sent_by, message_type, created_at)"
            f" values ('{_id('e1', msg_n)}', '{_id('a1', lead_n)}', '{_id('c1', lead_n)}', '{role}', '{c}', {sb}, {mt}, '{ts}');\n")


def _marcador(lead_n: int, msg_n: int, ts: str) -> str:
    return _msg(lead_n, msg_n, "system", "agent", ts, conteudo=MARCADOR)


def _handoff(at: str, vendedor: str = "João", segmento: str = "atacado", motivo: str = "pediu preço") -> str:
    return (f"jsonb_build_object('vendedor_id', '{VEND}', 'vendedor', '{vendedor}', 'segmento', '{segmento}',"
            f" 'motivo', '{motivo}', 'at', '{at}')")


# ═══ R1 — eventos 'repasse' a partir das mensagens-marcador ══════════════════════════

def _semear_r1() -> None:
    _psql(
        "begin;\n"
        # lead 1: carimbo bate com o 2º marcador (30 s), não com o 1º (1 h antes)
        + _lead(1, assigned=VEND, handoff=_handoff("2031-03-11T10:00:30-03:00"))
        + _marcador(1, 11, "2031-03-11 09:00-03")
        + _marcador(1, 12, "2031-03-11 10:00-03")
        # lead 2: sem carimbo e sem vendedor
        + _lead(2)
        + _marcador(2, 21, "2031-03-11 11:00-03")
        # lead 3: marcador que já tem evento (gravado pelo código novo) -> não duplica
        + _lead(3, assigned=VEND)
        + _marcador(3, 31, "2031-03-11 12:00-03")
        + f"insert into public.lead_events (lead_id, event_type, occurred_at, source, dedupe_key, metadata)"
          f" values ('{_id('a1', 3)}', 'repasse', '2031-03-11 12:00-03', 'ia', 'repasse:{_id('e1', 31)}', '{{}}');\n"
        # lead 4: carimbo com 'at' inválido -> evento sem vendedor/segmento/motivo, sem erro
        + _lead(4, assigned=VEND, handoff=_handoff("ontem"))
        + _marcador(4, 41, "2031-03-11 13:00-03")
        # lead 5: 'at' em UTC com Z, 4 min de diferença -> bate
        + _lead(5, handoff=_handoff("2031-03-11T16:04:00Z", vendedor="Arthur", segmento="varejo", motivo="m5"))
        + _marcador(5, 51, "2031-03-11 13:00-03")
        # lead 6: 6 min de diferença -> não bate
        + _lead(6, handoff=_handoff("2031-03-11T16:06:00+00:00"))
        + _marcador(6, 61, "2031-03-11 13:00-03")
        # lead 7: não-marcadores (outro texto de sistema; texto de marcador com role assistant)
        + _lead(7)
        + _msg(7, 71, "system", "agent", "2031-03-11 14:00-03", conteudo="[encaminhar_humano] outra coisa")
        + _msg(7, 72, "assistant", "agent", "2031-03-11 14:01-03", conteudo=MARCADOR)
        + "commit;\n")


_EVENTOS_R1 = f"""
select m.id || '|' || e.source || '|' || coalesce(e.new_value, '-') || '|'
       || coalesce(e.metadata->>'vendedor_id', '-') || '|' || coalesce(e.metadata->>'vendedor', '-') || '|'
       || coalesce(e.metadata->>'segmento', '-') || '|' || coalesce(e.metadata->>'motivo', '-') || '|'
       || (e.metadata->>'conversation_id' = m.conversation_id::text) || '|'
       || (e.metadata->>'message_id' = m.id::text) || '|' || (e.occurred_at = m.created_at) || '|'
       || (e.lead_id = m.lead_id)
  from public.lead_events e
  join public.messages m on e.dedupe_key = 'repasse:' || m.id
 where e.event_type = 'repasse' and e.source = 'backfill'
 order by m.id;
"""


def _e(n: int) -> str:
    return _id("e1", n)


ESPERADO_R1 = [
    f"{_e(11)}|backfill|-|{VEND}|-|-|-|true|true|true|true",
    f"{_e(12)}|backfill|João|{VEND}|João|atacado|pediu preço|true|true|true|true",
    f"{_e(21)}|backfill|-|-|-|-|-|true|true|true|true",
    f"{_e(41)}|backfill|-|{VEND}|-|-|-|true|true|true|true",
    f"{_e(51)}|backfill|Arthur|-|Arthur|varejo|m5|true|true|true|true",
    f"{_e(61)}|backfill|-|-|-|-|-|true|true|true|true",
]


def _snapshot_eventos() -> list[str]:
    return _linhas(f"""
select e.id || '|' || e.event_type || '|' || coalesce(e.source, '-') || '|' || coalesce(e.dedupe_key, '-')
  from public.lead_events e join public.leads l on l.id = e.lead_id
 where l.name = '{NOME}' order by e.id;
""")


@_com_limpeza
def test_r1_escreve_o_esperado_e_e_idempotente():
    _semear_r1()
    notices = _ok("r1_eventos_repasse.sql")
    assert "marcadores sem evento: 6" in notices, notices
    assert "inseridos: 6" in notices, notices
    assert "sem evento depois: 0" in notices, notices
    assert _linhas(_EVENTOS_R1) == ESPERADO_R1
    # o evento que já existia (source 'ia') continua único
    assert _linhas(f"select count(*) || '|' || min(source) from public.lead_events"
                   f" where dedupe_key = 'repasse:{_e(31)}';") == ["1|ia"]
    antes = _snapshot_eventos()
    notices = _ok("r1_eventos_repasse.sql")
    assert "marcadores sem evento: 0" in notices and "inseridos: 0" in notices, notices
    assert _snapshot_eventos() == antes


@_com_limpeza
def test_r1_teto_aborta_sem_escrever():
    _semear_r1()
    _psql(
        "begin;\n" + _lead(8)
        + f"insert into public.messages (lead_id, conversation_id, role, content, sent_by, created_at)"
          f" select '{_id('a1', 8)}', '{_id('c1', 8)}', 'system', '{MARCADOR}', 'agent',"
          f" '2031-03-12 10:00-03'::timestamptz + make_interval(secs => g) from generate_series(1, 2100) g;\n"
        + "commit;\n")
    _aborta("r1_eventos_repasse.sql", "teto")
    assert _linhas("select count(*) from public.lead_events where event_type = 'repasse' and source = 'backfill';") == ["0"]


@_com_limpeza
def test_r1_rollback_volta_ao_estado_anterior():
    _semear_r1()
    antes = _snapshot_eventos()
    _ok("r1_eventos_repasse.sql")
    assert len(_snapshot_eventos()) == len(antes) + 6
    notices = _ok("r1_rollback.sql")
    assert "removidos: 6" in notices, notices
    assert _snapshot_eventos() == antes
    # 2ª execução do rollback: nada a fazer
    assert "removidos: 0" in _ok("r1_rollback.sql")
    assert _snapshot_eventos() == antes


# ═══ R2 — leads.first_response_at pelo 1º marcador ═══════════════════════════════════

def _semear_r2(extra: str = "") -> None:
    _psql(
        "begin;\n"
        # lead 1: reação, IA e followup não contam; vale a 1ª seller (10:10)
        + _lead(1)
        + _marcador(1, 11, "2031-04-08 10:00-03")
        + _msg(1, 12, "assistant", "seller", "2031-04-08 10:05-03", tipo="reaction")
        + _msg(1, 13, "assistant", "agent", "2031-04-08 10:06-03")
        + _msg(1, 14, "assistant", "followup", "2031-04-08 10:07-03")
        + _msg(1, 15, "assistant", "seller", "2031-04-08 10:10-03")
        + _msg(1, 16, "assistant", "seller", "2031-04-08 10:20-03")
        # lead 2: seller só antes do marcador -> fica NULL
        + _lead(2)
        + _msg(2, 21, "assistant", "seller", "2031-04-08 09:00-03")
        + _marcador(2, 22, "2031-04-08 10:00-03")
        # lead 3: só marcador -> NULL
        + _lead(3)
        + _marcador(3, 31, "2031-04-08 10:00-03")
        # lead 4: dois marcadores; vale o 1º -> seller 10:30 (entre os dois)
        + _lead(4)
        + _marcador(4, 41, "2031-04-08 10:00-03")
        + _msg(4, 42, "assistant", "seller", "2031-04-08 10:30-03")
        + _marcador(4, 43, "2031-04-08 11:00-03")
        + _msg(4, 44, "assistant", "seller", "2031-04-08 11:30-03")
        # lead 5: o trigger já preencheu (10:15) e o valor bate -> não é tocado
        + _lead(5)
        + _marcador(5, 51, "2031-04-08 10:00-03")
        + _msg(5, 52, "assistant", "seller", "2031-04-08 10:15-03")
        # lead 7: respondido antes da migration; o trigger gravou a mensagem seguinte (11:45),
        # que chegou depois do deploy -> o R2 corrige para 10:20
        + _lead(7)
        + _marcador(7, 71, "2031-04-08 10:00-03")
        + _msg(7, 72, "assistant", "seller", "2031-04-08 10:20-03")
        + f"update public.leads set first_response_at = '2031-04-08 11:45-03' where id = '{_id('a1', 7)}';\n"
        # simula o passado (coluna nula): o trigger preencheu 1 e 4 na semeadura
        + f"update public.leads set first_response_at = null where id in ('{_id('a1', 1)}', '{_id('a1', 4)}');\n"
        + extra
        + "commit;\n")


_FR = f"""
select right(id::text, 2) || '=' || coalesce(to_char(first_response_at at time zone 'America/Sao_Paulo', 'HH24:MI'), 'NULL')
  from public.leads where name = '{NOME}' order by id;
"""
ANTES_R2 = ["01=NULL", "02=NULL", "03=NULL", "04=NULL", "05=10:15", "07=11:45"]
DEPOIS_R2 = ["01=10:10", "02=NULL", "03=NULL", "04=10:30", "05=10:15", "07=10:20"]


@_com_limpeza
def test_r2_escreve_o_esperado_e_e_idempotente():
    _semear_r2()
    assert _linhas(_FR) == ANTES_R2
    notices = _ok("r2_first_response.sql")
    assert "já certos: 1 | a preencher: 2 | a corrigir: 1" in notices, notices
    assert "gravados: 3 | fora da regra depois: 0" in notices, notices
    assert _linhas(_FR) == DEPOIS_R2
    assert _linhas(f"""
select right(lead_id::text, 2) || '|' || coalesce(first_response_at_anterior::text, 'NULL') || '|'
       || to_char(first_response_at_gravado at time zone 'America/Sao_Paulo', 'HH24:MI')
  from public.backup_r2_first_response_20261019 order by lead_id;
""") == ["01|NULL|10:10", "04|NULL|10:30", "07|2031-04-08 14:45:00+00|10:20"]
    # tabela de backup não fica exposta pela API
    assert _linhas("select has_table_privilege('anon', 'public.backup_r2_first_response_20261019', 'SELECT')"
                   " or has_table_privilege('authenticated', 'public.backup_r2_first_response_20261019', 'SELECT');") == ["f"]
    notices = _ok("r2_first_response.sql")
    assert "já certos: 4 | a preencher: 0 | a corrigir: 0" in notices and "gravados: 0" in notices, notices
    assert _linhas(_FR) == DEPOIS_R2
    assert _linhas("select count(*) from public.backup_r2_first_response_20261019;") == ["3"]


@_com_limpeza
def test_r2_aborta_se_valor_existente_diverge_da_regra():
    # lead 6: valor gravado por outro caminho, diferente da 1ª seller pós-marcador
    _semear_r2(_lead(6, fr="2031-01-01 00:00-03")
               + _marcador(6, 61, "2031-04-08 10:00-03")
               + _msg(6, 62, "assistant", "seller", "2031-04-08 10:40-03"))
    _aborta("r2_first_response.sql", "diverge")
    assert _linhas(_FR) == ANTES_R2[:5] + ["06=00:00"] + ANTES_R2[5:]
    assert _linhas("select to_regclass('public.backup_r2_first_response_20261019') is null;") == ["t"]


@_com_limpeza
def test_r2_teto_aborta_sem_escrever():
    _semear_r2(f"""
insert into public.leads (id, phone, name)
select ('7b143561-bf77-0000-0000-' || lpad(g::text, 12, '0'))::uuid, '55998' || lpad(g::text, 8, '0'), '{NOME}'
  from generate_series(1, 1898) g;
insert into public.messages (lead_id, role, content, sent_by, created_at)
select ('7b143561-bf77-0000-0000-' || lpad(g::text, 12, '0'))::uuid, 'system', '{MARCADOR}', 'agent', '2031-04-09 10:00-03'
  from generate_series(1, 1898) g;
insert into public.messages (lead_id, role, content, sent_by, created_at)
select ('7b143561-bf77-0000-0000-' || lpad(g::text, 12, '0'))::uuid, 'assistant', 'oi', 'seller', '2031-04-09 10:05-03'
  from generate_series(1, 1898) g;
update public.leads set first_response_at = null where id::text like '7b143561-bf77-%';
""")
    # 3 (leads 1, 4 e 7) + 1.898 = 1.901 > teto 1.900
    _aborta("r2_first_response.sql", "teto")
    assert _linhas(f"select count(*) from public.leads where name = '{NOME}' and first_response_at is not null;") == ["2"]
    assert _linhas("select to_regclass('public.backup_r2_first_response_20261019') is null;") == ["t"]


@_com_limpeza
def test_r2_rollback_volta_ao_estado_anterior():
    _semear_r2()
    _ok("r2_first_response.sql")
    assert _linhas(_FR) == DEPOIS_R2
    notices = _ok("r2_rollback.sql")
    assert "restaurados: 3" in notices, notices
    assert _linhas(_FR) == ANTES_R2
    assert _linhas("select to_regclass('public.backup_r2_first_response_20261019') is null;") == ["t"]
    assert "nada a desfazer" in _ok("r2_rollback.sql")
    assert _linhas(_FR) == ANTES_R2


@_com_limpeza
def test_r2_rollback_nao_apaga_valor_mudado_depois():
    _semear_r2()
    _ok("r2_first_response.sql")
    _psql(f"update public.leads set first_response_at = '2031-05-01 12:00-03' where id = '{_id('a1', 4)}';")
    notices = _ok("r2_rollback.sql")
    assert "restaurados: 2" in notices and "mantidos (valor mudou depois do R2): 1" in notices, notices
    assert _linhas(_FR) == ["01=NULL", "02=NULL", "03=NULL", "04=12:00", "05=10:15", "07=11:45"]


# ═══ R3 — deals tirados de Fechado Ganho pelo disparo ════════════════════════════════

PIPE = _id("f1", 1)
ST_REPO, ST_GANHO, ST_NOVO = _id("f2", 1), _id("f2", 2), _id("f2", 3)
BROAD = _id("b1", 1)


def _deal(n: int, stage: str, closed: str | None, entered: str, moved: str | None) -> str:
    c = "null" if closed is None else f"'{closed}'"
    sql = (_lead(n)
           + f"insert into public.deals (id, lead_id, title, value, pipeline_id, stage_id, closed_at, entered_stage_at)"
             f" values ('{_id('d1', n)}', '{_id('a1', n)}', 'Deal {n}', 100, '{PIPE}', '{stage}', {c}, '{entered}');\n")
    if moved is not None:
        sql += (f"insert into public.broadcast_leads (broadcast_id, lead_id, status, deal_moved_at)"
                f" values ('{BROAD}', '{_id('a1', n)}', 'sent', '{moved}');\n")
    return sql


def _semear_r3(extra: str = "") -> None:
    _psql(
        "begin;\n"
        f"insert into public.pipelines (id, name) values ('{PIPE}', '{NOME}');\n"
        f"insert into public.pipeline_stages (id, pipeline_id, label, key, order_index) values"
        f" ('{ST_REPO}', '{PIPE}', 'Chamado reposição', 'chamado_reposicao', 1),"
        f" ('{ST_GANHO}', '{PIPE}', 'Fechado ganho', 'fechado_ganho', 2),"
        f" ('{ST_NOVO}', '{PIPE}', 'Novo', 'novo', 0);\n"
        f"insert into public.broadcasts (id, name, template_name) values ('{BROAD}', '{NOME}', 't');\n"
        # 1 e 2: alvo (fechado em jan, movido pelo disparo em fev)
        + _deal(1, ST_REPO, "2031-01-10 10:00-03", "2031-02-01 09:00-03", "2031-02-01 09:00-03")
        + _deal(2, ST_REPO, "2031-01-11 10:00-03", "2031-02-01 09:05-03", "2031-02-01 09:05-03")
        # 3: disparo ANTES do fechamento -> fora
        + _deal(3, ST_REPO, "2031-03-01 10:00-03", "2031-02-01 09:10-03", "2031-02-01 09:10-03")
        # 4: sem closed_at -> fora
        + _deal(4, ST_REPO, None, "2031-02-01 09:15-03", "2031-02-01 09:15-03")
        + extra
        + "commit;\n")


_DEALS = f"""
select right(d.id::text, 2) || '|' || s.key || '|'
       || to_char(d.entered_stage_at at time zone 'America/Sao_Paulo', 'MM-DD HH24:MI')
  from public.deals d join public.pipeline_stages s on s.id = d.stage_id
 where d.pipeline_id = '{PIPE}' order by d.id;
"""
ANTES_R3 = ["01|chamado_reposicao|02-01 09:00", "02|chamado_reposicao|02-01 09:05",
            "03|chamado_reposicao|02-01 09:10", "04|chamado_reposicao|02-01 09:15"]
DEPOIS_R3 = ["01|fechado_ganho|01-10 10:00", "02|fechado_ganho|01-11 10:00",
             "03|chamado_reposicao|02-01 09:10", "04|chamado_reposicao|02-01 09:15"]
ESPERADO_2 = "set repasse.r3_esperado = '2';\n"


@_com_limpeza
def test_r3_escreve_o_esperado_e_e_idempotente():
    _semear_r3()
    assert _linhas(_DEALS) == ANTES_R3
    notices = _ok("r3_deals_fechado_ganho.sql", ESPERADO_2)
    assert "alvo: 2 (esperado 2)" in notices and "movidos: 2" in notices, notices
    assert "alvo depois: 0" in notices, notices
    assert _linhas(_DEALS) == DEPOIS_R3
    assert _linhas(f"""
select right(deal_id::text, 2) || '|' || (stage_id_anterior = '{ST_REPO}') || '|'
       || to_char(entered_stage_at_anterior at time zone 'America/Sao_Paulo', 'MM-DD HH24:MI')
  from public.backup_r3_deals_20261019 order by deal_id;
""") == ["01|true|02-01 09:00", "02|true|02-01 09:05"]
    # o gatilho existente registra a mudança de etapa
    assert _linhas(f"select count(*) from public.lead_events where event_type = 'etapa' and new_value = 'Fechado ganho'"
                   f" and lead_id in ('{_id('a1', 1)}', '{_id('a1', 2)}');") == ["2"]
    assert _linhas("select has_table_privilege('anon', 'public.backup_r3_deals_20261019', 'SELECT')"
                   " or has_table_privilege('authenticated', 'public.backup_r3_deals_20261019', 'SELECT');") == ["f"]
    notices = _ok("r3_deals_fechado_ganho.sql", ESPERADO_2)
    assert "alvo: 0" in notices and "nada a fazer" in notices, notices
    assert _linhas(_DEALS) == DEPOIS_R3


@_com_limpeza
def test_r3_aborta_se_contagem_diferente_do_esperado():
    _semear_r3()
    # padrão 30 (produção) com 2 alvos -> aborta
    _aborta("r3_deals_fechado_ganho.sql", "esperado 30")
    _aborta("r3_deals_fechado_ganho.sql", "esperado 3", "set repasse.r3_esperado = '3';\n")
    assert _linhas(_DEALS) == ANTES_R3
    assert _linhas("select to_regclass('public.backup_r3_deals_20261019') is null;") == ["t"]


@_com_limpeza
def test_r3_aborta_sem_exatamente_uma_etapa_fechado_ganho():
    _semear_r3(f"insert into public.pipeline_stages (pipeline_id, label, key, order_index)"
               f" values ('{PIPE}', 'Ganho 2', 'fechado_ganho', 3);\n")
    _aborta("r3_deals_fechado_ganho.sql", "fechado_ganho", ESPERADO_2)
    assert _linhas(_DEALS) == ANTES_R3


@_com_limpeza
def test_r3_rollback_volta_ao_estado_anterior():
    _semear_r3()
    _ok("r3_deals_fechado_ganho.sql", ESPERADO_2)
    assert _linhas(_DEALS) == DEPOIS_R3
    notices = _ok("r3_rollback.sql")
    assert "restaurados: 2" in notices, notices
    assert _linhas(_DEALS) == ANTES_R3
    assert _linhas("select to_regclass('public.backup_r3_deals_20261019') is null;") == ["t"]
    assert "nada a desfazer" in _ok("r3_rollback.sql")
    assert _linhas(_DEALS) == ANTES_R3


if __name__ == "__main__":
    if not PSQL:
        print("defina REPASSE_PSQL (ver scripts/repasse_sla/scratch_pg.md)")
        sys.exit(2)
    falhas = 0
    for nome, fn in sorted((n, f) for n, f in list(globals().items())
                           if n.startswith("test_") and callable(f)):
        try:
            fn()
            print(f"ok     {nome}")
        except Exception as exc:  # noqa: BLE001 — runner mínimo
            falhas += 1
            print(f"FALHOU {nome}: {exc}")
    sys.exit(1 if falhas else 0)
