# Legacy entry point (docker-compose: python -m app.campaign.worker) —
# delega para o runtime por domínios isolados.
from app.worker.main import run_worker

if __name__ == "__main__":
    import asyncio

    from app.logging_setup import setup_logging
    from app.observability import init_sentry

    setup_logging()
    init_sentry()
    asyncio.run(run_worker())
