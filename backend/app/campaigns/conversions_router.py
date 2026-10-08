from fastapi import APIRouter

from app.campaigns.conversion_analytics import conversion_dashboard

router = APIRouter(prefix="/api/conversions", tags=["conversions"])


@router.get("/dashboard")
async def conversion_dashboard_endpoint():
    """Analytics agregados p/ a seção 'Conversões (Ads)' do Dashboard (admin-only na UI)."""
    return conversion_dashboard()
