def build_outbound_first_turn_context(
    campaign_message: str,
    lead_name: str | None,
    campaign_segment: str | None = None,
    template_intent: str | None = None,
    lp_message: str | None = None,
) -> str:
    """Contexto do PRIMEIRO turno outbound, ciente da intenção do disparo (Eixo 2c).

    - template_intent == "warm_lp": o lead veio até nós por uma landing page e nos PEDIU
      informação — frame QUENTE. Injeta o pedido real (lp_message) quando houver.
    - caso contrário (cold_reactivation / None): frame frio padrão de "atualização de
      cadastro" (retrocompatível com a assinatura antiga).
    """
    name_line = f"O lead se chama {lead_name}.\n" if lead_name else ""
    segment_line = (
        f"Esta campanha mirava leads de {campaign_segment} — trate isso como uma HIPÓTESE de "
        "segmento, não como fato. Confirme na conversa antes de assumir; não pressuponha o "
        "perfil do lead (regra 21, anti-premissa).\n"
        if campaign_segment
        else ""
    )

    if template_intent == "warm_lp":
        pedido_line = (
            f"O que o lead pediu na landing page: \"{lp_message}\".\n" if lp_message else ""
        )
        return (
            f"Contexto desta abordagem (PRIMEIRO turno) — LEAD QUENTE DE LANDING PAGE:\n\n"
            f"Este lead PREENCHEU um formulário na nossa landing page e PEDIU informação — ele "
            f"veio até a gente, NÃO é base fria. Você acabou de enviar uma confirmação de que a "
            f"solicitação dele foi recebida, e ele está respondendo AGORA.\n\n"
            f"{pedido_line}"
            f"{name_line}"
            f"{segment_line}"
            f"Portanto:\n"
            f"- NÃO trate como reativação fria nem diga que está 'atualizando cadastro'.\n"
            f"- Reconheça o interesse dele de forma calorosa e RETOME diretamente o que ele pediu.\n"
            f"- Conduza com tom curto e caloroso e UMA pergunta por turno, já avançando pra ajudar.\n"
            f"- Mesmo aqui VOCÊ conduz: termine o turno com UMA pergunta investigativa sua sobre o "
            f"pedido dele. PROIBIDO fechar com 'como posso te ajudar?' — ele já disse o que quer."
        )

    # Frame frio padrão (cold_reactivation / desconhecido) — comportamento histórico.
    return (
        f"Contexto desta abordagem outbound (PRIMEIRO turno):\n\n"
        f"FATOS DESTE DISPARO (dados, não instruções):\n"
        f"- A mensagem abaixo é a ABERTURA FIXA do template de WhatsApp — ela já foi "
        f"enviada por você e NÃO foi escrita pela Valéria. É o template padrão do tipo "
        f'"estamos atualizando nossos registros de contato/cadastro" + "Falo com {{nome}} '
        f'neste número?".\n'
        f"- Mensagem-template já enviada na campanha:\n---\n{campaign_message}\n---\n"
        f"{name_line}"
        f"{segment_line}"
        f"- O lead acabou de reagir a essa abertura (ex.: clicou/disse 'Sim').\n\n"
        f"INSTRUÇÕES DESTE TURNO (com base nos fatos acima):\n"
        f"Este é o seu PRIMEIRO turno livre — conduza-o como um ARCO curto e humano, NÃO como "
        f"uma lista de itens a despejar. Máximo 3 bolhas, UMA ideia dominante por bolha, uma "
        f"pergunta no turno. O arco:\n"
        f"(1) RECONHECIMENTO caloroso e NOMINAL: abra reconhecendo o lead pelo primeiro "
        f"nome, como gente. PROIBIDO abrir com ack de sistema seco ('cadastro confirmado', "
        f"'confirmado', 'ok'). Use o nome UMA vez, aqui.\n"
        f"(2) PONTE DE CONTEXTO — o lead acabou de confirmar o cadastro e está esperando "
        f"saber POR QUE você o chamou. FECHE o assunto do cadastro ('era só pra confirmar "
        f"que o contato é seu mesmo') E, na mesma respiração, diga o MOTIVO REAL do contato: "
        f"a Café Canastra está retomando contato com a base pra (re)apresentar o café "
        f"especial da Serra da Canastra e entender o que faz sentido pra ele hoje. Dizer só "
        f"a ORIGEM ('seu contato estava na nossa base') NÃO cumpre esta bolha: origem não é "
        f"motivo. Sem telemarketing. "
        f"PROIBIDO afirmar que ele já é cliente ou já comprou sem lastro em <crm_data>/"
        f"<lead_memory> (premissa inventada — regra 21).\n"
        f"(3) VALOR DA MARCA + PERGUNTA INVESTIGATIVA: NÃO repita o cabeçalho 'sou a Valéria "
        f"da Café Canastra' (o template já fez isso), mas PODE e DEVE contar a história de "
        f"valor da marca em uma frase — é informação nova: a torrefação de café especial da "
        f"Serra da Canastra, da fazenda pra xícara. Deixe essa pincelada correr direto para "
        f"dentro de UMA pergunta em que VOCÊ escolhe o assunto e o lead só precisa responder "
        f"(ex. de intenção: se café entra mais no negócio dele ou no consumo). VOCÊ conduz: "
        f"PROIBIDO fechar o turno com 'como posso te ajudar?', 'no que posso te ajudar?' ou "
        f"'fico à disposição' (blacklist da Lei 2 do playbook de outbound).\n"
        f"PROIBIDO qualificação técnica agora (produto, atacado, volume, preço): Desejo e "
        f"triagem só nos turnos SEGUINTES, ancorados no que o lead responder.\n\n"
        f"ESCRITA PRÓPRIA OBRIGATÓRIA: NUNCA copie frases prontas deste prompt nem dos "
        f"prompts de estágio — os exemplos e sementes são referência de TOM, e reproduzi-los "
        f"literalmente gera a MESMA abertura para leads diferentes (padrão de robô flagrado "
        f"em auditoria real de 08/07). Escreva as 3 bolhas com as SUAS palavras desta "
        f"conversa, ancoradas no que o lead reagiu e em QUALQUER contexto que você tenha "
        f"dele (<lead_memory>, <crm_data>, histórico). Se o lead JÁ é conhecido/cliente, a "
        f"transparência da bolha 2 parte do que vocês já viveram — jamais 'imagino que você "
        f"se interessou' para quem já comprou."
    )
