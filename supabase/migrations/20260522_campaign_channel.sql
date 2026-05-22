-- supabase/migrations/20260522_campaign_channel.sql

-- 1. Limpar cadências de desenvolvimento
DELETE FROM campaign_enrollments;
DELETE FROM campaign_nodes;
DELETE FROM campaigns;

-- 2. Adicionar channel_id à tabela campaigns
ALTER TABLE campaigns
  ADD COLUMN IF NOT EXISTS channel_id UUID REFERENCES channels(id) ON DELETE SET NULL;
