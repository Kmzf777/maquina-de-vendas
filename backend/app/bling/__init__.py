"""Integracao com o ERP Bling (API v3).

Este pacote e o DONO UNICO da conta Bling no sistema. O limite de requisicoes do
Bling e por CONTA (3 req/s, 120.000/dia), nao por endpoint nem por processo — se
o Next e o worker chamassem a API por conta propria, um estouraria o orcamento do
outro e o IP seria bloqueado. Toda chamada passa por `client.BlingClient`.
"""
