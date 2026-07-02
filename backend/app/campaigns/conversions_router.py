from fastapi import APIRouter, Response

from app.campaigns.google_export import export_google_csv

router = APIRouter(prefix="/api/conversions", tags=["conversions"])


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
