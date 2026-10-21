"""Consultas do agente nos ESPELHOS `bling_*` (nunca na API do Bling).

Tudo síncrono sobre `get_supabase()` (quem chama de rota async usa
`asyncio.to_thread`) e sempre recortado por `account`: as duas contas têm
sequências de id independentes, o mesmo número aponta para cadastros diferentes.
"""
from app.bling.router import _termo_seguro
from app.db.supabase import get_supabase

LIMITE_CLIENTES = 10
LIMITE_PRODUTOS = 15
# A partir de quantos dígitos o termo é tratado como documento/telefone.
_MIN_DIGITOS = 8

_COLS_CONTATO = "id, nome, fantasia, doc_digits, telefone_e164, celular_e164, situacao, endereco"
_COLS_PRODUTO = "id, codigo, nome, preco, unidade, saldo_virtual, situacao"

# Formas de pagamento: finalidade 1 pagamentos, 2 recebimentos, 3 ambos.
_FINALIDADES = {"venda": (2, 3), "compra": (1, 3)}
# `bling_sellers.situacao` é texto cru do Bling. Some só o que é sabidamente inativo.
_VENDEDOR_INATIVO = {"I", "E", "0", "INATIVO"}


def _dados(res) -> list[dict]:
    return getattr(res, "data", None) or []


def formatar_documento(digitos: str | None) -> str | None:
    if not digitos:
        return None
    d = "".join(ch for ch in str(digitos) if ch.isdigit())
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    return d or None


def _cliente_saida(c: dict) -> dict:
    endereco = c.get("endereco") if isinstance(c.get("endereco"), dict) else {}
    return {
        "id": int(c["id"]),
        "nome": c.get("nome") or "",
        "fantasia": c.get("fantasia") or None,
        "documento": formatar_documento(c.get("doc_digits")),
        "telefone": c.get("celular_e164") or c.get("telefone_e164") or None,
        "cidade": (endereco or {}).get("municipio") or None,
        "uf": (endereco or {}).get("uf") or None,
    }


def clientes(conta: str, q: str | None) -> list[dict]:
    termo = (q or "").strip()
    if not termo:
        return []
    digitos = "".join(ch for ch in termo if ch.isdigit())
    query = (get_supabase().table("bling_contacts").select(_COLS_CONTATO)
             .eq("account", conta).eq("situacao", "A"))
    if len(digitos) >= _MIN_DIGITOS:
        alvo = f"%{digitos}%"
        query = query.or_(f"doc_digits.ilike.{alvo},telefone_e164.ilike.{alvo},"
                          f"celular_e164.ilike.{alvo}")
    else:
        seguro = _termo_seguro(termo)
        if not seguro:
            return []
        alvo = f"%{seguro}%"
        query = query.or_(f"nome.ilike.{alvo},fantasia.ilike.{alvo}")
    linhas = _dados(query.order("nome").limit(LIMITE_CLIENTES).execute())
    vistos, saida = set(), []
    for c in linhas:
        if c.get("id") in vistos:
            continue
        vistos.add(c.get("id"))
        saida.append(_cliente_saida(c))
    return saida[:LIMITE_CLIENTES]


def produtos(conta: str, q: str | None) -> list[dict]:
    termo = _termo_seguro((q or "").strip())
    if not termo:
        return []
    alvo = f"%{termo}%"
    linhas = _dados(get_supabase().table("bling_products").select(_COLS_PRODUTO)
                    .eq("situacao", "A").eq("account", conta)
                    .or_(f"nome.ilike.{alvo},codigo.ilike.{alvo}")
                    .order("nome").limit(LIMITE_PRODUTOS).execute())
    return [{"id": int(p["id"]), "codigo": p.get("codigo"), "nome": p.get("nome") or "",
             "preco": p.get("preco"), "unidade": p.get("unidade") or "UN",
             "saldo": p.get("saldo_virtual")} for p in linhas]


def _ativo(vendedor: dict) -> bool:
    return str(vendedor.get("situacao") or "").strip().upper() not in _VENDEDOR_INATIVO


def vendedores(conta: str) -> list[dict]:
    linhas = _dados(get_supabase().table("bling_sellers").select("id, nome, situacao")
                    .eq("account", conta).order("nome").execute())
    return [{"id": int(v["id"]), "nome": v.get("nome") or ""} for v in linhas if _ativo(v)]


def formas_pagamento(conta: str, finalidade: str) -> list[dict]:
    aceitas = _FINALIDADES.get(finalidade, _FINALIDADES["venda"])
    linhas = _dados(get_supabase().table("bling_payment_methods").select("*")
                    .eq("account", conta).order("descricao").execute())
    return [{"id": int(m["id"]), "descricao": m.get("descricao") or ""}
            for m in linhas if m.get("situacao") == 1 and m.get("finalidade") in aceitas]


def _um(tabela: str, colunas: str, conta: str, id_: int) -> dict | None:
    linhas = _dados(get_supabase().table(tabela).select(colunas)
                    .eq("account", conta).eq("id", int(id_)).limit(1).execute())
    return linhas[0] if linhas else None


def cliente(conta: str, id_: int) -> dict | None:
    return _um("bling_contacts", _COLS_CONTATO, conta, id_)


def produto(conta: str, id_: int) -> dict | None:
    """Produto da conta, ATIVO OU NÃO: quem chama decide o que fazer com inativo."""
    return _um("bling_products", _COLS_PRODUTO, conta, id_)


def vendedor(conta: str, id_: int) -> dict | None:
    v = _um("bling_sellers", "id, nome, situacao", conta, id_)
    return v if v and _ativo(v) else None


def forma(conta: str, id_: int) -> dict | None:
    """Forma de pagamento ativa da conta (qualquer finalidade)."""
    f = _um("bling_payment_methods", "*", conta, id_)
    return f if f and f.get("situacao") == 1 else None


def contato_por_documento(conta: str, digitos: str) -> dict | None:
    linhas = _dados(get_supabase().table("bling_contacts").select(_COLS_CONTATO)
                    .eq("account", conta).eq("doc_digits", digitos).limit(1).execute())
    return linhas[0] if linhas else None
