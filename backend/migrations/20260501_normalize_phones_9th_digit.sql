-- 20260501_normalize_phones_9th_digit.sql
--
-- Normaliza números brasileiros de celular de 12 dígitos para 13 dígitos
-- injetando o 9º dígito após o DDD.
--
-- PRECONDIÇÃO: rodar merge_duplicate_leads.sql PRIMEIRO para eliminar duplicatas.
-- Esta migração pula registros que já têm o par de 13 dígitos na base
-- (eles seriam tratados pelo merge, não aqui).
--
-- Verificação antes de rodar:
--   SELECT COUNT(*) FROM leads WHERE LENGTH(phone) = 12 AND phone LIKE '55%';
--
-- Verificação depois:
--   SELECT COUNT(*) FROM leads WHERE LENGTH(phone) = 12 AND phone LIKE '55%';
--   -- Deve retornar 0.

UPDATE leads
SET phone = LEFT(phone, 4) || '9' || RIGHT(phone, 8)
WHERE LENGTH(phone) = 12
  AND phone LIKE '55%'
  AND NOT EXISTS (
    SELECT 1 FROM leads l2
    WHERE l2.phone = LEFT(leads.phone, 4) || '9' || RIGHT(leads.phone, 8)
      AND l2.id != leads.id
  );
