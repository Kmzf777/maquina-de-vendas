# Espelho visual do motor de follow-up no builder de Cadências

## Problema

A lógica temporal do follow-up da Valéria (T1 same-day+jitter, T2 D+1, T3 D+3, T4
D+6h20, nudge outbound +18h, janela de 24h da Meta → template de reabertura, R1) vive
só em `follow_up/cadence.py`. A diretriz: o operador abre a aba Cadências, clica na
cadência da Valéria e vê o fluxo como fluxograma no builder React Flow existente
(`/campanhas/cadencias/[id]`, tabelas `campaigns`/`campaign_nodes`).

## Alternativas

1. Card virtual só no frontend — zero risco de execução, mas não fica no banco (viola
   a diretriz) e não abre no builder real.
2. Seed one-shot (script) — drifta silenciosamente a cada mudança do cadence.py.
3. **Espelho sincronizado no startup (ESCOLHIDA)** — módulo backend constrói o grafo A
   PARTIR do cadence.py (importando os `objective_prompt` reais e as constantes do
   template de reabertura do scheduler) e faz upsert idempotente no boot da API. Cada
   deploy re-sincroniza; edição manual dos nós se auto-cura no próximo deploy.

## Identidade e segurança de execução

- Campanha de sistema com UUID FIXO determinístico
  `uuid5(NAMESPACE_URL, "canastra://system/valeria-followup-cadence")` =
  `d4a7ffa3-62c2-51c4-91fc-5fcc06ec9055`; nós também com uuid5 por chave estável
  ("trigger", "t1", "wait1"…) — permite insert com FKs num único passe (ordem topológica
  reversa) e sync idempotente por delete+insert.
- `status` PERMANENTE `draft`: o automation engine só executa campanhas `active`
  (gates em `get_due_enrollments`/`_process_one` e `get_campaigns_with_trigger_type`).
- Guardas anti-ativação (409) para o UUID de sistema em AMBOS os caminhos: FastAPI
  `POST /{id}/activate` e `POST /{id}/enrollments`, e rota Next
  `/api/campaigns/[id]/activate`; DELETE também recusado nos dois.
- Builder: banner "Cadência de sistema — espelho somente-leitura do motor" e o toggle
  Ativar/Pausar substituído pelo banner quando `campaign.id` é o UUID de sistema
  (constante duplicada em `frontend/src/lib/system-campaign.ts`, com teste que fixa o
  literal). Edições de nó não são bloqueadas na UI — o re-sync de deploy as desfaz.

## Mapeamento motor → nós do builder (fidelidade)

Trigger `no_message` (days 0 = silêncio pós-turno; a cadência real é re-armada a cada
turno do agente) → `send_text` **T1** (message_text = cabeçalho com offset/jitter/janela
comercial + o `objective_prompt` REAL do toque; `on_reply: "cancel"` — espelha o
cancelamento da cadência quando o lead responde; nota do nudge outbound +18h no texto)
→ `wait` D+1 (days 1, janela 9–16) → `condition` `replied_recently` days 1 (semântica:
janela de 24h da Meta aberta?) com dois ramos:

- **yes** → `send_text` **T2** (reforço de valor, prompt real) → `wait` days 2 (→D+3)
  → `send_text` **T3** (prova social) → `wait` days 4 (≈D+6h20) → `send_text` **T4**
  (última chamada) → `end` "Cadência concluída — contato pausado".
- **no** → `send` **template de reabertura** com os valores REAIS do scheduler
  (`_REOPEN_TEMPLATE_NAME`, language `en_US`, 3 params posicionais
  primeiro_nome/assunto/data) `on_reply: "pause"` → `end` "Aguardando reabertura — R1:
  T3/T4 se dobram neste template".

A condição de janela é decisiva no T2 (Rodada 5: T2 D+1 vence sempre ~24h+ε após a
última msg do lead); nos demais toques ela também existe no motor e está anotada nos
textos — o grafo prioriza legibilidade sem mentir.

## Componentes

- `backend/app/campaigns/system_cadence.py`: constantes, `build_valeria_cadence_graph()`
  (pura) e `sync_valeria_cadence_campaign()` (upsert campanha por id fixo + delete nodes
  + insert em ordem topológica reversa; `env_tag` = `_ENV_TAG` de campaigns.service).
- `main.py` lifespan: `await asyncio.to_thread(sync_...)` fail-open (log warning).
- Guardas nos routers (backend e Next) por UUID.
- Frontend: `lib/system-campaign.ts` + banner/toggle no `cadence-flow/index.tsx`.

## Testes

- pytest: grafo válido (tipos permitidos, 1 trigger com next, todos os nós alcançam um
  end, ids determinísticos e estáveis); fidelidade (T1 contém objective_prompt de
  CADENCE[0]; nó de reopen usa exatamente `scheduler._REOPEN_TEMPLATE_NAME` e en_US;
  waits 1/2/4; on_reply cancel nos toques livres); sync idempotente (mock supabase:
  upsert+delete+insert; ids iguais em duas execuções); guardas 409 (activate/enroll/
  delete do UUID de sistema).
- vitest: constante do frontend fixada no literal; `toRFEdges` sobre fixture com o
  MESMO shape do grafo (chain trigger→…→end e ramos yes/no do condition) — valida que
  o conversor do builder renderiza as conexões esperadas.
- Smoke pós-deploy: campanha e nós presentes em prod (SQL), `GET
  /api/campaigns/d4a7ffa3-...` no FastAPI devolve nodes embed, activate devolve 409.
