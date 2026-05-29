

# Updated Implementation Plan — Critical Notes Integration

These three implementation notes will be woven into the existing MCP Discovery Platform plan as cross-cutting concerns applied during build.

## 1. tool_id URL Encoding

**Problem**: `tool_id` uses `::` separator (e.g., `github::search_repos`) which breaks in URL paths.

**Where it applies**:
- Every link/navigation to `/tools/:toolId` and `/dashboard/tools/:toolId`
- Route param reading in `ToolDetail` and `DashboardToolDetail` pages
- `ResultCard`, `ServerDetail` tool lists, `Dashboard` table rows — anywhere a tool link is built

**Implementation**:
- Links: `to={\`/tools/${encodeURIComponent(tool.tool_id)}\`}`
- Pages: `const toolId = decodeURIComponent(useParams().toolId!)`
- Apply consistently in all components that generate or consume tool URLs

## 2. Environment Variable Config Pattern

**File**: `src/lib/config.ts`

```text
config.supabase.isConfigured  →  checks VITE_SUPABASE_URL + VITE_SUPABASE_ANON_KEY
config.api.isConfigured       →  checks VITE_API_URL + VITE_MLP_API_KEY
```

**Where it applies**:
- All react-query hooks: `useQuery({ ..., enabled: config.supabase.isConfigured })`
- Search API calls: `enabled: config.api.isConfigured && !!query`
- Supabase client creation: guard against empty URL
- Each page renders a specific fallback message when the relevant config is not available (Stage 0/1/2 degradation from the original spec)

## 3. Error Handling Matrix

| Scenario | Detection | UI Response |
|----------|-----------|-------------|
| API 429 | `res.status === 429` | Sonner toast: "Rate limit reached, try again shortly" |
| API 5xx | `res.status >= 500` | Sonner toast: "Service temporarily unavailable" |
| Supabase query error | react-query `isError` | Inline message: "Could not load data" (no crash) |
| Session expired | `onAuthStateChange` SIGNED_OUT event while on protected route | Redirect to `/login?message=session_expired` |
| Email not confirmed | Supabase auth error code | Show "Please check your email to confirm your account" |
| Invalid credentials | Supabase auth error | Show "Invalid email or password" below form |
| Config missing | `!config.supabase.isConfigured` | Page-level: "Supabase is not configured yet" |
| Search API missing | `!config.api.isConfigured` | "Semantic search is coming soon. Browse the registry instead." |

**Implementation approach**:
- Wrap search API fetch in a helper that maps status codes to toast messages
- Use react-query's `onError` or error boundaries per-query for Supabase
- Auth errors handled in the Login page's submit handler with error code matching
- `ProtectedRoute` component listens to auth state and redirects with query param message

## No Other Changes

The rest of the original plan (pages, components, routing, design, types) remains exactly as specified. These three notes are implementation constraints applied across all relevant files during build.

