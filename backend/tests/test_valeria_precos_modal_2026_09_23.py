"""Preços da ValerIA editáveis no CRM (23/09/2026).

O admin troca o preço em /produtos e a ValerIA tem que obedecer:
1. o catálogo em memória vence em 60 s (antes 300 s);
2. nenhum prompt carrega um preço de exemplo — o "R$23,90" dos exemplos de voz era
   copiado como preço real (3 leads até 17/09/2026), por cima do catálogo.
"""
from pathlib import Path

from app.agent import catalog

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "app" / "agent" / "prompts"


def test_catalogo_vence_em_60s():
    assert catalog._CACHE_TTL_SECONDS == 60


def test_nenhum_prompt_tem_preco_de_exemplo_23_90():
    culpados = [
        str(p.relative_to(PROMPTS_DIR))
        for p in PROMPTS_DIR.rglob("*.py")
        if "23,90" in p.read_text(encoding="utf-8")
    ]
    assert culpados == []
