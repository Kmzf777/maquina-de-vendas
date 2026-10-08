from fastapi import APIRouter, Depends

from app.campaigns.conversion_analytics import conversion_dashboard
from app.campaigns.traffic_router import exigir_admin

router = APIRouter(prefix="/api/conversions", tags=["conversions"])


@router.get("/dashboard")
async def conversion_dashboard_endpoint(_admin: str = Depends(exigir_admin)):
    """Analytics agregados p/ a seção 'Conversões (Ads)' do Dashboard. Só admin, exigido AQUI
    (não só na proxy do Next): o backend é público em api.canastrainteligencia.com e o payload
    traz receita de vendas. A proxy (`frontend/src/app/api/conversions/dashboard`) repassa o JWT
    pelo `adminProxy`."""
    return conversion_dashboard()
