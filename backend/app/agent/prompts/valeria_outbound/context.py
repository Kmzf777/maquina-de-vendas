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
            f"- Conduza com tom curto e caloroso e UMA pergunta por turno, já avançando pra ajudar."
        )

    # Frame frio padrão (cold_reactivation / desconhecido) — comportamento histórico.
    return (
        f"Contexto desta abordagem outbound (PRIMEIRO turno):\n\n"
        f"A mensagem abaixo é a ABERTURA FIXA do template de WhatsApp — ela já foi "
        f"enviada por você e NÃO foi escrita pela Valéria. É o template padrão do tipo "
        f'"estamos atualizando nossos registros de contato/cadastro" + "Falo com {{nome}} '
        f'neste número?".\n\n'
        f"Mensagem-template já enviada na campanha:\n---\n{campaign_message}\n---\n\n"
        f"{name_line}"
        f"{segment_line}"
        f"O lead acabou de reagir a essa abertura (ex.: clicou/disse 'Sim'). Este é o seu "
        f"PRIMEIRO turno livre — conduza-o como um ARCO curto e humano, NÃO como uma lista "
        f"de itens a despejar (isso vira metralhadora de bolhas). Máximo 3 bolhas, UMA "
        f"ideia dominante por bolha, uma pergunta no turno. O arco:\n"
        f"(1) RECONHECIMENTO caloroso e NOMINAL: abra reconhecendo o lead pelo primeiro "
        f"nome, como gente. PROIBIDO abrir com ack de sistema seco ('cadastro confirmado', "
        f"'confirmado', 'ok'). Use o nome UMA vez, aqui.\n"
        f"(2) TRANSPARÊNCIA leve: em uma frase natural, diga por que você o procurou — o "
        f"contato dele estava na nossa base e provavelmente ele já teve algum interesse "
        f"pela Canastra antes. Sem tom de telemarketing.\n"
        f"(3) VALOR DA MARCA (uma pincelada, não ficha técnica): NÃO repita o cabeçalho "
        f"'sou a Valéria da Café Canastra' (o template já fez isso), mas PODE e DEVE contar "
        f"a história de valor da marca em uma frase — é informação nova: a torrefação de "
        f"café especial da Serra da Canastra, da fazenda pra xícara. Deixe essa pincelada "
        f"correr direto para dentro de UMA pergunta aberta e leve de rapport, na mesma "
        f"bolha, convidando o lead a se situar.\n"
        f"PROIBIDO qualificação técnica agora (produto, atacado, volume, preço): Desejo e "
        f"triagem só nos turnos SEGUINTES, ancorados no que o lead responder.\n\n"
        f"Exemplo de TOM e RITMO (nome ilustrativo — use o nome REAL do lead):\n"
        f'  "que bom, Marcelo"\n'
        f'  "seu contato tava aqui com a gente e imagino que uma hora você chegou a se '
        f'interessar pela Canastra, então quis puxar esse papo com você"\n'
        f'  "a gente é a torrefação de café especial da Serra da Canastra e antes de '
        f'qualquer coisa gosta de entender quem tá do outro lado, café pra você é mais um '
        f'prazer do dia a dia ou tem a ver com algum projeto seu?"'
    )
