# Avaliação Estratégica — Ecossistema Valéria

**Data:** 2026-04-20
**Natureza:** Este documento **não é um plano de implementação**. É uma avaliação crítica de produto/processo/inovação da arquitetura agêntica atual, pedida antes de ligar a máquina em produção. O "plano" aqui é diagnóstico e recomendação, não changelog.

---

## Contexto

A Valéria está pré-launch. A arquitetura (orquestrador único em `backend/app/agent/orchestrator.py`, `prompt_key` dinâmico inbound/outbound, 4 stages de negócio via tool `mudar_stage`, persistência em Supabase) **funciona como sistema**, mas a questão que importa agora não é "tá buildado?" — é **"quando encostar no caos do mundo real, isso soa humano ou engessado?"**.

O usuário pediu uma avaliação em três camadas: **(A)** stress test dos modos de falha conversacional prováveis, **(B)** onde Valéria se posiciona no espectro 2026 do que as empresas inovadoras estão fazendo, e **(C)** plays de disrupção que valem considerar antes/depois do launch.

Este documento é opinativo de propósito. Onde eu achar que uma escolha é frágil, vou dizer.

---

## Parte A — Stress Test de Fluidez

Os 7 modos de falha mais prováveis quando a Valéria encontrar o mundo real. Organizados por probabilidade × impacto na percepção de "é humano ou é bot?".

### A1. Classificação destrutiva em buckets mutuamente exclusivos

**O que quebra:** O prompt da secretária (`valeria_inbound/secretaria.py:60-119`) força o lead em **uma** de 4 categorias via `mudar_stage`. Mas a realidade B2B tem sobreposição constante:

- "Tenho cafeteria mas quero lançar minha marca própria" → ATACADO + PRIVATE_LABEL
- "Vou abrir um café em Lisboa" → CONSUMO pessoal + EXPORTAÇÃO
- "Sou revendedor mas pra um cliente que quer exportar" → ATACADO + EXPORTAÇÃO

**Por que soa bot:** o agente "escolhe um caminho" e a conversa passa a conduzir o lead *para aquele stage*. O lead sente que foi categorizado e perde interesse em tocar no outro ângulo.

**Como as melhores resolvem:** Sierra, Decagon e os agentes de ponta não fazem classificação exclusiva. Mantêm um **perfil multi-intent contínuo** — múltiplas hipóteses vivas simultaneamente, com confiança variável, re-avaliadas a cada turno. O "stage" vira um *peso*, não uma chave.

**Severidade: Alta.** Esse é provavelmente o modo de falha mais comum em B2B de café especial, onde a fronteira entre "comprador" e "empreendedor com marca" é fluida.

---

### A2. `mudar_stage` é uma transição sem undo

**O que quebra:** A troca de stage recarrega o prompt (`orchestrator.py:136-143`). Se a secretária classificou mal e o lead corrige 2 mensagens depois ("ah, não, pra exportação"), o sistema precisa voltar — mas o prompt atual já é `atacado.py`, que não tem vocabulário de exportação carregado. A "volta" depende do próprio agente chamar `mudar_stage` de novo, o que raramente acontece naturalmente.

**Como as melhores resolvem:** *intent drift detection* contínua — o modelo re-avalia intent a cada turno comparando contra todo o histórico, não só contra o turno atual. Transições são reversíveis e baratas.

**Severidade: Média-Alta.** Pouco frequente, mas quando acontece é muito visível pro lead.

---

### A3. Preços e catálogo hardcoded no prompt

**O que quebra:** `atacado.py` carrega preços e MOQs em texto. Quando preço muda (regra de negócio óbvia em commodity como café), precisa PR + redeploy. Até lá, a Valéria mente com confiança.

**Por que soa bot:** paradoxo — o bot **parece mais seguro** quando na verdade está errado. O lead confere com o vendedor humano e pega a IA mentindo. Credibilidade zero dali em diante.

**Como as melhores resolvem:** prompt enxuto + tool `consultar_preco(sku, quantidade, origem)` que lê da fonte canônica (banco, ERP, planilha). O prompt fica "se o lead pedir preço, chame a tool — nunca invente".

**Severidade: Alta.** Não é questão de *se* vai acontecer, é *quando*.

---

### A4. Zero memória entre conversas do mesmo lead

**O que quebra:** Cada nova janela Meta 24h começa virgem. Se o lead respondeu, pediu orçamento, sumiu por 3 semanas e voltou, a Valéria não sabe de nada. `messages` tem histórico, mas não há *síntese* carregada.

**Por que soa bot:** frase-assassina do lead: *"eu já falei isso pra vocês"*. É o ponto onde o humano sente que está reiniciando. Em ciclo de vendas B2B de café (semanas a meses), isso vai acontecer direto.

**Como as melhores resolvem:** perfil de lead persistente e resumido (mem0, Letta, ou simplesmente uma tabela `lead_profile` com `summary`, `open_questions`, `objections_raised`, `last_action`). Alimentada por um sumarizador ao fim de cada conversa e recuperada no início da seguinte.

**Severidade: Alta.** Especialmente em ATACADO e EXPORTAÇÃO, onde o ciclo é longo.

---

### A5. Single-modal num canal multi-modal

**O que quebra:** WhatsApp é áudio, imagem e PDF. Cliente B2B manda áudio de 90s explicando o negócio, foto do café da concorrência que quer igualar, PDF de spec do que já compra. Valéria hoje: texto só.

**Por que soa bot:** a falha é silenciosa. A Valéria responde algo genérico ou ignora, e o lead entende que "não adianta mandar áudio, ele não escuta".

**Como as melhores resolvem:** pipeline com transcription (Whisper/Gemini audio) + vision (Claude vision / Gemini) injetados como contexto textual rico antes do agente. Tool `analisar_imagem` / `transcrever_audio` quando quiser inspecionar de propósito.

**Severidade: Alta em B2B café.** Voz é o default de muito comprador brasileiro em WhatsApp.

---

### A6. Outbound é "dispara e reza" — não há orquestração durável

**O que quebra:** Broadcast dispara o template (`broadcast/worker.py:232-243`), marca `agent_profile_id`, e o sistema fica reativo. Cenários não cobertos:

- Lead abriu o link do catálogo mas não respondeu → silêncio total.
- Janela de 24h fechando sem resposta → nenhum nudge.
- Resposta do lead às 3h da manhã, Valéria processa na hora → soa ansioso demais ("respondeu às 3h01").
- Lead não respondeu em 48h → nenhum follow-up, embora o prompt outbound seja feito exatamente pra isso.

**Como as melhores resolvem:** workflows duráveis (Vercel Workflow, Temporal, Inngest). O outbound vira uma máquina de estados persistente — passos declarativos com timeouts, retries, nudges e fallbacks. **O próprio hook do sistema já sinalizou isso como relevante** (e está certo).

**Severidade: Crítica para outbound.** Valéria-outbound sem workflow durável é meio time.

---

### A7. Handoff humano é um terminal, não um ciclo

**O que quebra:** A tool `encaminhar_humano` fecha a participação da IA. Se o humano não responde em 2-4h, ninguém cutuca. O lead fica pendurado — pior cenário pra fluidez, porque agora o **humano + a IA juntos** pareceram bot.

**Como as melhores resolvem (Sierra, Decagon, Intercom Fin 2):** handoff é uma *fase*, não um fim. A IA continua observando, cutuca o humano internamente se silêncio > X min, resume a conversa com contexto quando o humano aparece, e pode reassumir se o humano pedir ou sumir. "Warm handoff" com resumo automático.

**Severidade: Média hoje (volume baixo), Alta quando escalar.**

---

### Resumo A — priorização pré-launch

| # | Modo de falha | Severidade | Ação mínima viável antes de ligar |
|---|---|---|---|
| A1 | Buckets exclusivos | Alta | Adicionar ao prompt da secretária: "se houver sobreposição, cite ambos e pergunte qual tratar primeiro". Patch barato, não resolve de raiz. |
| A2 | `mudar_stage` sem undo | Média-Alta | Aceitar no curto prazo; mitigar via prompt "se perceber que classificou errado, chame `mudar_stage` de novo". |
| A3 | Preço hardcoded | Alta | Auditoria dos prompts e extração para tool. **Não ligue a máquina sem isso.** |
| A4 | Zero memória inter-conversas | Alta | Tabela `lead_profile.summary` + carregamento no início da conversa. 1-2 dias de trabalho. |
| A5 | Mono-modal | Alta | Mínimo: transcrição de áudio automática antes de passar pro agente. |
| A6 | Outbound não durável | Crítica pro outbound | **Workflow durável (ver Parte C, play 3).** |
| A7 | Handoff terminal | Média → Alta com escala | Aceitar hoje; endereçar no ramp-up. |

---

## Parte B — Onde Valéria Está no Espectro 2026

### A escala de maturidade de agentes de vendas/CS em 2026

**L1 — Scripted bot** (fluxogramas, árvores de decisão). Intercom/Drift de 2020. Obsoleto.

**L2 — Single-prompt LLM scripted.** Um system prompt monstruoso + histórico. "ChatGPT vende pra mim". Frágil, mas funciona.

**L3 — Stage-based agent com tools** ← **Valéria está aqui.** Prompt segmentado por stage, tool-calling básico, transições manuais, estado em banco. É onde a maioria dos produtos "IA de vendas" de nicho estão em 2026.

**L4 — Tool-centric agentic (padrão Anthropic/OpenAI).** Prompt enxuto + conjunto rico de tools (consultar catálogo, enviar mídia, RAG na base de conhecimento, classificar intent via tool dedicada). Agente decide dinamicamente, não segue script por stage. Prompts não carregam dados.

**L5 — Multi-agent + memória persistente + workflow durável.** Agente supervisor delega a especialistas; memória de longo prazo por lead/cliente; workflows que sobrevivem a crashes e agendam proatividade. Sierra, Decagon, Harvey (no vertical legal), 11x/Artisan (SDR outbound) operam aqui.

### Players de referência relevantes

**Concorrentes diretos outbound (estude com atenção):**
- **11x.ai ("Alice")** — SDR outbound IA com enrichment, cadência multi-canal (email + LinkedIn + WhatsApp), memória por conta. Levantou ~$75M. O modelo mental é: *agente + base de conhecimento + workflow*, não *agente + prompt*.
- **Artisan ("Ava")** — mesmo jogo, mais focado em email.
- **Regie.ai** — híbrido com forte RAG em playbooks da empresa.

**Referência em CS/conversa (aprenda a arquitetura):**
- **Sierra** (fundada por Bret Taylor) — multi-agent, handoff humano impecável, memória persistente. Define o padrão de "não soa bot".
- **Decagon** — enterprise CS, foca em eval harness e observability.
- **Replicant** — voice-first, trata áudio como cidadão de primeira classe.

### Gap analysis honesto

**O que você faz bem hoje:**
- Separação inbound/outbound por `prompt_key` dinâmico é **mais sofisticado** do que 80% das soluções DIY que vejo no mercado brasileiro. Muitos times nem diferenciam contexto.
- Tool-calling (`mudar_stage`, `salvar_nome`, `encaminhar_humano`) já está na arquitetura certa — base sólida pra evoluir.
- Prompt outbound ter ETAPA 0 explícita ("não inicie com perguntas sobre fornecedor, vá direto ao produto") mostra maturidade de produto. Isso é raro.

**O que você NÃO tem e a fronteira tem:**
1. **Dados do lead enriquecidos antes da conversa** (site, LinkedIn, Instagram do negócio). 11x faz isso automaticamente; você manda template cego.
2. **Memória persistente entre conversas** (ver A4).
3. **Workflows duráveis no outbound** (ver A6).
4. **Multi-modalidade** (A5).
5. **Eval harness/observability** — Sierra publica NPS de conversas; Decagon tem dashboards de "bot-score" por turno. Você não tem nenhum sistema pra saber *objetivamente* se a Valéria tá boa.
6. **Prompt-as-data, não prompt-as-code** — hoje seus prompts estão em `.py`. Mudar tom ou preço exige commit. Players sérios têm CMS de prompts com versionamento, A/B test e rollback.

### Veredicto honesto

**Valéria está em L3 sólido, subindo pra L4.** Isso é muito bom para o estágio (pré-launch, time pequeno, custo controlado). Mas:

- **Para competir no outbound B2B** (especialmente contra players globais entrando no Brasil), você precisa subir para L5 em 12-18 meses.
- **Pro café especial Canastra especificamente**, há vantagem defensável: ninguém vai construir um agente de vendas tão específico pra *sua* operação quanto você. Mas **a camada de infraestrutura** (memória, workflow, multi-modal, eval) é commodity que todo mundo terá.

**O risco real não é a concorrência te ultrapassar em IA.** É o lead ter conversado com uma Alice (11x) da semana passada e chegar na sua Valéria achando que "IA de vendas brasileira é engessada". A régua de fluidez é definida por players globais, não pelo nicho.

---

## Parte C — Plays de Disrupção

Ranqueados por **impacto × esforço** e por **momento ideal** de aplicação.

### Play 1 — Eval harness sintético pré-launch 🔥

**O play:** antes de ligar a máquina, gerar 30-50 personas sintéticas de lead via LLM (lead agressivo, lead indeciso, lead que pede desconto de cara, lead com objeção de preço, lead multi-intent, lead que manda áudio, lead que some e volta, lead que corrige a categoria no meio, etc.). Rodar Valéria contra elas em batch. Um **LLM-as-judge** (modelo diferente) avalia cada conversa em dimensões: *fluidez*, *tom humano*, *conclusão do objetivo do stage*, *bot-score* (0-10), *taxa de falha em modos A1-A7*.

**Por que é o #1:** você **literalmente pediu** "validar fluidez antes de ligar a máquina". Isso é a ferramenta exata. Sem isso, o primeiro teste de stress é em clientes reais — e os erros ficam públicos.

**Esforço:** baixo. 2-4 dias. Reusa a própria Valéria e um modelo externo como juiz. Pode ser um script Python + planilha de resultados inicialmente.

**ROI:** altíssimo. Vira infra permanente: cada mudança de prompt passa a poder ser validada em 5 minutos antes de ir pra produção.

**Quando:** **antes do launch. Gate zero.**

---

### Play 2 — Perfil contínuo multi-dimensional em vez de 4 buckets

**O play:** substituir `conversations.stage ∈ {secretaria, atacado, private_label, exportacao, consumo}` por um objeto `lead_profile` com scores contínuos:
```
{
  p_atacado: 0.7, p_private_label: 0.4, p_exportacao: 0.1, p_consumo: 0.0,
  maturity: "descoberta" | "consideracao" | "decisao",
  objections_raised: [...],
  signals: { mencionou_concorrente: true, pediu_preco: false, ... }
}
```
Atualizado a cada turno. O prompt do agente é composto dinamicamente: "seu lead é 70% atacado e 40% private_label, fale de ambos e descubra qual tratar primeiro".

**Por que vale:** resolve A1 e A2 de raiz. Matching com como humanos pensam em leads ("esse cara é mais atacado, mas tem um quê de marca própria"). Zero perda de informação na transição.

**Esforço:** médio-alto. Refatoração do state management + ajuste dos prompts para consumirem perfil em vez de stage. 1-2 semanas.

**Quando:** pós-launch, quando tiver dados reais pra calibrar os scores.

---

### Play 3 — Outbound como workflow durável

**O play:** migrar outbound de "dispara e reza" para um workflow durável (Vercel Workflow é a ferramenta natural no seu stack). O fluxo vira:

```
dispara_template → aguarda_resposta(24h, evento: mensagem_do_lead)
  → respondeu: inicia_agent_loop
  → não respondeu, mas abriu_link: nudge_suave
  → não respondeu, janela_fechando: fallback_template_2 (com template de reengajamento)
  → ghost: marca lead como frio, agenda retry em 14d
```

Cada passo sobrevive a deploy, crash e restart. Retries são automáticos. Timeouts são declarativos.

**Por que vale:** resolve A6. Transforma outbound de esforço linear (cada lead é um problema manual quando algo foge do script) em máquina que opera 24/7 com comportamentos proativos. É a diferença entre 11x e um chatbot.

**Esforço:** médio. Vercel Workflow foi feito exatamente pra isso. 1-2 semanas pra um MVP de 1 workflow.

**Quando:** próximos 60-90 dias, pós-launch, depois que o fluxo reativo estiver estável.

---

### Play 4 — Memória persistente por lead

**O play:** `lead_profile.summary` em Supabase, gerado por um sumarizador (LLM barato tipo Haiku) ao fim de cada conversa, carregado no início da próxima. Conteúdo: perfil do negócio do lead, objeções já tratadas, promessas feitas (enviar catálogo, cotação), próximo passo pendente.

**Por que vale:** resolve A4. Em B2B com ciclo longo, é o que transforma "bot que reinicia" em "pessoa que lembra".

**Esforço:** baixo-médio. 2-4 dias. Reusa infra Supabase existente.

**Quando:** nos primeiros 30 dias pós-launch.

---

### Play 5 — Self-critique antes de enviar

**O play:** antes de cada mensagem da Valéria sair, um segundo LLM (pequeno, rápido) critica: *"isso soa humano? tá cumprindo o objetivo do stage? viola alguma regra? tá assumindo algo que o lead não disse?"*. Se achar problema, pede re-geração.

**Por que vale:** mata 80% das "falas de bot" com custo marginal. Usado pela Sierra, Decagon, Anthropic no próprio Claude.

**Esforço:** baixíssimo. 1-2 dias. +1 chamada LLM por mensagem (+30-100ms, alguns centavos).

**Quando:** pode ser imediato, inclusive pré-launch se o eval harness (Play 1) mostrar que melhora o bot-score.

---

### Play 6 — Self-learning de prompts via conversão

**O play:** job noturno analisa conversas de 7 dias, separa convertidas vs não convertidas, e um agente "prompt optimizer" sugere edits nos system prompts (ex: "adicione esse jeito de quebrar objeção de preço, funcionou em 8/10 conversões"). Edits propostos vão pra revisão humana (PR automático).

**Por que vale:** os prompts melhoram sozinhos com dados reais. DSPy, OpenAI Prompt Optimizer e a linha de pesquisa "TextGrad" provam que funciona.

**Esforço:** alto. 2-4 semanas pra algo decente.

**Quando:** 6-12 meses. Precisa de volume de conversas (mínimo ~500/mês por categoria) pra sinal ser confiável.

---

### Ranking consolidado

| Play | Impacto | Esforço | Quando |
|---|---|---|---|
| 1. Eval harness | Crítico | Baixo | **ANTES do launch** |
| 5. Self-critique | Alto | Baixíssimo | Pré ou logo após launch |
| 4. Memória de lead | Alto | Baixo-Médio | Primeiros 30 dias |
| 3. Outbound durável | Alto pro outbound | Médio | 60-90 dias |
| 2. Perfil contínuo | Alto | Médio-Alto | 90-180 dias |
| 6. Self-learning | Muito alto (longo prazo) | Alto | 6-12 meses |

---

## Recomendação final: 3 decisões, não 300

Se você só tiver energia pra absorver 3 coisas desse documento, que sejam essas:

1. **Antes de ligar a máquina, faça o eval harness (Play 1) e conserte preços hardcoded (A3).** Sem isso, o primeiro bug em produção vai ser "a Valéria mentiu um preço" ou "a Valéria travou num caso que eu nunca pensei". Os dois são reputacionalmente caros.

2. **Sua arquitetura está em L3 sólido e isso é bom para o momento.** Mas **a régua que o lead vai usar pra julgar fluidez é L5** (Sierra, 11x, Alice). Aceite que nos primeiros 90 dias alguns leads vão estranhar — e foque em instrumentar pra aprender com isso, não em buildar features.

3. **A ordem de evolução pós-launch deveria ser: memória de lead (A4/Play 4) → outbound durável (A6/Play 3) → multi-modal (A5) → perfil contínuo (A1/Play 2).** Nessa ordem porque cada um desbloqueia o próximo em termos de dados + aprendizado. Não comece pelo que é mais "sexy" arquiteturalmente; comece pelo que fecha o gap de humanização mais rápido.

---

## O que este documento NÃO cobre (de propósito)

- Custo de LLM em escala — não era a dor do usuário.
- Performance/latência — prematuro, sem tráfego real.
- Segurança, PII, LGPD — importante mas fora do escopo estratégico pedido.
- Code review dos prompts — usuário explicitamente pediu pra não fazer.

---

## Arquivos críticos se alguma dessas recomendações virar implementação

- `backend/app/agent/orchestrator.py` — onde o `prompt_key` resolve, ponto natural para injetar perfil contínuo (Play 2) ou self-critique (Play 5).
- `backend/app/agent/prompts/*/*.py` — onde os preços hardcoded vivem (A3).
- `backend/app/buffer/processor.py` — onde a memória de lead (Play 4) seria carregada no início da conversa.
- `backend/app/broadcast/worker.py` — ponto de migração para workflow durável (Play 3).
- `docs/superpowers/plans/2026-04-16-multi-agent-outbound.md` — spec atual do outbound, referência.

## Verificação (como validar se a avaliação faz sentido)

Não há código pra rodar. Validação qualitativa:

1. Leia a Parte A e marque quais dos 7 modos de falha você **sentiu no ar** ao testar manualmente — se ≥ 4 fizerem você assentir, o diagnóstico está calibrado.
2. Escolha 1 play de disrupção pra aprofundar numa conversa de implementação (Play 1 é o candidato natural pré-launch).
3. Se discordar de alguma severidade ou ranking, volte e me diga — o documento é opinativo, não gospel.
