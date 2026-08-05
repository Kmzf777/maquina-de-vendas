"""Runner do sync diário do Google Ads (cron). Uso: python -m scripts.sync_google_ads_spend"""
import asyncio
import logging

from app.campaigns.ad_spend_sync import sync_google_ads_spend

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    n = asyncio.run(sync_google_ads_spend(days=30))
    print(f"ad_spend sync: {n} linhas")
