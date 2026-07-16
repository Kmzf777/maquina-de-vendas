# Auditoria Outbound — Valéria — 15/07/2026

**Escopo:** exclusivamente fluxo **Outbound** (disparos ativos onde a Valéria enviou a primeira mensagem). Leads Inbound ignorados.
**Método:** leitura integral dos transcritos via SQL read-only na produção (`supabase-prod`). Janela: `2026-07-15 03:00 UTC` → agora (dia comercial de 15/07 no fuso BRT).
**Postura:** read-only. Nenhum código de orquestrador ou prompt foi alterado.

---

## Sumário Executivo

**Volume outbound do dia (60 conversas):**

| Métrica | Valor |
|---|---|
| Conversas outbound (assistant falou primeiro) | 60 |
| Disparo sem resposta | 18 (30%) |
| Responderam | 42 (70%)¹ |
| Handoff para João | 5 |
| Opt-outs | 5 |
| `registrar_sem_interesse_atual` (soft-park) | 3 |
| `ponte` → silêncio pós-handoff | 3 |

¹ Taxa de resposta alta é **inflada pelo pretexto** do disparo ("estamos atualizando nossos registros de contato… falo com X neste número?"), que induz resposta social antes de qualquer venda.

**Veredito geral:** a Valéria está **operacionalmente sólida** — sem alucinação de ferramentas, opt-outs impecáveis, precificação disciplinada, e vários atendimentos exemplares. As falhas encontradas são majoritariamente de **roteamento/pós-handoff** e **higiene da lista de disparo**, não de linguagem ou raciocínio. Não há nenhum incidente de canal silencioso ou fantasma.

**As 3 piores falhas do dia:**

1. **[ALTA] Cliente queimado devolvido ao vendedor que o queimou (Aislan Piuco).** Disparo re-contatou um cliente com pedido fechado e não entregue; a única jogada de recuperação foi handoff para o João — que o próprio lead identificou como o vendedor que o ignorou repetidas vezes. Lead perdido em frustração.
2. **[MÉDIA] Pedido explícito ignorado + cliente existente re-qualificado do zero (Francine).** Cliente pediu "pode me mandar a tabela?"; a tabela nunca foi enviada. A Valéria rodou o script de lead novo e confundiu a cliente ("não estava te entendendo", "qual nome de sua empresa?").
3. **[MÉDIA] Dead-air pós-handoff em sinal de compra quente (Itamar).** Após o handoff, o lead perguntou "gostaria de visitar a produção, como faço?" e recebeu **silêncio** (ponte), ficando 100% dependente do SLA humano do João.

---

## Categoria ALTA

### A1 — Cliente queimado re-contatado e devolvido ao rep que o queimou — Aislan Piuco (`5554999107411`)
**Conversa:** `afeda947-f703-476d-a207-d5c5d1aa9d3f` · stage `pending` · handoff verbalizado

Sequência real:
- Lead: *"Café faz parte da minha vida e da empresa, só que o porém é que esta difícil de negociar com vocês!"*
- Lead: *"faz quase 1 ano que estou tentando negociar com vocês e não consigo, ultima vez havia fechado o pedido porém não me enviaram mais nada"*
- Valéria (handoff): *"vou deixar o contato do João Bras, nosso supervisor… dá um oi pra ele agora mesmo que ele já te ajuda a finalizar o pedido e ver o que aconteceu com o anterior"*
- Lead: *"Fiz perguntas aos vendedores e não me enviaram mais nada, visualizam e não respondem"*
- Lead (desfecho): **"bah, esse ai é um deles que me deixou varias vezes sem me responder. vou agradecer por tudo!"**

**Por que é grave:** perda de conversão de um cliente com **intenção de compra real e histórico de pedido**, com dano reputacional explícito. A resposta da Valéria foi empática e correta em tom; o problema é **sistêmico**, em duas camadas:
- **Higiene da lista:** o disparo "estamos atualizando registros" atingiu um cliente com reclamação/pedido em aberto, reabrindo uma ferida.
- **Roteamento sem escape:** o único caminho de recuperação da Valéria é o handoff para o João. Não existe rota de **escalonamento acima do João** para casos em que o próprio João é a origem do problema. O lead foi devolvido ao gargalo.

> Observação de auditoria: isto **não** é um erro de prompt da Valéria. É um buraco de processo (escalonamento) + lista. Registrado como ALTA pelo impacto, não pela culpa do modelo.

---

## Categoria MÉDIA

### M1 — Pedido explícito ignorado + re-qualificação de cliente existente — Francine (`5551981162558`)
**Conversa:** `53e2c0da-2b3b-4de2-a04a-a2b603cee20f` · handoff proativo

- Abertura presuntiva: *"você já é cliente aqui com a gente, o que costuma levar por aí?"*
- Lead: *"geralmente compro por outro contato · **pode me mandar tabela?**"*
- **A tabela nunca foi enviada.** A Valéria re-qualificou do zero: "o café entra mais no seu negócio ou consumo?", "qual nome de sua empresa?", "você já tem fornecedor?".
- Lead confusa: *"qual nome de sua empresa?"* → e depois *"Sim, sempre compro dele · **Não estava te entendendo**"*.

**Erros:** (1) **pedido direto e acionável ("manda a tabela") ignorado** — atrito de UX puro; (2) sinal de **cliente existente** ("compro por outro contato" / "compro da serra da canastra") não reconhecido, disparando o funil de lead novo e gerando confusão. Desfecho: handoff para o João — de quem a Francine **já compra**. O loop terminou no lugar certo, mas por um caminho tortuoso e confuso.

### M2 — Dead-air pós-handoff em sinal de compra quente — Itamar (`5531997881510`)
**Conversa:** `db5243ea-7031-4876-8ba2-f93b21f07b9b` · handoff proativo

- Qualificação boa (loja de granéis em Betim/MG, quer café especial moído na hora).
- Handoff disparado com **`volume=a definir` e `urgencia=a definir`** — qualificação fina demais para um handoff proativo.
- Imediatamente após o handoff, o lead: **"Gostaria de visitar a produção, como faço?"** → `[ponte] pergunta de negócio detectada — silêncio, aguardando resposta humana`.

**Erro:** "quero visitar a produção" é entusiasmo de fundo de funil. Responder com **silêncio absoluto** transfere todo o risco de drop-off para o SLA humano. Um reconhecimento mínimo ("que ótimo! o João já te passa como funciona a visita") seguraria o calor sem violar o handoff.

### M3 — Objeção de preço + identidade não respondida, devolução ao rep que já falhou — Sirli Resin (`5548996779200`)
**Conversa:** `a0e7fe17-484f-4719-95ae-c32afcfa2f29` · handoff verbalizado

- Lead (ex-revendedora que saiu por preço): *"não estou mais adquirindo devido o reajuste… o custo elevou muito"*. A Valéria tentou contornar bem a objeção ("por quanto você pretende revender a unidade?").
- Lead: *"Na época eu tentei negociar com o João, mas não chegamos a um acordo"* → **handoff para o mesmo João**.
- Lead: **"Qual sua função na empresa?"** → `[ponte] silêncio`. Pergunta de identidade da lead ficou **sem resposta**.

**Erros:** (1) devolver ao João uma lead que **explicitamente já não fechou com o João** — sem contexto novo, tende a repetir o impasse; (2) o `ponte` engoliu uma pergunta simples de identidade ("qual sua função?") que a Valéria poderia ter respondido sem violar o handoff.

### M4 — Ponte presuntiva falsa + pergunta de mercado desviada — Hueiner Lessa (`5553999132983`)
**Conversa:** `ad8b0ccb-ecd7-4ae6-979c-3e14051cf499` · ai_enabled=true (run completo)

- Ponte do disparo presumiu cliente existente: *"a gente tá retomando contato com a base… **você já compra da gente, né?**"* → Lead: **"Ainda nao"**. Premissa falsa; recuperou com jogo de cintura, mas partiu de erro.
- Lead perguntou (preocupação de exclusividade/concorrência local): *"Eles ja sao comercializados em mercados como guanabara? Falo de pelotas Rio Grande do sul"*.
- Valéria **desviou**: *"nossos cafés são vendidos diretamente para consumidores e empresas no Brasil, e também exportamos…"* → pivotou para preço **sem responder** se o produto já está no varejo de Pelotas/Guanabara.

**Erro:** a pergunta era sobre **presença no mercado local do revendedor** (medo de competir com o próprio fornecedor na mesma praça). Desviar para preço deixa uma objeção crítica de revenda no ar.

### M5 — Padrão sistêmico: `ponte` → silêncio absoluto engole perguntas legítimas (3 leads)
Afetou **Itamar** (visita à produção), **Sirli** (qual sua função) e **Ricardo** (benchmark de concorrentes). O comportamento é por design (pergunta de negócio pós-handoff → humano), mas na prática **3 sinais quentes viraram dead-air** dependentes do SLA do João. Recomendação: permitir um **micro-acknowledgment não-comercial** ("o João já te responde isso") em vez de silêncio total, preservando o calor sem reabrir a venda pela IA.

---

## Categoria BAIXA

- **B1 — Manoel Leal (`5573991546603`):** lead pediu *"Tem como mandar a logo?"* (queria a logo do Café Canastra); a Valéria enviou o **portfólio de produtos**, não um arquivo de logo. Pedido literal não atendido. (No mais, atendimento exemplar — ver Boas Práticas.)
- **B2 — Laerte (`5551999570807`):** lead mandou uma **imagem** (caption "Negocio") que a Valéria não comentou visualmente; e rodou qualificação + preço completos num **parceiro homologado já atendido pelo João** ("são os mesmos valores q o João me passa") — redundante, porém inofensivo.
- **B3 — Wollace Rocha (`5521993111192`):** às 20:58 BRT o lead mandou foto de caminhão + *"Vou trabalhar pra voces"* (aparente oferta de **frete/logística**). A Valéria interpretou como "sem interesse em café" e fez soft-park. Possível sinal de parceiro logístico perdido; baixo valor comercial, parking razoável.
- **B4 — Ponte presuntiva como variante dominante:** entre os disparos do dia, a abertura que **presume relação existente** ("você já compra da gente" / "você já é cliente aqui" / "retomando contato com a base") apareceu com muito mais frequência que a neutra ("entra mais no seu negócio ou consumo?"). Quando a premissa é falsa (Hueiner) ou o lead é cliente confuso (Francine), ela gera atrito. Recomenda-se padronizar para a abertura neutra e só assumir relação existente com sinal confirmado.

---

## Boas Práticas Observadas (o que está impecável)

- **Integridade de mídia — 0 alucinações.** Todas as 13 conversas que prometeram fotos entregaram de fato (marcador `enviar_fotos`/`enviar_foto_produto` + 4–5 imagens reais em cada). Nenhuma foto prometida-e-não-enviada.
- **Opt-outs — 5/5 impecáveis.** Aline, Rafaela, Jeferson, Samuel e Rosângela: `registrar_optout` com **despedida enviada antes** de silenciar. Jeferson ("não sou mais franqueado, pode retirar meu contato") tratado com elegância.
- **José da Cunha (`5511973104340`) — pivô B2C exemplar.** Reconheceu consumidor final ("vocês só revendem em grande quantidade"), mudou stage → `consumo`, ofereceu loja online + cupom `ESPECIAL10` e fechou com reação ❤️ do lead. Salvamento perfeito.
- **Manoel Leal — cenário complexo dominado.** Entendeu o modelo de eventos itinerantes (100 pessoas/evento), enviou portfólio, precificou, e no *"deixa fechar o evento Suvinil primeiro"* usou corretamente `registrar_sem_interesse_atual` (**mantido no funil**, não descartado). Adiamento morno tratado pelo livro.
- **Ricardo #1 (`5511970144796`) — handoff pelo protocolo.** Respondeu **preço antes** de encaminhar ("responda, DEPOIS se despeça") e a `ponte` corretamente ficou em silêncio na pergunta de benchmark de concorrentes (Coffee++/Orfeu).
- **Disciplina de preço.** Números concretos e consistentes com o catálogo (R$28,70 / R$32,70 250g; R$169,70 grãos 2kg; mínimo 100un), sem faixas vagas.

---

## Recomendações (não implementadas — apenas diagnóstico)

1. **Higiene da lista de disparo (ALTA):** excluir do disparo "atualização de cadastro" leads com **pedido em aberto, reclamação ativa ou histórico de churn por atendimento** (casos Aislan, Sirli, Jeferson). Reabrir feridas custa reputação.
2. **Rota de escalonamento acima do João (ALTA):** para leads cuja dor **é o próprio atendimento do João** (Aislan), o handoff para o João é um beco sem saída. Prever escalonamento a supervisor/alerta gerencial.
3. **Respeitar pedidos diretos e sinais de cliente existente (MÉDIA):** "manda a tabela" deve enviar a tabela; "compro por outro contato" deve encurtar o funil, não reiniciá-lo (Francine).
4. **Micro-acknowledgment pós-handoff (MÉDIA):** substituir o silêncio absoluto da `ponte` por uma confirmação curta e não-comercial em sinais quentes (visita à produção, pergunta de identidade) — sem reabrir a venda pela IA.
5. **Padronizar a abertura neutra do disparo (BAIXA):** evitar presumir "você já compra da gente" sem sinal confirmado.

---

*Relatório gerado em auditoria read-only. Fonte: `supabase-prod`. Sem alterações de código/prompt.*
