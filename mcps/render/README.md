# Render MCP Config

## Planned Deployment

### Backend (Web Service)
```
Name:          kaggle-hackathon-backend
Root Dir:      backend
Runtime:       Python 3
Build Command: pip install -r requirements.txt
Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
Plan:          Free
```

### Frontend (Static Site)
```
Name:          kaggle-hackathon-frontend
Root Dir:      frontend
Build Command: npm install && npm run build
Publish Dir:   dist
Plan:          Free
```

### Environment Variables to Set in Dashboard
Copy from `backend/.env` into Render's Environment Variables section:
- `GEMINI_API_KEY`
- `DATABASE_URL`
- `PINECONE_API_KEY`
- `PINECONE_INDEX_NAME`
- `UPSTASH_REDIS_REST_URL` (when available)
- `UPSTASH_REDIS_REST_TOKEN` (when available)
- `LLM_PROVIDER=gemini`
- `ENABLE_PII_SHIELD=false`
- `DEBUG=false`

### Frontend Env
- `VITE_API_URL` = your backend Render URL (set after backend deploys)
