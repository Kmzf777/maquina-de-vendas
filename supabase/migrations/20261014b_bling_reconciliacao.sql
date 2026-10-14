-- supabase/migrations/20261014b_bling_reconciliacao.sql
--
-- Fase 3 da sincronia Bling (docs/avaliacao/2026-10-13-sync-bling-duas-contas.md):
-- resultado da reconciliacao diaria Bling x `sales`, por conta e por dia.
-- Escrita por app/bling/reconciliacao.py (uma vez por dia, de madrugada BRT).
--
-- Serve para o agente de consulta (e quem mais precisar) dizer "Bling da conta X
-- conferido ate D": o maior `dia` com status ok/reimportado sem nenhum
-- `divergente` antes dele na janela.
--
-- NAO E APLICADA PELO DEPLOY. Aplicar a mao ANTES do push da Fase 3: sem a
-- tabela, a reconciliacao falha no upsert (o resto do worker segue, isolado).
-- So ADITIVA e reexecutavel (IF NOT EXISTS / DROP ... IF EXISTS).

SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS bling_reconciliacao (
  account       text          NOT NULL,
  dia           date          NOT NULL,
  qtd_bling     integer       NOT NULL DEFAULT 0,
  qtd_banco     integer       NOT NULL DEFAULT 0,
  soma_bling    numeric(14,2) NOT NULL DEFAULT 0,
  soma_banco    numeric(14,2) NOT NULL DEFAULT 0,
  -- {faltando:[ids], sobrando:[ids], valor_diferente:[ids],
  --  apagados_no_bling:[ids], erros:[{pedido, erro}], reimportados:bool}
  divergentes   jsonb         NOT NULL DEFAULT '{}'::jsonb,
  -- ok: bateu de primeira; reimportado: divergia e bateu depois de reimportar;
  -- divergente: continua divergente (alerta bling_reconciliacao_divergente).
  status        text          NOT NULL,
  verificado_em timestamptz   NOT NULL DEFAULT now(),
  PRIMARY KEY (account, dia)
);

ALTER TABLE bling_reconciliacao DROP CONSTRAINT IF EXISTS bling_reconciliacao_status_check;
ALTER TABLE bling_reconciliacao ADD CONSTRAINT bling_reconciliacao_status_check
  CHECK (status IN ('ok', 'reimportado', 'divergente'));

CREATE INDEX IF NOT EXISTS bling_reconciliacao_divergente_idx
  ON bling_reconciliacao (account, dia) WHERE status = 'divergente';

-- Mesmo padrao das outras tabelas Bling: leitura para o app, escrita so pelo
-- backend (service_role ignora RLS).
ALTER TABLE bling_reconciliacao ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS bling_reconciliacao_select ON bling_reconciliacao;
CREATE POLICY bling_reconciliacao_select ON bling_reconciliacao
  FOR SELECT TO authenticated, service_role USING (true);

-- Leitura para o agente de consulta, se o role existir neste ambiente (ele e
-- criado fora deste repositorio). A view no schema `analytics` fica para o
-- trabalho do agente analista.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'consulta_ro') THEN
    GRANT SELECT ON bling_reconciliacao TO consulta_ro;
  END IF;
END $$;

-- ROLLBACK (nao executar; guardado aqui de proposito):
--   DROP TABLE IF EXISTS bling_reconciliacao;
