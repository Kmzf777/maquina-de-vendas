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
    Revisar a mao: 3+ leads, primeiros nomes diferentes, telefone fixo (9 injetado).
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

Saida: pares.csv, revisar.csv, excluidos.csv, deals_repetidos.csv, backup.json (+ aplicados.csv)
e as contagens em JSON no stdout. So stdlib: roda no host da VPS (psql), sem o venv do backend.
"""
import importlib.util
import re
import unicodedata
from pathlib import Path

# Irmao do Bling: Psql, _chave, _uuid, _texto, _csv, consultas e a lista de tabelas cobertas.
_BLING = Path(__file__).resolve().parents[1] / "bling" / "mesclar_leads_duplicados.py"
_spec = importlib.util.spec_from_file_location("_mesclar_bling", _BLING)
bling = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bling)


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
        return "revisar", "telefone fixo (9 injetado)"
    nomes = {_primeiro_nome(l.get("name")) for l in [grupo["sobrevivente"], *grupo["duplicados"]]}
    nomes.discard("")
    if len(nomes) > 1:
        return "revisar", "nomes diferentes"
    return "automatico", ""
