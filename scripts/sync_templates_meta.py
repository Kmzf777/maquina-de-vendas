"""Traz `message_templates` de volta ao que a Meta diz. O espelho e escrito UMA VEZ.

A AVARIA QUE ESTE SCRIPT CORRIGE
───────────────────────────────────────────────────────────────────────────────
Medida em 29/09/2026, simulando ligar as esteiras de prospeccao:

    5 dos 11 templates de utilidade estavam 'pending' na tabela LOCAL
    e 'approved' na Meta. As tres esteiras ficariam bloqueadas.

`message_templates` e um ESPELHO da Meta, mas nada nunca o atualiza. Ele e escrito:

  1. na CRIACAO do template (os scripts create_templates_*), com o status daquele
     instante — que e sempre `pending`;
  2. pelo auto-sync de `templates/preflight.py`, que faz `insert` e so quando a Meta
     ja diz APPROVED — ou seja, serve para linha AUSENTE, nao para linha existente
     com status velho;
  3. por `broadcast/worker.py`, no mesmo formato.

Nenhum dos tres atualiza uma linha quando a Meta muda o status DEPOIS. E ela muda
sempre: aprovacao leva minutos a horas, e a Meta ainda RECLASSIFICA categoria depois
de aprovar (medido: 10 dos 25 templates de 28/09 mudaram de categoria na revisao).

QUEM LE ESSE ESPELHO, E SE ENGANA JUNTO
───────────────────────────────────────────────────────────────────────────────
  · `follow_up/api.py::_status_dos_templates` — a trava de ativacao das esteiras.
    Le so a tabela local, sem fallback para a Meta, e RECUSA ligar a cadencia.
  · `/api/templates` (a rota Next) — o dropdown que escolhe o texto de cada toque.
    Um template aprovado depois da criacao nem aparece para ser escolhido.
  · `campaigns/validation.py` — a regra 12 do builder, mesma pergunta.

O QUE ESTE SCRIPT FAZ, E O QUE NAO FAZ
───────────────────────────────────────────────────────────────────────────────
FAZ: atualiza `status` e `category` das linhas que JA EXISTEM, pelo nome, em todos
os canais (o espelho guarda uma linha por canal — Arthur, Valeria, Joao — e o estado
na Meta e o mesmo para as tres, porque o template vive numa WABA so).

NAO FAZ: nao cria linha para template que a Meta tem e o banco nao. Criar exigiria
escolher `channel_id`, e essa e uma decisao de quem opera, nao deste script. Os
ausentes sao LISTADOS no fim para quem quiser resolve-los.

NAO FAZ: nao apaga nada, nunca.

Uso:
    python scripts/sync_templates_meta.py                 # dry-run: mostra o diff
    python scripts/sync_templates_meta.py --aplicar       # grava
    python scripts/sync_templates_meta.py --prefixo joao  # so os que comecam assim
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

WABA_ID = os.environ.get("META_WABA_ID")
TOKEN = os.environ.get("META_ACCESS_TOKEN")
API = "https://graph.facebook.com/v21.0"


def _da_meta() -> dict[str, dict]:
    """Todos os templates da WABA, por nome. Pagina ate o fim."""
    por_nome: dict[str, dict] = {}
    url = (f"{API}/{WABA_ID}/message_templates"
           f"?fields=name,status,category,language,id&limit=200")
    while url:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            corpo = json.loads(resp.read().decode("utf-8"))
        for t in corpo.get("data", []):
            # Nome + idioma identificam o template na Meta; o espelho local e por
            # nome, entao a ultima variante de idioma vence. Na pratica so ha pt_BR.
            por_nome[t["name"]] = t
        url = (corpo.get("paging") or {}).get("next")
    return por_nome


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if not WABA_ID or not TOKEN:
        print("Defina META_WABA_ID e META_ACCESS_TOKEN no ambiente.")
        return 1

    prefixo = None
    if "--prefixo" in sys.argv:
        prefixo = sys.argv[sys.argv.index("--prefixo") + 1]

    from app.db.supabase import get_supabase  # noqa: E402

    sb = get_supabase()
    meta = _da_meta()
    print(f"Meta: {len(meta)} templates.")

    consulta = sb.table("message_templates").select("id, name, status, category, channel_id")
    if prefixo:
        consulta = consulta.like("name", f"{prefixo}%")
    locais = consulta.execute().data or []
    print(f"Banco local: {len(locais)} linhas"
          + (f" (prefixo '{prefixo}')" if prefixo else "")
          + f", {len({x['name'] for x in locais})} nomes distintos.\n")

    # A Meta grava MAIUSCULO, o espelho local grava minusculo. Comparar normalizado —
    # senao todo template "aprovado" pareceria divergente e o script reescreveria tudo.
    def _norm(v):
        return (v or "").strip().lower()

    mudancas = []
    for linha in locais:
        t = meta.get(linha["name"])
        if not t:
            continue
        novo_status = _norm(t.get("status"))
        nova_cat = _norm(t.get("category"))
        if _norm(linha.get("status")) == novo_status and _norm(linha.get("category")) == nova_cat:
            continue
        mudancas.append((linha, novo_status, nova_cat))

    if not mudancas:
        print("Nada a atualizar — o espelho ja bate com a Meta.")
    else:
        print(f"{len(mudancas)} linha(s) divergente(s):\n")
        vistos = set()
        for linha, st, cat in mudancas:
            chave = (linha["name"], _norm(linha.get("status")), _norm(linha.get("category")))
            if chave in vistos:
                continue
            vistos.add(chave)
            n_linhas = sum(1 for m in mudancas if m[0]["name"] == linha["name"])
            print(f"   {linha['name']:<42} "
                  f"{_norm(linha.get('category'))}/{_norm(linha.get('status'))}"
                  f"  ->  {cat}/{st}   ({n_linhas} canal/canais)")

    ausentes = sorted(n for n in meta
                      if n not in {x["name"] for x in locais}
                      and (not prefixo or n.startswith(prefixo)))
    if ausentes:
        print(f"\n{len(ausentes)} template(s) na Meta SEM linha local "
              f"(este script nao cria — ver cabecalho):")
        for n in ausentes:
            print(f"   {n:<42} {_norm(meta[n].get('category'))}/{_norm(meta[n].get('status'))}")

    if "--aplicar" not in sys.argv:
        print("\n(dry-run) Use --aplicar para gravar.")
        return 0

    if not mudancas:
        return 0

    erros = 0
    for linha, st, cat in mudancas:
        try:
            sb.table("message_templates").update(
                {"status": st, "category": cat}
            ).eq("id", linha["id"]).execute()
        except Exception as exc:  # noqa: BLE001
            erros += 1
            print(f"   FALHOU {linha['name']} (canal {str(linha.get('channel_id'))[:8]}): {exc}")

    print(f"\n{len(mudancas) - erros} linha(s) atualizada(s), {erros} falha(s).")
    return 0 if not erros else 1


if __name__ == "__main__":
    raise SystemExit(main())
