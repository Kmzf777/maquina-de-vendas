#!/usr/bin/env python3
"""Mescla os leads `bling-*` duplicados no lead verdadeiro (spec 2026-10-06, P1.1).

POR QUE EXISTE: ate o fix `ba9cb923`, o webhook do Bling so olhava o campo `celular` do
contato. Quando o celular estava em `telefone` (o comum) ou no formato antigo sem o 9, o
`ensure_lead` nao achava o cliente e criava um lead `bling-<id>` com a venda — que caia
"sem origem" no /trafego (Jovens/Iago, Antonio Sergio). O fix impede NOVAS duplicatas; este
script junta as que ja existem.

REGRAS:
  - Candidato: `phone like 'bling-%'` OU `channel='bling'` com `metadata.origem='bling_webhook'`.
  - Par: chaves de celular do contato vinculado (com e sem o 9, mesmas de
    `app/bling/contacts._chaves_de_celular`) contra `leads.phone`, e `doc_digits` contra os
    digitos de `leads.cnpj`. Sobrevivente = o lead NAO-Bling. Mais de um possivel → ambiguo,
    nao mescla. Nenhum → orfao.
  - Move todas as linhas com `lead_id` (lista conferida contra information_schema — tabela
    nao coberta ABORTA; a foto do incidente de 03/10 e ignorada de proposito), copia
    cnpj/razao_social/nome_fantasia/email so onde o sobrevivente esta vazio, grava
    `lead_events` 'mesclagem' e apaga o duplicado.
  - Sobrevivente que receberia mais de 2 duplicados (celular compartilhado, contatos de
    teste) vai INTEIRO para os ambiguos.
  - Vendas gemeas (mesmo valor, sold_at a <= 1 dia, uma bling e outra manual/crm): so relata.

USO (dry-run e o padrao — so le):
  python3 scripts/bling/mesclar_leads_duplicados.py \\
      --psql "docker exec -i $(docker ps -q -f name=supabase_db | head -1) psql -U postgres -d postgres" \\
      --saida /root/mesclagem-dryrun
  ... --aplicar --pares /root/mesclagem-dryrun/pares-revisado.csv
      # executa SO os pares do CSV revisado (copia do pares.csv com as linhas aprovadas),
      # recalculando cada um; uma transacao por par — SO com OK do Rafael, depois do P0

  ... --excluir <lead_id,lead_id>   # tira esses leads (duplicado ou sobrevivente) dos pares

Saida: pares.csv, ambiguos.csv, orfaos.csv, excluidos.csv, gemeas.csv, backup.json (+ aplicados.csv) e as
contagens em JSON no stdout. So stdlib: roda no host da VPS (psql), sem o venv do backend.
"""
import argparse
import csv
import json
import os
import shlex
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Chaves de celular — COPIA FIEL de app/bling/contacts.py (_celular_br e
# _chaves_de_celular). O script nao importa `app` (precisa de redis/supabase).
# tests/test_cs_p1_mesclagem.py compara as duas implementacoes.
# ---------------------------------------------------------------------------


def celular_br(e164):
    if not e164 or not e164.startswith("55"):
        return None
    if len(e164) == 13 and e164[4] == "9":
        return e164
    if len(e164) == 12 and e164[4] in "6789":
        return e164[:4] + "9" + e164[4:]
    return None


def chaves_de_celular(contato):
    chaves = []
    for campo in ("celular_e164", "telefone_e164"):
        bruto = contato.get(campo)
        celular = celular_br(bruto)
        if celular:
            candidatos = [celular, celular[:4] + celular[5:]]
        elif campo == "celular_e164" and bruto:
            candidatos = [bruto]
        else:
            candidatos = []
        for c in candidatos:
            if c not in chaves:
                chaves.append(c)
    return chaves


def doc_para_par(valor):
    """Digitos de CPF/CNPJ que servem de chave: 11 ou 14, nao repetitivos (lixo de importacao fora)."""
    d = "".join(ch for ch in str(valor or "") if ch.isdigit())
    if len(d) in (11, 14) and len(set(d)) > 1:
        return d
    return None


# ---------------------------------------------------------------------------
# Pareamento
# ---------------------------------------------------------------------------


MAX_DUPLICADOS_POR_SOBREVIVENTE = 2


def parear(candidatos, leads):
    """candidatos: [{id, phone, name, contatos: [{account, id, nome, doc_digits,
    telefone_e164, celular_e164}]}]; leads: linhas de `leads` que casaram alguma chave
    ({id, phone, name, cnpj}). Devolve {pares, ambiguos, orfaos}."""
    ids_candidatos = {c["id"] for c in candidatos}
    por_phone, por_doc, info = {}, {}, {}
    for lead in leads:
        if lead["id"] in ids_candidatos:
            continue
        info[lead["id"]] = lead
        if lead.get("phone"):
            por_phone.setdefault(lead["phone"], set()).add(lead["id"])
        d = doc_para_par(lead.get("cnpj"))
        if d:
            por_doc.setdefault(d, set()).add(lead["id"])

    pares, ambiguos, orfaos = [], [], []
    for cand in candidatos:
        achados = {}
        for contato in cand.get("contatos") or []:
            for chave in chaves_de_celular(contato):
                for lid in por_phone.get(chave, ()):
                    achados.setdefault(lid, set()).add(f"celular:{chave}")
            d = doc_para_par(contato.get("doc_digits"))
            if d:
                for lid in por_doc.get(d, ()):
                    achados.setdefault(lid, set()).add(f"documento:{d}")
        base = {"duplicado": cand["id"], "duplicado_nome": cand.get("name"),
                "duplicado_phone": cand.get("phone")}
        if len(achados) == 1:
            (lid, motivos), = achados.items()
            pares.append({**base, "sobrevivente": lid,
                          "sobrevivente_nome": info[lid].get("name"),
                          "sobrevivente_phone": info[lid].get("phone"),
                          "motivo": ";".join(sorted(motivos))})
        elif achados:
            ambiguos.append({**base, "opcoes": sorted(achados),
                             "motivo": ";".join(f"{lid}={'|'.join(sorted(mv))}"
                                                for lid, mv in sorted(achados.items()))})
        else:
            orfaos.append(base)

    # Sobrevivente que receberia MAIS de 2 duplicados nao e cliente com cadastro repetido:
    # e um celular compartilhado (contatos "Teste Rafael" do Bling com o celular do Rafael,
    # 14 pares no dry-run de 06/10 — o --aplicar moveria 22 vendas de teste para o lead
    # real). O grupo inteiro vai para os ambiguos, para revisao a mao.
    por_sobrevivente = {}
    for par in pares:
        por_sobrevivente.setdefault(par["sobrevivente"], []).append(par)
    lotados = {lid for lid, ps in por_sobrevivente.items()
               if len(ps) > MAX_DUPLICADOS_POR_SOBREVIVENTE}
    for par in pares:
        if par["sobrevivente"] in lotados:
            n = len(por_sobrevivente[par["sobrevivente"]])
            ambiguos.append({
                "duplicado": par["duplicado"], "duplicado_nome": par["duplicado_nome"],
                "duplicado_phone": par["duplicado_phone"], "opcoes": [par["sobrevivente"]],
                "motivo": (f"sobrevivente {par['sobrevivente']} receberia {n} duplicados"
                           f" (limite {MAX_DUPLICADOS_POR_SOBREVIVENTE}) — revisar a mao;"
                           f" {par['motivo']}")})
    pares = [p for p in pares if p["sobrevivente"] not in lotados]
    return {"pares": pares, "ambiguos": ambiguos, "orfaos": orfaos}


# ---------------------------------------------------------------------------
# Vendas gemeas
# ---------------------------------------------------------------------------

_JANELA_GEMEAS = timedelta(days=1)


def _quando(valor):
    return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))


def vendas_gemeas(pares, vendas):
    """A mesma venda lancada duas vezes: uma pelo Bling (no duplicado ou no sobrevivente) e
    outra manual/crm, mesmo valor, sold_at a <= 1 dia. Canceladas nao contam. So relata."""
    por_lead = {}
    for v in vendas:
        if v.get("status") == "cancelada":
            continue
        por_lead.setdefault(v["lead_id"], []).append(v)
    saida = []
    for par in pares:
        do_dup = por_lead.get(par["duplicado"], [])
        do_sob = por_lead.get(par["sobrevivente"], [])
        for a in do_dup:
            for b in do_sob:
                origens = {a.get("origin"), b.get("origin")}
                if len(origens) != 2 or "bling" not in origens or not origens & {"manual", "crm"}:
                    continue
                if abs(float(a["value"]) - float(b["value"])) >= 0.005:
                    continue
                delta = abs(_quando(a["sold_at"]) - _quando(b["sold_at"]))
                if delta > _JANELA_GEMEAS:
                    continue
                bling, outra = (a, b) if a.get("origin") == "bling" else (b, a)
                saida.append({
                    "sobrevivente": par["sobrevivente"], "duplicado": par["duplicado"],
                    "valor": float(bling["value"]),
                    "venda_bling": bling["id"], "sold_at_bling": bling["sold_at"],
                    "venda_outra": outra["id"], "origin_outra": outra.get("origin"),
                    "sold_at_outra": outra["sold_at"],
                    "diferenca_horas": round(delta.total_seconds() / 3600, 2),
                })
    return saida


# ---------------------------------------------------------------------------
# Tabelas com lead_id
# ---------------------------------------------------------------------------

# So mover: nenhuma unicidade envolvendo lead_id (ou, em `conversations`, colisao em
# (lead_id, channel_id) derruba a transacao do par inteiro — preferivel a fundir conversas).
SO_MOVER = (
    "sales", "deals", "quotes", "lead_notes", "lead_events", "conversations", "messages",
    "messages_archive", "conversion_events", "campaign_execution_log", "lp_email_jobs",
    "token_usage",
)

# Com unicidade: a linha do duplicado que colidiria com uma do sobrevivente e APAGADA (o
# sobrevivente vence; a linha vai para o backup) e o resto e movido. `d` = duplicado,
# `s` = sobrevivente.
COLISAO = {
    "lead_bling_contacts": "s.account = d.account",
    "lead_tags": "s.tag_id = d.tag_id",
    "lead_daily_sends": "s.date = d.date",
    "lead_seller_feelings": "s.user_id = d.user_id",
    "lead_qualification_scores": "true",
    "broadcast_leads": "s.broadcast_id = d.broadcast_id",
    "campaign_enrollments": ("s.campaign_id = d.campaign_id"
                             " and s.status in ('active', 'paused')"
                             " and d.status in ('active', 'paused')"),
    "follow_up_jobs": ("s.job_type = d.job_type and s.sequence is not distinct from d.sequence"
                       " and coalesce(s.metadata->>'deal_id', '')"
                       " = coalesce(d.metadata->>'deal_id', '')"
                       " and s.status in ('pending', 'processing')"
                       " and d.status in ('pending', 'processing')"
                       r" and d.job_type like 'joao\_%'"),
}

TABELAS_COBERTAS = frozenset(SO_MOVER) | frozenset(COLISAO)

# Tabelas com lead_id que a mesclagem NAO toca, de proposito. So entra aqui o que nao e
# dado vivo — qualquer outra tabela fora de COBERTAS continua abortando.
#   follow_up_jobs_incidente_20261003: foto da explosao de follow-up de 03-04/10
#   (1.019.539 linhas, sem indice em lead_id e sem FK para leads). Mover por par era um
#   seq scan de 1M linhas em cada transacao; a foto fica com o lead_id da epoca.
TABELAS_IGNORADAS = frozenset({"follow_up_jobs_incidente_20261003"})


class TabelaNaoCoberta(RuntimeError):
    pass


def verificar_cobertura(tabelas_no_banco):
    faltando = sorted(set(tabelas_no_banco) - TABELAS_COBERTAS - TABELAS_IGNORADAS)
    if faltando:
        raise TabelaNaoCoberta(
            "tabela(s) com lead_id que o script nao sabe mesclar: " + ", ".join(faltando)
            + " — inclua em SO_MOVER ou COLISAO antes de rodar")


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------


def _uuid(valor):
    return str(uuid.UUID(str(valor)))


def _texto(valor):
    return "'" + str(valor).replace("'", "''") + "'"


CAMPOS_COPIADOS = ("cnpj", "razao_social", "nome_fantasia", "email")


def sql_mesclar_par(duplicado, sobrevivente, tabelas, motivo):
    """SQL de UM par, numa transacao. `tabelas` = tabelas com lead_id que existem no banco."""
    d, s = _uuid(duplicado), _uuid(sobrevivente)
    linhas = [
        "begin;",
        # Trava os dois leads antes de mover: um insert concorrente com lead_id = duplicado
        # (webhook do Bling, mensagem) espera o commit em vez de cair no lead que o DELETE
        # do fim apaga em cascata.
        f"select 1 from public.leads where id in ('{d}', '{s}') for update;",
        "do $$ begin",
        f"  if (select count(*) from public.leads where id in ('{d}', '{s}')) <> 2 then",
        f"    raise exception 'par {d} -> {s}: um dos leads nao existe mais';",
        "  end if;",
        "end $$;",
    ]
    for tabela in sorted(set(tabelas) & TABELAS_COBERTAS):
        if tabela in COLISAO:
            linhas.append(
                f"delete from public.{tabela} d using public.{tabela} s"
                f" where d.lead_id = '{d}' and s.lead_id = '{s}' and ({COLISAO[tabela]});")
        linhas.append(f"update public.{tabela} set lead_id = '{s}' where lead_id = '{d}';")
    sets = ",\n  ".join(
        f"{c} = case when coalesce(btrim(s.{c}), '') = '' then d.{c} else s.{c} end"
        for c in CAMPOS_COPIADOS)
    linhas.append(f"update public.leads s set\n  {sets}\nfrom public.leads d"
                  f" where s.id = '{s}' and d.id = '{d}';")
    linhas.append(
        "insert into public.lead_events"
        " (lead_id, event_type, old_value, new_value, metadata, occurred_at, source, dedupe_key)\n"
        f"select '{s}', 'mesclagem', '{d}', '{s}',"
        " jsonb_build_object('duplicado', jsonb_build_object('id', d.id, 'phone', d.phone,"
        " 'name', d.name, 'cnpj', d.cnpj, 'razao_social', d.razao_social, 'email', d.email,"
        " 'channel', d.channel, 'created_at', d.created_at, 'metadata', d.metadata),"
        f" 'motivo', {_texto(motivo)}),"
        f" now(), 'sistema', 'mesclagem:{d}'\n"
        f"from public.leads d where d.id = '{d}'\non conflict do nothing;")
    linhas.append(f"delete from public.leads where id = '{d}';")
    linhas.append("commit;")
    return "\n".join(linhas) + "\n"


# ---------------------------------------------------------------------------
# Banco (psql em subprocesso)
# ---------------------------------------------------------------------------


class Psql:
    def __init__(self, comando):
        self.base = shlex.split(comando)

    def _rodar(self, sql):
        proc = subprocess.run(self.base + ["-X", "-q", "-At", "-v", "ON_ERROR_STOP=1"],
                              input=sql, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or f"psql saiu com {proc.returncode}")
        return proc.stdout

    def linhas(self, sql):
        saida = self._rodar(f"select coalesce(json_agg(t), '[]'::json) from ({sql}) t;")
        return json.loads(saida.strip() or "[]")

    def executar(self, sql):
        self._rodar(sql)


Q_TABELAS = """
select c.table_name from information_schema.columns c
join information_schema.tables t using (table_schema, table_name)
where c.table_schema = 'public' and c.column_name = 'lead_id' and t.table_type = 'BASE TABLE'
"""

Q_COLUNAS_P0 = """
select column_name from information_schema.columns
where table_schema = 'public' and table_name = 'lead_events'
  and column_name in ('occurred_at', 'source', 'dedupe_key')
"""

Q_CANDIDATOS = """
select l.id, l.phone, l.name, l.cnpj, l.created_at,
       coalesce((select json_agg(json_build_object(
                   'account', bc.account, 'id', bc.id, 'nome', bc.nome,
                   'doc_digits', bc.doc_digits, 'telefone_e164', bc.telefone_e164,
                   'celular_e164', bc.celular_e164) order by bc.account)
                 from public.lead_bling_contacts lbc
                 join public.bling_contacts bc
                   on bc.account = lbc.account and bc.id = lbc.bling_contact_id
                 where lbc.lead_id = l.id), '[]'::json) as contatos
from public.leads l
where l.phone like 'bling-%'
   or (l.channel = 'bling' and l.metadata->>'origem' = 'bling_webhook')
order by l.created_at, l.id
"""


def _array_texto(valores):
    # So digitos chegam aqui (filtrados em `coletar_chaves`) — o literal e seguro.
    return "'{" + ",".join(sorted(valores)) + "}'::text[]"


def coletar_chaves(candidatos):
    chaves, docs = set(), set()
    for cand in candidatos:
        for contato in cand.get("contatos") or []:
            chaves.update(c for c in chaves_de_celular(contato) if c.isdigit())
            d = doc_para_par(contato.get("doc_digits"))
            if d:
                docs.add(d)
    return chaves, docs


def q_leads(chaves, docs):
    return ("select id, phone, name, cnpj from public.leads"
            f" where phone = any({_array_texto(chaves)})"
            rf" or regexp_replace(coalesce(cnpj, ''), '\D', '', 'g') = any({_array_texto(docs)})")


def q_vendas(ids):
    lista = ",".join(_uuid(i) for i in sorted(ids))
    return ("select id, lead_id, value, origin, status, sold_at from public.sales"
            f" where lead_id = any('{{{lista}}}'::uuid[])")


def q_backup(ids, tabelas):
    lista = ",".join(_uuid(i) for i in sorted(ids))
    extras = "".join(
        f", coalesce((select json_agg(to_jsonb(x)) from public.{t} x where x.lead_id = l.id),"
        f" '[]'::json) as {t}"
        for t in sorted(set(tabelas) & set(COLISAO)))
    return (f"select to_jsonb(l) as lead{extras} from public.leads l"
            f" where l.id = any('{{{lista}}}'::uuid[])")


# ---------------------------------------------------------------------------
# Execucao
# ---------------------------------------------------------------------------


def _csv(caminho, linhas, campos):
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        for linha in linhas:
            w.writerow({k: ("|".join(v) if isinstance(v, list) else v) for k, v in linha.items()})


def ler_pares_revisados(caminho):
    """Pares (duplicado, sobrevivente) do CSV revisado — o `pares.csv` do dry-run, com as
    linhas que nao devem ser aplicadas apagadas. Id que nao e uuid aborta tudo (ValueError)."""
    with open(caminho, newline="", encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))
    if linhas and not {"duplicado", "sobrevivente"} <= set(linhas[0]):
        raise ValueError(f"{caminho}: o CSV precisa das colunas duplicado e sobrevivente")
    return [{"duplicado": _uuid(lin["duplicado"]), "sobrevivente": _uuid(lin["sobrevivente"])}
            for lin in linhas]


def selecionar_revisados(pares, revisados):
    """Cruza o CSV revisado com o pareamento recalculado AGORA. So passa o par que ainda
    existe igual (mesmo duplicado -> mesmo sobrevivente); o resto volta como recusado."""
    atuais = {p["duplicado"]: p for p in pares}
    aplicar, recusados, vistos = [], [], set()
    for rev in revisados:
        if rev["duplicado"] in vistos:
            continue
        vistos.add(rev["duplicado"])
        atual = atuais.get(rev["duplicado"])
        if atual and atual["sobrevivente"] == rev["sobrevivente"]:
            aplicar.append(atual)
            continue
        hoje = (f"hoje pareia com {atual['sobrevivente']}" if atual
                else "hoje nao e par (ambiguo, orfao, excluido ou ja mesclado)")
        recusados.append({**rev, "motivo": "", "resultado": "recusado",
                          "erro": f"par revisado nao bate mais com o pareamento atual: {hoje}"})
    return aplicar, recusados


def executar(db, saida, aplicar=False, limite=None, pares_csv=None, excluir=()):
    excluir = {_uuid(i) for i in excluir}
    if aplicar and not pares_csv:
        raise SystemExit("--aplicar exige --pares <csv revisado> (o pares.csv do dry-run,"
                         " so com as linhas aprovadas)")
    revisados = ler_pares_revisados(pares_csv) if aplicar else []
    saida = Path(saida)
    saida.mkdir(parents=True, exist_ok=True)

    tabelas = {r["table_name"] for r in db.linhas(Q_TABELAS)}
    verificar_cobertura(tabelas)

    candidatos = db.linhas(Q_CANDIDATOS)
    chaves, docs = coletar_chaves(candidatos)
    leads = db.linhas(q_leads(chaves, docs)) if (chaves or docs) else []
    r = parear(candidatos, leads)
    # --excluir: lead que o Rafael marcou (duplicado OU sobrevivente) sai dos pares.
    r["excluidos"] = [{**p, "motivo": f"excluido via --excluir; {p['motivo']}"}
                      for p in r["pares"]
                      if p["duplicado"] in excluir or p["sobrevivente"] in excluir]
    r["pares"] = [p for p in r["pares"]
                  if p["duplicado"] not in excluir and p["sobrevivente"] not in excluir]
    pares = r["pares"]

    ids = {p["duplicado"] for p in pares} | {p["sobrevivente"] for p in pares}
    vendas = db.linhas(q_vendas(ids)) if ids else []
    gemeas = vendas_gemeas(pares, vendas)
    backup = db.linhas(q_backup({p["duplicado"] for p in pares}, tabelas)) if pares else []

    base = ["duplicado", "duplicado_nome", "duplicado_phone"]
    _csv(saida / "pares.csv", pares,
         base + ["sobrevivente", "sobrevivente_nome", "sobrevivente_phone", "motivo"])
    _csv(saida / "ambiguos.csv", r["ambiguos"], base + ["opcoes", "motivo"])
    _csv(saida / "orfaos.csv", r["orfaos"], base)
    _csv(saida / "excluidos.csv", r["excluidos"],
         base + ["sobrevivente", "sobrevivente_nome", "sobrevivente_phone", "motivo"])
    _csv(saida / "gemeas.csv", gemeas,
         ["sobrevivente", "duplicado", "valor", "venda_bling", "sold_at_bling",
          "venda_outra", "origin_outra", "sold_at_outra", "diferenca_horas"])
    (saida / "backup.json").write_text(json.dumps(backup, ensure_ascii=False, indent=1),
                                       encoding="utf-8")

    aplicados = []
    if aplicar:
        if len(db.linhas(Q_COLUNAS_P0)) != 3:
            raise SystemExit("lead_events sem occurred_at/source/dedupe_key: aplique "
                             "supabase/migrations/20261006_call_semanal_base.sql antes do --aplicar")
        a_aplicar, recusados = selecionar_revisados(pares, revisados)
        aplicados.extend(recusados)
        for par in a_aplicar[:limite] if limite else a_aplicar:
            try:
                db.executar(sql_mesclar_par(par["duplicado"], par["sobrevivente"], tabelas,
                                            par["motivo"]))
                aplicados.append({**par, "resultado": "ok", "erro": ""})
            except RuntimeError as exc:
                aplicados.append({**par, "resultado": "erro", "erro": str(exc)})
        _csv(saida / "aplicados.csv", aplicados,
             ["duplicado", "sobrevivente", "motivo", "resultado", "erro"])

    duplicados = {p["duplicado"] for p in pares}
    contagens = {
        "candidatos": len(candidatos), "pares": len(pares),
        "ambiguos": len(r["ambiguos"]), "orfaos": len(r["orfaos"]),
        "excluidos": len(r["excluidos"]),
        "gemeas": len(gemeas),
        "vendas_do_duplicado_movidas": sum(1 for v in vendas if v["lead_id"] in duplicados),
        "aplicados_ok": sum(1 for a in aplicados if a["resultado"] == "ok"),
        "aplicados_erro": sum(1 for a in aplicados if a["resultado"] == "erro"),
        "aplicados_recusados": sum(1 for a in aplicados if a["resultado"] == "recusado"),
        "modo": "aplicar" if aplicar else "dry-run",
    }
    return {"contagens": contagens, "gemeas": gemeas, "aplicados": aplicados, **r}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--psql", default=os.environ.get("MESCLAR_PSQL"),
                    help="comando psql completo (ou env MESCLAR_PSQL)")
    ap.add_argument("--saida", default=None, help="pasta dos CSVs (default ./mesclagem-<data>)")
    ap.add_argument("--aplicar", action="store_true",
                    help="EXECUTA a mesclagem (uma transacao por par). Sem isto, so le."
                         " Exige --pares.")
    ap.add_argument("--pares", default=None,
                    help="CSV revisado (formato do pares.csv do dry-run): o --aplicar aplica"
                         " SO estes pares, recalculados — o que nao bate mais e recusado")
    ap.add_argument("--excluir", default="",
                    help="lead_ids separados por virgula (duplicado ou sobrevivente) que saem"
                         " dos pares — vao para excluidos.csv")
    ap.add_argument("--limite", type=int, default=None, help="aplica so os N primeiros pares")
    args = ap.parse_args(argv)
    if not args.psql:
        ap.error("informe --psql ou a env MESCLAR_PSQL")
    if args.aplicar and not args.pares:
        ap.error("--aplicar exige --pares <csv revisado>")
    saida = args.saida or f"mesclagem-{datetime.now():%Y%m%d-%H%M%S}"
    resultado = executar(Psql(args.psql), saida, aplicar=args.aplicar, limite=args.limite,
                         pares_csv=args.pares,
                         excluir=[i.strip() for i in args.excluir.split(",") if i.strip()])
    print(json.dumps(resultado["contagens"], ensure_ascii=False))
    print(f"arquivos em {Path(saida).resolve()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
