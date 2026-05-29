# MCP Discovery Frontend Specification — MCP Discovery Platform

> **Version**: 1.0 (2026-04-04)
> **Target**: MCP Discovery prompt specification — copy-pasteable to generate the full frontend
> **Backend**: Supabase (PostgreSQL + Auth) + AWS API Gateway (REST endpoints)

---

## MCP Discovery Prompt

Build a developer-focused MCP (Model Context Protocol) tool discovery platform called **MCP Discovery**. It has two sides: (1) a public registry and semantic search engine for browsing and finding MCP tools, and (2) a provider dashboard showing GEO Score diagnostics that explain why a tool is or isn't being selected in search results.

Tech stack: React + TypeScript + Tailwind CSS + shadcn/ui. Connect to Supabase for auth, database queries, and row-level security. Call an external REST API (API Gateway) for semantic search and tool execution. Dark mode by default, desktop-first but mobile-responsive.

---

## 1. Pages & Routes

| Route | Page | Auth | Description |
|-------|------|------|-------------|
| `/` | Landing | Public | Hero section, value prop, quick search bar, stats |
| `/search` | Search | Public | Main search experience with result cards |
| `/servers` | Server Listing | Public | Browse all registered MCP servers |
| `/servers/:serverId` | Server Detail | Public | Server info + its tools list |
| `/tools/:toolId` | Tool Detail | Public | Full tool info, input schema, GEO score |
| `/dashboard` | Provider Dashboard | Auth | Overview of provider's tools, aggregate GEO scores |
| `/dashboard/tools/:toolId` | Tool GEO Detail | Auth | Per-tool GEO score radar, improvement suggestions, search simulator |
| `/login` | Login/Signup | Public | Supabase email/password auth |

---

## 2. Data Sources Per Page

### `/` — Landing Page

```
Data:
  - Supabase direct: SELECT count(*) FROM mcp_servers
  - Supabase direct: SELECT count(*) FROM mcp_tools
  - No auth required (anon key)

Display:
  - Hero: "Discover the right MCP tool for any task"
  - Subtitle: "Semantic search engine + provider optimization platform for MCP tools"
  - Quick search bar (navigates to /search?q=...)
  - Stats row: "{N} servers", "{N} tools indexed"
  - Three feature cards:
    1. "Semantic Search" — Find tools by describing what you need
    2. "GEO Score Diagnostics" — See why your tool ranks where it does
    3. "MCP Bridge" — Connect any LLM client to the best tools
  - CTA: "Browse Registry" → /servers, "Search Tools" → /search
```

### `/search` — Search Page

```
Data:
  - Input: search query from text input
  - API call: POST ${VITE_API_URL}/api/search
    Headers: { "Content-Type": "application/json", "x-api-key": VITE_MLP_API_KEY }
    Body: { "query": string, "top_k": 5 }
  - Response shape:
    {
      "results": [
        {
          "tool": {
            "tool_id": "github::search_repositories",
            "server_id": "github",
            "tool_name": "search_repositories",
            "description": "Search GitHub repositories by query..."
          },
          "score": 0.92,
          "rank": 1,
          "reason": "Directly matches repository search functionality",
          "input_schema": { "type": "object", "properties": { "query": { "type": "string" } } },
          "score_breakdown": { "relevance": 0.92, "quality": 0.0, "boost": 0.0 },
          "is_boosted": false
        }
      ],
      "query": "search GitHub repos",
      "strategy": "sequential",
      "latency_ms": 342
    }
  - No auth required (API key is in env var, not user credential)

Display:
  - Full-width search bar at top with placeholder "Describe what you need, e.g. 'search GitHub repositories'"
  - Below search bar: latency badge ("342ms"), strategy badge ("sequential")
  - Result cards (see ResultCard component below)
  - Empty state: "Enter a query to search across {N} MCP tools"
  - Loading state: skeleton cards
  - Error state: "Search is temporarily unavailable. Please try again."
```

### `/servers` — Server Listing Page

```
Data:
  - Supabase direct:
    SELECT server_id, name, description, tags, index_status, created_at
    FROM mcp_servers
    ORDER BY name ASC
    LIMIT 50 OFFSET (page * 50)
  - Supabase direct (for tool counts):
    SELECT server_id, count(*) as tool_count
    FROM mcp_tools
    GROUP BY server_id
  - No auth required (anon key)

Display:
  - Page title: "MCP Server Registry"
  - Filter bar: text search (client-side filter on name/description), tag filter dropdown
  - Grid of ServerCards (3 columns on desktop, 1 on mobile)
  - Index status badges: "indexed" (green), "pending" (yellow), "failed" (red)
  - Pagination: simple "Load More" button
```

### `/servers/:serverId` — Server Detail Page

```
Data:
  - Supabase direct:
    SELECT * FROM mcp_servers WHERE server_id = :serverId
  - Supabase direct:
    SELECT tool_id, tool_name, description, geo_score, index_status
    FROM mcp_tools
    WHERE server_id = :serverId
    ORDER BY tool_name ASC
  - No auth required

Display:
  - Server header: name, description, URL (as link), tags as badges, index_status
  - "Tools ({count})" section with list of ToolCards
  - Each ToolCard: tool_name (monospace), description (truncated 2 lines), GEO total score badge (if available), index status dot
  - Click ToolCard → navigate to /tools/:toolId
```

### `/tools/:toolId` — Tool Detail Page

```
Data:
  - Supabase direct:
    SELECT * FROM mcp_tools WHERE tool_id = :toolId
  - Supabase direct (for server info):
    SELECT name, server_id, url FROM mcp_servers WHERE server_id = (tool's server_id)
  - No auth required

Display:
  - Breadcrumb: Servers > {server_name} > {tool_name}
  - Tool header: tool_name (monospace, large), server badge (link to server page)
  - Description: full text, rendered as markdown
  - Input Schema section: render JSON schema as a readable form preview
    - For each property: name, type, required badge, description
    - Collapsible raw JSON view
  - GEO Score section (if geo_score is not null):
    - GEO Score Radar chart (6-axis)
    - Score breakdown table with dimension names and values (0.0-1.0)
    - Total score prominently displayed
  - Index status indicator
```

### `/dashboard` — Provider Dashboard (Auth Required)

```
Data:
  - Auth: Supabase session required, redirect to /login if not authenticated
  - Supabase direct:
    SELECT t.tool_id, t.tool_name, t.description, t.geo_score, t.server_id, s.name as server_name
    FROM mcp_tools t
    JOIN mcp_servers s ON t.server_id = s.server_id
    ORDER BY (t.geo_score->>'total')::float ASC NULLS LAST
    LIMIT 100
    (NOTE: MLP shows all tools, not filtered by provider. Provider-scoped in Phase 2.)
  - No API call needed

Display:
  - Page title: "Provider Dashboard"
  - Summary row: total tools, average GEO score, tools needing improvement (total < 0.5)
  - Tools table:
    Columns: Tool Name | Server | GEO Total | Clarity | Disambiguation | Params | Boundary | Stats | Precision | Actions
    - Each dimension cell: colored bar (red < 0.3, yellow 0.3-0.6, green > 0.6)
    - Sort by any column
    - Click tool name → /dashboard/tools/:toolId
  - "Tools Needing Attention" section: tools with GEO total < 0.5, sorted ascending
```

### `/dashboard/tools/:toolId` — Tool GEO Detail (Auth Required)

```
Data:
  - Auth: Supabase session required
  - Supabase direct:
    SELECT * FROM mcp_tools WHERE tool_id = :toolId
  - Supabase direct (competitor comparison — same server's tools or similar tools):
    SELECT tool_id, tool_name, geo_score, server_id
    FROM mcp_tools
    WHERE server_id = (tool's server_id) AND tool_id != :toolId
    ORDER BY tool_name
  - API call for search simulation:
    POST ${VITE_API_URL}/api/search
    Body: { "query": user_input, "top_k": 10 }

Display:
  - Tool header: tool_name, server_name, GEO total score (large)
  - GEO Score Radar Chart: 6-axis (clarity, disambiguation, parameter_coverage, boundary, stats, precision)
  - Dimension breakdown cards (6 cards in 2x3 grid):
    For each dimension:
      - Name and score (0.0-1.0)
      - Progress bar (colored)
      - Improvement suggestion text:
        - clarity < 0.5: "Start your description with a specific action verb. Explain WHAT the tool does in the first sentence."
        - disambiguation < 0.3: "Add explicit NOT/AVOID statements to distinguish from similar tools."
        - parameter_coverage < 0.5: "Mention key parameters, their types, and whether they are required or optional."
        - boundary < 0.3: "Describe what this tool does NOT do to prevent misuse."
        - stats < 0.3: "Include quantitative information: rate limits, max sizes, performance characteristics."
        - precision < 0.5: "Use specific technical terms, protocols, and standards (e.g., REST, OAuth, WebSocket)."
  - Competitor Comparison Table:
    - Table of tools from the same server
    - Columns: Tool Name | GEO Total | Each dimension
    - Current tool highlighted
  - Search Simulator:
    - Input field: "Test a query to see where this tool ranks"
    - Submit → POST /api/search with top_k: 10
    - Result: "Your tool '{tool_name}' is rank #{rank} for this query" (or "not in top 10")
    - Show full result list with this tool highlighted
```

### `/login` — Login Page

```
Data:
  - Supabase Auth: email + password sign in / sign up
  - No external API calls

Display:
  - Centered card with MCP Discovery logo
  - Tab toggle: "Sign In" / "Sign Up"
  - Sign In: email input, password input, submit button
  - Sign Up: email input, password input, confirm password, submit button
  - Error messages below form
  - Success: redirect to /dashboard
  - Link: "Back to Registry" → /servers
```

---

## 3. Component Specifications

### SearchBar

```
Props: onSearch(query: string), defaultValue?: string, placeholder?: string
Behavior:
  - Full-width input with search icon on left
  - Submit on Enter key or click search button
  - Debounce not needed (explicit submit, not live search)
  - URL sync: updates ?q= param on submit
Styling:
  - Height: 48px, rounded-lg, border-zinc-700, bg-zinc-900
  - Focus: ring-2 ring-teal-500
  - Placeholder text: text-zinc-500
```

### ResultCard

```
Props: result: SearchResult (tool, score, rank, reason, input_schema, score_breakdown, is_boosted)
Display:
  - Rank badge: "#1" in circle on left
  - Tool name: monospace, text-lg, text-white
  - Server name: text-sm, text-zinc-400, as badge/link
  - Score: colored badge (green > 0.7, yellow 0.4-0.7, red < 0.4), formatted as percentage
  - Reason: text-sm, text-zinc-300, 2 lines max
  - Description: text-sm, text-zinc-400, truncated to 3 lines with "show more"
  - Score breakdown row: three small badges "relevance: 0.92 | quality: 0.00 | boost: 0.00"
  - Expandable section (collapsed by default):
    - Input Schema: rendered as property list (name, type, required, description)
    - "View Full Tool →" link to /tools/:toolId
Styling:
  - Card: bg-zinc-900, border border-zinc-800, rounded-xl, p-6
  - Hover: border-zinc-700 transition
```

### GEOScoreRadar

```
Props: geoScore: { clarity: number, disambiguation: number, parameter_coverage: number, boundary: number, stats: number, precision: number, total: number }
Display:
  - 6-axis radar/spider chart using recharts (RadarChart)
  - Axes: Clarity, Disambiguation, Params, Boundary, Stats, Precision
  - Scale: 0.0 to 1.0
  - Fill: teal-500 with 30% opacity
  - Stroke: teal-400
  - Total score displayed in center of chart
  - Size: 300x300px
Library: recharts (already available in MCP Discovery)
```

### ServerCard

```
Props: server: { server_id, name, description, tags, index_status, tool_count }
Display:
  - Card with name (text-lg, font-semibold), description (truncated 2 lines)
  - Bottom row: tool count badge ("{N} tools"), tags as small badges
  - Index status dot: green (indexed), yellow (pending), red (failed)
  - Click → navigate to /servers/:serverId
Styling:
  - Card: bg-zinc-900, border border-zinc-800, rounded-xl, p-5
  - Hover: border-zinc-600, cursor-pointer
  - Tags: bg-zinc-800, text-xs, rounded-full, px-2 py-1
```

### ToolDetailPanel

```
Used on: /tools/:toolId page
Props: tool: MCPTool (from Supabase), server: MCPServer
Sections:
  1. Header: tool_name (monospace, text-2xl), server badge
  2. Description: full markdown-rendered text
  3. Input Schema:
     - If input_schema exists: render each property as a row
       (property name in monospace, type badge, "required" badge if in required[], description)
     - Collapsible "Raw JSON" toggle showing formatted JSON
     - If no schema: "No input schema defined"
  4. GEO Score (if geo_score not null):
     - GEOScoreRadar component
     - Table with 6 dimensions + values
```

### CompetitorTable

```
Used on: /dashboard/tools/:toolId page
Props: tools: MCPTool[], currentToolId: string
Display:
  - Table with columns: Tool Name | Total | Clarity | Disambig | Params | Boundary | Stats | Precision
  - Current tool row highlighted with bg-teal-900/20 and left border teal-500
  - Score cells: colored text (red < 0.3, yellow 0.3-0.6, green > 0.6)
  - Sort by Total descending
Styling:
  - Table: w-full, text-sm
  - Header: bg-zinc-800, text-zinc-400, uppercase, text-xs
  - Rows: border-b border-zinc-800
```

### SearchSimulator

```
Used on: /dashboard/tools/:toolId page
Props: targetToolId: string, targetToolName: string
Behavior:
  1. Text input: "Enter a search query"
  2. On submit: POST /api/search { query, top_k: 10 }
  3. Find targetToolId in results
  4. Display: "'{targetToolName}' ranked #{rank}" or "Not found in top 10 results"
  5. Show ordered result list with targetTool highlighted
Display:
  - Input + "Simulate" button
  - Results list below (after search):
    Each row: rank, tool_name, score, highlighted if matches targetToolId
Styling:
  - Input: same as SearchBar
  - Results: compact list, bg-zinc-900
  - Highlight: bg-teal-900/30, border-l-2 border-teal-500
```

### Navigation

```
Persistent top navbar:
  - Left: "MCP Discovery" logo/text (link to /)
  - Center: links — "Search" (/search), "Registry" (/servers), "Dashboard" (/dashboard)
  - Right: auth state
    - Not logged in: "Sign In" button → /login
    - Logged in: user email + "Sign Out" button
Styling:
  - Fixed top, bg-zinc-950/80 backdrop-blur, border-b border-zinc-800
  - Height: 56px
  - z-50
```

---

## 4. Auth Flow

```
Provider: Supabase Auth (email + password)

Sign Up:
  1. User fills email + password on /login
  2. supabase.auth.signUp({ email, password })
  3. Email confirmation (Supabase handles)
  4. After confirmation: redirect to /dashboard

Sign In:
  1. User fills email + password on /login
  2. supabase.auth.signInWithPassword({ email, password })
  3. On success: redirect to /dashboard
  4. On error: show error message

Session Management:
  - Use supabase.auth.onAuthStateChange() to track session
  - Store session in React context (AuthProvider)
  - Protected routes (/dashboard/*): redirect to /login if no session

Sign Out:
  - supabase.auth.signOut()
  - Redirect to /

Row Level Security:
  - mcp_servers, mcp_tools: readable by anon (no auth needed for registry)
  - query_logs, execution_logs: service_role only (not accessible from frontend)
  - Dashboard reads mcp_tools/mcp_servers with anon or authenticated role (both have SELECT)
```

---

## 5. API Integration Patterns

### Supabase Client Setup

```typescript
// src/lib/supabase.ts
import { createClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

export const supabase = createClient(supabaseUrl, supabaseAnonKey)
```

### Supabase Direct Queries (Registry Browsing)

```typescript
// Fetch all servers with tool counts
const { data: servers } = await supabase
  .from('mcp_servers')
  .select('server_id, name, description, tags, index_status, created_at')
  .order('name')
  .range(0, 49)

// Fetch tools for a specific server
const { data: tools } = await supabase
  .from('mcp_tools')
  .select('tool_id, tool_name, description, input_schema, geo_score, index_status')
  .eq('server_id', serverId)
  .order('tool_name')

// Fetch single tool by tool_id
const { data: tool } = await supabase
  .from('mcp_tools')
  .select('*')
  .eq('tool_id', toolId)
  .single()

// Aggregate stats for landing page
const { count: serverCount } = await supabase
  .from('mcp_servers')
  .select('*', { count: 'exact', head: true })

const { count: toolCount } = await supabase
  .from('mcp_tools')
  .select('*', { count: 'exact', head: true })
```

### API Gateway Calls (Semantic Search)

```typescript
// src/lib/api.ts
const API_URL = import.meta.env.VITE_API_URL
const API_KEY = import.meta.env.VITE_MLP_API_KEY

export interface SearchResult {
  tool: {
    tool_id: string
    server_id: string
    tool_name: string
    description: string
  }
  score: number
  rank: number
  reason: string | null
  input_schema: Record<string, unknown> | null
  score_breakdown: {
    relevance: number
    quality: number
    boost: number
  } | null
  is_boosted: boolean
}

export interface SearchResponse {
  results: SearchResult[]
  query: string
  strategy: string
  latency_ms: number
}

export async function searchTools(query: string, topK: number = 5): Promise<SearchResponse> {
  const res = await fetch(`${API_URL}/api/search`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': API_KEY,
    },
    body: JSON.stringify({ query, top_k: topK }),
  })

  if (!res.ok) {
    throw new Error(`Search failed: ${res.status} ${res.statusText}`)
  }

  return res.json()
}
```

---

## 6. TypeScript Types (Matching Supabase Schema)

```typescript
// src/types/database.ts

export interface MCPServer {
  id: string           // UUID
  server_id: string    // unique text key, e.g. "github"
  name: string
  description: string | null
  url: string | null
  tags: string[] | null
  index_status: 'pending' | 'indexed' | 'failed'
  created_at: string
  updated_at: string
}

export interface MCPTool {
  id: string           // UUID
  tool_id: string      // format: "server_id::tool_name"
  server_id: string
  tool_name: string
  description: string | null
  input_schema: Record<string, unknown> | null
  geo_score: GEOScore | null
  index_status: 'pending' | 'indexed' | 'failed'
  created_at: string
}

export interface GEOScore {
  clarity: number            // 0.0-1.0
  disambiguation: number     // 0.0-1.0
  parameter_coverage: number // 0.0-1.0
  boundary: number           // 0.0-1.0
  stats: number              // 0.0-1.0
  precision: number          // 0.0-1.0
  total: number              // 0.0-1.0 (average of 6 dimensions)
}
```

---

## 7. Design Direction

### Visual Identity

```
Theme: Dark mode default (no light mode toggle needed for MLP)
Background: zinc-950 (#09090b)
Surface: zinc-900 (#18181b)
Border: zinc-800 (#27272a)
Text primary: zinc-100 (#f4f4f5)
Text secondary: zinc-400 (#a1a1aa)
Text muted: zinc-500 (#71717a)
Accent primary: teal-500 (#14b8a6) — trust, technology
Accent hover: teal-400 (#2dd4bf)
Success: emerald-500 (#10b981)
Warning: amber-500 (#f59e0b)
Error: red-500 (#ef4444)
```

### Typography

```
Body: Inter (default sans-serif from Tailwind)
Code/Tool names: JetBrains Mono or system monospace (font-mono)
Headings: Inter, font-semibold
```

### Layout

```
Max width: 1280px (max-w-7xl), centered
Sidebar: none (top navigation only)
Spacing: consistent use of 4/6/8 spacing scale
Cards: rounded-xl, subtle border, no shadow (flat design)
```

### Aesthetic References

```
Inspired by: Smithery.ai (clean developer tool registry), Linear (dark minimal UI), Vercel dashboard
Key characteristics:
  - Generous whitespace
  - Minimal decoration, content-focused
  - Monospace for technical identifiers
  - Subtle hover states
  - Badge-heavy for metadata (tags, scores, status)
```

---

## 8. Environment Variables

```
VITE_SUPABASE_URL=https://ojuclgsxseygcnjgdpau.supabase.co
VITE_SUPABASE_ANON_KEY=<supabase-anon-key>
VITE_API_URL=https://<api-gateway-id>.execute-api.ap-northeast-2.amazonaws.com/prod
VITE_MLP_API_KEY=<api-gateway-usage-plan-key>
```

Set these in MCP Discovery's environment variable settings. The Supabase anon key is safe to expose (RLS enforces access control). The API key is a frontend-scoped key with rate limits.

---

## 9. Page-by-Page Detailed Specifications

### 9.1 Landing Page (`/`)

```
Layout:
  [Navbar]
  [Hero Section — full width, centered]
    h1: "Discover the Right MCP Tool"
    p: "Semantic search engine connecting LLM clients with the best MCP tools.
        Provider analytics show you how to improve your tool's discoverability."
    [SearchBar — max-w-2xl centered, navigates to /search?q=...]
    [Stats Row — 3 inline badges]
      "{serverCount} Servers" | "{toolCount} Tools" | "6D GEO Scoring"

  [Features Grid — 3 columns]
    Card 1: Icon (Search), "Semantic Search"
      "Describe what you need in natural language.
       Our 2-stage retrieval pipeline finds the best tool."
    Card 2: Icon (BarChart), "GEO Score Diagnostics"
      "6-dimension quality analysis for every tool description.
       See exactly what to improve."
    Card 3: Icon (Zap), "MCP Bridge"
      "Connect your LLM agent to a single endpoint.
       We route queries to the right tool automatically."

  [CTA Row]
    Button primary: "Search Tools" → /search
    Button secondary: "Browse Registry" → /servers

  [Footer — minimal]
    "MCP Discovery Platform" | "Built for MCP tool providers and LLM developers"
```

### 9.2 Search Page (`/search`)

```
Layout:
  [Navbar]
  [Search Section — max-w-4xl centered]
    [SearchBar — full width]
    [Metadata Row — only visible after search]
      "Found {results.length} results in {latency_ms}ms" | Strategy badge

    [Results List — vertical stack, gap-4]
      For each result:
        [ResultCard]

    [Empty State — before any search]
      Icon (Search)
      "Search across {toolCount} MCP tools"
      "Try: 'search GitHub repositories' or 'send emails via SMTP'"

    [No Results State]
      "No tools found for '{query}'"
      "Try rephrasing your query or browse the registry"
      Link: "Browse Registry" → /servers

URL behavior:
  - On page load, check for ?q= param → auto-execute search
  - On search submit, update URL to /search?q={query}
  - This enables shareable search links
```

### 9.3 Server Listing (`/servers`)

```
Layout:
  [Navbar]
  [Page Header]
    h1: "MCP Server Registry"
    p: "Browse {serverCount} registered MCP servers and their tools"

  [Filter Bar]
    [Text Input — "Filter servers..."] — client-side filter on name/description
    [Tag Dropdown — multi-select] — filter by tags (populated from distinct tags in data)
    [Status Filter — segmented control] — All | Indexed | Pending

  [Server Grid — 3 columns desktop, 2 tablet, 1 mobile]
    For each server:
      [ServerCard]

  [Load More Button — centered below grid]
    "Load More Servers"
    Hidden when all servers loaded
```

### 9.4 Server Detail (`/servers/:serverId`)

```
Layout:
  [Navbar]
  [Breadcrumb: Registry > {server.name}]

  [Server Header — full width card]
    h1: server.name
    p: server.description (full text)
    URL: server.url as clickable link (if present)
    Tags: horizontal badges
    Status: index_status badge
    Created: formatted date

  [Tools Section]
    h2: "Tools ({tools.length})"
    [Tool List — vertical stack]
      For each tool:
        [Compact ToolCard]
          tool_name (monospace) | description (1 line truncated) | GEO total badge | status dot
          Click → /tools/{tool_id}
```

### 9.5 Tool Detail (`/tools/:toolId`)

```
Layout:
  [Navbar]
  [Breadcrumb: Registry > {server.name} > {tool.tool_name}]

  [Tool Header Card]
    h1: tool.tool_name (monospace, text-2xl)
    Badge: server.name (clickable → /servers/:serverId)
    Badge: index_status
    Badge: GEO total score (if available)

  [Two Column Layout on desktop, stacked on mobile]

    [Left Column — 60%]
      [Description Section]
        h2: "Description"
        Rendered text (whitespace preserved, or markdown if contains formatting)

      [Input Schema Section]
        h2: "Input Schema"
        If input_schema exists:
          Table of properties:
            Name (monospace) | Type (badge) | Required (badge) | Description
          [Collapsible "View Raw JSON"]
            <pre> formatted JSON
        Else:
          "No input schema defined for this tool."

    [Right Column — 40%]
      [GEO Score Section — only if geo_score not null]
        h2: "Description Quality (GEO Score)"
        [GEOScoreRadar]
        [Score Table]
          Clarity:            0.XX [colored bar]
          Disambiguation:     0.XX [colored bar]
          Parameter Coverage:  0.XX [colored bar]
          Boundary:           0.XX [colored bar]
          Stats:              0.XX [colored bar]
          Precision:          0.XX [colored bar]
          ─────────────────
          Total:              0.XX (bold)

      [No GEO Score]
        "GEO Score not yet computed for this tool."
```

### 9.6 Provider Dashboard (`/dashboard`)

```
Layout:
  [Navbar]
  [Page Header]
    h1: "Provider Dashboard"
    p: "Monitor and improve your tools' search discoverability"

  [Summary Cards Row — 4 cards]
    Card 1: "Total Tools" — count
    Card 2: "Avg GEO Score" — average of all tools' geo_score.total (formatted 0.XX)
    Card 3: "Needs Improvement" — count where total < 0.5 (red if > 0)
    Card 4: "Fully Indexed" — count where index_status = 'indexed'

  [Tools Table — full width, sortable]
    Columns:
      Tool Name (monospace, link to /dashboard/tools/:toolId)
      Server
      GEO Total (sortable, colored)
      Clarity (mini bar)
      Disambiguation (mini bar)
      Params (mini bar)
      Boundary (mini bar)
      Stats (mini bar)
      Precision (mini bar)

    Color coding for dimension cells:
      < 0.3: red-500 bg
      0.3-0.6: amber-500 bg
      > 0.6: emerald-500 bg

    Default sort: GEO Total ascending (worst first — attention needed)
    Click row → /dashboard/tools/:toolId

  [Tools with no GEO Score — separate section at bottom]
    "These tools have not been scored yet:"
    Simple list of tool names
```

### 9.7 Tool GEO Detail (`/dashboard/tools/:toolId`)

```
Layout:
  [Navbar]
  [Breadcrumb: Dashboard > {tool.tool_name}]

  [Tool Header]
    h1: tool.tool_name (monospace)
    Server badge, GEO total score (large badge)

  [Two Column Layout]

    [Left Column — 50%]
      [GEO Score Radar]
        [GEOScoreRadar component — 300x300]

      [Dimension Breakdown — 6 cards in 2x3 grid]
        For each dimension:
          Card:
            Dimension name (bold)
            Score: 0.XX with progress bar
            Status icon: checkmark (>0.6), warning (0.3-0.6), x-mark (<0.3)
            Improvement suggestion (if score < 0.6):
              clarity: "Start with a specific action verb. First sentence should explain WHAT the tool does."
              disambiguation: "Add NOT/AVOID statements. Compare with similar tools using 'unlike X, this tool...'."
              parameter_coverage: "Document key parameters: name, type, required/optional, valid ranges."
              boundary: "State what the tool does NOT do. Prevents mismatched queries."
              stats: "Add quantitative info: rate limits, max items, response times, supported versions."
              precision: "Use specific technical terms: API protocols, data formats, authentication methods."

    [Right Column — 50%]
      [Search Simulator]
        h2: "Search Simulator"
        p: "See where this tool ranks for different queries"
        [SearchSimulator component]

      [Competitor Comparison]
        h2: "Same-Server Tool Comparison"
        [CompetitorTable — tools from same server_id]

  [Current Description — bottom section]
    h2: "Current Description"
    <pre> block showing the full current description
    Note: "To improve your description, update it on your MCP server and re-register."
```

---

## 10. Error Handling & Edge Cases

```
Global:
  - API Gateway 5xx: Show toast "Service temporarily unavailable"
  - API Gateway 429: Show toast "Rate limit reached. Please try again in a moment."
  - Supabase connection error: Show inline error "Could not load data"
  - 404 routes: Show "Page not found" with link back to /

Search specific:
  - Empty query submission: prevent, show "Please enter a search query"
  - API timeout (>10s): show "Search is taking longer than expected..."
  - No results: show friendly message with alternative suggestions

Auth specific:
  - Invalid credentials: "Invalid email or password"
  - Email not confirmed: "Please check your email to confirm your account"
  - Session expired: redirect to /login with message "Session expired, please sign in again"
  - Accessing /dashboard without auth: redirect to /login

Data specific:
  - tool_id URL encoding: tool_id contains "::" — URL-encode in links, decode on page load
  - geo_score null: hide GEO sections, show "Not yet scored" placeholder
  - input_schema null: show "No input schema defined"
  - description null or empty: show "No description available"
  - tags null or empty array: hide tags section
```

---

## 11. Responsive Breakpoints

```
Mobile (<640px / sm):
  - Single column layouts
  - Navbar: hamburger menu
  - Cards: full width
  - GEO Radar: 250x250
  - Tables: horizontal scroll

Tablet (640-1024px / md):
  - Server grid: 2 columns
  - Dashboard table: horizontal scroll
  - Two-column layouts stack vertically

Desktop (>1024px / lg):
  - Server grid: 3 columns
  - Full two-column layouts
  - Dashboard table: all columns visible
  - Max content width: 1280px
```

---

## 12. React Router Setup

```typescript
// src/App.tsx
import { BrowserRouter, Routes, Route } from 'react-router-dom'

// Pages
import Landing from './pages/Landing'
import Search from './pages/Search'
import Servers from './pages/Servers'
import ServerDetail from './pages/ServerDetail'
import ToolDetail from './pages/ToolDetail'
import Dashboard from './pages/Dashboard'
import DashboardToolDetail from './pages/DashboardToolDetail'
import Login from './pages/Login'
import NotFound from './pages/NotFound'

// Layout
import Layout from './components/Layout'  // Navbar + Outlet
import ProtectedRoute from './components/ProtectedRoute'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Landing />} />
          <Route path="/search" element={<Search />} />
          <Route path="/servers" element={<Servers />} />
          <Route path="/servers/:serverId" element={<ServerDetail />} />
          <Route path="/tools/:toolId" element={<ToolDetail />} />
          <Route path="/login" element={<Login />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/dashboard/tools/:toolId" element={<DashboardToolDetail />} />
          </Route>
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
```

---

## 13. Key Libraries

```
Already available in MCP Discovery (no manual install needed):
  - @supabase/supabase-js — Supabase client
  - react-router-dom — routing
  - recharts — charts (GEO Radar)
  - lucide-react — icons
  - tailwindcss — styling
  - shadcn/ui components — Button, Card, Input, Table, Badge, Tabs, Tooltip, etc.
  - @tanstack/react-query — data fetching (use for all Supabase and API calls)
```
