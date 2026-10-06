#!/usr/bin/env python3
"""Recupera leads.meta_ad_id a partir dos referrals CTWA arquivados (spec 2026-10-06, P2.5).

O webhook só passou a gravar o anúncio do Click-to-WhatsApp (referral.source_id → meta_ad_id) em
21/08/2026. Lead pago anterior tem ctwa_clid e meta_ad_id nulo, e no /trafego cai em "Meta,
campanha não identificada" (caso Antônio Sérgio/Serginho da call de 01/10). O referral da
mensagem que o trouxe continua guardado — em meta_referrals_arquivo (P0) ou, antes do P0 ser
aplicado, dentro do payload de meta_webhook_logs.

Casamento, do mais forte ao mais fraco:
  1. mesmo ctwa_clid → source_id do referral. Um clid apontando para dois anúncios = ambíguo,
     não grava;
  2. fallback: mesmo telefone (com e sem o 9º dígito — o WhatsApp ainda entrega número antigo
     sem o 9) e o referral mais próximo ANTES de leads.created_at, até 24 h.
Só referral de anúncio (source_type 'ad'); o que só casa com referral sem source_type sai no
CSV como `sem_source_type` e não é gravado. Só preenche nulos: o UPDATE leva
`and meta_ad_id is null`, então rodar de novo ou rodar depois de o lead mudar não sobrescreve.

Uso — dry-run é o padrão (sessão read-only, escreve CSV, não altera nada):
  python3 scripts/trafego/recuperar_meta_ad_id.py \\
      --psql "docker exec -i $(docker ps -q -f name=supabase_db | head -1) psql -U postgres -d postgres"
  --fonte auto|arquivo|log   (auto: meta_referrals_arquivo se existir, senão o log)
  --saida DIR                (pasta do CSV; padrão: diretório atual)
  --aplicar                  grava, um UPDATE (= uma transação) por lead. Só com OK do Rafael.
Sem dependência além da stdlib: fala com o banco pelo `psql`.
"""
import argparse
import csv
import io
import re
import shlex
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

JANELA_FALLBACK = timedelta(hours=24)

SQL_LEADS = """
select id, coalesce(name, '') as name, phone, created_at, ctwa_clid
  from public.leads
 where ctwa_clid is not null and btrim(ctwa_clid) <> '' and meta_ad_id is null
 order by created_at
""".strip()

SQL_TEM_ARQUIVO = "select to_regclass('public.meta_referrals_arquivo') is not null as tem"

SQL_REFERRALS_ARQUIVO = """
select received_at, from_number, ctwa_clid, source_id, source_type
  from public.meta_referrals_arquivo
 where source_id is not null
""".strip()

# Mesma extração de fn_arquiva_meta_referrals (P0) — produção antes da migração.
SQL_REFERRALS_LOG = """
select l.received_at,
       coalesce(m->>'from', l.from_number) as from_number,
       m->'referral'->>'ctwa_clid'   as ctwa_clid,
       m->'referral'->>'source_id'   as source_id,
       m->'referral'->>'source_type' as source_type
  from public.meta_webhook_logs l
  cross join lateral jsonb_path_query(l.payload, '$.entry[*].changes[*].value.messages[*]') as m
 where l.direction = 'inbound'
   and l.payload::text like '%"referral"%'
   and m ? 'referral'
""".strip()

SQL_CAMPANHAS = "select ad_id, campaign_name from public.meta_ad_campaigns"

CAMPOS_CSV = ("lead_id", "nome", "phone", "created_at", "status", "metodo", "meta_ad_id",
              "campanha", "referral_em")

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_AD_ID = re.compile(r"^\d{5,30}$")


def digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def chaves_telefone(v) -> frozenset:
    """O mesmo celular com e sem o 9º dígito (55 + DDD + número)."""
    d = digitos(v)
    if not d:
        return frozenset()
    chaves = {d}
    if d.startswith("55") and len(d) == 13 and d[4] == "9":
        chaves.add(d[:4] + d[5:])
    elif d.startswith("55") and len(d) == 12:
        chaves.add(d[:4] + "9" + d[4:])
    return frozenset(chaves)


def parse_ts(v):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _indexar(referrals) -> tuple:
    """(ctwa_clid -> {source_id: primeiro received_at}, telefone -> [(received_at, source_id)])."""
    por_clid = defaultdict(dict)
    por_tel = defaultdict(list)
    for r in referrals:
        sid = str(r.get("source_id") or "").strip()
        if not sid:
            continue
        ts = parse_ts(r.get("received_at"))
        clid = str(r.get("ctwa_clid") or "").strip()
        if clid:
            anuncios = por_clid[clid]
            if sid not in anuncios or (ts and (anuncios[sid] is None or ts < anuncios[sid])):
                anuncios[sid] = ts
        if ts:
            for k in chaves_telefone(r.get("from_number")):
                por_tel[k].append((ts, sid))
    return por_clid, por_tel


def _casar_lead(lead, indice, janela) -> dict:
    """{status, metodo, meta_ad_id, referral_em} do lead contra um índice; {} = nada casou."""
    por_clid, por_tel = indice
    clid = str(lead.get("ctwa_clid") or "").strip()
    anuncios = por_clid.get(clid, {}) if clid else {}
    if len(anuncios) > 1:
        return {"status": "ambiguo", "metodo": "ctwa_clid", "meta_ad_id": "|".join(sorted(anuncios))}
    if len(anuncios) == 1:
        sid, ts = next(iter(anuncios.items()))
        return {"status": "recuperado", "metodo": "ctwa_clid", "meta_ad_id": sid,
                "referral_em": ts.isoformat() if ts else ""}
    criado = parse_ts(lead.get("created_at"))
    if criado:
        candidatos = {(ts, sid) for k in chaves_telefone(lead.get("phone"))
                      for ts, sid in por_tel.get(k, ()) if criado - janela <= ts <= criado}
        if candidatos:
            ts, sid = max(candidatos)
            return {"status": "recuperado", "metodo": "telefone", "meta_ad_id": sid,
                    "referral_em": ts.isoformat()}
    return {}


def casar(leads, referrals, janela=JANELA_FALLBACK) -> list:
    """Uma linha por lead: status recuperado | ambiguo | sem_source_type | sem_referral. Pura.

    Só referral com source_type 'ad' recupera. O que só casa com referral SEM source_type
    vira `sem_source_type` (anúncio candidato no CSV, para revisão; nunca é gravado). Tipo
    diferente de 'ad' (post, ...) é ignorado."""
    de_anuncio, sem_tipo = [], []
    for r in referrals:
        tipo = str(r.get("source_type") or "").strip().lower()
        if tipo == "ad":
            de_anuncio.append(r)
        elif not tipo:
            sem_tipo.append(r)
    indice, indice_sem_tipo = _indexar(de_anuncio), _indexar(sem_tipo)

    out = []
    for lead in leads:
        linha = {"lead_id": lead.get("id"), "nome": lead.get("name") or "",
                 "phone": lead.get("phone") or "", "created_at": lead.get("created_at") or "",
                 "status": "sem_referral", "metodo": "", "meta_ad_id": "", "referral_em": ""}
        achado = _casar_lead(lead, indice, janela)
        if not achado:
            achado = _casar_lead(lead, indice_sem_tipo, janela)
            if achado:
                achado["status"] = "sem_source_type"
        linha.update(achado)
        out.append(linha)
    return out


def sql_de_aplicacao(resultados) -> tuple:
    """Um UPDATE por lead recuperado; id e anúncio validados antes de entrar no SQL."""
    linhas = []
    for r in resultados:
        if r.get("status") != "recuperado":
            continue
        lid, sid = str(r.get("lead_id") or "").lower(), str(r.get("meta_ad_id") or "")
        if not _UUID.match(lid) or not _AD_ID.match(sid):
            continue
        linhas.append(f"update public.leads set meta_ad_id = '{sid}' "
                      f"where id = '{lid}' and meta_ad_id is null;")
    return ("\n".join(linhas) + "\n" if linhas else ""), len(linhas)


def _executor_psql(psql_cmd: str):
    base = shlex.split(psql_cmd) + ["-X", "-q", "-v", "ON_ERROR_STOP=1"]

    def executar(sql: str) -> list:
        # Sessão read-only: o dry-run não grava nem por engano.
        cmd = base + ["-c", "set default_transaction_read_only = on",
                      "-c", f"copy ({sql}) to stdout with csv header"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return list(csv.DictReader(io.StringIO(res.stdout)))
    return executar


def _aplicador_psql(psql_cmd: str):
    base = shlex.split(psql_cmd) + ["-X"]

    def aplicar(sql: str) -> str:
        # Autocommit do psql: cada UPDATE é a sua transação — um lead com erro não leva os outros.
        res = subprocess.run(base + ["-f", "-"], input=sql, capture_output=True, text=True, check=True)
        if res.stderr.strip():
            print(res.stderr, file=sys.stderr)
        return res.stdout
    return aplicar


def main(argv=None, executar=None, aplicar=None) -> int:
    p = argparse.ArgumentParser(description="Recupera leads.meta_ad_id dos referrals CTWA (dry-run padrão).")
    p.add_argument("--psql", help='comando psql do banco-alvo, ex.: "docker exec -i <container> psql -U postgres -d postgres"')
    p.add_argument("--fonte", choices=("auto", "arquivo", "log"), default="auto")
    p.add_argument("--saida", default=".", help="pasta do CSV")
    p.add_argument("--aplicar", action="store_true", help="grava (só com OK do Rafael)")
    a = p.parse_args(argv)
    if executar is None or (a.aplicar and aplicar is None):
        if not a.psql:
            p.error("--psql é obrigatório")
    executar = executar or _executor_psql(a.psql)

    fonte = a.fonte
    if fonte == "auto":
        tem = executar(SQL_TEM_ARQUIVO)
        fonte = "arquivo" if tem and str(tem[0].get("tem")).lower() in ("t", "true") else "log"
    leads = executar(SQL_LEADS)
    referrals = executar(SQL_REFERRALS_ARQUIVO if fonte == "arquivo" else SQL_REFERRALS_LOG)
    resultados = casar(leads, referrals)
    campanha = {r.get("ad_id"): r.get("campaign_name") or "" for r in executar(SQL_CAMPANHAS)}
    for r in resultados:
        r["campanha"] = campanha.get(r["meta_ad_id"], "")

    Path(a.saida).mkdir(parents=True, exist_ok=True)
    caminho = Path(a.saida) / f"recuperar_meta_ad_id_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with caminho.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS_CSV, extrasaction="ignore")
        w.writeheader()
        w.writerows(resultados)

    status = Counter(r["status"] for r in resultados)
    metodo = Counter(r["metodo"] for r in resultados if r["status"] == "recuperado")
    com_campanha = sum(1 for r in resultados if r["status"] == "recuperado" and r["campanha"])
    print(f"fonte: {fonte}")
    print(f"leads com ctwa_clid e sem meta_ad_id: {len(resultados)}")
    print(f"recuperado: {status['recuperado']} (ctwa_clid: {metodo['ctwa_clid']}, "
          f"telefone: {metodo['telefone']}; com campanha conhecida: {com_campanha})")
    print(f"ambiguo: {status['ambiguo']}  sem_source_type: {status['sem_source_type']}  "
          f"sem_referral: {status['sem_referral']}")
    print(f"csv: {caminho}")

    if not a.aplicar:
        print("dry-run: nada foi gravado. --aplicar grava (só com OK do Rafael).")
        return 0
    sql, n = sql_de_aplicacao(resultados)
    if not n:
        print("nada para aplicar")
        return 0
    saida = (aplicar or _aplicador_psql(a.psql))(sql)
    gravados = sum(1 for linha in saida.splitlines() if linha.strip() == "UPDATE 1")
    print(f"aplicado: {gravados} de {n} leads (o resto já tinha meta_ad_id)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
