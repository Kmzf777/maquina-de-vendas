def build_outbound_first_turn_context(campaign_message: str, lead_name: str | None) -> str:
    name_line = f"O lead se chama {lead_name}.\n" if lead_name else ""
    return (
        f"Contexto desta abordagem outbound:\n\n"
        f"Mensagem enviada na campanha:\n---\n{campaign_message}\n---\n\n"
        f"{name_line}"
        f"O lead está respondendo a essa mensagem agora."
    )
