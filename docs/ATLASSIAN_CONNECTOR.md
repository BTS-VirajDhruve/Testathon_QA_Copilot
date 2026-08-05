# Atlassian Jira + Confluence Knowledge Connector

Backend-only OAuth 2.0 (3LO) integration that imports selected Jira issues and Confluence pages into the existing project-scoped Knowledge Base → chunk → embed → Vector RAG pipeline.

## Setup (Atlassian Developer Console)

1. Create an OAuth 2.0 (3LO) app at [developer.atlassian.com](https://developer.atlassian.com/).
2. Add callback URL:
   `http://localhost:8000/api/integrations/atlassian/callback`
3. Grant scopes (read-only):
   - `read:jira-work`
   - `read:space:confluence`
   - `read:page:confluence`
   - `offline_access`
4. Copy Client ID and Client Secret into `.env` (never commit secrets):

```bash
ATLASSIAN_INTEGRATION_ENABLED=true
ATLASSIAN_OAUTH_CLIENT_ID=
ATLASSIAN_OAUTH_CLIENT_SECRET=
ATLASSIAN_OAUTH_REDIRECT_URI=http://localhost:8000/api/integrations/atlassian/callback
ATLASSIAN_TOKEN_ENCRYPTION_KEY=  # optional strong passphrase; derived locally if empty
ATLASSIAN_FRONTEND_BASE_URL=http://localhost:3000
```

5. Restart the backend. Open **Knowledge Base → Add Knowledge → Import from Jira/Confluence → Connect Atlassian**.

## Security

- Client secret, access tokens, and refresh tokens stay on the backend.
- Tokens are encrypted at rest under `backend/data/atlassian/` (local-dev file adapter).
- Frontend never receives tokens or encryption keys.
- Imports are scoped to the active QA Copilot `project_id`.
- Comments and attachments are disabled by default.

## Sync

Use **Sync Now** on an imported source card to re-fetch remote content. Unchanged content hashes skip re-embedding.

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| configuration_missing | Missing client id/secret |
| Consent denied | User cancelled OAuth |
| 401 after idle | Refresh token revoked — disconnect and reconnect |
| 403 on browse | Missing product access or scope |
| 429 | Rate limited — automatic Retry-After backoff |

## Architecture

```
UI → FastAPI /api/integrations/atlassian → OAuth / Jira / Confluence adapters
  → normalize → DocumentIngester + VectorStore (project_id metadata)
  → Context Fusion / Evidence (existing path)
```
