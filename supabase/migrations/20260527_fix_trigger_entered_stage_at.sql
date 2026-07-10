-- Fix trigger que referencia OLD.seller_stage (coluna dropada em 009_deals.sql).
-- 002_crm_enrichment.sql criou a função com condição OR sobre seller_stage.
-- 009_deals.sql dropou a coluna mas não atualizou a função, causando erro 42703
-- em qualquer UPDATE em leads que não mude stage (encaminhar_humano, registrar_optout,
-- salvar_nome). Apenas mudar_stage funcionava porque o OR faz short-circuit quando
-- OLD.stage IS DISTINCT FROM NEW.stage é verdadeiro.

CREATE OR REPLACE FUNCTION update_entered_stage_at()
RETURNS trigger AS $$
BEGIN
    IF OLD.stage IS DISTINCT FROM NEW.stage THEN
        NEW.entered_stage_at = now();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
