import sys
sys.path.insert(0, '.')
from app.config import settings
print(f"OK - Settings loaded: {settings.supabase_url[:20]}")
