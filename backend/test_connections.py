"""
Test script: Verify all cloud service connections.
Run: python test_connections.py
"""

import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv()

async def test_supabase():
    """Test Supabase PostgreSQL connection and create tables."""
    import asyncpg
    
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        print("❌ DATABASE_URL not set")
        return False
    
    try:
        print(f"  Trying connection: {db_url.replace('jNZX32wCeIySdITU', '***')}")
        conn = await asyncpg.connect(db_url, timeout=10, ssl="require")
        version = await conn.fetchval("SELECT version()")
        print(f"  ✅ Connected! PostgreSQL: {version[:60]}...")
        
        # Create tables
        print("  Creating tables...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id         TEXT PRIMARY KEY,
                session_id      TEXT NOT NULL,
                domain          TEXT NOT NULL,
                agent_role      TEXT NOT NULL,
                goal            TEXT NOT NULL,
                input_data      JSONB DEFAULT '{}',
                output_data     JSONB DEFAULT '{}',
                status          TEXT DEFAULT 'pending',
                parent_task_id  TEXT,
                priority        INTEGER DEFAULT 0,
                error_message   TEXT,
                retry_count     INTEGER DEFAULT 0,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS inboxes (
                message_id      TEXT PRIMARY KEY,
                session_id      TEXT NOT NULL,
                target_agent    TEXT NOT NULL,
                source_agent    TEXT NOT NULL,
                task_id         TEXT NOT NULL,
                content         JSONB DEFAULT '{}',
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                read            BOOLEAN DEFAULT FALSE
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                log_id          TEXT PRIMARY KEY,
                session_id      TEXT NOT NULL,
                agent_role      TEXT NOT NULL,
                action          TEXT NOT NULL,
                details         JSONB DEFAULT '{}',
                status          TEXT DEFAULT 'completed',
                error_message   TEXT,
                token_count     INTEGER,
                latency_ms      DOUBLE PRECISION,
                timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id);
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks(agent_role);
            CREATE INDEX IF NOT EXISTS idx_inboxes_target ON inboxes(target_agent, read);
            CREATE INDEX IF NOT EXISTS idx_inboxes_session ON inboxes(session_id);
            CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_log(session_id);
        """)
        print("  ✅ Tables created: tasks, inboxes, audit_log")
        
        # Verify tables
        tables = await conn.fetch("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        """)
        print(f"  ✅ Tables in DB: {[t['table_name'] for t in tables]}")
        
        await conn.close()
        return True
        
    except Exception as e:
        print(f"  ❌ Connection failed: {str(e)[:80]}")
        return False


async def test_gemini():
    """Test Gemini API connection."""
    import httpx
    
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        print("❌ GEMINI_API_KEY not set")
        return False
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            )
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                flash_models = [m["name"] for m in models if "flash" in m.get("name", "")]
                print(f"  ✅ Gemini API connected! {len(models)} models available")
                print(f"  Flash models: {flash_models[:5]}")
                return True
            else:
                print(f"  ❌ Gemini API error: {resp.status_code} - {resp.text[:100]}")
                return False
    except Exception as e:
        print(f"  ❌ Gemini connection failed: {e}")
        return False


async def test_pinecone():
    """Test Pinecone connection and create index."""
    api_key = os.getenv("PINECONE_API_KEY", "")
    index_name = os.getenv("PINECONE_INDEX_NAME", "agency-rag")
    
    if not api_key:
        print("❌ PINECONE_API_KEY not set")
        return False
    
    try:
        from pinecone import Pinecone, ServerlessSpec
        
        pc = Pinecone(api_key=api_key)
        existing = [idx.name for idx in pc.list_indexes()]
        print(f"  Existing indexes: {existing}")
        
        if index_name not in existing:
            print(f"  Creating index '{index_name}' (384 dims, cosine)...")
            pc.create_index(
                name=index_name,
                dimension=384,
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )
            print(f"  ✅ Index '{index_name}' created!")
        else:
            print(f"  ✅ Index '{index_name}' already exists!")
        
        # Check index stats
        idx = pc.Index(index_name)
        stats = idx.describe_index_stats()
        print(f"  ✅ Index stats: {stats.total_vector_count} vectors, dim={stats.dimension}")
        return True
        
    except Exception as e:
        print(f"  ❌ Pinecone error: {e}")
        return False


async def main():
    print("=" * 60)
    print("🔧 AI Agency Platform — Connection Tests")
    print("=" * 60)
    
    print("\n1️⃣  GEMINI API (LLM)")
    await test_gemini()
    
    print("\n2️⃣  SUPABASE (PostgreSQL Database)")
    region = await test_supabase()
    
    print("\n3️⃣  PINECONE (Vector DB)")
    await test_pinecone()
    
    print("\n" + "=" * 60)
    print("✅ Connection tests complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
