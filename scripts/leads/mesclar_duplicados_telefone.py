#!/usr/bin/env python3
"""Mescla leads duplicados pelo telefone canonico (spec 2026-10-13, leads duplicados).

POR QUE EXISTE: `leads.phone` e unico, mas so na forma exata. O mesmo cliente entrou no CRM
com o telefone em formatos diferentes — importacao de planilha sem o 55, cadastro manual
sem o 9, inbound da Meta ja no formato novo — e virou 2 ou 3 leads (Douglas: `4999170363`,
`554999170363` e `5549999170363`). A conversa, os deals e o opt-out ficam espalhados. A
prevencao na entrada (POST/PATCH de lead e quick-add) impede NOVOS duplicados; este script
junta os que ja existem (389 grupos na investigacao de 13/10).

REGRAS:
  - Chave do grupo: telefone canonico `55 + DDD + 9 + 8 digitos`, a MESMA regra de
    `backend/app/campaign/importer.normalize_phone`, `leads.service.normalize_phone` e do
    `normalizePhoneBR` do front (12 digitos com 55 ganham o 9, inclusive fixo). Leads
    `bling-*` e lixo (`US.123`, curtos) ficam fora.
  - Sobrevivente = o lead mais antigo (`created_at`, empate pelo menor id). Ele fica com o
    telefone canonico e recebe todo o historico dos outros (tabelas com `lead_id`, conferidas
    contra information_schema — tabela nao coberta ABORTA, igual ao script do Bling).
  - Automatico: 2 leads com o mesmo primeiro nome (sem acento/caixa) ou um nome vazio.
    Revisar a mao: 3+ leads, primeiros nomes diferentes, possivel telefone fixo
    (canonico `55DD9[2-5]...`: pode ser fixo com o 9 injetado ou celular novo, como
    11 92092-1686). O sobrevivente fica SEMPRE com o canonico de 13 digitos, igual ao
    backend, que reescreve para 13 no proximo inbound de qualquer jeito.
  - Conversas do duplicado no mesmo canal de uma do sobrevivente sao FUNDIDAS (mensagens,
    follow-ups e vendas vao para a conversa do sobrevivente). Follow-up/matricula aberta
    que colidiria e CANCELADO (nao apagado). Demais colisoes: a linha do duplicado e apagada
    (vai inteira para o backup). Opt-out nunca se perde.
  - Deals abertos repetidos no mesmo funil: so relata (deals_repetidos.csv).

USO (dry-run e o padrao — so le):
  python3 scripts/leads/mesclar_duplicados_telefone.py \\
      --psql "docker exec -i $(docker ps -q -f name=supabase_db | head -1) psql -U postgres -d postgres" \\
      --saida /root/mesclagem-tel-dryrun
  ... --aplicar --pares /root/mesclagem-tel-dryrun/pares-revisado.csv
      # aplica SO os grupos do CSV (pares.csv e/ou linhas aprovadas do revisar.csv),
      # recalculando cada um; uma transacao por grupo — SO com OK do Rafael

  ... --excluir <lead_id,lead_id>   # tira os grupos que contem esses leads
  ... --limite N                    # aplica no maximo N grupos (0 = nenhum)

Saida: pares.csv, revisar.csv, excluidos.csv, deals_repetidos.csv e backup.json (dry-run). O
--aplicar grava backup-<AAAAMMDD-HHMMSS>.json e aplicados-<AAAAMMDD-HHMMSS>.csv e NUNCA
sobrescreve um backup anterior (aborta se o arquivo ja existir). O CSV do --aplicar precisa da
coluna `duplicados`. Contagens em JSON no stdout. So stdlib: roda no host da VPS (psql), sem o venv do backend.
"""
import argparse
import csv
import importlib.util
import json
import os
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

# Irmao do Bling: Psql, _chave, _uuid, _texto, _csv, consultas e a lista de tabelas cobertas.
_BLING = Path(__file__).resolve().parents[1] / "bling" / "mesclar_leads_duplicados.py"
_spec = importlib.util.spec_from_file_location("_mesclar_bling", _BLING)
bling = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bling)
Psql = bling.Psql


# ---------------------------------------------------------------------------
# Chave canonica, agrupamento e classificacao
# ---------------------------------------------------------------------------


def canonico(phone):
    """Mesma regra de backend/app/campaign/importer.normalize_phone + leads.service.normalize_phone
    e do frontend normalizePhoneBR: 55 + DDD + 9 + 8 digitos. None se nao for telefone BR."""
    if not phone or not isinstance(phone, str) or phone.startswith("bling-") or "." in phone:
        return None
    d = re.sub(r"\D", "", phone)
    if d.startswith("0"):
        d = d[1:]
    if len(d) in (10, 11):
        d = "55" + d
    if len(d) not in (12, 13) or not d.startswith("55"):
        return None
    if len(d) == 12:
        d = d[:4] + "9" + d[4:]
    return d if d[4] == "9" else None


def _primeiro_nome(nome):
    n = unicodedata.normalize("NFKD", (nome or "").strip().lower())
    n = "".join(c for c in n if not unicodedata.combining(c))
    return n.split()[0] if n.split() else ""


def agrupar(leads):
    """leads: [{id, phone, name, created_at}]. Devolve so os grupos com 2+ leads:
    [{canonico, sobrevivente, duplicados}], sobrevivente = o mais antigo (empate: menor id)."""
    grupos = {}
    for lead in leads:
        c = canonico(lead.get("phone"))
        if c:
            grupos.setdefault(c, []).append(lead)
    saida = []
    for c, membros in sorted(grupos.items()):
        if len(membros) < 2:
            continue
        membros = sorted(membros, key=lambda l: (str(l["created_at"]), str(l["id"])))
        saida.append({"canonico": c, "sobrevivente": membros[0], "duplicados": membros[1:]})
    return saida


def classificar(grupo):
    """("automatico", "") ou ("revisar", motivo)."""
    if len(grupo["duplicados"]) > 1:
        return "revisar", f"{len(grupo['duplicados']) + 1} leads no grupo"
    if grupo["canonico"][5] in "2345":
        return "revisar", "possivel telefone fixo (confira)"
    nomes = {_primeiro_nome(l.get("name")) for l in [grupo["sobrevivente"], *grupo["duplicados"]]}
    nomes.discard("")
    if len(nomes) > 1:
        return "revisar", "nomes diferentes"
    return "automatico", ""


# ---------------------------------------------------------------------------
# SQL de um grupo
# ---------------------------------------------------------------------------

# Colisoes que CANCELAM a linha do duplicado em vez de apagar: follow-up e matricula sao
# historico (o card mostra que existiu). Cancelada, ela sai do indice unico parcial
# (status pending/processing ou active/paused) e e movida normalmente.
CANCELAM = ("follow_up_jobs", "campaign_enrollments")

# Texto: copiado do duplicado so se o do sobrevivente esta vazio (primeiro nao vazio dos
# duplicados, do mais antigo para o mais novo).
CAMPOS_TEXTO = (
    "name", "company", "email", "cnpj", "razao_social", "nome_fantasia", "endereco",
    "telefone_comercial", "instagram", "inscricao_estadual", "wa_id", "bsuid", "ctwa_clid",
    "fbclid", "gclid", "gbraid", "wbraid", "utm_source", "utm_medium", "utm_campaign",
    "meta_ad_id", "traffic_type",
)
# Nao-texto: o do sobrevivente, senao o primeiro nao nulo dos duplicados.
CAMPOS_COALESCE = ("bling_contact_id", "assigned_to", "first_response_at", "wa_id_confirmed_at")
# Acompanham o opt_out / ja_era_cliente: vem do duplicado so quando a flag vem dele.
CAMPOS_OPT_OUT = ("opt_out_at", "opt_out_channel", "opt_out_evidence")
CAMPOS_JA_ERA_CLIENTE = ("ja_era_cliente_fonte", "ja_era_cliente_em", "ja_era_cliente_por")

_CANONICO = re.compile(r"^55\d{11}$")


# A mesma regra de `canonico()`, em SQL, sobre `l.phone` (conferida dentro da transacao).
_SQL_CANONICO_DE_L = (
    "public.leads l"
    r" cross join lateral (select regexp_replace(coalesce(l.phone, ''), '\D', '', 'g') as d0) n0"
    " cross join lateral (select case when n0.d0 like '0%' then substr(n0.d0, 2)"
    " else n0.d0 end as d1) n1"
    " cross join lateral (select case when length(n1.d1) in (10, 11) then '55' || n1.d1"
    " else n1.d1 end as d2) n2"
    " cross join lateral (select case when length(n2.d2) = 12"
    " then substr(n2.d2, 1, 4) || '9' || substr(n2.d2, 5) else n2.d2 end as d3) n3")


def _movidos(fonte):
    """{tabela: [chaves]} do que esta em `fonte` (_mesclagem_movidos ou _mesclagem_total)."""
    return ("(select coalesce(jsonb_object_agg(tabela, chaves), '{}'::jsonb) from"
            " (select tabela, jsonb_agg(chave order by chave) as chaves"
            f" from {fonte} group by tabela) t)")


_MOVIDOS_POR_DUPLICADO = (
    "(select coalesce(jsonb_object_agg(duplicado, movidos), '{}'::jsonb) from"
    " (select duplicado, jsonb_object_agg(tabela, chaves) as movidos from"
    " (select duplicado, tabela, jsonb_agg(chave order by chave) as chaves"
    " from _mesclagem_total group by duplicado, tabela) t group by duplicado) u)")


def _chave_como(tabela, chaves, alias):
    """`bling._chave` (escrita sobre o alias `x`) reescrita para outro alias."""
    return re.sub(r"\bx\b", alias, bling._chave(tabela, chaves))


def _primeiro(expr, filtro):
    return (f"(array_agg({expr} order by x.created_at, x.id)"
            f" filter (where {filtro}))[1]")


# Fusao de conversas: o que a conversa que fica herda da que some.
_CONV_GREATEST = ("last_msg_at", "last_customer_message_at", "last_seller_response_at")
_CONV_DA_MAIS_RECENTE = ("stage", "status", "flow_state", "agent_profile_id")
# Tabelas com conversation_id reapontadas na fusao (nome do registro em _mesclagem_movidos).
_REAPONTAR = (
    ("sales", "sales_reapontadas"),
    ("follow_up_jobs", "follow_up_jobs_reapontados"),
    ("messages_archive", "messages_archive_reapontadas"),
    ("quotes", "quotes_reapontadas"),
)


def _set_cancelado(tabela, colunas):
    sets = "status = 'cancelled'"
    if "cancel_reason" in colunas.get(tabela, ()):
        sets += ", cancel_reason = 'mesclagem'"
    return sets


def _reaponta(tabela, colunas):
    return {"id", "conversation_id"} <= colunas.get(tabela, set())


def _sql_fundir_conversas(d, s, tabelas, colunas):
    """Conversa do duplicado no mesmo canal de uma do sobrevivente: (lead_id, channel_id) e
    unico, entao em vez de mover, tudo o que aponta para ela vai para a conversa do
    sobrevivente, que herda o estado (follow-up, nao lidas, ultimas datas, etapa da mais
    recente) e a do duplicado e apagada. Cada reapontamento e registrado com a conversa de
    origem ({id, de}) e o estado anterior da conversa que fica vai em `para_antes`."""
    conv = colunas.get("conversations", set())
    corpo = [
        "    insert into _mesclagem_movidos select 'conversas_fundidas', jsonb_build_object("
        "'de', r.de, 'para', r.para, 'para_antes', to_jsonb(sc))"
        " from public.conversations sc where sc.id = r.para;",
    ]
    reapontar = []
    if "messages" in tabelas and _reaponta("messages", colunas):
        reapontar.append(("messages", "messages_fundidas", f"lead_id = '{s}', "))
    reapontar += [(t, nome, "") for t, nome in _REAPONTAR
                  if t in tabelas and _reaponta(t, colunas)]
    for tabela, nome, extra in reapontar:
        corpo.append(
            f"    with reapontadas as (update public.{tabela} x set {extra}conversation_id = r.para"
            " where x.conversation_id = r.de"
            " returning jsonb_build_object('id', x.id, 'de', r.de) as chave)"
            f" insert into _mesclagem_movidos select '{nome}', chave from reapontadas;")
    sets = []
    if "followup_enabled" in conv:
        # conservador: se alguma das duas tinha o follow-up desligado, fica desligado
        sets.append("followup_enabled = coalesce(sc.followup_enabled, true)"
                    " and coalesce(dc.followup_enabled, true)")
    sets += [f"{k} = greatest(sc.{k}, dc.{k})" for k in _CONV_GREATEST if k in conv]
    if "unread_count" in conv:
        sets.append("unread_count = coalesce(sc.unread_count, 0) + coalesce(dc.unread_count, 0)")
    if "last_msg_at" in conv:
        recente = ("coalesce(dc.last_msg_at, '-infinity'::timestamptz)"
                   " > coalesce(sc.last_msg_at, '-infinity'::timestamptz)")
        sets += [f"{k} = case when {recente} then dc.{k} else sc.{k} end"
                 for k in _CONV_DA_MAIS_RECENTE if k in conv]
    if sets:
        corpo.append("    update public.conversations sc set " + ", ".join(sets)
                     + " from public.conversations dc where sc.id = r.para and dc.id = r.de;")
    corpo.append("    delete from public.conversations where id = r.de;")
    return "\n".join([
        "do $$",
        "declare r record;",
        "begin",
        "  for r in select dc.id as de, sc.id as para from public.conversations dc"
        f" join public.conversations sc on sc.lead_id = '{s}' and sc.channel_id = dc.channel_id"
        f" where dc.lead_id = '{d}' order by dc.created_at, dc.id loop",
        *corpo,
        "  end loop;",
        "end $$;",
    ])


def sql_mesclar_grupo(grupo, tabelas, chaves=None, colunas=None):
    """SQL de UM grupo, numa transacao: funde no sobrevivente cada duplicado (em ordem de
    created_at), apaga os duplicados e so entao reescreve o telefone e copia os campos (bsuid
    e bling_contact_id sao unicos em `leads`). `tabelas` = tabelas com lead_id do banco;
    `chaves` = {tabela: colunas da PK} (bling.Q_CHAVES); `colunas` = {tabela: colunas}
    (Q_COLUNAS) — a fusao de conversas so usa colunas que existem."""
    c = str(grupo["canonico"])
    if not _CANONICO.match(c):
        raise ValueError(f"telefone canonico invalido: {c!r}")
    s = bling._uuid(grupo["sobrevivente"]["id"])
    dups = [bling._uuid(d["id"]) for d in grupo["duplicados"]]
    if not dups or s in dups or len(set(dups)) != len(dups):
        raise ValueError(f"grupo {c}: duplicados invalidos")
    todos = ", ".join(f"'{i}'" for i in [s, *dups])
    lista_dups = ", ".join(f"'{i}'" for i in dups)
    tabelas = set(tabelas)
    if "conversations" in tabelas and colunas is None:
        raise ValueError("sql_mesclar_grupo: passe `colunas` (Q_COLUNAS) — sem elas a fusao"
                         " de conversas nao sabe o que reapontar")
    colunas = {t: set(cs) for t, cs in (colunas or {}).items()}
    cobertas = sorted(tabelas & bling.TABELAS_COBERTAS)

    linhas = [
        "begin;",
        # Lead preso por outra transacao (webhook, vendedor no CRM): o grupo cai como erro
        # em 5s e a rodada segue, em vez de ficar parada esperando.
        "set local lock_timeout = '5s';",
        # Trava o grupo inteiro antes de mover: um insert concorrente com lead_id de um
        # duplicado espera o commit em vez de cair no lead que o DELETE apaga em cascata.
        f"select 1 from public.leads where id in ({todos}) for update;",
        "do $$ begin",
        f"  if (select count(*) from public.leads where id in ({todos})) <> {len(dups) + 1} then",
        f"    raise exception 'grupo {c}: algum lead nao existe mais';",
        "  end if;",
        # Depois da trava: o telefone de cada membro ainda normaliza para o canonico? (o
        # grupo foi calculado fora da transacao; alguem pode ter editado o numero)
        f"  if exists (select 1 from {_SQL_CANONICO_DE_L} where l.id in ({todos})"
        f" and (n3.d3 is distinct from '{c}' or l.phone like 'bling-%' or l.phone like '%.%')) then",
        f"    raise exception 'grupo {c}: telefone de algum lead mudou (nao e mais deste grupo)';",
        "  end if;",
        "end $$;",
        "create temp table _mesclagem_movidos (tabela text not null, chave jsonb) on commit drop;",
        "create temp table _mesclagem_total (duplicado text not null, tabela text not null,"
        " chave jsonb) on commit drop;",
        f"create temp table _dups on commit drop as select * from public.leads where id in ({lista_dups});",
    ]
    motivo = bling._texto(f"telefone canonico {c}")
    for d in dups:
        if "follow_up_jobs" in tabelas:
            # Follow-up aberto do duplicado com o mesmo job_type de um aberto do sobrevivente
            # (no lead, o que inclui a conversa de destino): cancelado, para o cliente nao
            # receber a mesma cadencia duas vezes. Cobre a colisao do indice unico do Joao.
            linhas.append(
                "with cancelados as (update public.follow_up_jobs d set"
                f" {_set_cancelado('follow_up_jobs', colunas)} where d.lead_id = '{d}'"
                " and d.status in ('pending', 'processing') and exists (select 1 from"
                f" public.follow_up_jobs s where s.lead_id = '{s}'"
                " and s.status in ('pending', 'processing') and s.job_type = d.job_type)"
                f" returning {_chave_como('follow_up_jobs', chaves, 'd')} as chave)"
                " insert into _mesclagem_movidos select 'follow_up_jobs_cancelados', chave"
                " from cancelados;")
        if "conversations" in tabelas:
            linhas.append(_sql_fundir_conversas(d, s, tabelas, colunas))
        for tabela in cobertas:
            if tabela == "follow_up_jobs":
                pass  # cancelado acima, antes da fusao
            elif tabela in CANCELAM:
                linhas.append(
                    f"with cancelados as (update public.{tabela} d set"
                    f" {_set_cancelado(tabela, colunas)}"
                    f" from public.{tabela} s where d.lead_id = '{d}' and s.lead_id = '{s}'"
                    f" and ({bling.COLISAO[tabela]})"
                    f" returning {_chave_como(tabela, chaves, 'd')} as chave)"
                    f" insert into _mesclagem_movidos select '{tabela}_cancelados', chave"
                    " from cancelados;")
            elif tabela in bling.COLISAO:
                # a linha inteira vai para o evento 'mesclagem' (e esta no backup)
                linhas.append(
                    f"with apagados as (delete from public.{tabela} d using public.{tabela} s"
                    f" where d.lead_id = '{d}' and s.lead_id = '{s}' and ({bling.COLISAO[tabela]})"
                    " returning to_jsonb(d) as chave) insert into _mesclagem_movidos"
                    f" select '{tabela}_apagados', chave from apagados;")
            linhas.append(
                f"with movidas as (update public.{tabela} x set lead_id = '{s}'"
                f" where x.lead_id = '{d}' returning {bling._chave(tabela, chaves)} as chave)"
                f" insert into _mesclagem_movidos select '{tabela}', chave from movidas;")
        linhas.append(
            "insert into public.lead_events"
            " (lead_id, event_type, old_value, new_value, metadata, occurred_at, source, dedupe_key)\n"
            f"select '{s}', 'mesclagem', '{d}', '{s}',"
            " jsonb_build_object('duplicado', jsonb_build_object('id', d.id, 'phone', d.phone,"
            " 'name', d.name, 'channel', d.channel, 'created_at', d.created_at),"
            f" 'motivo', {motivo}, 'movidos', {_movidos('_mesclagem_movidos')}),"
            f" now(), 'sistema', 'mesclagem:{d}'\n"
            f"from _dups d where d.id = '{d}'\non conflict do nothing;")
        linhas.append(f"insert into _mesclagem_total select '{d}', tabela, chave"
                      " from _mesclagem_movidos;")
        linhas.append("truncate _mesclagem_movidos;")

    linhas.append(f"delete from public.leads where id in ({lista_dups});")

    sets = [f"phone = '{c}'"]
    sets += [f"{k} = case when coalesce(btrim(s.{k}), '') = '' then coalesce(d.{k}, s.{k})"
             f" else s.{k} end" for k in CAMPOS_TEXTO]
    sets += [f"{k} = coalesce(s.{k}, d.{k})" for k in CAMPOS_COALESCE]
    sets.append("opt_out = coalesce(s.opt_out, false) or d.opt_out")
    sets += [f"{k} = case when coalesce(s.opt_out, false) or not d.opt_out then s.{k}"
             f" else d.{k} end" for k in CAMPOS_OPT_OUT]
    sets += [f"{k} = greatest(s.{k}, d.{k})" for k in ("last_msg_at", "last_customer_message_at")]
    # null = desconhecido (P0): so vira true; nunca transforma null em false.
    sets.append("ja_era_cliente = case when coalesce(s.ja_era_cliente, false) or d.ja_era_cliente"
                " then true else s.ja_era_cliente end")
    sets += [f"{k} = case when coalesce(s.ja_era_cliente, false) or not d.ja_era_cliente"
             f" then s.{k} else d.{k} end" for k in CAMPOS_JA_ERA_CLIENTE]
    sets.append("metadata = d.metadata || coalesce(s.metadata, '{}'::jsonb)")

    agregados = [_primeiro(f"x.{k}", "coalesce(btrim(x.%s), '') <> ''" % k) + f" as {k}"
                 for k in CAMPOS_TEXTO]
    agregados += [f"{_primeiro(f'x.{k}', f'x.{k} is not null')} as {k}" for k in CAMPOS_COALESCE]
    agregados.append("coalesce(bool_or(x.opt_out), false) as opt_out")
    agregados += [f"{_primeiro(f'x.{k}', 'x.opt_out')} as {k}" for k in CAMPOS_OPT_OUT]
    agregados += [f"max(x.{k}) as {k}" for k in ("last_msg_at", "last_customer_message_at")]
    agregados.append("coalesce(bool_or(x.ja_era_cliente), false) as ja_era_cliente")
    agregados += [f"{_primeiro(f'x.{k}', 'x.ja_era_cliente')} as {k}"
                  for k in CAMPOS_JA_ERA_CLIENTE]
    # metadata de todos os duplicados; na mesma chave vence o duplicado mais antigo (e o
    # sobrevivente vence todos, no `||` do set).
    agregados.append(
        "coalesce((select jsonb_object_agg(m.k, m.v) from (select distinct on (e.key)"
        " e.key as k, e.value as v from _dups y cross join lateral jsonb_each(case when"
        " jsonb_typeof(y.metadata) = 'object' then y.metadata else '{}'::jsonb end) e"
        " order by e.key, y.created_at, y.id) m), '{}'::jsonb) as metadata")

    linhas.append(
        "update public.leads s set " + ",\n  ".join(sets)
        + "\nfrom (select\n  " + ",\n  ".join(agregados) + "\n  from _dups x) d"
        + f"\nwhere s.id = '{s}';")
    linhas.append(f"select 'movidos=' || {_movidos('_mesclagem_total')}::text;")
    linhas.append(f"select 'movidos_por_duplicado=' || {_MOVIDOS_POR_DUPLICADO}::text;")
    linhas.append("commit;")
    return "\n".join(linhas) + "\n"


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------

# FKs que apontam para leads/conversations. O SQL do grupo so sabe tratar as conhecidas:
# para leads, toda FK via `lead_id` (as tabelas sao conferidas por bling.verificar_cobertura);
# para conversations, as tres abaixo (reapontadas na fusao). Qualquer outra ABORTA — apagar
# o lead ou a conversa fundida poderia levar linhas em cascata ou falhar no meio.
Q_FKS = """
select c.conrelid::regclass::text as tabela, a.attname::text as coluna,
       c.confrelid::regclass::text as alvo
from pg_constraint c
join pg_attribute a on a.attrelid = c.conrelid and a.attnum = any(c.conkey)
where c.contype = 'f'
  and c.confrelid in ('public.leads'::regclass, 'public.conversations'::regclass)
"""

FKS_PARA_CONVERSATIONS = frozenset({
    ("messages", "conversation_id"), ("follow_up_jobs", "conversation_id"),
    ("sales", "conversation_id"),
})


# Colunas das tabelas que a fusao de conversas e os cancelamentos tocam: o SQL so usa as que
# existem (cancel_reason, estado da conversa, conversation_id de quotes/messages_archive).
Q_COLUNAS = """
select table_name, column_name from information_schema.columns
where table_schema = 'public'
  and table_name in ('conversations', 'follow_up_jobs', 'campaign_enrollments', 'messages',
                     'sales', 'quotes', 'messages_archive')
"""


class FKDesconhecida(RuntimeError):
    pass


def _sem_public(nome):
    return nome[len("public."):] if nome.startswith("public.") else nome


def verificar_fks(fks):
    estranhas = []
    for fk in fks:
        tabela, coluna, alvo = _sem_public(fk["tabela"]), fk["coluna"], _sem_public(fk["alvo"])
        conhecida = "." not in tabela and (
            (alvo == "leads" and coluna == "lead_id")
            or (alvo == "conversations" and (tabela, coluna) in FKS_PARA_CONVERSATIONS))
        if not conhecida:
            estranhas.append(f"{fk['tabela']}.{coluna} -> {fk['alvo']}")
    if estranhas:
        raise FKDesconhecida("FK(s) para leads/conversations que o script nao sabe mesclar: "
                             + ", ".join(sorted(estranhas)) + " — trate no SQL antes de rodar")

Q_LEADS = ("select id, phone, name, created_at from public.leads where phone is not null"
           " and phone <> '' and phone not like 'bling-%' order by created_at, id")


def _lista_uuid(ids):
    return "'{" + ",".join(bling._uuid(i) for i in sorted(ids)) + "}'::uuid[]"


def q_deals_abertos(ids):
    return ("select id, lead_id, pipeline_id from public.deals"
            f" where closed_at is null and lead_id = any({_lista_uuid(ids)})")


def q_conversas(ids):
    return ("select c.lead_id, json_agg(to_jsonb(c) order by c.created_at, c.id) as conversas"
            f" from public.conversations c where c.lead_id = any({_lista_uuid(ids)})"
            " group by c.lead_id")


def q_antes(ids):
    """A linha inteira do sobrevivente antes da mesclagem (o UPDATE reescreve telefone e campos)."""
    return f"select l.id, to_jsonb(l) as antes from public.leads l where l.id = any({_lista_uuid(ids)})"


def _ids(grupo):
    return [grupo["sobrevivente"]["id"], *(d["id"] for d in grupo["duplicados"])]


def deals_repetidos(grupos, deals):
    """Grupo com 2+ deals abertos no mesmo funil (somando os membros): so relata."""
    por_lead = {}
    for deal in deals:
        por_lead.setdefault(deal["lead_id"], []).append(deal)
    saida = []
    for g in grupos:
        por_funil = {}
        for lid in _ids(g):
            for deal in por_lead.get(lid, []):
                por_funil.setdefault(deal.get("pipeline_id"), []).append(deal["id"])
        for funil, ids in sorted(por_funil.items(), key=lambda kv: str(kv[0])):
            if len(ids) > 1:
                saida.append({"canonico": g["canonico"], "sobrevivente": g["sobrevivente"]["id"],
                              "pipeline_id": funil or "", "deals": sorted(ids)})
    return saida


# ---------------------------------------------------------------------------
# Execucao
# ---------------------------------------------------------------------------

COLUNAS_GRUPO = ["canonico", "sobrevivente", "sobrevivente_nome", "sobrevivente_phone",
                 "duplicados", "duplicados_nomes", "duplicados_phones", "motivo"]


def _linha(grupo, motivo):
    s, dups = grupo["sobrevivente"], grupo["duplicados"]
    return {"canonico": grupo["canonico"], "sobrevivente": s["id"],
            "sobrevivente_nome": s.get("name") or "", "sobrevivente_phone": s.get("phone") or "",
            "duplicados": [d["id"] for d in dups],
            "duplicados_nomes": [d.get("name") or "" for d in dups],
            "duplicados_phones": [d.get("phone") or "" for d in dups],
            "motivo": motivo}


def ler_grupos_revisados(caminho):
    """Linhas (canonico, sobrevivente[, duplicados]) do CSV revisado — pares.csv e/ou linhas
    aprovadas do revisar.csv. Id que nao e uuid aborta tudo (ValueError)."""
    with open(caminho, newline="", encoding="utf-8") as f:
        leitor = csv.DictReader(f)
        campos = set(leitor.fieldnames or [])
        linhas = list(leitor)
    if not {"canonico", "sobrevivente"} <= campos:
        raise ValueError(f"{caminho}: o CSV precisa das colunas canonico e sobrevivente")
    saida = []
    for lin in linhas:
        item = {"canonico": (lin.get("canonico") or "").strip(),
                "sobrevivente": bling._uuid((lin.get("sobrevivente") or "").strip())}
        # Sem a coluna `duplicados` a linha e recusada: so o sobrevivente nao basta para
        # garantir que o grupo de hoje e o mesmo que foi revisado.
        item["duplicados"] = (sorted(bling._uuid(i.strip())
                                     for i in (lin.get("duplicados") or "").split("|")
                                     if i.strip())
                              if "duplicados" in campos else None)
        saida.append(item)
    return saida


def selecionar_revisados(grupos, excluidos, revisados):
    """Cruza o CSV revisado com os grupos recalculados AGORA. So passa o grupo que ainda
    existe igual (mesmo sobrevivente e mesmos duplicados)."""
    atuais = {g["canonico"]: g for g in grupos}
    aplicar, recusados, vistos = [], [], set()
    for rev in revisados:
        if rev["canonico"] in vistos:
            continue
        vistos.add(rev["canonico"])
        g = atuais.get(rev["canonico"])
        if not rev.get("duplicados"):
            erro = "linha sem a coluna duplicados (ou vazia) — use o pares.csv/revisar.csv do dry-run"
        elif g is None:
            erro = ("grupo excluido via --excluir" if rev["canonico"] in excluidos
                    else "sem grupo hoje (ja mesclado, lead apagado ou telefone mudou)")
        elif g["sobrevivente"]["id"] != rev["sobrevivente"]:
            erro = f"sobrevivente hoje e {g['sobrevivente']['id']}"
        elif sorted(d["id"] for d in g["duplicados"]) != rev["duplicados"]:
            erro = "duplicados hoje sao " + "|".join(d["id"] for d in g["duplicados"])
        else:
            aplicar.append(g)
            continue
        recusados.append({"canonico": rev["canonico"], "sobrevivente": rev["sobrevivente"],
                          "duplicados": rev.get("duplicados") or [], "motivo": "",
                          "resultado": "recusado",
                          "erro": f"linha revisada nao bate mais com o grupo atual: {erro}"})
    return aplicar, recusados


def _json_do_stdout(saida, prefixo):
    for linha in (saida or "").splitlines():
        if linha.startswith(prefixo):
            return json.loads(linha[len(prefixo):])
    return None


def _carimbo():
    return f"{datetime.now():%Y%m%d-%H%M%S}"


def executar(db, saida, aplicar=False, limite=None, pares_csv=None, excluir=()):
    excluir = {bling._uuid(i) for i in excluir}
    if aplicar and not pares_csv:
        raise SystemExit("--aplicar exige --pares <csv revisado> (pares.csv e/ou linhas"
                         " aprovadas do revisar.csv)")
    revisados = ler_grupos_revisados(pares_csv) if aplicar else []
    saida = Path(saida)
    saida.mkdir(parents=True, exist_ok=True)
    # O --aplicar nunca sobrescreve um backup: cada rodada grava backup-<carimbo>.json e
    # aplicados-<carimbo>.csv, e aborta se o arquivo ja existir. O dry-run usa backup.json.
    if aplicar:
        carimbo = _carimbo()
        arq_backup = saida / f"backup-{carimbo}.json"
        arq_aplicados = saida / f"aplicados-{carimbo}.csv"
        for arq in (arq_backup, arq_aplicados):
            if arq.exists():
                raise SystemExit(f"{arq} ja existe — o --aplicar nao sobrescreve backup;"
                                 " espere um segundo ou use outra --saida")
    else:
        arq_backup = saida / "backup.json"

    tabelas = {r["table_name"] for r in db.linhas(bling.Q_TABELAS)}
    bling.verificar_cobertura(tabelas)
    verificar_fks(db.linhas(Q_FKS))
    colunas = {}
    for r in db.linhas(Q_COLUNAS):
        colunas.setdefault(r["table_name"], set()).add(r["column_name"])
    pks = {r["tabela"]: r["colunas"] for r in db.linhas(bling.Q_CHAVES)}

    leads = db.linhas(Q_LEADS)
    todos = agrupar(leads)
    grupos, excluidos, pares, revisar = [], [], [], []
    for g in todos:
        classe, motivo = classificar(g)
        if excluir & set(_ids(g)):
            excluidos.append(_linha(g, "excluido via --excluir; " + (motivo or "automatico")))
            continue
        grupos.append(g)
        (pares if classe == "automatico" else revisar).append(_linha(g, motivo))
    motivos = {lin["canonico"]: lin["motivo"] for lin in pares + revisar}

    membros = {i for g in grupos for i in _ids(g)}
    deals = db.linhas(q_deals_abertos(membros)) if membros and "deals" in tabelas else []
    repetidos = deals_repetidos(grupos, deals)

    dup_ids = {d["id"] for g in grupos for d in g["duplicados"]}
    backup = []
    if dup_ids:
        backup = db.linhas(bling.q_backup(dup_ids, tabelas, pks))
        conversas = ({r["lead_id"]: r["conversas"] for r in db.linhas(q_conversas(dup_ids))}
                     if "conversations" in tabelas else {})
        antes = {r["id"]: r["antes"]
                 for r in db.linhas(q_antes({g["sobrevivente"]["id"] for g in grupos}))}
        grupo_do_dup = {d["id"]: g for g in grupos for d in g["duplicados"]}
        for item in backup:
            g = grupo_do_dup.get(item["lead"]["id"])
            if g:
                item["canonico"] = g["canonico"]
                item["sobrevivente"] = g["sobrevivente"]["id"]
                item["sobrevivente_antes"] = antes.get(g["sobrevivente"]["id"])
            item["conversas_duplicados"] = conversas.get(item["lead"]["id"], [])

    bling._csv(saida / "pares.csv", pares, COLUNAS_GRUPO)
    bling._csv(saida / "revisar.csv", revisar, COLUNAS_GRUPO)
    bling._csv(saida / "excluidos.csv", excluidos, COLUNAS_GRUPO)
    bling._csv(saida / "deals_repetidos.csv", repetidos,
               ["canonico", "sobrevivente", "pipeline_id", "deals"])
    arq_backup.write_text(json.dumps(backup, ensure_ascii=False, indent=1), encoding="utf-8")

    aplicados = []
    if aplicar:
        if len(db.linhas(bling.Q_COLUNAS_P0)) != 3:
            raise SystemExit("lead_events sem occurred_at/source/dedupe_key: aplique "
                             "supabase/migrations/20261006_call_semanal_base.sql antes do --aplicar")
        a_aplicar, recusados = selecionar_revisados(
            grupos, {lin["canonico"] for lin in excluidos}, revisados)
        aplicados.extend(recusados)
        for g in a_aplicar[:limite] if limite is not None else a_aplicar:
            base = {"canonico": g["canonico"], "sobrevivente": g["sobrevivente"]["id"],
                    "duplicados": [d["id"] for d in g["duplicados"]],
                    "motivo": motivos.get(g["canonico"], "")}
            try:
                saida_psql = db.executar(sql_mesclar_grupo(g, tabelas, pks, colunas))
                aplicados.append({**base, "resultado": "ok", "erro": "",
                                  "movidos": bling.movidos_do_stdout(saida_psql),
                                  "movidos_por_duplicado":
                                      _json_do_stdout(saida_psql, "movidos_por_duplicado=")})
            except RuntimeError as exc:
                aplicados.append({**base, "resultado": "erro", "erro": str(exc)})
        bling._csv(arq_aplicados, aplicados,
                   ["canonico", "sobrevivente", "duplicados", "motivo", "resultado", "erro"])
        # o backup ganha, por duplicado aplicado, o que de fato mudou de dono
        movidos = {}
        for a in aplicados:
            movidos.update(a.get("movidos_por_duplicado") or {})
        for item in backup:
            if item["lead"]["id"] in movidos:
                item["movidos"] = movidos[item["lead"]["id"]]
        arq_backup.write_text(json.dumps(backup, ensure_ascii=False, indent=1),
                              encoding="utf-8")

    contagens = {
        "leads_lidos": len(leads), "grupos": len(todos),
        "automaticos": len(pares), "revisar": len(revisar), "excluidos": len(excluidos),
        "deals_repetidos": len(repetidos),
        "aplicados_ok": sum(1 for a in aplicados if a["resultado"] == "ok"),
        "aplicados_erro": sum(1 for a in aplicados if a["resultado"] == "erro"),
        "aplicados_recusados": sum(1 for a in aplicados if a["resultado"] == "recusado"),
        "modo": "aplicar" if aplicar else "dry-run",
    }
    return {"contagens": contagens, "pares": pares, "revisar": revisar, "excluidos": excluidos,
            "deals_repetidos": repetidos, "aplicados": aplicados}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--psql", default=os.environ.get("MESCLAR_PSQL"),
                    help="comando psql completo (ou env MESCLAR_PSQL)")
    ap.add_argument("--saida", default=None,
                    help="pasta dos CSVs (default ./mesclagem-tel-<data>)")
    ap.add_argument("--aplicar", action="store_true",
                    help="EXECUTA a mesclagem (uma transacao por grupo). Sem isto, so le."
                         " Exige --pares.")
    ap.add_argument("--pares", default=None,
                    help="CSV revisado (colunas canonico, sobrevivente e, de preferencia,"
                         " duplicados): o --aplicar aplica SO estes grupos, recalculados —"
                         " o que nao bate mais e recusado")
    ap.add_argument("--excluir", default="",
                    help="lead_ids separados por virgula: os grupos que os contem saem"
                         " (vao para excluidos.csv)")
    ap.add_argument("--limite", type=int, default=None,
                    help="aplica no maximo N grupos (0 = nenhum)")
    args = ap.parse_args(argv)
    if not args.psql:
        ap.error("informe --psql ou a env MESCLAR_PSQL")
    if args.aplicar and not args.pares:
        ap.error("--aplicar exige --pares <csv revisado>")
    saida = args.saida or f"mesclagem-tel-{datetime.now():%Y%m%d-%H%M%S}"
    resultado = executar(Psql(args.psql), saida, aplicar=args.aplicar,
                         limite=args.limite, pares_csv=args.pares,
                         excluir=[i.strip() for i in args.excluir.split(",") if i.strip()])
    print(json.dumps(resultado["contagens"], ensure_ascii=False))
    print(f"arquivos em {Path(saida).resolve()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
