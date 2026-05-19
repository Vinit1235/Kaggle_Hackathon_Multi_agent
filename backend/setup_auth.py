import asyncio
import os
from dotenv import load_dotenv
import asyncpg

load_dotenv()

async def setup_auth():
    # See the service role key
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if service_key:
        print(f"Found Service Role Key! (Snippet: {service_key[:15]}...)")
    else:
        print("SUPABASE_SERVICE_ROLE_KEY not found in .env")
        
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("No DATABASE_URL found in .env")
        return
        
    print("Connecting to database to create auth schemas and tables...")
    try:
        conn = await asyncpg.connect(db_url, timeout=10, ssl="require")
        
        # Create a dedicated schema for custom auth if needed
        await conn.execute("CREATE SCHEMA IF NOT EXISTS custom_auth;")
        
        # Create custom auth tables
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_auth.users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                role VARCHAR(50) DEFAULT 'user',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS custom_auth.sessions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID REFERENCES custom_auth.users(id) ON DELETE CASCADE,
                session_token VARCHAR(255) UNIQUE NOT NULL,
                expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS custom_auth.roles (
                id SERIAL PRIMARY KEY,
                role_name VARCHAR(50) UNIQUE NOT NULL,
                permissions JSONB DEFAULT '{}'
            );
        """)
        
        print("✅ Successfully created 'custom_auth' schema and related tables (users, sessions, roles).")
        await conn.close()
    except Exception as e:
        print(f"❌ Error setting up auth tables: {e}")

if __name__ == "__main__":
    asyncio.run(setup_auth())
