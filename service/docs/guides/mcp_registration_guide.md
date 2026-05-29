# MCP Registration Guide

This guide explains how to register an MCP server in our platform, from the easiest no-auth case to real-world OAuth-protected MCPs such as GitHub Remote MCP.

## 1. What registration does

Registering an MCP server means our platform stores:

1. The upstream MCP server endpoint.
2. A normalized list of tools exposed by that MCP.
3. Provider-facing descriptions and usage hints for tool selection.
4. Optional provider/execution auth needed to reach the upstream MCP.
5. Optional delegated client auth needed before a user can execute a tool.
6. Indexing records so `find_best_tool` can retrieve the tool later.

After registration and indexing, Claude can call our MCP endpoint and use:

```text
find_best_tool -> execute_tool
```

## 2. Where to register

Local UI:

```text
http://127.0.0.1:3001/dashboard/register
```

Local backend API:

```text
http://127.0.0.1:3000/api/servers
```

For normal operation, use the UI because it guides discovery, manual fallback, metadata editing, and delegated auth setup.

## 3. Registration wizard overview

The UI has four steps:

1. **Connect**
   - Enter server ID, name, URL, description, tags, discovery auth, and optional delegated client auth.
2. **Review**
   - Review tool metadata discovered from upstream, or enter tools manually if discovery fails.
3. **Edit**
   - Write the final provider-facing descriptions, parameter notes, examples, and hints used by selection.
4. **Confirm**
   - Review the final payload and register the server.

## 4. Field-by-field explanation

### 4.1 Server ID

Example:

```text
context7-realworld-pw-hybrid
github-copilot-oauth-realworld
```

Rules:

- Use lowercase letters, numbers, hyphens, and underscores when possible.
- It should be stable because tool IDs are derived from it.
- Tool IDs become:

```text
<server_id>::<tool_name>
```

Example:

```text
context7-realworld-pw-hybrid::query-docs
```

### 4.2 Server Name

Human-readable display name.

Example:

```text
Context7 Real World MCP
GitHub Copilot Remote MCP OAuth
```

### 4.3 Server URL

The upstream MCP endpoint.

Examples:

```text
https://mcp.context7.com/mcp
https://api.githubcopilot.com/mcp/
```

Important:

- Stateless HTTP MCPs often use `/mcp`.
- Some providers require a trailing slash; preserve the official provider URL.
- If the server requires auth, discovery may fail until auth metadata is configured.

### 4.4 Description

Write when and why this server should be used.

Good example:

```text
GitHub official remote MCP server for repository, issues, pull requests, code search, and workflow operations. Requires delegated GitHub OAuth authorization.
```

Avoid vague descriptions like:

```text
GitHub tools
```

The description feeds selection and provider-facing review.

### 4.5 Tags

Comma-separated labels.

Example:

```text
github, oauth, repos, issues, pull-requests, real-world
```

Tags are not a substitute for a good description.

## 5. Discovery authentication

Discovery auth is for the platform contacting the upstream MCP during metadata fetch.

Options include:

- No auth
- Bearer token
- API key header
- Custom headers
- OAuth session

Use this when the upstream MCP requires platform/provider-owned credentials just to list tools.

### No auth

Use for public MCPs like Context7:

```text
Auth type: No auth
```

### Bearer token/API key/custom headers

Use only when the provider gives a static credential for server discovery/execution.

Never paste secrets into docs, Claude prompts, screenshots, or logs.

### OAuth session

Use when the platform/provider owns an OAuth refresh token for the upstream MCP. This is different from delegated end-user OAuth.

## 6. Optional delegated client auth

Delegated client auth means the end user must connect their provider account before `execute_tool` can run.

This is the right model for:

- GitHub user/repo access
- Google Drive/Calendar user data
- Slack user/workspace actions
- Notion user workspace access

Fields:

```text
OAuth provider key:
github

Scope mode:
Default provider scopes

Required OAuth scopes:
repo
read:user
```

This creates an auth requirement. At execute time, if the user has no valid connection, the backend returns `auth_required` instead of contacting upstream.

## 7. Provider bootstrap: when it is required

If you enter:

```text
OAuth provider key: github
```

then `github` must exist and be enabled in `oauth_provider_registry`.

If not, registration fails with:

```text
Delegated client auth provider 'github' is not configured in oauth_provider_registry. Bootstrap the provider registry before registering this server.
```

This is intentional. It prevents registering a tool that would later claim to support OAuth but cannot actually start the OAuth flow.

## 8. How to bootstrap a new OAuth provider

Provider bootstrap is an **admin-only operation**. The backend routes for bootstrap and enable require a platform-admin user. If a non-admin user tries this path, the API returns 403.

Bootstrap also requires the backend secret store to be available when the provider uses `client_secret_post` or `client_secret_basic`. In deployed AWS environments this means AWS Secrets Manager permissions must be configured for the relevant Lambda roles. If the secret store is unavailable, bootstrap fails instead of storing the client secret unsafely.

The wizard includes:

```text
Bootstrap this OAuth provider if it is new
```

Fill this when the provider key does not already exist and you are operating as a platform admin.

For GitHub local testing:

```text
Provider display name:
GitHub

Token auth method:
Client secret POST

Authorization endpoint:
https://github.com/login/oauth/authorize

Token endpoint:
https://github.com/login/oauth/access_token

Bootstrap client ID:
<GitHub OAuth App Client ID>

Bootstrap client secret:
<GitHub OAuth App Client Secret>
```

The client secret must be sent only through the UI/backend bootstrap flow. Do not put it in markdown, shell history, screenshots, or Claude prompts. The backend stores a secret reference, not a plaintext secret, when the configured secret store is available.

Promotion is path-bound: enabling `/api/oauth/providers/{provider_key}/enable` verifies that `{provider_key}` matches the draft's provider before promotion. This prevents an admin from accidentally promoting a `github` draft through a different provider path.

## 9. Creating a GitHub OAuth App for local testing

In GitHub:

```text
Settings -> Developer settings -> OAuth Apps -> New OAuth App
```

Recommended local values:

```text
Application name:
MLP Local GitHub MCP Broker

Homepage URL:
http://127.0.0.1:3001

Authorization callback URL:
http://127.0.0.1:3000/api/oauth/providers/github/callback
```

After creation, copy:

```text
Client ID
Client Secret
```

Use those in the provider bootstrap section.

## 10. Discovery failure and manual tool entry

Authenticated MCPs may reject metadata discovery before the user has connected OAuth.

Example GitHub Remote MCP discovery result during local testing:

```text
POST /api/providers/servers/discovery -> 502
```

In that case:

1. Click **Continue manually**.
2. Add the tools you want to publish.
3. Fill upstream descriptions from provider docs or known tool definitions.
4. Continue to metadata editing.

Manual entry is acceptable, but it must be accurate. If you are unsure about tool names or parameter schema, do not guess for production.

## 11. Example: public no-auth MCP registration

Use Context7 as a simple public MCP test.

Connect step:

```text
Server ID:
context7-realworld-pw-hybrid

Server Name:
Context7 Real World MCP

Server URL:
https://mcp.context7.com/mcp

Description:
Real-world Context7 remote MCP server for documentation lookup and library ID resolution.

Tags:
docs, context7, real-world

Discovery authentication:
No auth

Delegated client auth:
leave empty
```

Expected result:

- discovery succeeds
- tools appear in review step
- registration succeeds
- indexing completes
- `find_best_tool` can return Context7 tools
- `execute_tool` can run without OAuth

## 12. Example: GitHub Remote MCP registration

Target URL:

```text
https://api.githubcopilot.com/mcp/
```

Connect step:

```text
Server ID:
github-copilot-oauth-realworld

Server Name:
GitHub Copilot Remote MCP OAuth

Server URL:
https://api.githubcopilot.com/mcp/

Description:
GitHub official remote MCP server for repository, issues, pull requests, code search, and workflow operations. Requires delegated GitHub OAuth authorization.

Tags:
github, oauth, repos, issues, pull-requests, real-world
```

Discovery authentication:

```text
No auth
```

Delegated client auth:

```text
OAuth provider key:
github

Scope mode:
Default provider scopes

Required OAuth scopes:
repo
read:user
```

Provider bootstrap, if `github` is not already enabled:

```text
Provider display name:
GitHub

Token auth method:
Client secret POST

Authorization endpoint:
https://github.com/login/oauth/authorize

Token endpoint:
https://github.com/login/oauth/access_token

Bootstrap client ID:
<client id from GitHub OAuth App>

Bootstrap client secret:
<client secret from GitHub OAuth App>
```

If discovery fails:

1. Click **Continue manually**.
2. Add representative tools.
3. Fill descriptions, parameter notes, examples, and hints.
4. Confirm registration.

Representative manual tools for GitHub testing:

```text
search_issues
list_issues
get_file_contents
```

Important: exact upstream tool names and schemas should be verified against the current GitHub MCP docs before production publication.

## 13. What happens after registration

Registration writes:

- `mcp_servers`
- `mcp_tools`
- optional `mcp_server_auth`
- optional `mcp_auth_requirements`
- provider ownership metadata

Then it publishes an indexing event.

Indexing:

1. Fetches pending tools.
2. Claims them as `indexing`.
3. Writes embeddings into Qdrant.
4. Marks tools `indexed` with `indexed_at`.
5. Reconciles server status.

For local hybrid search, compose defaults to:

```text
QDRANT_COLLECTION_NAME=mcp_tools_hybrid
```

## 14. How to verify registration

### UI

Go to registry/search and confirm the server/tools appear.

### Supabase

Check server/tool status:

```sql
select s.server_id, s.index_status as server_status, t.tool_id, t.index_status as tool_status, t.indexed_at
from public.mcp_servers s
join public.mcp_tools t on t.server_id = s.server_id
where s.server_id = '<server_id>'
order by t.tool_id;
```

Expected:

```text
server_status = indexed
tool_status = indexed
indexed_at is not null
```

### Search API

```bash
curl -fsS -X POST http://127.0.0.1:3000/api/search \
  -H "x-api-key: $MLP_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"find GitHub issues","top_k":5}'
```

Expected:

- relevant registered tool appears
- `degraded=false`

### Claude

Claude should call our MCP endpoint:

```text
http://127.0.0.1:8080/mcp
```

Then ask:

```text
find_best_tool로 GitHub issue를 조회할 수 있는 tool을 찾아줘.
```

Then:

```text
execute_tool로 방금 찾은 tool을 실행해줘. 인증이 필요하면 oauth_url을 알려줘.
```

For delegated OAuth tools, first execute should return `auth_required` until the user completes OAuth.

## 15. Common errors

### Provider key not configured

```text
Delegated client auth provider 'github' is not configured in oauth_provider_registry.
```

Fix:

- Bootstrap and enable the provider first.

### Discovery 502

Possible causes:

- upstream requires auth
- upstream is down
- URL is wrong
- provider blocks unauthenticated tool listing

Fix:

- configure discovery auth if available
- otherwise continue manually only if tool metadata is known

### Upstream 406

Cause:

- upstream MCP requires MCP-compatible Accept header

Expected platform behavior:

```http
Accept: application/json, text/event-stream
```

### Tool indexed but server pending

Expected platform behavior after this lane:

- server status is reconciled from tool statuses.

## 16. Production checklist

Before publishing a real provider MCP:

- [ ] Upstream URL verified from official provider docs.
- [ ] Tool names and schemas verified from discovery or official docs.
- [ ] Provider OAuth app created with correct callback URL.
- [ ] User performing bootstrap/enable has platform-admin role.
- [ ] AWS Secrets Manager or the configured secret store is available for client-secret providers.
- [ ] Provider registry row enabled.
- [ ] Client secret stored through backend secret flow, not plaintext docs.
- [ ] Required scopes are minimal.
- [ ] Discovery/manual metadata reviewed by a human.
- [ ] Registration returns success.
- [ ] Indexing reaches `indexed`.
- [ ] `find_best_tool` returns the tool for expected queries.
- [ ] First `execute_tool` returns `auth_required` for a new user.
- [ ] OAuth callback stores connection.
- [ ] Second `execute_tool` executes upstream successfully.
