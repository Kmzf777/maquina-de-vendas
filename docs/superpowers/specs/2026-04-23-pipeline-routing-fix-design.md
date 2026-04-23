# Fix: Pipeline Routing Cleanup + Hard Test

## Problema

1. Funis residuais no banco ("funil atacado", "raposo nao pegue", possivelmente "Principal") criados manualmente durante testes — precisam ser removidos.
2. O rehearsal existente (R1-R5) verifica `encaminhar_humano` nos eventos mas não valida o lado do banco: se o deal foi criado no pipeline correto ("Atacado", "Private Label", etc.) na primeira coluna (stage não-protegido de menor order_index).

## Escopo

### Parte 1 — Limpeza DB (MCP SQL)
- Deletar pipelines pelo nome exato: "funil atacado", "raposo nao pegue" (stages caem via ON DELETE CASCADE)
- Confirmar via SELECT que só existem os 4 pipelines legítimos: Atacado, Private Label, Exportação, Consumo

### Parte 2 — Pytest: test_encaminhar_humano_pipeline.py
Dois testes unitários (mock Supabase):
- Lead `stage="atacado"` → `execute_tool("encaminhar_humano")` → `create_deal` chamado com `category="atacado"`
- Lead `stage="private_label"` → `create_deal` chamado com `category="private_label"`

### Parte 3 — Hard check nos arquétipos
Adicionar `deal_in_pipeline_correto(expected_category)` como check nos arquétipos R1 (atacado) e R2/R3/R4/R5 (private_label), verificando via Supabase se o deal criado está no pipeline correto.

### Parte 4 — Verificação DB pós-rehearsal (MCP SQL)
SELECT nos deals mais recentes para confirmar `pipeline_id` correto.

## Mapeamento categoria → pipeline
```python
CATEGORY_PIPELINE_NAMES = {
    "atacado": "Atacado",
    "private_label": "Private Label",
    "exportacao": "Exportação",
    "consumo": "Consumo",
}
```

## Critério de sucesso
- Banco sem funis residuais
- 2 testes pytest passando
- Rehearsal R1 e pelo menos um R2-R5 com `encaminhar_humano` + deal no pipeline correto
