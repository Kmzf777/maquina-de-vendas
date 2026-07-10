# backend/app/templates/preflight.py
"""Pre-flight de template para disparo em massa (wartime T3, 10/07).

Por que existe: o /start de broadcast validava billing e pendências, mas ZERO
validação de template — nome inexistente, locale divergente do aprovado
(armadilha `automacao_valeria_to_joao`: só existe em `en`, pedir pt_BR dava 404)
e contagem de params errada (armadilha `reativacao_*`: 5 params aprovados vs 1
enviado → #132000) só explodiam NO MEIO da campanha, lead a lead, queimando a
lista inteira. Este módulo valida ANTES do primeiro envio.

Contrato: `validate_template_for_broadcast(...)` retorna uma LISTA de erros
legíveis em PT-BR (vazia = aprovado). TODOS os problemas encontrados são
retornados de uma vez — o operador corrige tudo numa passada, não um erro por
tentativa.

Fail-closed com escape hatch: se o template não puder ser verificado (banco E
Meta API indisponíveis), o disparo é BLOQUEADO com erro explicando — disparo em
massa às cegas é exatamente o incidente que queremos matar. O kill-switch
`PREFLIGHT_TEMPLATE=off` (env, lido a cada chamada) desliga o gate inteiro sem
deploy, padrão do repo para reversão de emergência.
"""
import logging
import os
import re
from typing import Any

import httpx

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_META_API_BASE = "https://graph.facebook.com/v21.0"

# Placeholder do BODY aprovado: {{1}}..{{n}} (posicional) ou {{nome}} (nomeado).
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([^{}\s]+)\s*\}\}")

# Formatos de header que exigem __header_url__ no builder do broadcast
# (ver _build_template_components em app/broadcast/worker.py).
_MEDIA_HEADER_FORMATS = ("IMAGE", "VIDEO", "DOCUMENT")


def _preflight_disabled() -> bool:
    """Kill-switch lido a cada chamada (mudança de env não exige restart de teste)."""
    return os.environ.get("PREFLIGHT_TEMPLATE", "on").strip().lower() in ("off", "0", "false")


def _component_type(component: dict) -> str:
    return str(component.get("type") or "").upper()


def _body_text(components: list) -> str:
    body = next((c for c in components or [] if _component_type(c) == "BODY"), None)
    return (body or {}).get("text") or ""


def _header_component(components: list) -> dict | None:
    return next((c for c in components or [] if _component_type(c) == "HEADER"), None)


def _lookup_local(template_name: str) -> list[dict] | None:
    """Todas as linhas locais do template (uma por idioma). None = banco indisponível.

    Lista vazia = o banco respondeu e o template NÃO existe localmente — distinção
    importante para o fail-closed (banco fora ≠ template ausente).
    """
    try:
        sb = get_supabase()
        result = (
            sb.table("message_templates")
            .select("name, language, status, components")
            .eq("name", template_name)
            .execute()
        )
        return result.data or []
    except Exception as exc:
        logger.warning("[PREFLIGHT] lookup local falhou p/ '%s': %s", template_name, exc)
        return None


async def _lookup_meta(template_name: str, channel: dict | None) -> list[dict] | None:
    """Variantes do template na Meta API (uma por idioma). None = não foi possível verificar.

    Reusa o padrão de fallback+auto-sync de `_render_template_body` (broadcast/worker.py):
    o que a Meta devolver aprovado é semeado em message_templates (best-effort) para o
    próximo preflight/render resolver localmente.
    """
    if not channel:
        return None
    config = channel.get("provider_config") or {}
    waba_id = config.get("waba_id") or os.environ.get("META_WABA_ID", "")
    access_token = config.get("access_token") or os.environ.get("META_ACCESS_TOKEN", "")
    if not waba_id or not access_token:
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{_META_API_BASE}/{waba_id}/message_templates",
                params={"name": template_name},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
    except Exception as exc:
        logger.warning("[PREFLIGHT] lookup Meta falhou p/ '%s': %s", template_name, exc)
        return None

    # O filtro `name` da Meta é por substring — mantém só o match exato.
    variants = [t for t in data if t.get("name") == template_name]

    # Auto-sync best-effort dos aprovados p/ o banco local (paridade com o worker).
    for t in variants:
        if str(t.get("status") or "").upper() != "APPROVED":
            continue
        try:
            sb = get_supabase()
            sb.table("message_templates").insert({
                "channel_id": channel.get("id"),
                "name": template_name,
                "language": t.get("language", "pt_BR"),
                "requested_category": t.get("category", "UTILITY"),
                "category": t.get("category", "UTILITY"),
                "components": t.get("components", []),
                "meta_template_id": t.get("id"),
                "status": "approved",
            }).execute()
            logger.info("[PREFLIGHT] Auto-sync do template '%s' (%s) p/ o banco local", template_name, t.get("language"))
        except Exception as sync_err:
            logger.warning("[PREFLIGHT] Auto-sync falhou p/ '%s': %s", template_name, sync_err)

    return variants


def _normalize_variants(rows: list[dict], source: str) -> list[dict]:
    """Uniformiza linha local / payload Meta em {language, status, components}."""
    out = []
    for row in rows:
        out.append({
            "language": row.get("language") or "",
            "status": str(row.get("status") or "").lower(),  # local: 'approved'; Meta: 'APPROVED'
            "components": row.get("components") or [],
            "source": source,
        })
    return out


def _check_body_params(body_text: str, template_variables: dict) -> list[str]:
    """Checagem 3: placeholders do BODY aprovado × variáveis configuradas no broadcast.

    Compara com a semântica REAL do builder (_build_template_components): chaves `__*`
    e a legada 'components' são reservadas; `__params_type__` ausente = 'named'.
    """
    errors: list[str] = []
    placeholders = _PLACEHOLDER_RE.findall(body_text)
    positional = bool(placeholders) and all(p.isdigit() for p in placeholders)
    declared_type = (template_variables or {}).get("__params_type__", "named")

    body_vars = {
        k: v for k, v in (template_variables or {}).items()
        if not str(k).startswith("__") and k != "components"
    }

    if not placeholders:
        if body_vars:
            errors.append(
                f"o BODY aprovado não tem placeholders, mas o disparo define "
                f"{len(body_vars)} variável(is) ({', '.join(sorted(map(str, body_vars)))}) — "
                f"a Meta rejeita parâmetros extras (#132000)"
            )
        return errors

    if positional:
        expected = sorted({int(p) for p in placeholders})
        if declared_type != "positional":
            errors.append(
                f"o BODY aprovado usa placeholders POSICIONAIS ({{{{1}}}}..{{{{{expected[-1]}}}}}), "
                f"mas as variáveis do disparo estão configuradas como '{declared_type}' "
                f"(__params_type__) — o envio sairia com formato errado"
            )
        if len(body_vars) != len(expected):
            errors.append(
                f"o BODY aprovado exige {len(expected)} parâmetro(s) posicional(is), "
                f"mas o disparo define {len(body_vars)} — contagem divergente causa erro Meta #132000"
            )
    else:
        expected_names = {p for p in placeholders}
        if declared_type == "positional":
            errors.append(
                f"o BODY aprovado usa placeholders NOMEADOS ({', '.join(sorted(expected_names))}), "
                f"mas as variáveis do disparo estão configuradas como 'positional' "
                f"(__params_type__) — o envio sairia com formato errado"
            )
        provided_names = {str(k) for k in body_vars}
        missing = expected_names - provided_names
        extra = provided_names - expected_names
        if missing:
            errors.append(
                f"faltam variável(is) nomeada(s) exigida(s) pelo BODY aprovado: "
                f"{', '.join(sorted(missing))}"
            )
        if extra:
            errors.append(
                f"variável(is) não existente(s) no BODY aprovado: {', '.join(sorted(extra))} — "
                f"a Meta rejeita parâmetros desconhecidos (#132000)"
            )
    return errors


def _check_header(components: list, template_variables: dict) -> list[str]:
    """Checagem 4: header do template aprovado × configuração de mídia do disparo."""
    errors: list[str] = []
    header = _header_component(components)
    header_format = str((header or {}).get("format") or "").upper()
    provided_type = str((template_variables or {}).get("__header_type__") or "").upper()
    provided_url = (template_variables or {}).get("__header_url__") or ""

    if header_format in _MEDIA_HEADER_FORMATS:
        if not provided_url:
            errors.append(
                f"o template aprovado tem header de mídia ({header_format}), mas o disparo "
                f"não define __header_url__ — a Meta exige o link da mídia no envio"
            )
        if provided_type and provided_type != header_format:
            errors.append(
                f"tipo de header divergente: o template aprovado usa {header_format}, "
                f"mas o disparo está configurado como {provided_type}"
            )
    elif header_format == "TEXT":
        if _PLACEHOLDER_RE.search((header or {}).get("text") or ""):
            errors.append(
                "o template aprovado tem header TEXT com placeholder — o builder de "
                "broadcast atual não envia parâmetros de header de texto; use um "
                "template sem variável no header"
            )
        if provided_url or provided_type in _MEDIA_HEADER_FORMATS:
            errors.append(
                "o disparo define mídia de header (__header_url__/__header_type__), "
                "mas o template aprovado tem header de TEXTO — a mídia seria rejeitada"
            )
    else:  # sem header no template
        if provided_url or provided_type in _MEDIA_HEADER_FORMATS:
            errors.append(
                "o disparo define mídia de header (__header_url__/__header_type__), "
                "mas o template aprovado NÃO tem header — a Meta rejeita o componente extra"
            )
    return errors


async def validate_template_for_broadcast(
    template_name: str,
    template_language_code: str,
    template_variables: dict | None,
    channel: dict | None,
) -> list[str]:
    """Valida o template de um broadcast ANTES do primeiro envio.

    Retorna lista de erros legíveis em PT-BR (vazia = liberado). Checagens:
      1. existência/aprovação (message_templates local, fallback Meta API + auto-sync);
      2. locale do broadcast == language de uma variante aprovada;
      3. params do BODY (posicional/nomeado/__params_type__) × template_variables;
      4. header de mídia × __header_url__/__header_type__.

    Fail-closed: sem conseguir verificar (banco E Meta fora) → erro bloqueante.
    Kill-switch: PREFLIGHT_TEMPLATE=off → retorna [] (gate desligado, sem deploy).
    """
    if _preflight_disabled():
        logger.warning(
            "[PREFLIGHT] PREFLIGHT_TEMPLATE=off — validação de template PULADA p/ '%s'",
            template_name,
        )
        return []

    template_name = (template_name or "").strip()
    template_variables = template_variables or {}
    if not template_name:
        return ["broadcast sem template_name definido — nada a enviar"]

    # ── Lookup: local primeiro, Meta como fallback/complemento ──────────────
    local_rows = _lookup_local(template_name)
    variants: list[dict] = _normalize_variants(local_rows or [], "local")
    approved = [v for v in variants if v["status"] == "approved"]
    meta_rows: list[dict] | None = None

    # Sem variante aprovada localmente (banco fora, template ausente ou só pendente)
    # → tenta a Meta, que é a autoridade final sobre aprovação.
    if not approved:
        meta_rows = await _lookup_meta(template_name, channel)
        if meta_rows is not None:
            meta_variants = _normalize_variants(meta_rows, "meta")
            variants.extend(meta_variants)
            approved = [v for v in variants if v["status"] == "approved"]

    # ── Fail-closed: nenhuma fonte verificável ───────────────────────────────
    if local_rows is None and meta_rows is None:
        return [
            f"não foi possível verificar o template '{template_name}' (banco local e "
            f"Meta API indisponíveis) — disparo em massa às cegas é bloqueado por "
            f"segurança; tente novamente ou defina PREFLIGHT_TEMPLATE=off para forçar"
        ]

    # ── Checagem 1: existência/aprovação ────────────────────────────────────
    if not approved:
        if variants:
            statuses = ", ".join(sorted({v["status"] or "desconhecido" for v in variants}))
            return [
                f"template '{template_name}' existe mas NÃO está aprovado "
                f"(status: {statuses}) — aguarde a aprovação da Meta antes de disparar"
            ]
        if meta_rows is None:
            # Banco respondeu (ausente localmente), mas a Meta não pôde confirmar —
            # bloqueia do mesmo jeito (fail-closed), com o motivo exato.
            return [
                f"template '{template_name}' não existe em message_templates e a Meta "
                f"API não pôde ser consultada para confirmar — disparo bloqueado por "
                f"segurança; sincronize os templates ou confira o nome exato"
            ]
        return [
            f"template '{template_name}' não encontrado (nem em message_templates, "
            f"nem na Meta API do canal) — confira o nome exato do template aprovado"
        ]

    errors: list[str] = []

    # ── Checagem 2: locale do broadcast × language da aprovação ─────────────
    approved_langs = sorted({v["language"] for v in approved if v["language"]})
    match = next((v for v in approved if v["language"] == template_language_code), None)
    if match is None:
        errors.append(
            f"locale divergente: o broadcast pede '{template_language_code}', mas o "
            f"template '{template_name}' só está aprovado em: {', '.join(approved_langs)} "
            f"— locale errado dá 404/#132001 no envio"
        )
        # Segue validando params/header contra a 1ª variante aprovada, para
        # devolver TODOS os problemas de uma vez (não um por tentativa).
        match = approved[0]

    components = match.get("components") or []

    # ── Checagem 3: params do BODY ───────────────────────────────────────────
    errors.extend(_check_body_params(_body_text(components), template_variables))

    # ── Checagem 4: header ───────────────────────────────────────────────────
    errors.extend(_check_header(components, template_variables))

    return errors
