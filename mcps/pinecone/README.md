# Pinecone MCP Config

## Account Details
- **Index Name:** `agency-rag`
- **Dimension:** 384 (matches `all-MiniLM-L6-v2`)
- **Metric:** cosine
- **Cloud:** AWS, Region: us-east-1

## Usage in Project
- **Semantic Cache** (`memory.py`) — Deduplicates LLM calls
- **RAG Engine** (`rag.py`) — Hybrid retrieval for agent context

## Setup
The index `agency-rag` must be created in Pinecone dashboard:
1. Go to [app.pinecone.io](https://app.pinecone.io)
2. Create Index → Name: `agency-rag`, Dimensions: 384, Metric: cosine
3. Select Serverless → AWS → us-east-1

## Key (stored in backend/.env)
- `PINECONE_API_KEY`
