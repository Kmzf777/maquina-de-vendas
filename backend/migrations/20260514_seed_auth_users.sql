-- =============================================================================
-- SEED: Usuários do CRM com roles admin / vendedor
-- Execute manualmente no Supabase SQL Editor (não é migration automática)
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- PARTE 1 — Criar novos usuários
-- Cada bloco cria 1 usuário em auth.users + 1 identity para login email/senha
-- ─────────────────────────────────────────────────────────────────────────────

DO $$
DECLARE
  v_user_id uuid;
BEGIN

  -- ── Usuário 1: ADMIN ────────────────────────────────────────────────────────
  v_user_id := gen_random_uuid();

  INSERT INTO auth.users (
    id,
    instance_id,
    aud,
    role,
    email,
    encrypted_password,
    email_confirmed_at,
    raw_app_meta_data,
    raw_user_meta_data,
    created_at,
    updated_at,
    confirmation_token,
    recovery_token,
    email_change_token_new,
    email_change
  ) VALUES (
    v_user_id,
    '00000000-0000-0000-0000-000000000000',
    'authenticated',
    'authenticated',
    'comercial@cafecanastra.com',
    crypt('Canastrainteligencia#321', gen_salt('bf')),
    NOW(),
    '{"provider": "email", "providers": ["email"], "role": "admin"}',
    '{"full_name": "Administrador"}',
    NOW(),
    NOW(),
    '', '', '', ''
  );

  INSERT INTO auth.identities (
    id,
    provider_id,
    user_id,
    identity_data,
    provider,
    last_sign_in_at,
    created_at,
    updated_at
  ) VALUES (
    gen_random_uuid(),
    'comercial@cafecanastra.com',
    v_user_id,
    jsonb_build_object('sub', v_user_id::text, 'email', 'comercial@cafecanastra.com'),
    'email',
    NOW(),
    NOW(),
    NOW()
  );

  -- ── Usuário 2: VENDEDOR ─────────────────────────────────────────────────────
  v_user_id := gen_random_uuid();

  INSERT INTO auth.users (
    id,
    instance_id,
    aud,
    role,
    email,
    encrypted_password,
    email_confirmed_at,
    raw_app_meta_data,
    raw_user_meta_data,
    created_at,
    updated_at,
    confirmation_token,
    recovery_token,
    email_change_token_new,
    email_change
  ) VALUES (
    v_user_id,
    '00000000-0000-0000-0000-000000000000',
    'authenticated',
    'authenticated',
    'Comercial2@cafecanastra.com',
    crypt('Joao*321', gen_salt('bf')),
    NOW(),
    '{"provider": "email", "providers": ["email"], "role": "vendedor"}',
    '{"full_name": "Comercial 2"}',
    NOW(),
    NOW(),
    '', '', '', ''
  );

  INSERT INTO auth.identities (
    id,
    provider_id,
    user_id,
    identity_data,
    provider,
    last_sign_in_at,
    created_at,
    updated_at
  ) VALUES (
    gen_random_uuid(),
    'Comercial2@cafecanastra.com',
    v_user_id,
    jsonb_build_object('sub', v_user_id::text, 'email', 'Comercial2@cafecanastra.com'),
    'email',
    NOW(),
    NOW(),
    NOW()
  );

END $$;


-- =============================================================================
-- PARTE 2 — Definir role em usuários JÁ EXISTENTES
-- Use se o usuário já foi criado pelo painel ou pelo CRM
-- Substitua o email pelo email real do usuário
-- =============================================================================

-- Promover usuário existente para ADMIN:
UPDATE auth.users
SET raw_app_meta_data = raw_app_meta_data || '{"role": "admin"}'::jsonb
WHERE email = 'comercial@cafecanastra.com';

-- Definir usuário existente como VENDEDOR:
-- UPDATE auth.users
-- SET raw_app_meta_data = raw_app_meta_data || '{"role": "vendedor"}'::jsonb
-- WHERE email = 'outro.usuario@canastra.com';       -- ← trocar email


-- =============================================================================
-- PARTE 3 — Verificar usuários criados
-- Execute após o bloco acima para confirmar
-- =============================================================================

SELECT
  u.email,
  u.raw_app_meta_data->>'role'  AS role,
  u.raw_user_meta_data->>'full_name' AS nome,
  u.email_confirmed_at IS NOT NULL  AS email_confirmado,
  u.created_at
FROM auth.users u
ORDER BY u.created_at DESC
LIMIT 10;
