"""Seed da tabela `products` (catálogo de grounding da IA) a partir do CSV de ops.

Lê o CSV exportado pela equipe (delimitador `;`) e insere os produtos na tabela
`products` do Supabase. É **idempotente**: produtos já presentes (mesma combinação
`sector` + `name`) são ignorados, então rodar de novo não duplica linhas.

Uso:
    python backend/scripts/seed_products.py [caminho_do_csv]

Sem argumento, usa o CSV padrão na raiz do repositório. O destino (Supabase) é o
mesmo do app: carrega `.env` (prod) — siga a convenção dos outros seeds do repo.
A coluna de fotos pode conter várias URLs separadas por `;` (entre aspas no CSV);
ela é limpa e normalizada para uma string única separada por `;`, no formato que o
serviço `app.agent.catalog` espera.
"""
import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.db.supabase import get_supabase  # noqa: E402

# Caminho padrão do CSV exportado por ops (raiz do repositório).
_DEFAULT_CSV = os.path.join(
    os.path.dirname(__file__), "..", "..", "cafe_canastra_simples (3) (1).csv"
)

# Valores que representam "vazio" em colunas opcionais (ops usa travessão).
_EMPTY_TOKENS = {"", "-", "—", "–", "n/a", "na"}

# ---------------------------------------------------------------------------
# Atacado Outbound — tabela de preços agressiva da prospecção ativa
# ---------------------------------------------------------------------------
# O funil outbound (valeria_outbound) usa preços mais baixos que o inbound. Em vez
# de hardcodar no prompt (risco de alucinação), o banco vira a fonte de verdade:
# clonamos os produtos de "Atacado" para o setor "Atacado Outbound", aplicando o
# preço outbound apenas onde há divergência. Produtos sem override mantêm o preço
# padrão — assim o outbound enxerga o catálogo completo, só que com a tabela certa.
_OUTBOUND_ATACADO_SECTOR = "Atacado Outbound"

# name (exato, como no CSV) -> price_formatted outbound
_OUTBOUND_PRICE_OVERRIDES = {
    "Canastra Clássico — Moído 250g": "R$ 27,70",
    "Canastra Clássico — Moído 500g": "R$ 46,70",
    "Canastra Clássico — Em Grãos 250g": "R$ 29,70",
    "Canastra Clássico — Em Grãos 500g": "R$ 48,70",
    "Canastra Clássico — Em Grãos 1kg": "R$ 88,70",
    "Canastra Suave — Moído 250g": "R$ 27,70",
    "Canastra Suave — Moído 500g": "R$ 46,70",
    "Canastra Suave — Em Grãos 250g": "R$ 29,70",
    "Canastra Suave — Em Grãos 500g": "R$ 48,70",
    "Canastra Suave — Em Grãos 1kg": "R$ 88,70",
    "Canastra Canela — Moído 250g": "R$ 27,70",
    "Microlote — Moído 250g": "R$ 31,70",
    "Microlote — Em Grãos 250g": "R$ 31,70",
    "Drip Coffee Canastra Suave — Display 10 sachês": "R$ 24,70",
    "Cápsula Canastra Clássico — Display 10 cápsulas": "R$ 17,70",
    "Cápsula Canastra Canela — Display 10 cápsulas": "R$ 17,70",
    "Granel Canastra Suave — 2kg em grãos": "R$ 155,70",
    "Granel Canastra Clássico — 2kg em grãos": "R$ 155,70",
}


def _build_outbound_atacado(products: list[dict]) -> list[dict]:
    """Clona os produtos de 'Atacado' para o setor 'Atacado Outbound'.

    Aplica o preço outbound onde há divergência (ver _OUTBOUND_PRICE_OVERRIDES);
    os demais herdam o preço padrão. Avisa se algum override não casou com nenhum
    produto (proteção contra erro de digitação no mapa).
    """
    atacado = [p for p in products if p["sector"] == "Atacado"]
    catalog_names = {p["name"] for p in atacado}
    for name in _OUTBOUND_PRICE_OVERRIDES:
        if name not in catalog_names:
            print(f"  [aviso] override outbound sem produto correspondente: {name!r}")

    clones: list[dict] = []
    for p in atacado:
        clone = dict(p)
        clone["sector"] = _OUTBOUND_ATACADO_SECTOR
        if p["name"] in _OUTBOUND_PRICE_OVERRIDES:
            clone["price_formatted"] = _OUTBOUND_PRICE_OVERRIDES[p["name"]]
        clones.append(clone)
    return clones


def _clean(value: str | None) -> str | None:
    """Normaliza célula: strip e converte tokens vazios/travessão em None."""
    if value is None:
        return None
    v = value.strip()
    return None if v.lower() in _EMPTY_TOKENS else v


def _clean_image_urls(raw: str | None) -> str | None:
    """Normaliza a coluna de fotos: URLs separadas por `;`, sem espaços/vazios."""
    if not raw:
        return None
    urls = [u.strip() for u in raw.split(";") if u.strip()]
    return ";".join(urls) if urls else None


def _parse_rows(csv_path: str) -> list[dict]:
    """Faz o parse do CSV (delimitador `;`) ignorando linhas em branco."""
    products: list[dict] = []
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";", quotechar='"')
        for row in reader:
            sector = _clean(row.get("Setor"))
            name = _clean(row.get("Produto"))
            if not sector or not name:
                continue  # linha de preenchimento vazia
            products.append(
                {
                    "sector": sector,
                    "name": name,
                    "price_formatted": _clean(row.get("Preço (R$)")),
                    "min_lot": _clean(row.get("Lote Mínimo")),
                    "description": _clean(row.get("Descrição")),
                    "image_urls": _clean_image_urls(row.get("Foto (URL)")),
                    "is_active": True,
                }
            )
    return products


def seed(csv_path: str) -> None:
    products = _parse_rows(csv_path)
    outbound = _build_outbound_atacado(products)
    products += outbound
    print(
        f"CSV parseado: {len(products)} produtos válidos em {csv_path!r} "
        f"(inclui {len(outbound)} de '{_OUTBOUND_ATACADO_SECTOR}')"
    )

    sb = get_supabase()

    # Idempotência: descobre o que já existe (sector, name) e insere só o que falta.
    existing = sb.table("products").select("sector,name").execute().data or []
    seen = {(r["sector"], r["name"]) for r in existing}

    to_insert = [p for p in products if (p["sector"], p["name"]) not in seen]
    skipped = len(products) - len(to_insert)

    if not to_insert:
        print(f"Nada a inserir — {skipped} produtos já presentes. Banco atualizado.")
        return

    result = sb.table("products").insert(to_insert).execute()
    inserted = len(result.data or [])
    print(f"Inseridos: {inserted} | Ignorados (já existiam): {skipped}")

    by_sector: dict[str, int] = {}
    for p in to_insert:
        by_sector[p["sector"]] = by_sector.get(p["sector"], 0) + 1
    for sector, count in sorted(by_sector.items()):
        print(f"  - {sector}: {count}")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_CSV
    if not os.path.exists(path):
        sys.exit(f"CSV não encontrado: {path!r}")
    seed(path)
