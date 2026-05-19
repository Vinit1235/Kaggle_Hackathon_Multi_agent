# Upstash MCP Config

## What You Have
- **Upstash Vector** ✅ (provided)
  - URL: `https://regular-piranha-41676-us1-vector.upstash.io`
  - Can be used as an alternative to Pinecone

## What's Missing
- **Upstash Redis** ❌ (NOT provided)
  - Needed for: memX real-time state sync between agents
  - Create at: [console.upstash.com](https://console.upstash.com) → Redis → Create Database
  - Then add to `.env`:
    ```
    UPSTASH_REDIS_REST_URL=https://xxxx.upstash.io
    UPSTASH_REDIS_REST_TOKEN=AXxx...
    ```

## Current Fallback
Without Upstash Redis, the app uses **in-memory dict** for state sync.
This works fine for a single-instance hackathon demo.

## Keys (stored in backend/.env)
- `UPSTASH_VECTOR_REST_URL`
- `UPSTASH_VECTOR_REST_TOKEN`
