# Supabase MCP Config

## Project Details
- **Project Ref:** `ckvfoozbanyixxfkiutg`
- **URL:** `https://ckvfoozbanyixxfkiutg.supabase.co`
- **Region:** ap-south-1 (verify in Supabase dashboard)

## Connection String (for backend)
```
postgresql://postgres.ckvfoozbanyixxfkiutg:[PASSWORD]@aws-0-ap-south-1.pooler.supabase.com:6543/postgres
```

## Keys (stored in backend/.env — never commit)
- `SUPABASE_ANON_KEY` — for frontend/public access
- `SUPABASE_SERVICE_ROLE_KEY` — for backend admin access (NEVER expose to frontend)

## Tables Created by Backend
- `tasks` — Main task records
- `inboxes` — Agent inbox messages
- `audit_log` — Immutable action log

## Important Notes
- The `DATABASE_URL` region in the pooler URL must match your Supabase project region
- If connection fails, check the region in your Supabase dashboard:
  Settings → General → Region
- Adjust `aws-0-ap-south-1` to match (e.g., `aws-0-us-east-1`)
