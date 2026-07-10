# Opt5 — Processo de migrações: pasta única + ledger + runner leve

**Data:** 2026-07-10
**Status:** aprovado para implementação

## Problema

92 arquivos SQL em **3 diretórios desconexos** (`migrations/` 3, `backend/migrations/` 75, `supabase/migrations/` 14), duas convenções de nome misturadas (sequencial `001_`–`014_` com **colisão `009_deals.sql` vs `009_multi_agent_schema.sql`**; datada `20260417_`+), **nenhum registro do que foi aplicado** e aplicação 100% manual (editor SQL/MCP). A ordem real de aplicação vive na cabeça de quem opera; prod e homolog divergem silenciosamente.

## Design

### 1. Consolidação em `supabase/migrations/` (única pasta)

- Mover os arquivos de `migrations/` (raiz) e `backend/migrations/` para `supabase/migrations/`, **preservando nomes** (histórico rastreável via `git log --follow`).
- Exceções de nome: `009_multi_agent_schema.sql` → `009b_multi_agent_schema.sql` (resolve a colisão preservando ordem relativa); arquivos duplicados entre diretórios (mesmo nome) são deduplicados por hash — se o conteúdo divergir, prevalece o de `backend/migrations/` (histórico mais ativo) e o outro é descartado com nota no commit.
- Ordenação futura: lexicográfica — os legados `0NN_` ordenam antes dos datados `2026*`, o que espelha a história real. **Convenção daqui em diante: `YYYYMMDD_slug.sql`.**
- Os diretórios antigos deixam de existir.

### 2. Ledger `schema_migrations`

Criada pelo próprio runner (idempotente):

```sql
create table if not exists public.schema_migrations (
  filename text primary key,
  sha256 text not null,
  applied_at timestamptz not null default now(),
  baseline boolean not null default false
);
```

`baseline=true` marca registros gravados sem execução (banco que já tinha o estado).

### 3. Runner `backend/scripts/apply_migrations.py` (sem dependência nova)

- Execução de SQL arbitrário via **Supabase Management API** (`POST /v1/projects/{ref}/database/query`) com `httpx` (já no requirements) e `User-Agent` explícito (lição registrada: urllib puro → Cloudflare 1010). Env: `SUPABASE_PROJECT_REF` + `SUPABASE_ACCESS_TOKEN` (PAT). Sem Alembic, sem psycopg.
- Comandos:
  - `--status` (default): lista aplicadas vs pendentes (compara pasta × ledger).
  - `--baseline`: registra TODOS os arquivos atuais como aplicados **sem executar** — passo único de adoção em prod/homolog, que já têm o estado. Recusa-se a rodar se o ledger já tiver linhas (proteção contra baseline duplo).
  - `--apply`: aplica, em ordem lexicográfica, somente arquivos ausentes do ledger; cada arquivo = 1 chamada; grava no ledger após sucesso; **para no primeiro erro** (não pula adiante).
  - `--dry-run` combinável com `--apply`.
- Alerta de drift: arquivo já aplicado cujo `sha256` atual difere do registrado gera warning (arquivo editado após aplicado — proibido pela convenção; criar novo arquivo).

### 4. Processo (documentado no cabeçalho do runner)

1. Nova migração = novo arquivo `YYYYMMDD_slug.sql` em `supabase/migrations/`, no MESMO commit da feature (lição da cadência morta por constraint).
2. Aplicar: `python -m scripts.apply_migrations --apply` com o PAT do ambiente-alvo (homolog primeiro, prod após validar).
3. Sem step automático no deploy por ora (aplicação continua deliberada/humana, mas agora registrada e ordenada) — automatizar no CI é iteração futura.

## Adoção segura em bancos existentes

Prod/homolog já contêm o estado atual → o primeiro contato é **somente** `--baseline` (zero execução de SQL de schema; só cria o ledger e o povoa). Nada é reexecutado por construção: `--apply` ignora tudo que está no ledger.

## Fora de escopo (YAGNI)

Down-migrations/rollback, squash do histórico, aplicação automática no deploy, diff de schema entre ambientes.
