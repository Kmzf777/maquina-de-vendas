# Conversões infladas no Google Ads — spec

**Data:** 2026-10-14
**Cartão:** "URGENTE: Conversões infladas no Google Ads (Lead_Qualificado somando com Lead_Captado)"
(cf1d26dd, quadro BEEINSIDE CANSTRA CRM)
**Branch:** `agente/cf1d26dd`, criado de `origin/master` (8a4c5f55)
**Base:** `2026-10-13-conversoes-ads-ativacao-design.md` (cartão 23ab1cc4, publicado em 13–14/10)

---

## 1. Problema

A Tati (tráfego), em 14/10: "começou a aparecer agora a lead qualificado… tem 29 de terceirização e 9
de lead qualificado. E está contando. Então quer dizer que está duplicando?… compromete completamente
as campanhas".

Print da campanha "Leads-Search | Terceirização | 20.03.24": total **43,43** = Conversation started
4,00 + Atacado 2 obg 0,96 + Terceirização 2 Obg 29,04 + **Lead_Qualificado 9,44**.

### Diagnóstico (conferido em produção, só leitura)

- **Não é duplicação do mesmo evento.** `ad_conversions` em 14/10: Google qualified 345, purchase 41,
  opportunity 2; Meta qualified 48. Zero `event_id` repetido por plataforma e zero lead com duas linhas
  na mesma plataforma×etapa. O `transactionId` (= `event_id`) é estável e o Google deduplica por ele.
- **É soma de ações diferentes.** A mesma pessoa conta quando chega (conversões do site / WhatsApp) e de
  novo quando é qualificada. Em 13/10 a Tati deixou **Lead_Qualificado e Venda_Fechada como principais**,
  e toda principal entra na coluna "Conversões".
- **Agravante:** a ativação de 14/10 mandou de uma vez o histórico de 90 dias (345 qualificados). O
  Google contabiliza pela data do evento/clique, então os relatórios mudaram para trás.

### "Lead_Captado"

Não existe ação Lead_Captado no código: desde 13/10 a etapa `lead` (clique) não vai ao Google. O
"Lead captado" do funil já existe na conta como **metas personalizadas** (prints da Tati, 14/10):

- **Empório e Cafeteria** = Atacado 2 obg (7382055753) + Conversation started (7288479086)
- **Terceirização** = Terceirização 2 Obg (7394745545) + Conversation started (7288479086)

A Tati pediu que o nome "Lead_Captado" seja trocado por esses nomes. Não se cria ação nova no Google.

## 2. Decisões

| Tema | Decisão |
|---|---|
| Correção principal | Na conta do Google Ads (Tati): Lead_Qualificado, Oportunidade_Criada e Venda_Fechada viram **secundárias**; as metas Empório e Cafeteria / Terceirização seguem como principais. Não é código. |
| Janela retroativa | Configurável por `CONVERSIONS_BACKFILL_DAYS`, **padrão 90** (Rafael, 14/10: "é assim que está configurado no Google Ads; trocar para 30 ou 7 perde a inteligência adquirida"). Com 90, o comportamento atual não muda. |
| Proteção contra o salto | **Modo simulação** (`CONVERSIONS_DRY_RUN`) + script `simular_ativacao`: antes de qualquer reativação, mostra quantos eventos sairiam por plataforma × etapa e por idade, sem gravar nem enviar. |
| Eventos já enviados | Os 345+41+2 (Google) e 48 (Meta) **não são reenviados nem apagados**. |
| Lead_Captado | Renomeado na documentação para as metas "Empório e Cafeteria" e "Terceirização". O rótulo "Lead" da aba Conversões enviadas não muda (a etapa não é enviada). |

## 3. O que muda no código

Repo `ValerIA`, `backend/`.

### 3.1 Relatório de duplicatas — `app/conversions/audit.py` (novo) + `scripts/conversoes/checar_duplicatas.py` (novo)

- `find_duplicates(rows)` — função pura. Recebe linhas de `ad_conversions`
  (`id, lead_id, platform, stage, event_id, sale_id, status`) e devolve três listas de grupos repetidos:
  1. **por lead × etapa × plataforma** para `qualified`/`opportunity`/`lead` (deve haver no máximo um);
  2. **por venda × plataforma** para `purchase` (`sale_id`);
  3. **por `event_id` × plataforma**.
  Cada grupo traz a chave, a quantidade e os `id`/`status` das linhas. Linhas `ignorado` e
  `fora_da_janela` (nunca enviadas) não contam.
- O script lê `ad_conversions` inteira (`paginar`), chama `find_duplicates`, imprime o total de linhas
  por plataforma × etapa e os grupos duplicados (ou "0 duplicatas"). Sai com código 1 se houver
  duplicata. Só leitura.
  Uso: `python -m scripts.conversoes.checar_duplicatas` (no container, em `/app`).

### 3.2 Janela retroativa — `app/conversions/sweep.py` e `sender.py`

- `backfill_window()` (em `eligibility.py`): lê `CONVERSIONS_BACKFILL_DAYS`; ausente/inválido → 90;
  limitado a 1..90. Aplica-se à **idade do evento** (`now - event_at`); as janelas das plataformas
  (Meta 7 dias do evento, Google 90 dias do clique) seguem valendo por cima.
- **Varredura:** `LOOKBACK` passa a ser `backfill_window()`; `build_candidates` não gera evento com
  `now - event_at > backfill`.
- **Sender:** linha `pendente` com `event_at` mais velho que a janela vira `fora_da_janela` (mesmo
  tratamento que já existe para a janela da plataforma), sem envio.

### 3.3 Modo simulação

- `run_sweep(now, dry_run=False)`: com `dry_run`, monta os candidatos, consulta quais `dedupe_key` já
  existem e **não** faz upsert. Devolve e loga `[CONVERSOES][SIMULACAO]` com novos por plataforma ×
  etapa e por faixa de idade do evento (≤7, 8–30, 31–90 dias).
- `run_sender(now, limit, dry_run=False)`: com `dry_run`, só conta as linhas que seriam enviadas (já
  aplicando janelas e plataformas prontas), sem claim, sem envio, sem update. Loga a contagem.
- Worker: as tarefas `conversions-sweep` e `conversions-send` passam `dry_run=True` quando
  `CONVERSIONS_DRY_RUN=true`. Ausente → comportamento atual.
- Script `scripts/conversoes/simular_ativacao.py [--dias N]`: roda varredura e sender em `dry_run`
  (com a janela `N` se informada) e imprime a tabela. Não precisa de `CONVERSIONS_*_ENABLED`
  (simula as duas plataformas).

### 3.4 Documentação — `docs/setup/conversoes-ads.md`

- Ações do CRM no Google são **secundárias**; a coluna "Conversões" fica com as metas do site/WhatsApp.
- "Lead captado" = metas **Empório e Cafeteria** e **Terceirização** (composição acima); nenhuma ação
  Lead_Captado.
- `CONVERSIONS_BACKFILL_DAYS`, `CONVERSIONS_DRY_RUN` e os dois scripts. Regra: **rodar
  `simular_ativacao` antes de qualquer reativação** (pausa, etapa ou plataforma nova).

### Testes automatizados (TDD)

- `tests/test_conversions_audit.py`: sem duplicata → listas vazias; duas linhas do mesmo lead×etapa×
  plataforma → 1 grupo; mesmo `event_id` → 1 grupo; mesma venda duas vezes → 1 grupo; linha
  `ignorado` não conta; mesmo lead em plataformas diferentes não é duplicata.
- `tests/test_conversions_sweep.py`: com janela 30, evento de 40 dias não vira candidato e de 20 vira;
  janela ausente → 90; valor inválido → 90; valor > 90 → 90; `dry_run` não chama upsert e devolve as
  contagens.
- `tests/test_conversions_sender.py`: linha pendente fora da janela → `fora_da_janela` sem chamar o
  cliente; `dry_run` não chama cliente nem grava.
- Suíte de backend inteira verde.

## 4. Google Ads (Tati, fora do código)

1. Lead_Qualificado, Oportunidade_Criada e Venda_Fechada → secundárias (desmarcar "Incluir em
   Conversões"). Elas seguem visíveis em "Todas as conv.".
2. Conferir na campanha Terceirização que "Conversões" volta a somar só Terceirização 2 Obg +
   Conversation started (meta Terceirização).
3. Avaliar com a Tati o efeito dos dados retroativos de 14/10 nos relatórios e nos lances.

O agente entrega ao Rafael o texto para a Tati; não mexe na conta.

## 5. Como testar em modo teste

Onde: worktree `agente/cf1d26dd` (local) e um **container descartável** na VPS com a imagem
`canastra-api` e o código do branch montado (não toca nos serviços).

1. `python -m pytest -q tests` no container descartável — tudo verde.
2. `checar_duplicatas` contra o banco de produção (só leitura) → **0 duplicatas** esperado.
3. `simular_ativacao` contra o banco de produção, com as plataformas **desligadas** no container
   (sem credenciais) → tabela por plataforma × etapa × idade; confirmar que nada foi gravado
   (`count(*)` de `ad_conversions` igual antes e depois) e que nada foi enviado.
4. `simular_ativacao --dias 30` → números menores que com 90.

Não há tela nova: a evidência é a saída dos scripts e a contagem SQL antes/depois (vira print de texto
no relatório). Nenhum envio a Meta ou Google nesta fase.

## 6. Como publicar

Depois do [Liberar produção]:

1. Merge de `agente/cf1d26dd` em `master` + `git push origin master`. O GitHub Actions (`deploy.yml`)
   faz `docker stack deploy` de `canastra` e `service update --force` em `canastra_api` e
   `canastra_worker` (e `crm_crm`, sem mudança de frontend).
2. Sem migration. Sem mudança no `.env`: sem `CONVERSIONS_BACKFILL_DAYS` vale 90 (igual a hoje); sem
   `CONVERSIONS_DRY_RUN` o envio segue normal.

**Voltar atrás:** `git revert` do merge em `master` + push (redeploy). Nenhum dado é alterado pela
mudança.

## 7. Como testar em produção

- `docker exec` no container do `canastra_worker`: `python -m scripts.conversoes.checar_duplicatas`
  (só leitura) → 0 duplicatas; `python -m scripts.conversoes.simular_ativacao` (dry-run) → tabela,
  `count(*)` de `ad_conversions` igual antes e depois.
- Logs do worker (`docker service logs canastra_worker`): varredura e sender seguem com as linhas
  `[CONVERSOES]` normais.

**Ação real com efeito externo:** nenhuma nova. O teste usa só leitura e dry-run. O worker continua
enviando as conversões reais como já faz desde 14/10 (comportamento inalterado com a janela de 90).

## 8. Fora de escopo

- Reenviar, apagar ou "retirar" os eventos já enviados (não há como retirar no Google/Meta; precisaria
  de aprovação do Rafael).
- Mexer na conta do Google Ads (é da Tati) e mudar a janela de conversão das ações no Google.
- Enviar a etapa `lead` ou criar ação Lead_Captado.
- Mudanças na aba "Conversões enviadas" do /trafego.
