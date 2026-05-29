# MCP Discovery Service Local-First Runbook

## 0. Conventions and gotchas

- **`service/mcp_server/*.py` must use module-top imports only.**
  Function-body imports are blocked by
  `tests/unit/test_import_hygiene.py::test_no_function_body_imports_in_mcp_server`
  — any lazy import must be hoisted or placed under a `TYPE_CHECKING` guard.
  This guardrail was introduced after a `from mlp.lambdas.bridge.handler` (pre-refactor path) import
  in `service/mcp_server/local_app.py` caused a Lambda runtime `ModuleNotFoundError`
  (fixed in commit `ffde203`).

- **`service/scripts/build_dashboard_snapshot.py` must be invoked via `uv run`.**
  The script adds the project root to `sys.path` at runtime so `service.*`
  resolves without an installed wheel (no `[build-system]` is declared in
  `pyproject.toml`). Run:
  ```bash
  uv run python service/scripts/build_dashboard_snapshot.py --help
  ```
  Invoking plain `python service/scripts/build_dashboard_snapshot.py` without
  `uv run` will fail with `ModuleNotFoundError: service`. Related commits:
  `d4efd3f` (drop stale mlp shim), `e8409b0` (restore imports + correct path).

- Before changing MCP auth code, review the special locked auth reference artifact in `service/docs/history/2026-04-20_auth_reference_audit.md` (stable preflight reference, not a normal timestamped evidence record).
- Auth work is not complete unless it is checked against Claude Code docs, OpenAI MCP docs, the MCP Authorization spec, and at least one reference remote MCP auth implementation.

## 1. Confirm current scope

Current goal is **not** AWS rollout. Current goal is to prove the local provider journey:

`/login -> HTTP MCP registration wizard/manual fallback -> override publish -> indexing/dashboard reflection -> outward-facing published metadata -> refresh diff preview`

If this local journey is not closed, do not escalate to staging/prod deployment work.

## 2. Prepare local prerequisites

1. Ensure frontend env is present locally:
   - `VITE_SUPABASE_URL`
   - `VITE_SUPABASE_ANON_KEY`
   - `VITE_API_URL`
   - `VITE_MLP_API_KEY`
2. Ensure Supabase Google OAuth provider is configured for the local frontend origin.
3. Have a reachable HTTP MCP endpoint (and auth material if required) ready for wizard discovery checks.
4. Ensure Docker/container runtime is available if local SAM needs containers.
5. For the local FastAPI/EventBridge path (`MLP_EVENT_MODE=local_direct`), ensure `.env` points at a reachable external Qdrant deployment (`QDRANT_URL`, `QDRANT_API_KEY`). The local app does **not** replace Qdrant in this mode.
6. Before testing OAuth-backed `execute_tool`, apply Supabase migrations
   `service/supabase/migrations/025_provider_oauth_broker.sql` and
   `service/supabase/migrations/026_pending_execution_resume_contract.sql`.
   Verify with:
   ```bash
   uv run python service/scripts/verify_runtime_schema.py
   ```
   The delegated OAuth checks `oauth_provider_registry`, `user_provider_connections`, and
   `pending_executions.resume_contract` must be present.
7. Re-check known local blockers before claiming E2E is ready:
   - `pydantic_core._pydantic_core` ABI mismatch in local Lambda path
   - `sam build --use-container` Makefile path failure (`cp //service/...`)

## 3. Run repo-local regression checks

### Backend

```bash
uv run pytest tests/unit/mlp/test_mlp_catalog_dashboard.py tests/unit/mlp/test_mlp_catalog_service.py tests/unit/mlp/test_mlp_handlers.py -q
uv run pytest tests/unit/mlp/test_mlp_template_contract.py tests/unit/mlp/test_mlp_index_loop.py tests/unit/mlp/test_mlp_execute_loop.py tests/unit/mlp/test_mlp_smoke_api.py -q
```

### Frontend

```bash
cd service/frontend
npm test -- src/lib/api.test.ts src/pages/Dashboard.test.tsx
npm test -- src/contexts/AuthContext.test.tsx src/pages/Login.test.tsx
npm test
npm run build
```

## 4. Run harnesses

```bash
uv run python -m service.harness.search_loop
uv run python -m service.harness.index_loop
uv run python -m service.harness.execute_loop
uv run python -m service.harness.smoke_api --sample
uv run python -m service.harness.claude_auth_probe
uv run python -m service.harness.delegated_oauth_resume_loop
```

These prove the existing search/index/execute surfaces still behave while registration work is being closed.

For live Claude/Codex auth and delegated OAuth resume proof, capture these steps:

1. Run `auth_probe` without current client auth and confirm `auth_required`.
2. Re-authenticate Claude or Codex and confirm `auth_probe` returns an authenticated platform user.
3. Clear authentication in the client and confirm `auth_probe` falls back to `auth_required`.
4. Run `execute_tool` against a real OAuth-backed provider and capture `auth_required` with `resume_token`.
5. Complete browser OAuth and confirm the pending execution reaches `ready_to_resume`.
6. Resume once through `resume_pending_execution` and confirm the final result returns through the MCP client flow.

### Provider bearer token source for `verify_provider_dashboard.py`

`verify_provider_dashboard.py` reads `--base-url`, `--api-key`, and `--bearer-token` from CLI args or shell env only. It does **not** load `service/frontend/.env.local` automatically.

Current local env split:
- root `.env` → `MLP_BASE_URL=http://127.0.0.1:3000`, `MLP_API_KEY`
- `service/frontend/.env.local` → `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_API_URL=http://127.0.0.1:3000`, optional cached `MLP_BEARER_TOKEN`

Current Supabase browser storage key:
- `sb-ojuclgsxseygcnjgdpau-auth-token`

Before reusing `service/frontend/.env.local` for provider proof, verify the cached bearer token is still live:

```bash
set -a
source service/frontend/.env.local
set +a

python - <<'PY'
import base64
import json
import os
import time

token = os.environ.get("MLP_BEARER_TOKEN", "")
if not token:
    raise SystemExit("MLP_BEARER_TOKEN missing in service/frontend/.env.local")

parts = token.split(".")
if len(parts) != 3:
    raise SystemExit(f"unexpected JWT shape: {len(parts)} segments")

payload = parts[1] + "=" * (-len(parts[1]) % 4)
claims = json.loads(base64.urlsafe_b64decode(payload))
print(
    json.dumps(
        {
            "exp": claims.get("exp"),
            "expired": claims.get("exp", 0) <= int(time.time()),
        },
        indent=2,
    )
)
PY
```

If `expired` is `true`, refresh the provider session before running the verifier. The stable manual path is:
1. Open `http://127.0.0.1:4173/login?redirect=/dashboard`.
2. Complete Google OAuth sign-in.
3. On `/dashboard`, open DevTools Console and run:

   ```js
   const session = JSON.parse(localStorage.getItem("sb-ojuclgsxseygcnjgdpau-auth-token") ?? "null");
   session?.access_token ?? ""
   ```

4. Export that fresh token into the same shell that will run the verifier:

   ```bash
   read -rsp "Paste fresh MLP_BEARER_TOKEN: " MLP_BEARER_TOKEN && echo
   export MLP_BEARER_TOKEN
   ```

Minimal local verifier shell:

```bash
set -a
source .env
set +a
export MLP_BEARER_TOKEN="<fresh token>"
UV_CACHE_DIR=/tmp/uv-cache uv run python service/scripts/verify_provider_dashboard.py --server-id dashboard-provider-ux-proof
```

## 5. Verify the local provider journey

Target proof:
1. Open local frontend `/login`.
2. Complete Google OAuth sign-in.
3. Navigate to the HTTP MCP registration wizard.
4. Enter an MCP URL and confirm discovery prefill works, or explicitly continue through the manual fallback path if discovery fails.
5. Review fetched upstream metadata and edit the published override metadata (`description`, notes/examples/hints as needed).
6. Submit provider registration.
7. Observe pending/indexing or equivalent progress signal, then confirm the local-direct lane reaches indexed against the configured external Qdrant endpoint from `.env`.
8. Confirm provider dashboard reflects the new owned server/tool and shows the published metadata editor state.
9. Confirm outward-facing catalog/tool detail reads expose the published `description`, while `upstream_description` remains reference-only metadata.
10. Open metadata refresh preview and confirm diff/review happens before apply.
11. If structured parameter metadata exists, confirm the dashboard editor shows per-parameter published description fields and that the effective schema preview reflects those overrides before save.
12. Trigger at least one refresh preview where upstream parameter paths change and confirm orphaned parameter warnings plus parameter-level diff details are visible before apply.

If any step fails, record:
- exact failed step
- exact error or missing surface
- next operator action

### 5.1 Local-direct indexing note

- Scope: applies only to the dev-only FastAPI adapter path in `service/api/local_app.py` when `MLP_EVENT_MODE=local_direct`.
- Behavior: the local app routes `server.registered` events directly to the index Lambda handler inside the same process, but the handler still uses the normal Qdrant configuration from `.env`.
- Requirement: `QDRANT_URL` and (if needed) `QDRANT_API_KEY` must point to a reachable Qdrant deployment before claiming the lane is healthy.
- Non-goal: this does **not** change `service/template.yaml`, deployed Lambda defaults, or any production Qdrant configuration.

### 5.2 Public-read override precedence check

For any registered tool validated in the dashboard:

- dashboard/tool detail should show the published provider-authored `description`
- catalog/public readers should also surface that same published `description`
- `upstream_description` may still appear in payloads for reference/diff UI, but it must not replace the outward-facing `description`

When capturing API proof, include at least one successful read from the server tools or tool detail surface and record the published description value that was returned.

### 5.3 Parameter metadata verification

For at least one provider-owned tool with structured parameter metadata:

1. Confirm registration review or dashboard detail shows the normalized upstream parameter paths, required flags, and descriptions.
2. Edit one published parameter description and confirm the dashboard effective schema preview updates to show the published description in the merged schema.
3. Save the override and record the parameter path plus the exact effective description shown in the preview.
4. Run refresh preview against an upstream schema/path change and confirm both of the following before apply:
   - orphaned published parameter paths are listed explicitly
   - parameter-level additions/removals/changes are visible in the diff detail

## 6. Record evidence

1. Update `service/docs/current_slave.md` or `service/docs/current_master.md`.
2. Add matching `service/docs/history/YYYY-MM-DD_HHMM_<owner>_<task_slug>.md`.
3. Mark the run as one of:
   - `PASS` — local provider journey closed
   - `BLOCKED` — local blocker remains, with evidence

### 6.1 Delegated provider OAuth local proof

Run the delegated provider OAuth loop before closing auth-aware execute work:

```bash
uv run python -m service.harness.delegated_oauth_execute_loop
```

For a live local proof, provide `MLP_BASE_URL`, `MLP_API_KEY`, and `MLP_BEARER_TOKEN`.
The proof is green only when:
1. the first execute attempt returns `auth_required`
2. the provider callback stores a user-owned provider connection
3. the retry execute attempt succeeds

## 7. Only after local gate passes

The following are deferred until the local gate is green:
- AWS staging deployment
- AWS prod deployment
- live-stage API smoke
- hosted frontend/browser verification

## 8. Hosted runtime schema gate

Before any staging/prod gateway rollout, confirm migration 009 and later runtime migrations are present:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python service/scripts/verify_runtime_schema.py   --supabase-url "$SUPABASE_URL"   --service-key "$SUPABASE_SERVICE_KEY"
```

This check is read-only against hosted Supabase. Proceed to gateway deployment only when the output reports `"ready": true`.

## 9. Repo-local pre-deployment rehearsal

Run this before any future AWS staging/prod execution lane opens.

```bash
UV_CACHE_DIR=/tmp/uv-cache scripts/ci/run_mlp_predeploy_checks.sh
```

This command is intentionally repo-local only. It should:
1. run focused unit/contract checks for build helpers, gateway contracts, and rehearsal helpers
2. run `service.build.doctor`, `service.build.build`, and `service.build.smoke`
3. print a sample gateway deploy manifest
4. run sample gateway health, transport-proof, runtime-loop, and API smoke harnesses

If this rehearsal fails, do **not** escalate to AWS deployment work. Record the failing step and fix the repo-local package first.

## 10. Hosted container-first deployment planning gate

This section is a future-operator preflight, not execution proof.

1. Verify hosted schema readiness first:

   ```bash
   UV_CACHE_DIR=/tmp/uv-cache uv run python service/scripts/verify_runtime_schema.py      --supabase-url "$SUPABASE_URL"      --service-key "$SUPABASE_SERVICE_KEY"
   ```

2. Freeze the Lambda/API artifact boundary at `service/template.yaml`.
3. Freeze the gateway container contract with `service/gateway/Dockerfile` and `service/ops/apprunner.gateway.yaml`.
4. Print and record the gateway deploy manifest before any future App Runner rollout:

   ```bash
   UV_CACHE_DIR=/tmp/uv-cache uv run python service/scripts/print_gateway_deploy_manifest.py      --image-identifier "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/mlp-gateway:staging"      --gateway-base-url "https://gateway.example.com"
   ```

5. Do not open execution unless the future operator can name all of the following:
   - authoritative hosted `ApiUrl`
   - authoritative hosted gateway URL
   - gateway image identifier/tag
   - `GATEWAY_INTERNAL_AUTH_SECRET` source
   - hosted Google OAuth redirect/origin settings
   - rollback owner
