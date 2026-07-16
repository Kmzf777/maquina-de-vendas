# Auditoria de Qualidade — Conversas INBOUND (últimas 24h)

**Data da auditoria:** 10/07/2026 (janela UTC: 2026-07-10T00:27 → 2026-07-11T00:27)
**Escopo:** apenas leads da modalidade INBOUND (excluídas conversas com disparo `cold_reactivation` ou resposta `agent_persona=valeria_outbound` em qualquer ponto do histórico).
**Ambiente:** produção (`tshmvxxxyxgctrdkqvam`), acesso read-only.
**Método:** extração via script temporário (`backend/scripts/temp_audit_inbound.py`, removido após o uso) + leitura integral dos transcritos + heurísticas automáticas (loop, repetição, pedido de humano, vazamento de sistema, ghosting) + validação de preços citados contra a tabela `products`.

## Volumetria

| Métrica | Valor |
|---|---|
| Mensagens totais na janela | 215 |
| Conversas distintas | 44 |
| Conversas OUTBOUND (excluídas) | 32 |
| **Conversas INBOUND auditadas** | **12** |
| Leads inbound distintos | 9 |
| Conversas com flags heurísticas | 4 |

O volume inbound do dia é pequeno (12 conversas), então a auditoria cobriu **100% das conversas**, não uma amostra.

---

## 🔴 Achado grave (sistêmico)

### 1. Mensagens do vendedor persistidas VAZIAS (5 ocorrências no dia)

- **Conversa Nayara Brito** (`e015e28f-a505-4d5f-b73e-2844b838f969`): 4 mensagens `assistant/seller` com `content` vazio (12:49, 13:37, 15:07 ×2 UTC), todas com `wamid=NULL` e `metadata=NULL`.
- **Conversa Carina** (`8f94a0a5-1b81-4d0e-a006-febf34486329`): 1 ocorrência (14:57 UTC), mesmo padrão.

**Diagnóstico:** não é fala da IA — é o caminho de persistência de mensagens enviadas pelo vendedor (provavelmente mídia: áudio/imagem respondendo aos áudios da lead) gravando linha vazia, sem wamid e sem placeholder. A lead reagiu com 👍 depois, ou seja, **o conteúdo chegou no WhatsApp mas não existe no banco**.

**Impacto:** (a) o CRM exibe balões em branco; (b) o histórico usado pela IA, pelo dossiê (`rolling_summary`) e por qualquer auditoria fica cego para o que o vendedor disse; (c) contexto de retomada pós-handoff degradado.

**Recomendação:** investigar o caminho de persistência de mensagem outbound do vendedor para tipos de mídia — gravar placeholder `[audio]`/`[imagem]` + wamid, como já é feito no inbound (`[audio transcrito: ...]`, `[imagem]`).

---

## 🟡 Achados moderados (comportamento do modelo)

### 2. Handoff prematuro por sinal fraco — conversa Nilson Gaspar (`1c735bff`)

O lead é **representante comercial de laticínios** (mussarela/leite) que entrou por curiosidade. Após um "SIM aaaaaaaaa", aplausos "👏👏👏👏" e nenhuma confirmação concreta de interesse/volume, a IA encaminhou como **"private label qualificado"** para o vendedor. A recomendação de abordagem gerada não reflete o perfil real (o lead se despediu logo em seguida: "quando passar pro Paraná, tem um amigo aqui").

Também na mesma conversa: a IA perguntou "quer que eu te mostre os tipos de café e os valores?" e enviou as fotos **sem aguardar resposta afirmativa**.

**Impacto:** polui a fila do vendedor com lead frio rotulado de qualificado.

### 3. Micro-promessa fora de persona — mesma conversa (Nilson)

Lead: *"Quando passar pro Paraná, sabe que tem um amigo aqui"* → Valéria: *"quando passar por aí, te aviso?"*. A persona (atendente virtual) sugeriu que avisaria o lead ao "passar pelo Paraná" — promessa irreal/antropomórfica. Sem dano comercial, mas é vazamento de persona.

### 4. `mudar_stage` inconsistente

- **Nilson (`1c735bff`):** flapping `private_label → atacado → private_label` em ~3 minutos, reagindo a cada áudio ambíguo.
- **João Marcos Martins (`36c6cd74`):** o mesmo gatilho de entrada ("Quero saber mais sobre ter a Marca Própria de Café") que nos outros 3 leads disparou `mudar_stage → private_label` em ~10s **não disparou aqui** — o lead segue em `pending` após 2 turnos da IA. Consequência: a conversa roda sem o catálogo do funil (o catálogo só é injetado para stage ∈ funis conhecidos).

### 5. Handoff verbalizado sem tool-call — conversa Mayckel (`30205e0b`)

A IA verbalizou o encaminhamento ao João sem chamar `encaminhar_humano`; a **guarda determinística** capturou e efetivou o handoff (`handoff verbalizado sem tool-call (guarda deterministica)`). O desfecho foi correto — registrado aqui como evidência de que (a) a guarda recém-implantada está funcionando em produção e (b) o erro de modelo subjacente continua ocorrendo e merece monitoramento.

---

## 🟢 Verificações sem anomalia

| Verificação | Resultado |
|---|---|
| Loops / mensagens repetidas da IA | **Nenhum caso** (0 duplicatas consecutivas, 0 repetições ≥3×) |
| Stack traces / erros de sistema / `tool_code` enviados ao cliente | **Nenhum caso** |
| Alucinação de preço | **Nenhuma** — todos os valores citados (R$26,70 / R$25,70 / R$29,70 / R$27,70 / R$47,70) e lotes mínimos (100 un; 50 un p/ Microlote embalagem do cliente) conferem **exatamente** com a tabela `products` |
| Falha de handoff a pedido do lead | **Nenhuma** — Regina pediu "responsável pelo comercial" e foi encaminhada em 17s, sem a IA insistir |
| Ghosting com IA ligada | **Não confirmado** — João Marcos (candidato) foi respondido 39s após o áudio; ponte pós-handoff (`bridge`) respondeu corretamente leads que continuaram falando com a Valéria |
| Qualidade geral das respostas | Persona consistente, tom adequado, sem carimbo; handoff do Douglas (private label qualificado de verdade) exemplar |

## Observação fora do escopo da IA

Douglas Passos iniciou a conversa com o João (canal do vendedor) às 21:17 UTC com "Olá boa noite" e o dossiê de qualificação estava postado — sem resposta humana até o fim da janela (~3h). Latência do time comercial, não da IA, mas afeta a experiência do lead mais quente do dia.

## Priorização sugerida

1. **P1 — bug de persistência de mensagem de vendedor vazia** (achado 1): perda real de dados em produção, 5 ocorrências/dia.
2. **P2 — critério de qualificação do handoff** (achado 2): exigir sinal concreto (interesse + contexto de negócio) antes de rotular "qualificado".
3. **P3 — consistência do `mudar_stage`** (achado 4): investigar por que o gatilho padrão não moveu o lead João Marcos de `pending`.
4. **Monitorar** — taxa de acionamento da guarda determinística de handoff (achado 5) como métrica de saúde do modelo.
