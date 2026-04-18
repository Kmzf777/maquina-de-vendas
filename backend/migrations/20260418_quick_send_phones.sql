-- backend/migrations/20260418_quick_send_phones.sql
CREATE TABLE IF NOT EXISTS quick_send_phones (
  id         uuid primary key default gen_random_uuid(),
  phone      text not null unique,
  label      text,
  created_at timestamptz default now()
);
