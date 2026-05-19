"""Quick Supabase connection test — tries multiple URL formats."""
import asyncio, os
from dotenv import load_dotenv
load_dotenv()

PASSWORD = "jNZX32wCeIySdITU"
REF = "ckvfoozbanyixxfkiutg"

# All possible connection string formats
URLS = [
    # Direct connection
    f"postgresql://postgres:{PASSWORD}@db.{REF}.supabase.co:5432/postgres",
    # Pooler — transaction mode (various regions)
    f"postgresql://postgres.{REF}:{PASSWORD}@aws-0-ap-south-1.pooler.supabase.com:6543/postgres",
    f"postgresql://postgres.{REF}:{PASSWORD}@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
    f"postgresql://postgres.{REF}:{PASSWORD}@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres",
    # Pooler — session mode
    f"postgresql://postgres.{REF}:{PASSWORD}@aws-0-ap-south-1.pooler.supabase.com:5432/postgres",
    f"postgresql://postgres.{REF}:{PASSWORD}@aws-0-us-east-1.pooler.supabase.com:5432/postgres",
]

async def main():
    import asyncpg
    for i, url in enumerate(URLS):
        display = url.replace(PASSWORD, "***")
        print(f"\n[{i+1}/{len(URLS)}] Trying: {display}")
        try:
            conn = await asyncpg.connect(url, timeout=10, ssl="require")
            ver = await conn.fetchval("SELECT version()")
            print(f"  >>> CONNECTED! {ver[:60]}")
            print(f"  >>> WORKING URL: {display}")
            await conn.close()
            return url
        except Exception as e:
            print(f"  FAILED: {str(e)[:80]}")
    print("\nAll URLs failed. Check Supabase dashboard for exact connection string.")

asyncio.run(main())
