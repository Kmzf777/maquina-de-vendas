# Legacy entry point — delegates to broadcast worker
from app.broadcast.worker import run_worker

if __name__ == "__main__":
    import asyncio
    import logging
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
