# Legacy entry point (docker-compose: python -m app.campaign.worker) —
# delega para o runtime por domínios isolados.
from app.worker.main import run_worker

if __name__ == "__main__":
    import asyncio
    import logging
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
