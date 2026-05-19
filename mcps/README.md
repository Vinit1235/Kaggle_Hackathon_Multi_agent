# MCP Configurations

Model Context Protocol (MCP) server configs for the AI Agency Platform cloud services.

## Services

| MCP | Service | Purpose |
|---|---|---|
| `render/` | Render | Backend + Frontend hosting |
| `supabase/` | Supabase | PostgreSQL database (TaskBox) |
| `upstash/` | Upstash | Redis (memX state sync) |
| `pinecone/` | Pinecone | Vector DB (RAG + semantic cache) |

## Usage

Add these MCP configs to your IDE settings (e.g., `.claude/settings.json` or `.gemini/settings.json`)
to enable AI-assisted management of each cloud service.
