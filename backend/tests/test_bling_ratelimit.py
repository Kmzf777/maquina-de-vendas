import asyncio

import pytest

import app.bling.ratelimit as rl
from app.bling.errors import BlingDailyCapError, BlingRateLimitError


class FakeRedis:
    """Espelha o script Lua UNICO que `acquire()` agora chama.

    Um so `eval` recebe as duas chaves (segundo, dia) e os dois limites, e decide
    tudo atomicamente — igual ao script real: {status, valor}, onde 0 = ok,
    1 = estourou o limite por segundo (contador diario NAO e tocado), 2 = estourou
    o teto diario.
    """

    def __init__(self, fail: bool = False):
        self.counts: dict[str, int] = {}
        self.fail = fail
        self.calls = 0

    async def eval(self, script, numkeys, *args):
        self.calls += 1
        if self.fail:
            raise ConnectionError("redis down")
        sec_key, day_key, _sec_ttl, _day_ttl, sec_limit, day_limit = args

        sec = self.counts[sec_key] = self.counts.get(sec_key, 0) + 1
        if sec > int(sec_limit):
            return [1, sec]

        day = self.counts[day_key] = self.counts.get(day_key, 0) + 1
        if day > int(day_limit):
            return [2, day]

        return [0, day]


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Nao dorme de verdade — so registra que dormiu."""
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(rl.asyncio, "sleep", fake_sleep)
    return slept


@pytest.fixture(autouse=True)
def _reset_cooldown(monkeypatch):
    """Zera o cooldown pos-falha antes de cada teste — e estado de MODULO (nao
    passa por monkeypatch dentro de `_mark_unavailable`), entao vaza entre testes
    sem isso. Mesmo padrao usado em `test_lead_lock_2026_06_24.py`."""
    monkeypatch.setattr(rl, "_unavailable_until", 0.0, raising=False)


def test_tres_chamadas_no_mesmo_segundo_passam(monkeypatch, _no_sleep):
    fake = FakeRedis()
    monkeypatch.setattr(rl, "_get_client", lambda: fake)
    monkeypatch.setattr(rl.time, "time", lambda: 1_000_000.0)

    async def run():
        for _ in range(3):
            await rl.acquire()

    asyncio.run(run())
    assert _no_sleep == [], "nao deveria esperar dentro do orcamento de 3 req/s"


def test_quarta_chamada_no_mesmo_segundo_espera(monkeypatch, _no_sleep):
    fake = FakeRedis()
    monkeypatch.setattr(rl, "_get_client", lambda: fake)
    # Primeiro o relogio fica parado (forca o estouro), depois avanca 1s.
    ticks = iter([1_000_000.0] * 5 + [1_000_001.0] * 5)
    monkeypatch.setattr(rl.time, "time", lambda: next(ticks))

    async def run():
        for _ in range(4):
            await rl.acquire()

    asyncio.run(run())
    assert _no_sleep, "a 4a chamada no mesmo segundo tinha que esperar o proximo segundo"


def test_teto_diario_recusa(monkeypatch, _no_sleep):
    fake = FakeRedis()
    # _day_key agora exige a conta (chave por conta) — rl.acquire() sem
    # argumento usa "default", entao a semente tem que vir da mesma conta.
    fake.counts[rl._day_key(rl.config.DEFAULT_ACCOUNT)] = rl.config.DAILY_SOFT_CAP
    monkeypatch.setattr(rl, "_get_client", lambda: fake)
    monkeypatch.setattr(rl.time, "time", lambda: 1_000_000.0)

    with pytest.raises(BlingDailyCapError):
        asyncio.run(rl.acquire())


def test_redis_fora_do_ar_e_fail_closed(monkeypatch, _no_sleep):
    """Ao contrario do lead_lock (fail-open), aqui seguir sem contagem arrisca
    bloqueio de IP por tempo indeterminado. Melhor recusar e enfileirar."""
    monkeypatch.setattr(rl, "_get_client", lambda: FakeRedis(fail=True))
    monkeypatch.setattr(rl.time, "time", lambda: 1_000_000.0)

    with pytest.raises(BlingRateLimitError):
        asyncio.run(rl.acquire())


def test_falha_ativa_cooldown_e_proxima_chamada_nao_toca_redis(monkeypatch, _no_sleep):
    """Depois de uma falha, a chamada seguinte tem que recusar IMEDIATAMENTE, sem
    sequer tentar `eval` de novo — senao toda chamada durante uma queda prolongada
    paga o timeout de CONEXAO inteiro (o job de sync em lote pagaria ~2-4s/item).
    Prova contando as chamadas no fake: se o cooldown nao ativou, `calls` sobe."""
    fake = FakeRedis(fail=True)
    monkeypatch.setattr(rl, "_get_client", lambda: fake)
    monkeypatch.setattr(rl.time, "time", lambda: 1_000_000.0)

    with pytest.raises(BlingRateLimitError):
        asyncio.run(rl.acquire())
    assert fake.calls == 1

    with pytest.raises(BlingRateLimitError):
        asyncio.run(rl.acquire())
    assert fake.calls == 1, "cooldown deveria evitar nova tentativa de conexao ao Redis"


def test_chave_do_segundo_inclui_a_conta():
    from app.bling import ratelimit
    assert ratelimit._second_key(1757800000.4, "default") == "bling:rl:default:1757800000"
    assert ratelimit._second_key(1757800000.4, "secundaria") == "bling:rl:secundaria:1757800000"


def test_chave_do_dia_inclui_a_conta():
    from app.bling import ratelimit
    a = ratelimit._day_key("default")
    b = ratelimit._day_key("secundaria")
    assert a.startswith("bling:rl:default:day:")
    assert b.startswith("bling:rl:secundaria:day:")
    assert a != b


def test_contas_nao_compartilham_orcamento():
    """O teto do Bling e POR CONTA (3 req/s, 120k/dia). Chave compartilhada
    faria duas contas dividirem um orcamento so."""
    from app.bling import ratelimit
    agora = 1757800000.0
    assert ratelimit._second_key(agora, "default") != ratelimit._second_key(agora, "secundaria")


def test_duas_contas_nao_disputam_o_orcamento_do_mesmo_segundo(monkeypatch, _no_sleep):
    """Prova acquire() de ponta a ponta, nao so os formatadores de chave: se
    alguem grudasse "default" direto dentro de acquire (bug que os testes de
    _second_key/_day_key sozinhos NAO pegariam, porque os formatadores
    continuariam corretos), 6 chamadas no mesmo segundo estourariam o limite
    de 3/s e uma delas dormiria."""
    fake = FakeRedis()
    monkeypatch.setattr(rl, "_get_client", lambda: fake)
    monkeypatch.setattr(rl.time, "time", lambda: 1_000_000.0)

    async def run():
        for _ in range(3):
            await rl.acquire("default")
        for _ in range(3):
            await rl.acquire("secundaria")

    asyncio.run(run())
    assert _no_sleep == [], "contas diferentes nao podem disputar o mesmo orcamento de 3 req/s"
