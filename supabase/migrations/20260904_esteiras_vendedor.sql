-- supabase/migrations/20260904_esteiras_vendedor.sql
--
-- Esteiras do vendedor (itens 6, 7 e 8 da ata de 03/09/2026).
-- Spec: docs/superpowers/specs/2026-09-04-esteiras-vendedor-design.md
--
-- NAO E APLICADA PELO DEPLOY. O GitHub Actions sobe imagem, nao roda migration.
-- Executar a mao no SQL editor do Supabase ANTES do push.
--
-- PRE-REQUISITO: 20260825_quotes.sql precisa ter rodado antes. E ela quem cria a
-- etapa `proposta_enviada`, que e o gatilho da esteira E3. Sem ela a E3 nasce sem
-- etapa para observar.
--
-- Reexecutar e seguro: tudo IF NOT EXISTS / OR REPLACE, e o backfill do bloco 1 so
-- toca linha com entered_stage_at IS NULL.

-- ===========================================================================
-- 1. deals.entered_stage_at
-- ===========================================================================
-- Espelha leads.entered_stage_at (002_crm_enrichment.sql). Sem esta coluna nao ha
-- como saber ha quanto tempo um card esta parado numa coluna do Kanban — que e a
-- pergunta que as tres esteiras fazem.
--
-- Sem DEFAULT now() de proposito: com default, o ALTER carimbaria "agora" em todo
-- card existente e as esteiras so acordariam 15 dias depois de aplicada a migration.
-- O backfill abaixo usa updated_at, que e a melhor aproximacao da ultima
-- movimentacao real.
ALTER TABLE deals ADD COLUMN IF NOT EXISTS entered_stage_at timestamptz;

UPDATE deals
   SET entered_stage_at = COALESCE(updated_at, created_at)
 WHERE entered_stage_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_deals_entered_stage_at ON deals(entered_stage_at);

-- Observa as DUAS colunas de etapa: o Kanban usa stage_id, mas caminhos legados
-- ainda escrevem o texto em stage (ex.: 'ja_chamado'). Observar so uma deixaria
-- cards com data velha depois de terem sido movidos.
CREATE OR REPLACE FUNCTION update_deal_entered_stage_at()
RETURNS TRIGGER AS $$
BEGIN
    IF (NEW.stage_id IS DISTINCT FROM OLD.stage_id)
       OR (NEW.stage IS DISTINCT FROM OLD.stage) THEN
        NEW.entered_stage_at = now();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_update_deal_entered_stage_at ON deals;
CREATE TRIGGER trg_update_deal_entered_stage_at
    BEFORE UPDATE ON deals
    FOR EACH ROW EXECUTE FUNCTION update_deal_entered_stage_at();

-- ===========================================================================
-- 2. campaigns.audience
-- ===========================================================================
-- Quem a campanha pode tocar: leads da IA, leads sob controle humano, ou ambos.
--
-- O DEFAULT 'ia' e a rede de seguranca da mudanca inteira. A alternativa —
-- remover o filtro ai_enabled=TRUE dos gatilhos — faria TODA campanha ja existente
-- passar a enrolar lead sob controle humano, disparando automacao por cima de
-- conversa que um vendedor esta conduzindo. Com o default, nada muda para quem ja
-- existe; so quem marcar 'humano'/'ambos' opta por entrar.
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS audience text NOT NULL DEFAULT 'ia';

DO $$ BEGIN
  ALTER TABLE campaigns ADD CONSTRAINT campaigns_audience_check
    CHECK (audience IN ('ia', 'humano', 'ambos'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ===========================================================================
-- 3. campaign_enrollments.metadata
-- ===========================================================================
-- Guarda a "guarda de etapa" do enrollment:
--   {"guard": {"deal_id": "...", "stage_id": "...", "stage_key": "..."}}
-- Gravar no enrollment (em vez de reler o no de gatilho a cada tick) deixa a regra
-- de saida imune a edicao posterior da campanha: quem mexer no gatilho nao muda o
-- criterio de quem ja esta dentro.
ALTER TABLE campaign_enrollments ADD COLUMN IF NOT EXISTS metadata jsonb NOT NULL DEFAULT '{}';

-- ===========================================================================
-- 4. RPC get_deals_stage_stagnant
-- ===========================================================================
-- Uma funcao cobre as tres esteiras. Em SQL porque a decisao depende de um
-- MAX(created_at) por conversa; via PostgREST isso seria N+1 sobre centenas de
-- cards a cada tick.
--
-- p_stage_days  = dias parado na ETAPA   (relogio do item 8: "proposta enviada conta 3 dias")
-- p_silence_days= dias sem MENSAGEM      (relogio dos itens 6 e 7: "sem conversa")
-- Os dois combinam por AND; 0 desliga o respectivo filtro.
--
-- A funcao NAO devolve so "quem esta parado": ela ja devolve "quem esta parado E pode
-- receber". Os motivos PERMANENTES de pulo (cooldown, opt-out, conversa finalizada,
-- numero errado) moram aqui, e nao so no laco Python, por uma razao operacional:
-- o gatilho processa no maximo `p_limit` linhas por tick, ORDENADAS pelo silencio mais
-- antigo. Lead que o Python pula nunca recebe mensagem, entao o `last_message_at` dele
-- nunca muda e ele fica no TOPO da ordenacao para sempre, ocupando um slot. Bastam
-- `p_limit` leads assim para a esteira devolver 20 linhas, pular as 20 e parar de
-- funcionar em silencio — sem erro, sem alerta. As guardas Python continuam existindo
-- como defesa em profundidade; o que elas nao podem e ser a UNICA linha.
--
-- DROP antes do CREATE: `p_campaign_id`/`p_cooldown_days` mudam a lista de tipos, e
-- CREATE OR REPLACE nesse caso cria um OVERLOAD em vez de substituir. Com as duas
-- assinaturas no catalogo, uma chamada de 9 argumentos casa com as duas e o Postgres
-- levanta "function ... is not unique" — a esteira para de rodar. Mesmo motivo do bloco 5.
DROP FUNCTION IF EXISTS get_deals_stage_stagnant(uuid, text, uuid, uuid, int, int, text, text, int);
CREATE OR REPLACE FUNCTION get_deals_stage_stagnant(
  p_stage_id      uuid,
  p_stage_key     text,
  p_pipeline_id   uuid,
  p_channel_id    uuid,
  p_stage_days    int,
  p_silence_days  int,
  p_last_speaker  text,
  p_audience      text,
  p_limit         int  DEFAULT 20,
  -- Campanha que esta perguntando. Opcional (DEFAULT NULL) para nao quebrar quem
  -- chame a RPC sem ela — a previa da tela, por exemplo.
  p_campaign_id   uuid DEFAULT NULL,
  p_cooldown_days int  DEFAULT 90
)
RETURNS TABLE(lead_id uuid, deal_id uuid, stage_id uuid, last_speaker text, last_message_at timestamptz)
AS $$
  WITH candidatos AS (
    SELECT
      d.id            AS deal_id,
      d.lead_id       AS lead_id,
      d.stage_id      AS stage_id,
      d.entered_stage_at,
      d.created_at    AS deal_created_at,
      (
        SELECT m.created_at
          FROM messages m
          JOIN conversations c ON c.id = m.conversation_id
         WHERE c.lead_id = d.lead_id
           AND (p_channel_id IS NULL OR c.channel_id = p_channel_id)
         ORDER BY m.created_at DESC
         LIMIT 1
      ) AS ultima_msg_at,
      (
        SELECT CASE WHEN m.role = 'user' THEN 'lead' ELSE 'nos' END
          FROM messages m
          JOIN conversations c ON c.id = m.conversation_id
         WHERE c.lead_id = d.lead_id
           AND (p_channel_id IS NULL OR c.channel_id = p_channel_id)
         ORDER BY m.created_at DESC
         LIMIT 1
      ) AS falante
      FROM deals d
      JOIN leads l          ON l.id = d.lead_id
      JOIN pipeline_stages s ON s.id = d.stage_id
     WHERE
       -- FAIL-CLOSED sem etapa. Os dois nulos significavam "qualquer etapa", e a
       -- funcao varria TODO card aberto de TODO funil: uma esteira ligada antes de ser
       -- configurada dispararia template para a base inteira, 20 por tick, repetindo.
       -- A API das esteiras (`esteiras_router`) ja recusa ativar sem etapa, mas o
       -- builder de cadencias monta o mesmo gatilho e liga sem passar por ela. Fechar
       -- no lugar mais profundo protege TODOS os chamadores; a regra da API vira
       -- defesa em profundidade em vez de unico anteparo.
       (p_stage_id IS NOT NULL OR p_stage_key IS NOT NULL)
       -- etapa alvo: por id exato OU por key (vale em todo funil)
       AND (p_stage_id IS NULL OR d.stage_id = p_stage_id)
       AND (p_stage_key IS NULL OR s.key = p_stage_key)
       AND (p_pipeline_id IS NULL OR s.pipeline_id = p_pipeline_id)
       -- card tem de estar ABERTO. 'fechado_perdido'/'perdido' porque
       -- 20260626_valeria_unify_stage_keys.sql deixou funis usando 'perdido' em vez
       -- de 'fechado_perdido'; 'encerrado' porque o funil "Importacao Leads Frios"
       -- nao tem coluna "Perdido" e usa "Encerrado" no lugar dela — mesma lista de
       -- quatro keys que backend/app/leads/service.py::_perdido_stage_id ja trata
       -- como fechamento. Omitir 'encerrado' aqui deixaria a esteira de reposicao
       -- cobrando lead cujo card ja foi encerrado.
       AND (s.key IS NULL OR s.key NOT IN ('fechado_ganho', 'fechado_perdido', 'perdido', 'encerrado'))
       -- publico
       AND (
         p_audience = 'ambos'
         OR (p_audience = 'ia'     AND l.ai_enabled = TRUE)
         OR (p_audience = 'humano' AND l.ai_enabled = FALSE)
       )
       -- COOLDOWN: card que ja passou por ESTA campanha nos ultimos p_cooldown_days
       -- nao volta. Sem isto a esteira NUNCA PARA.
       --
       -- O gatilho pulava reinscricao com `is_already_enrolled`, que so conta
       -- enrollment 'active'/'paused'. Ao chegar no no `end` o enrollment vira
       -- 'completed' e sai daquele filtro — e nada impede a reinscricao do mesmo card
       -- no tick seguinte. Dois casos reais das esteiras seed:
       --   • `novo_reengajamento` (silence_days=3, last_speaker='nos', um toque so):
       --     a NOSSA propria mensagem zera o relogio de silencio. Tres dias depois o
       --     lead esta elegivel de novo, com o ultimo falante sendo nos. Um template a
       --     cada 3 dias, para sempre.
       --   • `proposta` (stage_days=3, silence_days=0, nunca move o card): o
       --     entered_stage_at so muda quando o card troca de coluna, entao continua
       --     satisfazendo o corte; o filtro de silencio esta desligado; e o ultimo
       --     falante somos nos, porque o nosso template acabou de sair. Reinscricao a
       --     cada ~10 dias, indefinidamente.
       --
       -- Por que COOLDOWN e nao exclusao permanente: card que sai da etapa e volta
       -- meses depois e uma oportunidade legitima e deve poder entrar na esteira de
       -- novo. O que nao pode e a esteira recomecar sozinha na semana seguinte.
       --
       -- Deliberadamente SEM filtro de status no subselect: e justamente o enrollment
       -- 'completed' — o que terminou a esteira — que precisa segurar a reentrada.
       AND (
         p_campaign_id IS NULL
         OR NOT EXISTS (
           SELECT 1 FROM campaign_enrollments ce
            WHERE ce.campaign_id = p_campaign_id
              AND ce.deal_id = d.id
              AND ce.enrolled_at > now() - make_interval(days => p_cooldown_days)
         )
       )
       -- OPT-OUT. Espelha `backend/app/leads/service.py::is_lead_blacklisted`, que e a
       -- fonte de verdade: `leads.opt_out` (canonico, setado por registrar_optout) OU
       -- qualquer deal no pipeline Blacklist (lead movido a mao sem o flag).
       -- NAO inclui stage='perdido' — aquilo e rejeicao SOFT e o lead e reativavel.
       AND l.opt_out IS NOT TRUE
       AND NOT EXISTS (
         SELECT 1 FROM deals bd
          WHERE bd.lead_id = d.lead_id
            -- Mesmo UUID de leads/service.py::BLACKLIST_PIPELINE_ID, ja hardcoded em
            -- 20260618_pipelines_owner_user.sql. O funil Blacklist e universal
            -- (is_universal=true) e unico na instalacao.
            AND bd.pipeline_id = '8988e852-2836-4add-b023-4db4d6cd0e6e'
       )
       -- As DUAS marcas que `follow_up/scheduler.py::_lead_stop_reason` trata como
       -- parada definitiva. Numero errado e o pior caso possivel para uma esteira:
       -- o card fica aberto, o lead esta em silencio POR DEFINICAO e tem
       -- ai_enabled=False — ou seja, e o candidato perfeito do gatilho. Cada toque
       -- iria para um desconhecido, que e quem mais tende a apertar "Bloquear" e
       -- derrubar a reputacao do numero na Meta.
       AND (l.metadata->>'wrong_number_at') IS NULL
       AND (l.metadata->>'blacklisted_at') IS NULL
       -- CONVERSA FINALIZADA pelo vendedor em /conversas. Espelha
       -- `automation/engine.py::_conversation_followup_disabled`. Aqui a versao SQL e
       -- de proposito mais conservadora: quando p_channel_id e NULL ela olha QUALQUER
       -- conversa do lead, enquanto o Python pega uma linha arbitraria (`.limit(1)`).
       -- Na duvida, nao toca.
       AND NOT EXISTS (
         SELECT 1 FROM conversations cf
          WHERE cf.lead_id = d.lead_id
            AND (p_channel_id IS NULL OR cf.channel_id = p_channel_id)
            AND cf.followup_enabled = FALSE
       )
  )
  SELECT
    c.lead_id,
    c.deal_id,
    c.stage_id,
    COALESCE(c.falante, 'nos') AS last_speaker,
    COALESCE(c.ultima_msg_at, c.deal_created_at) AS last_message_at
    FROM candidatos c
   WHERE
     (p_stage_days <= 0
       OR (c.entered_stage_at IS NOT NULL
           AND c.entered_stage_at <= now() - make_interval(days => p_stage_days)))
     -- Conversa SEM nenhuma mensagem conta como silencio: cai para deal.created_at.
     -- Sem esse COALESCE, card criado por importacao nunca entraria em esteira.
     AND (p_silence_days <= 0
       OR COALESCE(c.ultima_msg_at, c.deal_created_at) <= now() - make_interval(days => p_silence_days))
     AND (p_last_speaker = 'qualquer' OR COALESCE(c.falante, 'nos') = p_last_speaker)
   ORDER BY COALESCE(c.ultima_msg_at, c.deal_created_at) ASC
   LIMIT p_limit;
$$ LANGUAGE sql STABLE;

-- O NOT EXISTS do cooldown e correlacionado: roda uma vez por card candidato, a cada
-- tick, para cada esteira ligada. Sem este indice ele vira um scan de
-- campaign_enrollments por card. O indice existente (idx_campaign_enrollments_campaign)
-- nao cobre deal_id.
CREATE INDEX IF NOT EXISTS idx_campaign_enrollments_campaign_deal
    ON campaign_enrollments(campaign_id, deal_id, enrolled_at);

-- ===========================================================================
-- 5. audience nas RPCs existentes
-- ===========================================================================
-- DEFAULT 'ia' preserva o COMPORTAMENTO para qualquer chamador que nao passe o
-- argumento — inclusive o codigo em producao entre o SQL rodar e o deploy subir.
--
-- O DROP antes de cada CREATE OR REPLACE NAO e limpeza cosmetica. A identidade de
-- uma funcao no Postgres inclui a lista de TIPOS dos parametros: acrescentar
-- p_audience nao substitui a funcao de 2/3 argumentos existente, cria um OVERLOAD
-- novo ao lado dela. Com as duas assinaturas coexistindo, uma chamada com o numero
-- antigo de argumentos passa a casar com dois candidatos (o de aridade exata e o de
-- aridade maior preenchido por default) e o Postgres nao tem criterio de desempate
-- — o erro e "function ... is not unique", e ele derruba TODO gatilho de polling
-- que chame a RPC por esse nome, nao so as esteiras novas.
-- Derrubar a assinatura antiga antes do CREATE e seguro para o codigo que estiver
-- em producao no intervalo entre este SQL rodar e a imagem nova subir: o PostgREST
-- chama a RPC por nome com argumentos NOMEADOS, e o parametro novo tem DEFAULT, entao
-- a mesma chamada de 2/3 argumentos que hoje bate na funcao antiga passa a bater
-- na funcao nova (unica) sem precisar mudar nada no chamador.
DROP FUNCTION IF EXISTS get_leads_for_repurchase(TIMESTAMPTZ, TEXT);
CREATE OR REPLACE FUNCTION get_leads_for_repurchase(
  cutoff_date TIMESTAMPTZ,
  p_env_tag TEXT,
  p_audience TEXT DEFAULT 'ia'
)
RETURNS TABLE(id UUID, phone TEXT) AS $$
  SELECT l.id, l.phone
  FROM leads l
  WHERE (
    p_audience = 'ambos'
    OR (p_audience = 'ia'     AND l.ai_enabled = TRUE)
    OR (p_audience = 'humano' AND l.ai_enabled = FALSE)
  )
  AND EXISTS (SELECT 1 FROM sales s WHERE s.lead_id = l.id)
  AND (
    SELECT MAX(s2.sold_at) FROM sales s2 WHERE s2.lead_id = l.id
  ) <= cutoff_date;
$$ LANGUAGE sql;

-- Mesmo motivo do DROP acima: p_audience muda a lista de tipos, entao o CREATE OR
-- REPLACE por si so criaria um segundo overload em vez de substituir a funcao de
-- 3 argumentos existente.
DROP FUNCTION IF EXISTS get_leads_no_sale_in_stage(TEXT, TIMESTAMPTZ, TEXT);
CREATE OR REPLACE FUNCTION get_leads_no_sale_in_stage(
  p_stage TEXT,
  cutoff_date TIMESTAMPTZ,
  p_env_tag TEXT,
  p_audience TEXT DEFAULT 'ia'
)
RETURNS TABLE(id UUID, phone TEXT) AS $$
  SELECT l.id, l.phone
  FROM leads l
  WHERE l.stage = p_stage
    AND (
      p_audience = 'ambos'
      OR (p_audience = 'ia'     AND l.ai_enabled = TRUE)
      OR (p_audience = 'humano' AND l.ai_enabled = FALSE)
    )
    AND l.entered_stage_at IS NOT NULL
    AND l.entered_stage_at <= cutoff_date
    AND NOT EXISTS (
      SELECT 1 FROM sales s WHERE s.lead_id = l.id
    );
$$ LANGUAGE sql;

NOTIFY pgrst, 'reload schema';
