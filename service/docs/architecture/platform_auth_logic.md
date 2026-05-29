# Platform Authentication Logic

This document explains the authentication logic in our MCP platform in plain language and maps it to the main code paths.

## 1. Why auth is split into layers

MCP registration and execution involve three different actors:

1. **Provider**
   - The person or organization registering an MCP server in our platform.
2. **Client**
   - Claude or another MCP client calling our MCP endpoint.
3. **End user**
   - The human whose external account may be needed to execute a tool.

Because of this, one generic auth field is not enough. We intentionally split auth into separate layers.

## 2. The three auth layers

### 2.1 Platform/API auth

This protects our own API and MCP endpoint.

Examples:

- API key for direct backend search/execute calls.
- Supabase browser session JWT for dashboard/provider users.
- Bearer token passed by local MCP clients.

Purpose:

> Decide whether the caller may use our platform.

Main files:

- `service/api/local_app.py`
- `service/mcp_server/local_app.py`
- `service/lambdas/authorizer/`

### 2.2 Execution auth / upstream provider auth

This is auth our platform uses to contact the upstream MCP server.

Examples:

- static bearer token
- API key header
- custom headers
- provider-owned OAuth refresh token

Purpose:

> Let the platform reach the provider MCP server.

This is configured at registration through `execution_auth` and persisted in server auth tables.

Main files:

- `service/services/register_service.py`
- `service/services/upstream_auth.py`
- `service/adapters/supabase_client.py`
- `service/adapters/aws_secrets_manager.py`

### 2.3 Delegated client auth

This is auth the end user must complete before a tool can run on that user's behalf.

Examples:

- GitHub OAuth for repo access
- Google OAuth for user files/calendar
- Slack OAuth for workspace/user actions

Purpose:

> Let a user authorize the platform to call a provider MCP for that user.

This is configured through `client_auth` and persisted in `mcp_auth_requirements`.

Main files:

- `service/services/register_service.py`
- `service/services/execute_service.py`
- `service/services/oauth_broker.py`
- `service/services/oauth_provider_bootstrap.py`
- `service/adapters/execution.py`
- `service/adapters/supabase_client.py`

## 3. Registration-time auth logic

Registration starts in the local/API boundary and routes to `RegisterService.register()`.

The important steps are:

1. Validate server fields:
   - `server_id`
   - `name`
   - `url`
   - `tools`
2. Validate `execution_auth`.
3. Validate transport metadata.
4. Validate descriptions.
5. Build delegated client auth rows from `client_auth`.
6. Persist server row.
7. Persist provider/execution auth if present.
8. Persist tools.
9. Persist delegated auth requirements.
10. Publish indexing event.

## 4. `execution_auth` in detail

`execution_auth` answers this question:

> What credentials does our platform need when calling the upstream MCP server?

Examples:

```json
{
  "execution_auth": {
    "auth_type": "none"
  }
}
```

```json
{
  "execution_auth": {
    "auth_type": "bearer",
    "bearer_token": "..."
  }
}
```

```json
{
  "execution_auth": {
    "auth_type": "api_key",
    "api_key_header": "X-API-Key",
    "api_key": "..."
  }
}
```

```json
{
  "execution_auth": {
    "auth_type": "oauth_session",
    "oauth_token_endpoint": "https://provider.example.com/oauth/token",
    "oauth_client_id": "...",
    "oauth_client_secret": "...",
    "oauth_refresh_token": "..."
  }
}
```

Security rule:

> Secret values should be converted to secret refs when possible. They should not be printed or stored in docs.

## 5. `client_auth` in detail

`client_auth` answers this question:

> Does the end user need to connect an external provider account before executing this tool?

Example:

```json
{
  "client_auth": {
    "provider_key": "github",
    "required_scopes": ["repo", "read:user"],
    "scope_mode": "default"
  }
}
```

This creates rows in `mcp_auth_requirements`.

There are two levels:

1. Server-level auth requirement
   - applies to all tools in the server.
2. Tool-level auth requirement
   - applies only to a specific tool.

Tool-level requirement is useful when one MCP server exposes both public and private tools.

## 6. Why `oauth_provider_registry` is required

`client_auth.provider_key` is only a key. It is not enough to start OAuth.

The runtime also needs:

- authorization endpoint
- token endpoint
- client id
- client secret ref when required
- redirect URI
- PKCE setting
- token auth method
- enabled flag

Those values live in `oauth_provider_registry`.

If a provider key is missing or disabled, registration/execution fails closed.

Example fail-closed message during GitHub MCP registration:

```text
Delegated client auth provider 'github' is not configured in oauth_provider_registry. Bootstrap the provider registry before registering this server.
```

This prevents a bad state where a tool advertises GitHub OAuth but the platform cannot actually start GitHub OAuth.

## 7. OAuth provider bootstrap logic

Provider bootstrap is the process of creating or enabling an `oauth_provider_registry` entry. It is intentionally **platform-admin only**. The route handler checks the authenticated user's role before allowing discovery/manual/DCR bootstrap or enable operations. Non-admin users should register ordinary MCP servers only after an admin has enabled the provider key they need.

For providers that require `client_secret_post` or `client_secret_basic`, bootstrap also requires the backend secret store. In AWS deployments this is AWS Secrets Manager plus IAM permissions for the Lambda role. If the secret store is unavailable, bootstrap fails closed with a retryable bootstrap error rather than persisting plaintext client secrets.

Supported paths:

1. Discovery
   - Try provider metadata documents such as OAuth/OIDC authorization server metadata.
2. DCR
   - Dynamic Client Registration when the provider supports it.
3. Guided manual bootstrap
   - Operator enters OAuth app values from the provider console.

Manual bootstrap is required for many real providers because app creation and client secret issuance are operator-controlled.

For GitHub local testing, manual bootstrap uses:

```text
provider_key: github
display_name: GitHub
authorize_url: https://github.com/login/oauth/authorize
token_url: https://github.com/login/oauth/access_token
client_id: <GitHub OAuth App Client ID>
client_secret: <GitHub OAuth App Client Secret>
token_endpoint_auth_method: client_secret_post or client_secret_basic
redirect_uri: http://127.0.0.1:3000/api/oauth/providers/github/callback
```

Main file:

```text
service/services/oauth_provider_bootstrap.py
```

Important safeguards:

- bootstrap and enable routes require platform-admin role
- enable is path-bound: `/api/oauth/providers/{provider_key}/enable` verifies that the draft provider matches `{provider_key}` before promotion
- provider keys are normalized and validated
- metadata URLs must be safe HTTPS URLs unless explicitly local
- private/link-local/loopback metadata hosts are blocked for public discovery
- sensitive fields are redacted from diagnostics
- secrets are stored as refs through a secret store, and client-secret flows fail if that store is unavailable
- drafts are separate from enabled runtime registry rows

## 8. Execute-time delegated auth flow

The main execution path is `ExecuteService.execute()`.

High-level flow:

1. Fetch tool contract by `tool_id`.
2. Validate server allow-list if configured.
3. Validate params against the tool input schema.
4. Check whether the tool has `auth_requirement`.
5. If no auth requirement, call upstream.
6. If auth requirement exists:
   - require an authenticated platform user
   - find an existing user provider connection
   - if connection exists and scopes cover the requirement, resolve Authorization header
   - if no connection exists, create pending execution and return `auth_required`
7. Merge upstream auth headers and delegated user auth headers.
8. Call upstream MCP.
9. Log execution result.

## 9. `auth_required` response

When delegated auth is required but missing, execute returns a structured response instead of contacting upstream.

Shape:

```json
{
  "status": "auth_required",
  "tool_id": "github-copilot-oauth-realworld::search_issues",
  "server_id": "github-copilot-oauth-realworld",
  "auth": {
    "provider": "github",
    "required_scopes": ["repo", "read:user"],
    "oauth_url": "http://127.0.0.1:3001/login?redirect=...",
    "pending_execution_id": "...",
    "resume_token": "..."
  }
}
```

Important behavior:

- No upstream call happens yet.
- The tool params are stored in pending execution state.
- The OAuth URL includes enough state to resume after login/connection.
- The resume token is opaque and should not expose secret material.

## 10. Pending execution and resume token

A pending execution exists because OAuth is a browser flow but `execute_tool` starts from Claude.

Without pending execution, the platform would forget:

- which tool Claude tried to execute
- what params were supplied
- which provider/scopes were required
- which user started the flow

The pending execution stores this context server-side.

The resume token lets the platform connect the post-auth flow back to the original execution attempt without putting sensitive state in the browser URL.

Main file:

```text
service/services/pending_execution.py
```

## 11. OAuth start flow

When the user opens the OAuth URL:

1. The platform identifies provider key and required scopes.
2. `OAuthBrokerService.start_authorization()` loads the enabled registry row.
3. It creates a PKCE verifier/challenge if required.
4. It creates an opaque nonce.
5. It stores a hashed nonce and server-side facts in `oauth_state_nonces`:
   - user id
   - provider key
   - required scopes
   - tool id
   - pending execution id
   - redirect URI
   - issuer
   - code verifier
   - expiry
6. It builds the provider authorization URL.
7. The user's browser is redirected to the provider.

Main file:

```text
service/services/oauth_broker.py
```

## 12. OAuth callback flow

After the user approves provider OAuth:

1. Provider redirects to our callback with `code` and `state`.
2. State is decoded and expiry is checked.
3. The nonce is hashed and consumed from `oauth_state_nonces`.
4. Replay is blocked because nonce consumption is one-time.
5. Provider key, issuer, and redirect URI are compared against server-side nonce facts.
6. Code is exchanged at the provider token endpoint.
7. Granted scopes are normalized.
8. `user_provider_connections` is upserted.
9. Tokens are stored for the connection.
10. Pending execution is marked ready when applicable.

Security properties:

- PKCE verifier is stored server-side, not trusted from URL state.
- Front-channel state is only a pointer/nonce plus provider and expiry.
- Callback fails closed on provider mismatch, issuer mismatch, redirect mismatch, missing nonce, expired state, or replay.

## 13. User provider connection lookup

At execute time, `find_user_provider_connection()` checks whether the current user already has a provider connection whose scopes cover the required scopes.

If yes:

- execution continues
- token headers are resolved

If no:

- `auth_required` is returned

Scope coverage matters. A GitHub connection with only `read:user` should not satisfy a tool that requires `repo`.

## 14. Token resolution and refresh

`resolve_user_provider_headers()` loads the stored token row.

It checks:

- access token exists
- provider key can be determined
- provider registry row exists and is enabled
- token is not expired or too close to expiry
- refresh token is available when refresh is needed

If refresh is needed and possible:

1. Call provider token endpoint with `grant_type=refresh_token`.
2. Use the registry's token endpoint auth method.
3. Store refreshed token values.
4. Return:

```http
Authorization: Bearer <access_token>
```

If token cannot be resolved safely, execution returns `auth_revoked` or fails before upstream.

## 15. Header merge order

During upstream execution:

1. Resolve platform/provider upstream headers from `execution_auth`.
2. Resolve delegated user headers from `client_auth` connection.
3. Merge them.
4. Call upstream MCP.

Current behavior:

```python
headers = {**upstream_headers, **delegated_headers}
```

This means delegated headers win on duplicate keys such as `Authorization`.

That is intentional for user-delegated OAuth tools because the upstream MCP should receive the user's provider token.

## 16. MCP HTTP client behavior

The upstream MCP HTTP client sends JSON-RPC `tools/call`.

For real-world stateless HTTP MCP compatibility, it now sends:

```http
Accept: application/json, text/event-stream
Content-Type: application/json
```

This matters because some MCP servers reject generic JSON requests with HTTP 406 unless the Accept header includes MCP streamable response types.

Main file:

```text
service/adapters/mcp_http_client.py
```

## 17. Gateway vs stateless HTTP

Some MCP transports require a long-running session:

- `streamable_http`
- `sse`
- `stdio`

For these, registration must set:

```json
{
  "transport_type": "sse",
  "requires_gateway": true
}
```

Stateless HTTP tools can execute directly through `MCPHTTPClient`.

Gateway execution receives delegated headers too, so auth behavior should stay consistent across transports.

## 18. Fail-closed rules

The platform should fail closed when:

- non-admin user attempts provider bootstrap or provider enable
- provider enable path key does not match the draft provider key
- provider key is unknown
- provider registry row is disabled
- OAuth state nonce is missing or replayed
- OAuth state provider mismatches callback provider
- redirect URI mismatches nonce/registry
- issuer mismatches nonce/registry
- required user context is missing
- required scopes are not covered
- delegated token is missing, expired, or revoked
- upstream auth secret refs cannot be resolved
- OAuth provider client secret cannot be stored or resolved for a client-secret flow

Failing closed means returning a structured error/auth response before making an unsafe upstream call.

## 19. Data model summary

Important tables:

- `mcp_servers`
  - registered MCP server metadata
- `mcp_tools`
  - registered tools and indexing state
- `mcp_server_auth`
  - platform/provider upstream auth metadata
- `mcp_auth_requirements`
  - delegated client auth requirements per server/tool
- `oauth_provider_registry`
  - enabled provider OAuth runtime metadata
- `oauth_provider_bootstrap_drafts`
  - draft provider bootstrap data before promotion
- `oauth_state_nonces`
  - one-time OAuth state/PKCE replay protection
- `user_provider_connections`
  - user-to-provider connection rows
- token storage table/secret refs
  - access/refresh tokens or references
- `pending_executions`
  - execute attempts waiting on browser OAuth
- `execution_logs`
  - execution observability

## 20. End-to-end example: GitHub MCP

### Registration

The provider registers:

```json
{
  "server_id": "github-copilot-oauth-realworld",
  "url": "https://api.githubcopilot.com/mcp/",
  "client_auth": {
    "provider_key": "github",
    "required_scopes": ["repo", "read:user"],
    "scope_mode": "default"
  }
}
```

### First execute

Claude calls:

```json
{
  "tool_id": "github-copilot-oauth-realworld::search_issues",
  "params": {
    "query": "repo:owner/repo is:issue is:open"
  }
}
```

If the user has no GitHub connection, response is:

```text
auth_required
```

### User connects GitHub

The user opens the OAuth URL, approves GitHub, and returns to callback.

The platform stores the user provider connection and token.

### Second execute

Claude retries the same tool.

The platform now resolves:

```http
Authorization: Bearer <user GitHub token>
```

and calls the upstream GitHub MCP.

## 21. Security notes

- Never log OAuth client secrets, access tokens, refresh tokens, codes, or code verifiers.
- Prefer secret refs over plaintext storage.
- Keep OAuth state small and non-sensitive.
- Store PKCE verifier server-side.
- Consume nonce once.
- Keep provider registry disabled until verified.
- Use minimal scopes.
- Treat upstream MCP output as untrusted user data.
- Do not register delegated-auth tools against unknown provider keys.

## 22. Current known limitation

GitHub Remote MCP live execution cannot be completed until the operator creates a GitHub OAuth App and bootstraps the `github` provider registry entry with its client id/secret.

The platform currently behaves correctly by rejecting the GitHub MCP registration before that bootstrap exists.
