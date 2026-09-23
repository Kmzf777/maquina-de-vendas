# Valeria Score — desenho

## Objetivo e alcance

Priorizar todos os leads de atacado do Café Canastra por critérios objetivos captados exclusivamente pela ValerIA, sem misturar a percepção do vendedor ao cálculo. O score aparece durante a conversa e após a qualificação. A entrada fica em `/campanhas`, por um botão **Valeria Score** que abre um modal com a lista geral, busca e filtros por score, prioridade e campanha de tráfego.

O primeiro processamento retroativo cobre leads de atacado cuja **última interação** ocorreu nos 60 dias anteriores à execução. Depois disso, conversas novas e retomadas são atualizadas continuamente, independentemente da data de criação do lead. Leads sem conversa suficiente permanecem visíveis como provisórios. O recorte de 60 dias vale somente para o processamento inicial, não para a consulta do modal.

## Regras de pontuação

O cálculo é determinístico; a IA só classifica os dados da conversa. Valores ausentes rendem zero pontos e mantêm o estado provisório. Valor explicitamente negativo, como “não pretendo comprar”, é conhecido e rende zero.

| Critério | Valor | Pontos |
| --- | --- | ---: |
| Segmento | Cafeteria | 2 |
| Segmento | Empório, loja especializada, adega, loja de queijos, produtos naturais, granel, artesanais, coloniais ou da roça | 1 |
| Segmento | Supermercado, hotel, restaurante, padaria ou outros | 0 |
| Volume mensal | Até 30 kg/mês, inclusive | 1 |
| Volume mensal | Acima de 30 kg/mês ou não informado | 0 |
| Motivo | Substituir fornecedor atual | 2 |
| Motivo | Segundo fornecedor, ampliar mix, começar com café especial, pesquisa ou outros | 0 |
| Momento | Comprar em até 15 dias | 1 |
| Momento | 16–30 dias, 1–3 meses, mais de 3 meses, sem previsão ou não informado | 0 |
| Intenção | Interesse claro em compra, cotação ou proposta | 2 |
| Intenção | Ausência de intenção clara | 0 |

A soma normal vai de 0 a 8. **Motivo = substituir fornecedor e intenção = clara** produz score final 10, independentemente dos outros critérios. Classificação: 0–2 baixa; 3–4 moderada; 5–6 alta; 10 máxima. Scores finais 7–9 são inalcançáveis sob essas regras. O rótulo da interface usa `x/8` na soma normal e `10 — Prioridade Máxima` na exceção, sem representar 10 como parte da escala normal.

O estado é **provisório** enquanto ao menos um critério for desconhecido; torna-se **consolidado** quando os cinco tiverem valor conhecido. O score 10 pode surgir ainda provisório e permanece 10 enquanto a combinação estiver sustentada. O handoff para o vendedor não força consolidação nem muda o cálculo. Cada critério guarda valor normalizado, trecho de evidência e referência à mensagem quando disponível. Uma correção explícita posterior do lead substitui o valor anterior e registra a nova evidência. A ausência de evidência não autoriza uma classificação positiva. Na extração retroativa, trechos ambíguos permanecem desconhecidos.

## Coleta e armazenamento

Uma tabela `lead_qualification_scores` mantém uma linha por lead de atacado: cinco critérios estruturados, evidências por critério, soma normal, score final, prioridade, estado provisório, origem/versão da regra e datas de atualização. Um módulo Python puro calcula o score a partir desses campos; a persistência chama esse módulo em cada atualização. O modelo nunca informa pontos nem prioridade. A coleta ao vivo estende a ferramenta `qualificar_lead`, sem alterar os portões existentes de handoff (finalidade, volume concreto e preço apresentado). Ela aceita os critérios de score de forma opcional, atualizando apenas campos que a conversa sustentou. O prompt orienta a ValerIA a registrar mudanças durante a conversa sem transformar o atendimento num questionário.

O backfill é um comando idempotente, paginado e com modo de ensaio que lê os leads elegíveis e o histórico das mensagens. Usa extração estruturada com o modelo já configurado no backend; não envia mensagens ao cliente nem dispara handoff. Não sobrescreve evidência mais recente registrada ao vivo. Erros por lead são registrados e o lote segue; o comando resume após interrupção.

## Feeling do vendedor

Uma tabela separada `lead_seller_feelings` guarda um registro por par lead/vendedor (`baixo`, `medio`, `alto`), justificativa não vazia, identificador do usuário autenticado e horário. Apenas o vendedor autenticado salva ou altera o próprio registro; se houver mais de um vendedor, a lista mostra o registro atualizado mais recentemente e identifica seu autor. Não há campo de feeling no módulo de cálculo nem na tabela de score. A API rejeita justificativa vazia e jamais aceita score ou critérios objetivos enviados pelo navegador.

## Consulta e interface

O botão **Valeria Score** no cabeçalho de `/campanhas` abre um modal amplo. A lista agrega leads de atacado e seus snapshots de score, inclui leads ainda sem score, ordena por prioridade e interação recente, e pagina no servidor. Filtros: busca por nome/telefone/empresa; score ou faixa de prioridade; provisório/consolidado; campanha de tráfego; origem paga/orgânica/sem atribuição. A atribuição da campanha vem de `utm_campaign` para landing pages e de `leads.meta_ad_id → meta_ad_campaigns` para anúncios Click-to-WhatsApp. Campanhas de cadência/disparo não entram nesse filtro.

Cada linha mostra lead, campanha, score, prioridade, estado e última interação. Ao selecionar um lead, o modal exibe o detalhamento dos cinco critérios e suas evidências, além de Feeling e justificativa em bloco independente. Vendedor pode editar apenas Feeling e justificativa; a interface mostra autor e data. Score desconhecido é exibido como `—`, não como zero. Dados ainda não informados exibem `Não identificado` e a prioridade provisória é explicitamente rotulada.

## Segurança e operação

As rotas Next.js validam sessão antes de usar o cliente de serviço. A rota de leitura retorna só os campos necessários e usa paginação; a rota de escrita do Feeling deriva o vendedor da sessão, valida valores e tamanho da justificativa. As tabelas têm RLS/índices e remoção em cascata com o lead. A migração e o backfill são separados do deploy de código; executar o backfill exige configuração de banco e modelo, e é uma etapa operacional explícita.

## Verificação

Testes de unidade cobrem pontuação, regra 10, casos ausentes, limites de 30 kg e 15 dias, correções e independência do Feeling. Testes da integração cobrem a atualização parcial sem regressão dos portões de handoff. Testes das rotas cobrem autenticação, filtros, paginação, campanha Meta/UTM e validação do Feeling. Testes da interface cobrem abertura, filtros, estados provisório/consolidado e justificativa obrigatória. O backfill é testado com histórico contraditório, ambíguo e falhas parciais.
