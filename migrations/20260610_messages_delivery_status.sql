-- Adiciona coluna delivery_status na tabela messages.
-- Rastreia o status de entrega de mensagens de saída (sent, delivered, read, failed).
-- Nullable para compatibilidade com mensagens existentes e mensagens de entrada.
ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS delivery_status TEXT;
