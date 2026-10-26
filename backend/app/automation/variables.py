# backend/app/automation/variables.py
from datetime import datetime, timezone
from dateutil.parser import parse as parse_dt
from app.db.supabase import get_supabase
from app.utils.receita_venda import receita_da_venda, venda_cancelada
from app.vendedores import service as vendedores_service


def substitute_variables(text: str, lead: dict, enrollment: dict | None = None) -> str:
    """Replace {{var}} placeholders with CRM data. Missing data → empty string."""
    replacements: dict[str, str] = {
        "{{nome}}":       lead.get("name") or "",
        "{{empresa}}":    lead.get("company") or "",
        "{{telefone}}":   lead.get("phone") or "",
        # dot-notation aliases
        "{{lead.name}}":  lead.get("name") or "",
        "{{lead.phone}}": lead.get("phone") or "",
        "{{lead.company}}": lead.get("company") or "",
        "{{lead.stage}}": lead.get("stage") or "",
    }

    _fill_sale_vars(text, lead, replacements)
    _fill_seller_var(text, lead, replacements)
    _fill_deal_vars(text, lead, replacements)

    for var, value in replacements.items():
        text = text.replace(var, value)
    return text


def _fill_sale_vars(text: str, lead: dict, out: dict) -> None:
    if not any(v in text for v in ("{{produto}}", "{{valor_ultima_venda}}", "{{dias_sem_compra}}")):
        return
    sb = get_supabase()
    # D7 (1e6381fe): "última venda" = a última NÃO cancelada, e o valor sai sem frete.
    # Sem `limit`, para a cancelada mais recente não esconder a válida.
    rows = (
        sb.table("sales")
        .select("product, value, freight, status, sold_at")
        .eq("lead_id", lead["id"])
        .order("sold_at", desc=True)
        .execute()
        .data
    ) or []
    rows = [r for r in rows if not venda_cancelada(r)]
    if rows:
        s = rows[0]
        out["{{produto}}"] = s.get("product") or ""
        raw_val = receita_da_venda(s)
        out["{{valor_ultima_venda}}"] = (
            f"R$ {raw_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        )
        sold_at = parse_dt(s["sold_at"]) if isinstance(s["sold_at"], str) else s["sold_at"]
        days = (datetime.now(timezone.utc) - sold_at).days
        out["{{dias_sem_compra}}"] = str(days)
    else:
        out["{{produto}}"] = ""
        out["{{valor_ultima_venda}}"] = ""
        out["{{dias_sem_compra}}"] = ""


def _fill_seller_var(text: str, lead: dict, out: dict) -> None:
    if "{{vendedor}}" not in text:
        return
    # Cadastro único `vendedores` (b67f1c6b); `team_users` nunca existiu.
    assigned = lead.get("assigned_to")
    vendedor = vendedores_service.por_id(assigned) if assigned else None
    out["{{vendedor}}"] = (vendedor or {}).get("nome") or ""


def _fill_deal_vars(text: str, lead: dict, out: dict) -> None:
    if not any(v in text for v in ("{{deal_titulo}}", "{{pipeline}}")):
        return
    sb = get_supabase()
    rows = (
        sb.table("deals")
        .select("title, pipelines!inner(name)")
        .eq("lead_id", lead["id"])
        .order("created_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    if rows:
        d = rows[0]
        out["{{deal_titulo}}"] = d.get("title") or ""
        out["{{pipeline}}"] = (d.get("pipelines") or {}).get("name") or ""
    else:
        out["{{deal_titulo}}"] = ""
        out["{{pipeline}}"] = ""
