-- Vincula cada canal a um usuário do Supabase Auth
-- NULL = canal sem dono (visível apenas para admins)
ALTER TABLE channels
  ADD COLUMN IF NOT EXISTS owner_user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_channels_owner_user_id ON channels(owner_user_id);

COMMENT ON COLUMN channels.owner_user_id IS
  'ID do usuário (auth.users) responsável por este canal. NULL = canal administrativo, visível apenas para admins.';
