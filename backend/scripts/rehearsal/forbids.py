"""Forbid-check factories and shared forbid lists used by archetypes and verifier.

Kept in a separate module to avoid circular imports between archetypes.py and
verifier.py (verifier imports Archetype from archetypes; archetypes uses forbids).
"""
import re


def forbids_regex(pattern: str, label: str, description: str):
    """Factory de verificador anti-alucinação.

    Retorna (True, reason) se o padrão NAO aparecer em nenhuma mensagem com
    role='assistant'. Retorna (False, "[VIOLATION:LABEL] ...") ao primeiro match.
    """
    compiled = re.compile(pattern, re.IGNORECASE)

    def check(run_data: dict) -> tuple[bool, str]:
        messages = run_data.get("messages", [])
        for m in messages:
            if m.get("role") != "assistant":
                continue
            content = m.get("content", "")
            match = compiled.search(content)
            if match:
                start = max(0, match.start() - 20)
                end = min(len(content), match.end() + 20)
                snippet = content[start:end].replace("\n", " ")
                return False, f"[VIOLATION:{label}] {description} — trecho: '{snippet}'"
        return True, f"{label}: sem violação"

    check.__name__ = f"forbid_{label.lower()}"
    return check


FORBID_PIX = forbids_regex(
    r"\bpix\b|chave\s+pix|copia\s+e\s+cola|qr[\s-]?code",
    label="PIX",
    description="bot mencionou PIX — pagamento é responsabilidade do comercial humano",
)

FORBID_PRECO_FRETE = forbids_regex(
    r"(investimento\s+inicial|fica\s+em\s+torno\s+de|custo\s+final|total\s+de)[^.\n]{0,40}R\$\s*\d",
    label="PRECO_FRETE",
    description="bot prometeu preço final/total — só supervisor faz orçamento fechado",
)

FORBID_PRAZO = forbids_regex(
    r"\b(prazo\s+de|chega\s+em|entrego\s+em|em\s+ate)\s*\d+\s*(dias?\s+ute?i?s?|dias?|horas?)",
    label="PRAZO",
    description="bot prometeu prazo de entrega — depende do frete e supervisor",
)

FORBID_DESCONTO = forbids_regex(
    r"(posso\s+fazer\s+por|libero\s+por|sai\s+por\s+R\$|desconto\s+de\s+\d+\s*%|promocao|condicao\s+especial)",
    label="DESCONTO",
    description="bot ofereceu desconto improvisado — condições são fechadas pelo comercial",
)

FORBID_PAPEL = forbids_regex(
    r"(passa(ndo|rei)?|vou\s+passar|encaminho)\s+(voce\s+)?(pro|para\s+o|ao)\s+comercial\b",
    label="PAPEL",
    description="bot disse 'pro comercial' sendo ela mesma do comercial — deve dizer 'pro supervisor' ou 'pro João Bras'",
)

UNIVERSAL_FORBIDS = [
    FORBID_PIX,
    FORBID_PRECO_FRETE,
    FORBID_PRAZO,
    FORBID_DESCONTO,
    FORBID_PAPEL,
]

FORBID_PONTO_VENDA_FISICO = forbids_regex(
    r"(temos\s+(ponto|loja)|voce\s+encontra\s+em|disponivel\s+em\s+loja)\s+(em|no|na|em\s+lojas)?\s*(charqueadas|rs\b|rio\s+grande\s+do\s+sul|porto\s+alegre)",
    label="PONTO_VENDA_RS",
    description="bot inventou ponto de venda físico no RS — Canastra só tem venda direta",
)
