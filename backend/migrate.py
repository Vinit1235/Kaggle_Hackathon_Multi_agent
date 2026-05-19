import asyncio
import os
import asyncpg
from dotenv import load_dotenv

load_dotenv()

async def migrate():
    db_url = os.getenv("DATABASE_URL", "")
    conn = await asyncpg.connect(db_url, ssl="require")
    
    print("Running migration...")
    
    # Create sessions table
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            session_id TEXT PRIMARY KEY,
            user_id UUID NOT NULL,
            title TEXT DEFAULT 'New Chat',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    
    # Add user_id to tasks if it doesn't exist
    try:
        await conn.execute("ALTER TABLE tasks ADD COLUMN user_id UUID;")
    except asyncpg.exceptions.DuplicateColumnError:
        pass
        
    print("Migration complete!")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(migrate())
