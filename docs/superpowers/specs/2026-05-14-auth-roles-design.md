# Design Spec: Sistema de Autenticação com Roles (Admin/Vendedor)

**Data:** 2026-05-14  
**Status:** Aprovado

---

## Visão Geral

Adicionar controle de acesso baseado em roles ao CRM existente. O Supabase Auth já está em uso (email/password). A solução adiciona dois roles — `admin` e `vendedor` — sem criar novas tabelas no banco.

---

## Armazenamento do Role

O role é armazenado em `app_metadata.role` no Supabase Auth.

- Valores: `'admin'` | `'vendedor'`
- **Por que `app_metadata` e não `user_metadata`?** Usuários autenticados podem alterar o próprio `user_metadata` via `supabase.auth.updateUser()`. O `app_metadata` só pode ser escrito via service role — usuários não conseguem alterar o próprio role.
- O Supabase inclui `app_metadata` no JWT automaticamente. Nenhuma query adicional ao banco é necessária em cada request.
- Role é definido via endpoint administrativo protegido (`POST /api/admin/users/set-role`), que usa o Supabase Admin Client (service role).

---

## Proteção de Rotas — Frontend (Next.js Middleware)

`middleware.ts` na raiz do frontend intercepta todas as requisições ao grupo `(authenticated)` antes de qualquer renderização — sem flash de conteúdo não autorizado.

### Mapa de permissões

| Role       | Páginas permitidas                                               |
|------------|------------------------------------------------------------------|
| `admin`    | todas                                                            |
| `vendedor` | `/dashboard`, `/leads`, `/conversas`, `/campanhas`, `/qualificacao`, `/vendas` |
| sem role   | redirect para `/login`                                           |

### Lógica do middleware

1. Lê o JWT do cookie Supabase SSR (`@supabase/ssr`)
2. Extrai `session.user.app_metadata.role`
3. Se a rota requisitada não está na lista de permissões do role → redirect `302` para `/dashboard`
4. Se não há sessão → redirect para `/login`

---

## Proteção de Rotas — Backend (FastAPI)

Dependency `require_role(roles: list[str])` injeta verificação em rotas selecionadas.

### Validação JWT

- FastAPI valida o JWT Supabase usando JWKS (chave pública do projeto Supabase)
- Endpoint JWKS: `{SUPABASE_URL}/auth/v1/jwks`
- Biblioteca: `python-jose` (já disponível via dependências existentes ou adicionada)
- Extrai `app_metadata.role` do payload JWT

### Rotas protegidas (admin-only)

| Prefixo                    | Motivo                             |
|----------------------------|------------------------------------|
| `GET/POST /api/channels/*` | Página `/canais` (admin-only)      |
| `GET /api/stats/*`         | Página `/estatisticas` (admin-only)|
| `GET/POST /api/agent-profiles/*` | Configurações de IA (admin-only) |
| `POST /api/evolution/*`    | Integração WhatsApp (admin-only)   |
| `POST /api/admin/*`        | Gerenciamento de usuários          |

Resposta em caso de role insuficiente: `403 Forbidden` com `{"detail": "Permissão insuficiente"}`.

---

## Gerenciamento de Usuários

Admin gerencia usuários diretamente no **painel do Supabase** (Authentication → Users) para criar contas e, opcionalmente, via endpoint interno para definir roles programaticamente.

### Endpoint `POST /api/admin/users/set-role`

```
Body: { user_id: string, role: 'admin' | 'vendedor' }
Auth: require_role(['admin'])
```

Usa `supabase.auth.admin.updateUserById(user_id, { app_metadata: { role } })` com service role.

---

## Componentes Novos

### Frontend

| Arquivo | Responsabilidade |
|---------|-----------------|
| `frontend/src/middleware.ts` | Intercepta rotas, valida role, redireciona |
| `frontend/src/lib/auth/roles.ts` | Constante `ROLE_PERMISSIONS` (mapa role → rotas) |
| `frontend/src/app/api/admin/users/set-role/route.ts` | Endpoint Next.js para definir role via service role |

### Backend

| Arquivo | Responsabilidade |
|---------|-----------------|
| `backend/app/auth/jwt.py` | Validação JWT Supabase via JWKS + extração de claims |
| `backend/app/auth/dependencies.py` | `get_current_role()` e `require_role()` como FastAPI dependencies |

---

## Navegação (Sidebar)

A sidebar existente deve esconder itens de menu com base no role da sessão atual:

- Vendedor não vê: Canais, Estatísticas, Config
- A leitura do role vem do objeto de sessão Supabase (`useSession` ou Server Component)

---

## Fluxo Completo

```
1. Usuário faz login → Supabase emite JWT com app_metadata.role
2. Browser acessa rota protegida
3. Next.js Middleware lê JWT → permite ou redireciona (server-side)
4. Página carrega → sidebar renderiza somente itens autorizados
5. Usuário chama API → FastAPI valida JWT + role → permite ou 403
```

---

## O que NÃO está no escopo

- Isolamento de dados por usuário (vendedor vê todos os leads/conversas)
- Roles além de `admin` e `vendedor`
- UI de gerenciamento de usuários dentro do CRM (usa painel Supabase)
- Auditoria de ações por usuário
