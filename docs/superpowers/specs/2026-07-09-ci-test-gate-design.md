# CI Test Gate — Suíte de testes como bloqueio de deploy

**Data:** 2026-07-09
**Status:** aprovado para implementação

## Problema

O `.github/workflows/deploy.yml` sobe para produção (Docker Swarm, push em `master`) validando apenas:

- **Backend:** `python -m compileall app` + instanciação de `Settings` com env dummy (`deploy.yml:117-125`).
- **Frontend:** `tsc --noEmit` + `next build` com placeholders (`deploy.yml:34-46`).

Existem **219 arquivos de teste** no backend (suíte hermética: `conftest.py` seta env fake antes dos imports, `FakeRedis`, Supabase stubado por autouse fixtures) e **16 arquivos vitest** no frontend (129 casos, utilitários puros, `environment: node`). Nenhum roda no pipeline. Regressões cobertas por teste chegam à produção sem barreira.

## Design

Inserir a execução das suítes como steps bloqueantes nos jobs existentes, antes do step de deploy SSH. Nenhum job novo, nenhuma dependência nova, nenhum serviço externo.

### Job `deploy-backend`

1. `python-version: '3.11'` → `'3.12'` — alinha com o runtime real (`backend/Dockerfile`: `python:3.12-slim`). Hoje o CI valida numa versão que a produção não usa.
2. Instalar também `requirements-dev.txt` (fakeredis, pytest-asyncio, respx — pytest vem como dependência transitiva de pytest-asyncio; adicionar `pytest` explícito ao requirements-dev para não depender de resolução implícita).
3. Novo step **"Run backend tests"** após os smoke checks:
   ```yaml
   run: python -m pytest -q -m "not integration" -p no:cacheprovider
   ```
   - `-m "not integration"`: exclui explicitamente os testes que exigem Supabase real (marker documentado em `pytest.ini`; eles já se auto-pulam via `skipif`, o filtro é cinto e suspensório).
   - Mesmas env dummies do smoke check (o conftest já provê fallbacks).
4. Os smoke checks atuais permanecem (validam contrato de `Settings`, que os testes não cobrem da mesma forma).

### Job `deploy-crm`

1. Novo step `actions/setup-node@v4` com `node-version: '20'` (alinha com `node:20-alpine` do Dockerfile) e `cache: npm`.
2. Novo step **"Run frontend tests"** entre o type-check e o build:
   ```yaml
   run: npm run test   # vitest run
   ```

### Comportamento de falha

Steps são sequenciais dentro do job; qualquer teste vermelho falha o step e o step de deploy (condicionado ao sucesso dos anteriores) não executa. Sem mudança na detecção de path (`crm_changed`/`backend_changed`) nem no script SSH.

## Riscos e mitigação

- **Suite vermelha ou não-hermética no runner** → validado rodando localmente `pytest -q -m "not integration"` e `npm run test` antes do push (pré-condição desta entrega).
- **Tempo de pipeline** → suíte backend é in-memory/mockada; estimativa de poucos minutos. Aceitável para um gate de produção que hoje não existe.
- **3.11 → 3.12 no runner** → o próprio run de CI valida; produção já roda 3.12.

## Fora de escopo (YAGNI)

Threshold de cobertura, matrix de versões, job separado de CI para branches, branch protection rules, workflow de PR (o fluxo do projeto não usa PRs).
