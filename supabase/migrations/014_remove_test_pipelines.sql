-- 014_remove_test_pipelines.sql
-- Remove pipelines de teste criados manualmente durante desenvolvimento.
-- Mantém apenas os 4 pipelines legítimos do sistema.

DELETE FROM pipelines
WHERE name NOT IN ('Atacado', 'Private Label', 'Exportação', 'Consumo');
