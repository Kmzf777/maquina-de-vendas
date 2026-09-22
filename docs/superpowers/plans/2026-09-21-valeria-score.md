# Valeria Score Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Classificar leads de atacado em tempo de conversa e exibir a lista geral de scores, campanhas de tráfego e Feeling independente no modal de `/campanhas`.

**Architecture:** O backend Python registra evidências estruturadas e calcula o score por função pura. Um backfill idempotente cobre o histórico dos últimos 60 dias pela última interação. O frontend consulta snapshots paginados via rotas autenticadas e grava Feeling em tabela separada.

**Tech Stack:** Python/FastAPI, Supabase/Postgres, Next.js/TypeScript, pytest, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-21-valeria-score-design.md`

## Global Constraints

- Somente a ValerIA escreve critérios objetivos; o cliente nunca envia pontos, prioridade ou critérios pela API.
- Feeling e justificativa pertencem ao vendedor autenticado e não entram no cálculo.
- Score final 10 apenas para substituição do fornecedor e intenção clara; sem essa combinação, 0–6.
- Campos desconhecidos rendem zero provisório; score ausente aparece como `—`.
- Backfill: última interação nos 60 dias anteriores à execução, sem mensagens outbound.
- A implementação acontece na branch `feat/valeria-score`; agentes em paralelo não fazem commits concorrentes.

## Review Focus

- Volume exatamente 30 kg recebe um ponto; volume vago permanece desconhecido.
- Momento exatamente 15 dias recebe um ponto; intervalo ambíguo permanece desconhecido.
- Uma correção explícita posterior do lead substitui valor anterior sem perder a evidência.
- Leads de CTWA usam campanha via `meta_ad_campaigns`; landing pages usam `utm_campaign`.
- Feeling sem justificativa ou de usuário não autenticado é rejeitado.

---

### Task 1: Modelo e persistência do score

**Files:** Create `backend/app/lead_score/__init__.py`, `backend/app/lead_score/model.py`, `backend/app/lead_score/repository.py`, `supabase/migrations/20260921_valeria_score.sql`, `backend/tests/test_lead_score_model.py`, `backend/tests/test_lead_score_repository.py`.

**Interfaces:** `calculate_score(criteria: dict) -> dict` retorna `normal_score`, `final_score`, `priority`, `is_provisional`. `save_score_evidence(lead_id: str, updates: dict, evidence: dict | None = None, source: str = 'live') -> dict` atualiza snapshot e recalcula; não sobrepõe evidência ao vivo com backfill.

- [ ] **Step 1: Write failing tests** para soma, exceção 10, ausência, limites de volume/prazo e mescla parcial. Exemplo:

```python
assert calculate_score({'segment': 'cafeteria', 'monthly_volume_kg': 30,
    'supplier_reason': 'replace', 'purchase_timing': 'within_15_days',
    'purchase_intent': 'clear'})['final_score'] == 10
```

- [ ] **Step 2: Run** `cd backend; python -m pytest tests/test_lead_score_model.py tests/test_lead_score_repository.py -q`; verificar falha por módulo ausente.
- [ ] **Step 3: Implement** enums/categorias, cálculo puro, persistência com service Supabase do backend e atualização de campos válidos. Rejeitar valores fora dos enums; preservar `None` de critérios não enviados. Criar duas tabelas separadas, índices de score/prioridade e RLS.
- [ ] **Step 4: Run** o mesmo comando e confirmar aprovação. Registrar arquivos alterados no relatório do agente.

### Task 2: Coleta ao vivo e backfill

**Files:** Modify `backend/app/agent/tools.py`, `backend/app/agent/prompts/base.py`; create `backend/scripts/backfill_valeria_score.py`, `backend/tests/test_lead_score_live.py`, `backend/tests/test_backfill_valeria_score.py`.

**Interfaces:** Consome `save_score_evidence` da Task 1. A ferramenta `qualificar_lead` aceita `segment`, `monthly_volume_kg`, `supplier_reason`, `purchase_timing`, `purchase_intent` e evidência opcional; os argumentos antigos continuam válidos. O backfill expõe `run_backfill(days: int = 60, dry_run: bool = True, limit: int | None = None)`.

- [ ] **Step 1: Write failing tests** para atualização parcial no atacado, nenhuma atualização em outro stage, portões de handoff intactos, extração ambígua e retomada de lote. Exemplo:

```python
assert save_score_evidence_mock.call_args.kwargs['updates']['supplier_reason'] == 'replace'
```

- [ ] **Step 2: Run** `cd backend; python -m pytest tests/test_lead_score_live.py tests/test_backfill_valeria_score.py -q`; verificar falha esperada.
- [ ] **Step 3: Implement** a extensão opcional da tool, instruções de extração com evidência e o backfill paginado usando o modelo existente. Não enviar mensagens nem chamar handoff no backfill. Proteger registros mais recentes feitos ao vivo.
- [ ] **Step 4: Run** testes novos e `python -m pytest tests/test_qualificar_lead_portao_2026_09_09.py -q`.

### Task 3: Rotas de consulta e Feeling

**Files:** Create `frontend/src/app/api/valeria-score/route.ts`, `frontend/src/app/api/valeria-score/[leadId]/feeling/route.ts`, `frontend/src/lib/valeria-score.ts`, testes de rota próximos aos módulos; modify migration da Task 1 se necessário, coordenando com o implementador da Task 1.

**Interfaces:** `GET /api/valeria-score?page=&page_size=&q=&priority=&score=&status=&campaign=&traffic_type=` retorna `{items, total, page, page_size, campaigns}`. `PUT /api/valeria-score/[leadId]/feeling` recebe `{feeling, justification}` e retorna registro do vendedor autenticado.

- [ ] **Step 1: Write failing tests** de sessão ausente, paginação, UTM, mapeamento Meta e validação de Feeling. Exemplo:

```ts
expect(await saveFeeling({ feeling: 'alto', justification: '   ' })).toMatchObject({ status: 422 });
```

- [ ] **Step 2: Run** `cd frontend; npm test -- --run` com foco nos arquivos novos; verificar falha esperada.
- [ ] **Step 3: Implement** rotas com `getCurrentUser`, paginação no servidor, consulta apenas de atacado, lookup de campanha, e escrita somente do Feeling da sessão. Não aceitar critério/score do navegador.
- [ ] **Step 4: Run** testes de rota e `npx tsc --noEmit`.

### Task 4: Modal Valeria Score

**Files:** Modify `frontend/src/app/(authenticated)/campanhas/page.tsx`; create `frontend/src/components/campaigns/valeria-score-modal.tsx` e teste de componente.

**Interfaces:** Consome as rotas da Task 3 sem acesso direto ao banco. O modal recebe `open` e `onClose`, consulta páginas e filtros, mostra os critérios/evidências e salva Feeling.

- [ ] **Step 1: Write failing component tests** de abertura, filtros, estado provisório, score desconhecido, detalhe e justificativa obrigatória. Exemplo:

```tsx
expect(screen.getByText('Valeria Score')).toBeVisible();
expect(screen.getByText('Não identificado')).toBeVisible();
```

- [ ] **Step 2: Run** teste de componente e verificar falha esperada.
- [ ] **Step 3: Implement** botão no cabeçalho, modal responsivo com lista paginada, filtros de score/status/campanha/tráfego e painel de detalhes. Mostrar Feeling separado; não permitir edição de critérios.
- [ ] **Step 4: Run** teste do componente, lint/TypeScript e build quando dependências locais estiverem disponíveis.

### Task 5: Integração e verificação final

**Files:** Somente ajustes necessários nos arquivos das Tasks 1–4; atualizar este plano com resultado dos testes.

- [ ] **Step 1: Review** os diffs de cada frente contra a spec e corrigir incompatibilidades de interfaces.
- [ ] **Step 2: Run** suites de score, portões de qualificação, rotas e modal; executar TypeScript e build do frontend.
- [ ] **Step 3: Validate** migração em banco local/ambiente de teste quando disponível; executar backfill apenas em `--dry-run`, sem alterar dados externos.
- [ ] **Step 4: Record** comandos e resultados no relatório final; entregar branch/worktree e etapas de aplicação de migração/backfill.
