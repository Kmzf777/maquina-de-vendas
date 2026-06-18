"""Catálogo de produtos (grounding dinâmico da IA).

Lê a tabela `products` do Supabase e formata o catálogo do funil solicitado em
Markdown legível, pronto para ser injetado nas System Instructions do Gemini.

Princípios:
- **Fail-open**: qualquer erro (DB fora do ar, tabela ausente, etc.) retorna ""
  em vez de levantar — o agente NUNCA pode quebrar por causa do catálogo.
- **Tolerância a digitação de ops**: `sector` é comparado de forma normalizada
  (sem acento, caixa baixa, espaço/hífen → underscore), então "Private Label",
  "private_label" e "Atacado" casam com a stage/funil correspondente.
- **Cache TTL curto**: evita um hit no banco a cada turno/transição de stage.
"""

import logging
import time
import unicodedata

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

# Funis (setores) que possuem catálogo comercial. `secretaria` é o stage de entrada
# e não recebe catálogo. `atacado_outbound` é o setor com a tabela de preços agressiva
# usada na prospecção ativa (valeria_outbound) — ver _resolve_sector.
_KNOWN_FUNNELS = frozenset(
    {"atacado", "atacado_outbound", "private_label", "exportacao", "consumo"}
)

# Cache em memória: {funnel_normalizado: (timestamp, markdown)}. TTL curto porque
# ops pode atualizar o CSV a qualquer momento; 5 min é um bom equilíbrio entre
# frescor e não martelar o banco a cada mensagem.
_CACHE_TTL_SECONDS = 300
_cache: dict[str, tuple[float, str]] = {}


def _normalize(value: str | None) -> str:
    """Normaliza para comparação: sem acento, minúsculo, espaço/hífen → underscore."""
    if not value:
        return ""
    nfkd = unicodedata.normalize("NFKD", value)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    return "_".join(no_accents.lower().split())  # colapsa espaços e troca por '_'


def _clean_image_urls(raw: str | None) -> list[str]:
    """Separa as URLs de imagem (texto com ';') e remove vazios/espaços."""
    if not raw:
        return []
    return [u.strip() for u in raw.split(";") if u.strip()]


def _format_products(products: list[dict]) -> str:
    """Formata uma lista de produtos em Markdown legível para o prompt."""
    blocks: list[str] = []
    for p in products:
        name = (p.get("name") or "").strip() or "Produto sem nome"
        lines = [f"- **{name}**"]
        if p.get("price_formatted"):
            lines.append(f"  - Preço: {p['price_formatted']}")
        if p.get("min_lot"):
            lines.append(f"  - Lote mínimo: {p['min_lot']}")
        if p.get("description"):
            lines.append(f"  - Descrição: {p['description']}")
        urls = _clean_image_urls(p.get("image_urls"))
        if urls:
            lines.append(f"  - Fotos: {', '.join(urls)}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def _fetch_active_products() -> list[dict]:
    """Busca todos os produtos ativos do Supabase. Levanta em erro (caller trata)."""
    sb = get_supabase()
    result = (
        sb.table("products")
        .select("sector,name,price_formatted,min_lot,description,image_urls")
        .eq("is_active", True)
        .execute()
    )
    return result.data or []


def _resolve_sector(funnel_name: str | None, prompt_key: str | None) -> str:
    """Resolve a stage + perfil de prompt no `sector` correspondente no banco.

    O atacado de prospecção ativa (`valeria_outbound`) tem uma tabela de preços
    própria (mais agressiva), persistida no setor `Atacado Outbound`. Para todos
    os demais casos, o setor é a própria stage normalizada.
    """
    funnel = _normalize(funnel_name)
    if funnel == "atacado" and _normalize(prompt_key) == "valeria_outbound":
        return "atacado_outbound"
    return funnel


def get_products_by_funnel(funnel_name: str, prompt_key: str | None = None) -> str:
    """Retorna o catálogo do funil em Markdown, ou "" se não houver/erro.

    `funnel_name` é a stage da conversa (atacado, private_label, exportacao,
    consumo). `prompt_key` distingue inbound/outbound — o atacado outbound usa o
    setor `Atacado Outbound`. Filtra `products` por `is_active=true` e `sector`
    casando com o funil resolvido (comparação normalizada). Fail-open: qualquer
    exceção → "".
    """
    funnel = _resolve_sector(funnel_name, prompt_key)
    if not funnel or funnel not in _KNOWN_FUNNELS:
        return ""

    now = time.monotonic()
    cached = _cache.get(funnel)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    try:
        all_active = _fetch_active_products()
    except Exception as exc:  # fail-open — nunca quebrar o agente por causa do catálogo
        logger.warning("get_products_by_funnel: falha ao ler catálogo (%s): %s", funnel, exc)
        return ""

    matching = [p for p in all_active if _normalize(p.get("sector")) == funnel]
    markdown = _format_products(matching) if matching else ""
    _cache[funnel] = (now, markdown)
    return markdown


def clear_cache() -> None:
    """Limpa o cache em memória (útil para testes e invalidação manual)."""
    _cache.clear()
