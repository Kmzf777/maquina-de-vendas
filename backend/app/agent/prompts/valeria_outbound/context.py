def build_outbound_first_turn_context(
    campaign_message: str,
    lead_name: str | None,
    campaign_segment: str | None = None,
) -> str:
    name_line = f"O lead se chama {lead_name}.\n" if lead_name else ""
    segment_line = (
        f"Esta campanha mirava leads de {campaign_segment} — trate isso como uma HIPÓTESE de "
        "segmento, não como fato. Confirme na conversa antes de assumir; não pressuponha o "
        "perfil do lead (regra 21, anti-premissa).\n"
        if campaign_segment
        else ""
    )
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
