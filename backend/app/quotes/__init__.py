"""Orçamentos — a proposta comercial do Bling vista pelo CRM.

O pacote é deliberadamente vazio de importações: `pdf.py` não depende de rede
nem de banco e `proposals.py`/`router.py` dependem dos dois. Reexportar
qualquer coisa aqui faria `import app.quotes` arrastar o cliente HTTP e o
Supabase para dentro de um teste que só quer gerar um PDF — e um `__init__`
que importa tudo é o caminho mais curto para import circular quando o router
passar a importar o pacote de volta.
"""
