"""Simula uma ativação (dry-run): quantos eventos a varredura enfileiraria e quantos o sender
enviaria agora, por plataforma × etapa × idade do evento. Não grava nem envia nada.

Rodar ANTES de qualquer reativação (pausa, etapa ou plataforma nova) — spec de 14/10.

Uso (de dentro do container, em /app):
    python -m scripts.conversoes.simular_ativacao [--dias N]
"""
import argparse
import sys

from app.conversions.sender import simulate_sender
from app.conversions.sweep import simulate_sweep


def _tabela(titulo: str, cont: dict) -> None:
    print(titulo)
    if not cont:
        print("  (nada)")
    for (p, s, faixa), n in sorted(cont.items()):
        print(f"  {p:7} {s:12} {faixa:7} {n}")
    print(f"  total: {sum(cont.values())}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dias", type=int, default=None,
                    help="janela retroativa (padrão: CONVERSIONS_BACKFILL_DAYS ou 90)")
    a = ap.parse_args(argv)
    sw = simulate_sweep(backfill_days=a.dias)
    se = simulate_sender(backfill_days=a.dias)
    print(f"SIMULAÇÃO — janela retroativa {sw['backfill_days']} dias — nada foi gravado nem enviado")
    _tabela("Varredura: novos eventos que entrariam na fila", sw["novos"])
    print(f"  (já na fila, ignorados: {sw['ja_na_fila']})")
    _tabela("Sender: pendentes que sairiam agora", se["enviaria"])
    print(f"  (pendentes fora da janela: {se['fora_da_janela']})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
