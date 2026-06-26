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
        f"O lead está respondendo AGORA a essa abertura fixa. Você assume a conversa a "
        f"partir da reação dele. Portanto:\n"
        f"- NÃO repita a auto-apresentação (nome/empresa): isso já foi feito no template.\n"
        f"- Reconheça brevemente que a abertura era sobre confirmar o cadastro/contato e, "
        f"na sequência, PIVOTE para valor já no próximo movimento (ver '## RESPOSTA À "
        f"ABERTURA').\n"
        f"- Responda a partir da reação concreta do lead (confirmou, perguntou quem é, "
        f"recusou etc.), com tom curto e caloroso e UMA pergunta por turno."
    )
