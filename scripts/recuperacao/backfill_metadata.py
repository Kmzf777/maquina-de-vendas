"""Promove para leads.metadata os dados do Bling que hoje so existem como texto.

Dry-run por padrao. So escreve com --apply explicito.

── Por que este script existe ────────────────────────────────────────────────
A importacao de 14/08/2026 (scripts/reativacao/lote_completo.py:metadata_do_lead)
gravou em leads.metadata apenas 10 chaves fixas: origem, lote, criado_por_lote,
id_bling, segmento, total_gasto, ultima_compra, whatsapp_tipo, vendedor_anterior,
phone_raw. Tudo mais foi para o BRIEFING — texto livre em lead_notes, montado por
transform.montar_briefing:

    CLIENTE INATIVO ha 1.109 dias (ultima compra: 26/07/2023)
    Historico: 126 pedidos - R$ 404.082,26 - ticket medio R$ 3.207,00
    Comprava: Cafe Canastra Classico Moido 250g (1.190 un)
    Cadastro: CNPJ 00.000.000/0001-00 - Lajeado/RS

Um humano le isso muito bem. Um renderizador de template, nao. Consequencia direta:
o template T-B da campanha de recuperacao (spec §6.1) e

    "Vi aqui no cadastro que a ultima compra da {{2}} com a gente foi em {{3}} — {{4}}"

e {{4}} e o produto que a pessoa levava. Sem este backfill, {{4}} nao existe, o
template perde a unica alavanca de MEMORIA CONCRETA que ele tem, e vira mais um
"ola, temos novidades" — a categoria de mensagem que a propria Meta reclassifica e
que a base ja mostrou converter mal.

── Por que a fonte e o CSV e nao a nota ──────────────────────────────────────
Parsear o briefing exigiria regex sobre texto formatado em pt-BR (milhar com ponto,
decimal com virgula, "126 pedidos" vs "1 pedido", linhas opcionais) e falharia em
silencio nos casos que nao casam. O CSV do Bling
`leads-bling-completo-2026-08-08-br (1).csv` (2.771 linhas x 106 colunas) tem os
mesmos numeros em coluna propria e casa por metadata.id_bling com **match de 100%**
nos 1.208 leads da coorte (verificado em 09/09/2026: 1208/1208; considerando todos
os 1.456 leads do CRM com id_bling, 8 nao casam — sao cadastros criados no Bling
DEPOIS do snapshot de 08/08).

── O que este script NUNCA faz ───────────────────────────────────────────────
- Nao apaga nem sobrescreve chave que ja existe com valor diferente por acidente:
  o UPDATE e `metadata || patch`, e o patch so carrega as chaves desta lista.
- Nao toca `ultima_compra` (a chave do lote de 14/08). A data do CSV entra em
  `data_ultima_compra`, chave nova, para que uma divergencia entre as duas fique
  VISIVEL em vez de ser resolvida em silencio a favor de uma delas.
- Nao dispara nada, nao cria deal, nao mexe em tag.

⚠️ `dias_sem_comprar` e um numero CONGELADO em 08/08/2026, nao um numero de hoje.
Por isso o patch carrega `bling_snapshot`: quem for montar a mensagem TEM que
recalcular a recencia de `sales` no momento do disparo (spec §11, risco 5 — 15 leads
da coorte compraram DEPOIS do corte do CSV, um deles em 06/09). O campo esta aqui
para segmentacao e briefing, nunca para ser lido em voz alta ao cliente.

Uso:
    python scripts/recuperacao/backfill_metadata.py                 # so mostra
    python scripts/recuperacao/backfill_metadata.py --amostra 20    # mostra mais
    python scripts/recuperacao/backfill_metadata.py --pipeline all  # todo lead c/ id_bling
    python scripts/recuperacao/backfill_metadata.py --apply         # GRAVA (autorizar antes)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

# O console do Windows abre em cp1252 e engasga em "Café Canastra Clássico Moído".
# O relatorio deste script E a lista de produtos — sem isto ele fica ilegivel
# justamente na coluna que importa.
# try/except porque o modulo tambem e IMPORTADO pelo teste, e ali o sys.stdout e o
# objeto de captura do pytest — reconfigura-lo nao pode derrubar a coleta.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:
    pass

# Os parsers de numero/data do lote de importacao. Reusar em vez de reescrever nao
# e preguica: `_num` tem a regra de desempate BR-vs-US ("o separador que aparecer
# por ultimo e o decimal") que decide se '3.207,00' vale 3207.00 ou 3.20700, e
# `formatar_data` conhece a sentinela '0000-00-00' do Bling. Duplicar isso aqui
# criaria duas verdades sobre o mesmo CSV.
sys.path.insert(0, str(RAIZ / "scripts" / "reativacao"))
import transform  # noqa: E402

CSV_PADRAO = RAIZ / "leads-bling-completo-2026-08-08-br (1).csv"

# Data do corte do CSV. Vai gravada em cada lead como `bling_snapshot`.
SNAPSHOT = "2026-08-08"

# Funil Reativacao Bling (1.208 leads, dono Joao) — o escopo desta campanha.
PIPELINE_RECUPERACAO = "b2f9c31d-8a47-4e26-95c0-3d7a1f6e8b09"

# As chaves que este script promove. Ordem = ordem do relatorio.
CHAVES = (
    "produto_top1",
    "produto_top1_qtd",
    "cidade_uf",
    "ticket_medio",
    "pedidos_faturados",
    "dias_sem_comprar",
    "data_ultima_compra",
    "bling_snapshot",
)


# ── Leitura ─────────────────────────────────────────────────────────────────
def _env() -> dict[str, str]:
    """Variaveis de ambiente + backend/.env.local (mesmo padrao de sync_templates.py)."""
    env = dict(os.environ)
    caminho = RAIZ / "backend" / ".env.local"
    if caminho.exists():
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, valor = linha.split("=", 1)
            env.setdefault(chave.strip(), valor.strip())
    return env


def _sql(env: dict[str, str], query: str) -> list[dict]:
    url = env["SUPABASE_URL"].rstrip("/") + "/pg/query"
    key = env["SUPABASE_SERVICE_KEY"]
    req = urllib.request.Request(
        url,
        data=json.dumps({"query": query}).encode("utf-8"),
        headers={"Content-Type": "application/json", "apikey": key,
                 "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())


def carregar_csv(caminho) -> dict[str, dict]:
    """CSV do Bling indexado por id_bling.

    utf-8-sig e ';' sao o formato real do arquivo (conferido nos bytes: BOM
    EF BB BF, delimitador ';'), o mesmo que lote_completo.carregar_csv usa.
    Linha sem id_bling e descartada: sem chave nao ha como casar com o CRM.
    """
    with open(caminho, encoding="utf-8-sig", newline="") as fh:
        linhas = list(csv.DictReader(fh, delimiter=";"))
    indice: dict[str, dict] = {}
    for linha in linhas:
        chave = (linha.get("id_bling") or "").strip()
        if chave:
            indice[chave] = linha
    return indice


# ── Logica pura (o que o teste exercita) ────────────────────────────────────
def cidade_uf(linha: dict) -> str:
    """'Uberlandia/MG'. So a cidade, so a UF, ou '' — nunca uma barra solta.

    Cidade vazia com UF preenchida acontece nos cadastros estrangeiros do Bling
    (uf='EX'), e 'Uberlandia/' ou '/EX' seria pior que nada numa mensagem.
    """
    partes = [(linha.get("cidade") or "").strip(), (linha.get("uf") or "").strip()]
    return "/".join(p for p in partes if p)


def patch_do_lead(linha: dict) -> dict:
    """As chaves a promover para metadata a partir de UMA linha do CSV. Funcao pura.

    Chave cujo valor e vazio/zero fica FORA do patch em vez de entrar como 0 ou "".
    Motivo: quem consome (o renderizador do template) checa presenca — `produto_top1`
    ausente cai no texto sem produto, `produto_top1` igual a "" renderizaria a frase
    "voce levava  — hoje ele esta ..." com um buraco no meio. Um zero em
    `pedidos_faturados` tambem e informacao falsa: o CSV traz 0 tanto para "nunca
    faturou" quanto para "coluna vazia", e os 103 leads `lead_sem_compra` da coorte
    nao devem ganhar historico nenhum.
    """
    patch: dict = {"bling_snapshot": SNAPSHOT}

    produto = (linha.get("produto_top1") or "").strip()
    if produto:
        patch["produto_top1"] = produto
        qtd = transform.parse_inteiro(linha.get("qtd_top1"))
        if qtd > 0:
            patch["produto_top1_qtd"] = qtd

    local = cidade_uf(linha)
    if local:
        patch["cidade_uf"] = local

    ticket = transform.parse_numero(linha.get("ticket_medio"))
    if ticket > 0:
        # round(2): o CSV ja vem com 2 casas, mas o float da divisao BR->US pode
        # trazer 3207.0000000000005 e isso viraria ruido no jsonb.
        patch["ticket_medio"] = round(ticket, 2)

    pedidos = transform.parse_inteiro(linha.get("pedidos_faturados"))
    if pedidos > 0:
        patch["pedidos_faturados"] = pedidos

    dias = transform.parse_inteiro(linha.get("dias_sem_comprar"))
    if dias > 0:
        patch["dias_sem_comprar"] = dias

    # formatar_data devolve '' para a sentinela '0000-00-00' do Bling e para lixo;
    # aqui queremos ISO (o resto do metadata usa ISO, ver `ultima_compra`), entao
    # so usamos a funcao como VALIDADOR e gravamos a string original.
    iso = (linha.get("ultima_compra") or "").strip()[:10]
    if transform.formatar_data(iso):
        patch["data_ultima_compra"] = iso

    return patch


def diferenca(metadata: dict, patch: dict) -> dict:
    """So as chaves do patch que o lead ainda nao tem, ou tem com valor diferente.

    Evita gerar 1.208 UPDATEs numa segunda execucao — e faz o relatorio do dry-run
    dizer a verdade sobre o que MUDA, nao sobre o que existe.
    """
    atual = metadata or {}
    return {k: v for k, v in patch.items() if atual.get(k) != v}


# ── Escrita ─────────────────────────────────────────────────────────────────
def _escapar(valor: str) -> str:
    return valor.replace("'", "''")


def sql_update(pares: list[tuple[str, dict]]) -> str:
    """UPDATE em lote: `metadata || patch`, um statement para N leads.

    O `||` de jsonb e merge raso e do lado direito ganha — exatamente o que
    queremos: as 10 chaves da importacao sobrevivem intactas e so as nossas sao
    escritas. Um `SET metadata = '<json>'` apagaria id_bling, lote e origem, e com
    eles o rollback do lote de 14/08.
    """
    valores = ",\n       ".join(
        "('%s', '%s')" % (lead_id, _escapar(json.dumps(patch, ensure_ascii=False, sort_keys=True)))
        for lead_id, patch in pares
    )
    return (
        "UPDATE leads l\n"
        "   SET metadata = COALESCE(l.metadata, '{}'::jsonb) || v.patch::jsonb\n"
        "  FROM (VALUES %s) AS v(id, patch)\n"
        " WHERE l.id = v.id::uuid;" % valores
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="GRAVA no banco. Sem esta flag o script so mostra.")
    ap.add_argument("--csv", default=str(CSV_PADRAO), help="caminho do CSV do Bling")
    ap.add_argument("--pipeline", default=PIPELINE_RECUPERACAO,
                    help="uuid do funil a backfillar, ou 'all' p/ todo lead com id_bling")
    ap.add_argument("--amostra", type=int, default=5, help="quantos leads mostrar")
    ap.add_argument("--lote", type=int, default=200, help="leads por UPDATE")
    args = ap.parse_args()

    caminho = Path(args.csv)
    if not caminho.exists():
        sys.exit(f"CSV nao encontrado: {caminho}")
    csv_por_id = carregar_csv(caminho)

    env = _env()
    if args.pipeline == "all":
        escopo = "todo lead do CRM com metadata.id_bling"
        where = "l.metadata->>'id_bling' IS NOT NULL"
        origem = "leads l"
    else:
        escopo = f"funil {args.pipeline}"
        where = (f"d.pipeline_id = '{_escapar(args.pipeline)}'::uuid "
                 "AND l.metadata->>'id_bling' IS NOT NULL")
        origem = "leads l JOIN deals d ON d.lead_id = l.id"
    leads = _sql(env, f"SELECT DISTINCT l.id, l.name, l.metadata FROM {origem} WHERE {where};")

    a_gravar: list[tuple[str, dict]] = []
    sem_match: list[dict] = []
    ja_ok = 0
    for lead in leads:
        id_bling = (lead.get("metadata") or {}).get("id_bling")
        linha = csv_por_id.get(str(id_bling or "").strip())
        if linha is None:
            sem_match.append(lead)
            continue
        delta = diferenca(lead.get("metadata") or {}, patch_do_lead(linha))
        if delta:
            a_gravar.append((lead["id"], delta))
        else:
            ja_ok += 1

    print(f"CSV: {caminho.name}  ({len(csv_por_id)} id_bling distintos)")
    print(f"escopo: {escopo}  ->  {len(leads)} leads")
    print(f"  sem linha no CSV : {len(sem_match)}")
    print(f"  ja em dia        : {ja_ok}")
    print(f"  A ATUALIZAR      : {len(a_gravar)}")

    cobertura = {chave: 0 for chave in CHAVES}
    for _id, patch in a_gravar:
        for chave in patch:
            cobertura[chave] = cobertura.get(chave, 0) + 1
    print("\n  cobertura por chave (entre os que seriam atualizados):")
    for chave in CHAVES:
        n = cobertura.get(chave, 0)
        pct = (100.0 * n / len(a_gravar)) if a_gravar else 0.0
        print(f"    {chave:<20} {n:>5}  ({pct:5.1f}%)")

    if sem_match:
        print(f"\n  ⚠️ {len(sem_match)} lead(s) sem linha no CSV — ficam como estao:")
        for lead in sem_match[:args.amostra]:
            print(f"    {lead['id']}  id_bling={(lead.get('metadata') or {}).get('id_bling')}"
                  f"  {lead.get('name')}")

    nomes = {lead["id"]: lead.get("name") for lead in leads}
    print(f"\n  amostra ({min(args.amostra, len(a_gravar))} de {len(a_gravar)}):")
    for lead_id, patch in a_gravar[:args.amostra]:
        print(f"    {nomes.get(lead_id)}")
        print(f"      {json.dumps(patch, ensure_ascii=False, sort_keys=True)}")

    if not args.apply:
        print("\n(dry-run — NADA foi gravado. Use --apply, com autorizacao do dono.)")
        return

    gravados = 0
    for inicio in range(0, len(a_gravar), args.lote):
        pedaco = a_gravar[inicio:inicio + args.lote]
        _sql(env, sql_update(pedaco))
        gravados += len(pedaco)
        print(f"gravados {gravados}/{len(a_gravar)}")
    print("pronto.")


if __name__ == "__main__":
    main()
