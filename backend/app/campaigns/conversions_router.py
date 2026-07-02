from fastapi import APIRouter, Response

from app.campaigns.google_export import export_google_csv, conversion_stats
from app.campaigns.conversion_analytics import conversion_dashboard

router = APIRouter(prefix="/api/conversions", tags=["conversions"])


@router.get("/stats")
async def conversion_stats_endpoint():
    """Métricas agregadas dos eventos de conversão p/ a seção do Dashboard."""
    return conversion_stats()


@router.get("/dashboard")
async def conversion_dashboard_endpoint():
    """Analytics agregados p/ a seção 'Conversões (Ads)' do Dashboard (admin-only na UI)."""
    return conversion_dashboard()


@router.get("/google-export.csv")
async def google_export_csv(all: bool = False):
    """Baixa o CSV de conversões do Google Ads (importação offline). Por padrão só as pendentes,
    marcando-as como exportadas. ?all=true baixa tudo sem marcar (reprocesso)."""
    csv_text, count = export_google_csv(include_all=all, mark=not all)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="google_conversions.csv"',
            "X-Conversion-Count": str(count),
        },
    )
