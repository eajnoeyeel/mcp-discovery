import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import type { ClientAuthScopeMode, UpstreamAuthType } from '@/types/database';

export interface RegistrationDiscoveryFormState {
  serverId: string;
  name: string;
  url: string;
  description: string;
  tags: string;
  authType: UpstreamAuthType;
  clientAuthProviderKey: string;
  clientAuthRequiredScopes: string;
  clientAuthScopeMode: ClientAuthScopeMode;
  clientAuthBootstrapDisplayName: string;
  clientAuthBootstrapAuthorizeUrl: string;
  clientAuthBootstrapTokenUrl: string;
  clientAuthBootstrapClientId: string;
  clientAuthBootstrapClientSecret: string;
  clientAuthBootstrapTokenAuthMethod: string;
  bearerToken: string;
  apiKeyHeaderName: string;
  apiKey: string;
  customHeadersText: string;
  oauthTokenEndpoint: string;
  oauthClientId: string;
  oauthClientSecret: string;
  oauthRefreshToken: string;
  oauthScope: string;
}

interface DiscoveryStepProps {
  value: RegistrationDiscoveryFormState;
  onChange: (field: keyof RegistrationDiscoveryFormState, value: string) => void;
  onFetchMetadata: () => void;
  onContinueManually: () => void;
  isDiscovering: boolean;
  discoveryError: string;
}

const AUTH_OPTIONS: Array<{ value: UpstreamAuthType; label: string }> = [
  { value: 'none', label: 'No auth' },
  { value: 'bearer', label: 'Bearer token' },
  { value: 'api_key_header', label: 'API key header' },
  { value: 'custom_headers', label: 'Custom headers' },
  { value: 'oauth_session', label: 'OAuth session' },
];

const CLIENT_AUTH_SCOPE_MODE_OPTIONS: Array<{ value: ClientAuthScopeMode; label: string }> = [
  { value: 'default', label: 'Default provider scopes' },
  { value: 'override', label: 'Only required scopes' },
];

export default function DiscoveryStep({
  value,
  onChange,
  onFetchMetadata,
  onContinueManually,
  isDiscovering,
  discoveryError,
}: DiscoveryStepProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Connect to the upstream MCP server</CardTitle>
        <CardDescription>
          Provide the server endpoint first. If the upstream server requires hosted OAuth or an API-key connect ceremony,
          the wizard will route there before it fetches tool metadata.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="server-id">Server ID</Label>
            <Input
              id="server-id"
              value={value.serverId}
              onChange={event => onChange('serverId', event.target.value)}
              placeholder="acme-search"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="server-name">Server Name</Label>
            <Input
              id="server-name"
              value={value.name}
              onChange={event => onChange('name', event.target.value)}
              placeholder="Acme Search MCP"
            />
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="server-url">Server URL</Label>
          <Input
            id="server-url"
            type="url"
            value={value.url}
            onChange={event => onChange('url', event.target.value)}
            placeholder="https://example.com/mcp"
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="server-description">Description</Label>
          <Textarea
            id="server-description"
            value={value.description}
            onChange={event => onChange('description', event.target.value)}
            placeholder="Describe your server and when providers should use it."
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="server-tags">Tags</Label>
          <Input
            id="server-tags"
            value={value.tags}
            onChange={event => onChange('tags', event.target.value)}
            placeholder="search, docs, github"
          />
          <p className="text-xs text-muted-foreground">Optional. Separate multiple tags with commas.</p>
        </div>

        <div className="space-y-4 rounded-lg border border-border p-4">
          <div>
            <h2 className="font-medium text-foreground">Discovery authentication</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Use the same auth details the backend needs during discovery, or leave this as No auth to let hosted connect
              detect and orchestrate provider-managed credentials first.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="auth-type">Auth type</Label>
            <select
              id="auth-type"
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              value={value.authType}
              onChange={event => onChange('authType', event.target.value)}
            >
              {AUTH_OPTIONS.map(option => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          {value.authType === 'bearer' && (
            <div className="space-y-2">
              <Label htmlFor="bearer-token">Bearer token</Label>
              <Input
                id="bearer-token"
                type="password"
                value={value.bearerToken}
                onChange={event => onChange('bearerToken', event.target.value)}
                placeholder="Paste the bearer token used by the upstream MCP server"
              />
            </div>
          )}

          {value.authType === 'api_key_header' && (
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="api-key-header-name">API key header name</Label>
                <Input
                  id="api-key-header-name"
                  value={value.apiKeyHeaderName}
                  onChange={event => onChange('apiKeyHeaderName', event.target.value)}
                  placeholder="x-provider-key"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="api-key">API key</Label>
                <Input
                  id="api-key"
                  type="password"
                  value={value.apiKey}
                  onChange={event => onChange('apiKey', event.target.value)}
                  placeholder="Paste the API key"
                />
              </div>
            </div>
          )}

          {value.authType === 'custom_headers' && (
            <div className="space-y-2">
              <Label htmlFor="custom-headers">Custom headers</Label>
              <Textarea
                id="custom-headers"
                value={value.customHeadersText}
                onChange={event => onChange('customHeadersText', event.target.value)}
                placeholder={['x-team-id: provider-123', 'x-region: ap-northeast-2'].join('\n')}
              />
              <p className="text-xs text-muted-foreground">Enter one header per line in the form Key: Value.</p>
            </div>
          )}

          {value.authType === 'oauth_session' && (
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2 sm:col-span-2">
                <Label htmlFor="oauth-token-endpoint">OAuth token endpoint</Label>
                <Input
                  id="oauth-token-endpoint"
                  type="url"
                  value={value.oauthTokenEndpoint}
                  onChange={event => onChange('oauthTokenEndpoint', event.target.value)}
                  placeholder="https://provider.test/oauth/token"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="oauth-client-id">OAuth client ID</Label>
                <Input
                  id="oauth-client-id"
                  value={value.oauthClientId}
                  onChange={event => onChange('oauthClientId', event.target.value)}
                  placeholder="provider-client-id"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="oauth-scope">OAuth scope</Label>
                <Input
                  id="oauth-scope"
                  value={value.oauthScope}
                  onChange={event => onChange('oauthScope', event.target.value)}
                  placeholder="tools.execute"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="oauth-client-secret">OAuth client secret</Label>
                <Input
                  id="oauth-client-secret"
                  type="password"
                  value={value.oauthClientSecret}
                  onChange={event => onChange('oauthClientSecret', event.target.value)}
                  placeholder="Paste the OAuth client secret"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="oauth-refresh-token">OAuth refresh token</Label>
                <Input
                  id="oauth-refresh-token"
                  type="password"
                  value={value.oauthRefreshToken}
                  onChange={event => onChange('oauthRefreshToken', event.target.value)}
                  placeholder="Paste the OAuth refresh token"
                />
              </div>
            </div>
          )}
        </div>

        <div className="space-y-4 rounded-lg border border-border p-4">
          <div>
            <h2 className="font-medium text-foreground">Optional delegated client auth</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Add a server-level OAuth requirement for downstream clients without changing the provider credentials used for
              discovery or execution.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="client-auth-provider-key">OAuth provider key</Label>
              <Input
                id="client-auth-provider-key"
                value={value.clientAuthProviderKey}
                onChange={event => onChange('clientAuthProviderKey', event.target.value)}
                placeholder="github"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="client-auth-scope-mode">Scope mode</Label>
              <select
                id="client-auth-scope-mode"
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={value.clientAuthScopeMode}
                onChange={event => onChange('clientAuthScopeMode', event.target.value)}
              >
                {CLIENT_AUTH_SCOPE_MODE_OPTIONS.map(option => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="client-auth-required-scopes">Required OAuth scopes</Label>
              <Textarea
                id="client-auth-required-scopes"
                value={value.clientAuthRequiredScopes}
                onChange={event => onChange('clientAuthRequiredScopes', event.target.value)}
                placeholder={['repo', 'issues:write'].join('\n')}
              />
              <p className="text-xs text-muted-foreground">
                Optional. Separate scopes with commas or new lines. Leave the provider key empty to omit delegated client
                auth from registration.
              </p>
            </div>
          </div>

          {value.clientAuthProviderKey.trim() && (
            <div className="space-y-4 rounded-md border border-dashed border-border p-4 sm:col-span-2">
              <div>
                <h3 className="text-sm font-medium text-foreground">Bootstrap this OAuth provider if it is new</h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  Optional guided manual fallback. If the provider key is not already enabled, enter the OAuth app values
                  from the provider console. The client secret is sent only to the backend secret store.
                </p>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="client-auth-bootstrap-display-name">Provider display name</Label>
                  <Input
                    id="client-auth-bootstrap-display-name"
                    value={value.clientAuthBootstrapDisplayName}
                    onChange={event => onChange('clientAuthBootstrapDisplayName', event.target.value)}
                    placeholder="GitHub"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="client-auth-bootstrap-token-auth-method">Token auth method</Label>
                  <select
                    id="client-auth-bootstrap-token-auth-method"
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={value.clientAuthBootstrapTokenAuthMethod}
                    onChange={event => onChange('clientAuthBootstrapTokenAuthMethod', event.target.value)}
                  >
                    <option value="none">PKCE public client</option>
                    <option value="client_secret_post">Client secret POST</option>
                    <option value="client_secret_basic">Client secret Basic</option>
                  </select>
                </div>
                <div className="space-y-2 sm:col-span-2">
                  <Label htmlFor="client-auth-bootstrap-authorize-url">Authorization endpoint</Label>
                  <Input
                    id="client-auth-bootstrap-authorize-url"
                    type="url"
                    value={value.clientAuthBootstrapAuthorizeUrl}
                    onChange={event => onChange('clientAuthBootstrapAuthorizeUrl', event.target.value)}
                    placeholder="https://provider.example/oauth/authorize"
                  />
                </div>
                <div className="space-y-2 sm:col-span-2">
                  <Label htmlFor="client-auth-bootstrap-token-url">Token endpoint</Label>
                  <Input
                    id="client-auth-bootstrap-token-url"
                    type="url"
                    value={value.clientAuthBootstrapTokenUrl}
                    onChange={event => onChange('clientAuthBootstrapTokenUrl', event.target.value)}
                    placeholder="https://provider.example/oauth/token"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="client-auth-bootstrap-client-id">Bootstrap client ID</Label>
                  <Input
                    id="client-auth-bootstrap-client-id"
                    value={value.clientAuthBootstrapClientId}
                    onChange={event => onChange('clientAuthBootstrapClientId', event.target.value)}
                    placeholder="client-id"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="client-auth-bootstrap-client-secret">Bootstrap client secret</Label>
                  <Input
                    id="client-auth-bootstrap-client-secret"
                    type="password"
                    value={value.clientAuthBootstrapClientSecret}
                    onChange={event => onChange('clientAuthBootstrapClientSecret', event.target.value)}
                    placeholder="Required for secret-based methods"
                  />
                </div>
              </div>
            </div>
          )}
        </div>

        {discoveryError && (
          <Alert variant="destructive">
            <AlertTitle>Automatic metadata fetch failed</AlertTitle>
            <AlertDescription>{discoveryError}</AlertDescription>
          </Alert>
        )}

        <div className="flex flex-col gap-3 sm:flex-row sm:justify-end">
          {discoveryError && (
            <Button type="button" variant="outline" onClick={onContinueManually}>
              Continue manually
            </Button>
          )}
          <Button type="button" onClick={onFetchMetadata} disabled={isDiscovering}>
            {isDiscovering ? 'Fetching metadata…' : 'Fetch metadata'}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
