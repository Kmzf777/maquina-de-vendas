"""Sincroniza message_templates (banco) com o estado real dos templates na Meta.

Dry-run por padrao. So escreve com --apply.

── Por que este script existe ────────────────────────────────────────────────
`templates/service.py:create_template` grava a linha do banco UMA vez, no momento
da criacao, e nada nunca mais a atualiza. Duas consequencias medidas em 09/09/2026:

1. **O status congela em `pending`.** Um template aprovado pela Meta horas depois
   continua `pending` no banco para sempre. Quem criou pela API crua (como o
   `criar_templates.py` deste diretorio) nem linha tem.

2. **A categoria mente.** A Meta RECLASSIFICA templates: nesta conta, 28 de 28
   reclassificacoes foram UTILITY -> MARKETING. Hoje ha 26 templates do canal do
   Joao marcados `utility` no banco que ja sao MARKETING na Meta. Isso quebra
   qualquer calculo de custo — e e uma bomba-relogio em
   `follow_up/scheduler.py:1810-1828`, que CANCELA o job e levanta alerta
   `critical` quando o template de reabertura de janela nao e utility.

Rode este script antes de cada campanha, e de manha depois de criar templates.

Uso:
    python scripts/recuperacao/sync_templates.py                    # so mostra
    python scripts/recuperacao/sync_templates.py --apply            # grava
    python scripts/recuperacao/sync_templates.py --prefix recuperacao_ --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

API = "https://graph.facebook.com/v21.0"
RAIZ = Path(__file__).resolve().parents[2]

# Canal NUMERO JOAO — dono do funil Reativacao Bling e de onde o agente fala.
CANAL_JOAO = "a3a607b1-6bff-4370-8609-b275eef270dd"


def _env() -> dict[str, str]:
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
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def _meta_templates(env: dict[str, str]) -> list[dict]:
    waba = env.get("META_WABA_ID")
    token = env.get("META_ACCESS_TOKEN")
    if not waba or not token:
        sys.exit("META_WABA_ID / META_ACCESS_TOKEN ausentes")
    campos = "name,status,category,language,components,previous_category,rejected_reason,id"
    url = f"{API}/{waba}/message_templates?limit=200&fields={campos}"
    saida: list[dict] = []
    while url:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            dados = json.loads(resp.read())
        saida.extend(dados.get("data", []))
        url = (dados.get("paging") or {}).get("next")
    return saida


def _escapar(valor: str) -> str:
    return valor.replace("'", "''")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="grava no banco")
    ap.add_argument("--prefix", default="", help="so templates cujo nome comeca assim")
    ap.add_argument("--channel", default=CANAL_JOAO, help="channel_id para linhas novas")
    args = ap.parse_args()

    env = _env()
    na_meta = [t for t in _meta_templates(env) if t["name"].startswith(args.prefix)]
    nomes = ", ".join(f"'{_escapar(t['name'])}'" for t in na_meta) or "''"
    no_banco = {
        (linha["name"], linha["language"]): linha
        for linha in _sql(env, f"SELECT id, name, language, category, status, meta_template_id "
                               f"FROM message_templates WHERE name IN ({nomes});")
    }

    inserir: list[dict] = []
    atualizar: list[tuple[dict, dict]] = []
    for tpl in na_meta:
        # A Meta devolve o status em MAIUSCULA (APPROVED/PENDING/REJECTED); o banco
        # usa minuscula, seguindo o que create_template ja gravava.
        chave = (tpl["name"], tpl["language"])
        linha = no_banco.get(chave)
        if linha is None:
            inserir.append(tpl)
            continue
        novo_status = tpl["status"].lower()
        nova_cat = (tpl.get("category") or "").lower()
        if linha["status"] != novo_status or (linha["category"] or "").lower() != nova_cat:
            atualizar.append((linha, tpl))

    print(f"templates na Meta com prefixo {args.prefix!r}: {len(na_meta)}")
    print(f"  faltando no banco: {len(inserir)}")
    for tpl in inserir:
        print(f"    + {tpl['name']} [{tpl['category']}/{tpl['language']}] {tpl['status']}")
    print(f"  divergentes: {len(atualizar)}")
    for linha, tpl in atualizar:
        print(f"    ~ {tpl['name']}: status {linha['status']} -> {tpl['status'].lower()}"
              f" | category {linha['category']} -> {(tpl.get('category') or '').lower()}"
              + (f"   (a Meta reclassificou de {tpl['previous_category']})"
                 if tpl.get("previous_category") else ""))

    if not args.apply:
        print("\n(dry-run — nada gravado. Use --apply.)")
        return

    for tpl in inserir:
        componentes = _escapar(json.dumps(tpl.get("components") or [], ensure_ascii=False))
        _sql(env, f"""
            INSERT INTO message_templates
              (channel_id, name, language, requested_category, category, components,
               meta_template_id, status)
            VALUES ('{args.channel}', '{_escapar(tpl['name'])}', '{_escapar(tpl['language'])}',
                    '{_escapar(tpl.get('category') or '')}', '{_escapar((tpl.get('category') or '').lower())}',
                    '{componentes}'::jsonb, '{_escapar(str(tpl.get('id') or ''))}',
                    '{_escapar(tpl['status'].lower())}')
            ON CONFLICT DO NOTHING;
        """)
        print(f"inserido {tpl['name']}")

    for linha, tpl in atualizar:
        _sql(env, f"""
            UPDATE message_templates
               SET status = '{_escapar(tpl['status'].lower())}',
                   category = '{_escapar((tpl.get('category') or '').lower())}'
             WHERE id = '{linha['id']}';
        """)
        print(f"atualizado {tpl['name']}")


if __name__ == "__main__":
    main()
