import { useMemo, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import ConnectScopeSelector from '@/components/connect/ConnectScopeSelector';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useAuth } from '@/contexts/AuthContext';
import { createClientConnectSession } from '@/lib/api';
import type { ClientConnectAuthType, HostedConnectReuseScope } from '@/types/database';

const DEFAULT_CLIENT_APP_ID = 'dashboard-web';
const CLIENT_API_KEY_UNAVAILABLE_COPY =
  'Client API-key hosted connect is not available yet. The backend cannot persist and reuse client API keys for resumable execution in this slice.';
const PROVIDER_API_KEY_UNAVAILABLE_COPY =
  'Provider API-key hosted connect is not available yet. The browser shell cannot finalize provider-owned API keys in this slice.';

function normalizeClientAuthType(value: string | null): ClientConnectAuthType | null {
  return value === 'api_key' || value === 'oauth' ? value : null;
}

function buildConnectCompleteUrl(params: Record<string, string | undefined>) {
  const next = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value) {
      next.set(key, value);
    }
  });
  return `/connect/complete?${next.toString()}`;
}

function extractOAuthState(startUrl: string): string {
  if (!startUrl) {
    return '';
  }
  try {
    return new URL(startUrl).searchParams.get('state') ?? '';
  } catch {
    return '';
  }
}

export default function HostedConnect() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { session } = useAuth();
  const accessToken = session?.access_token ?? '';

  const actor = searchParams.get('actor') === 'provider' ? 'provider' : 'client';
  const providerKey = searchParams.get('provider') ?? '';
  const serverId = searchParams.get('server_id') ?? '';
  const toolName = searchParams.get('tool_name') ?? '';
  const toolId = searchParams.get('tool_id') ?? '';
  const startUrl = searchParams.get('start_url') ?? '';
  const existingSessionId = searchParams.get('session') ?? searchParams.get('connect_session_id') ?? '';
  const resumeToken = searchParams.get('resume_token') ?? '';
  const pendingExecutionId = searchParams.get('pending_execution_id') ?? '';
  const returnTo = searchParams.get('return_to') ?? '/dashboard';
  const clientAppId = searchParams.get('client_app_id') ?? '';
  const initialAuthType = normalizeClientAuthType(searchParams.get('auth_type')) ?? 'oauth';

  const [scope, setScope] = useState<HostedConnectReuseScope>(clientAppId ? 'client_app' : 'user');
  const [authType, setAuthType] = useState<ClientConnectAuthType>(initialAuthType);
  const [error, setError] = useState('');
  const [clientOAuthStartUrl, setClientOAuthStartUrl] = useState('');
  const [clientCompletionUrl, setClientCompletionUrl] = useState('');

  const summaryBadges = useMemo(() => {
    const badges = [actor === 'provider' ? 'Provider flow' : 'Client flow'];
    badges.push(authType === 'oauth' ? 'OAuth' : 'API key');
    if (toolName) {
      badges.push(toolName);
    }
    return badges;
  }, [actor, authType, toolName]);

  const createSessionMutation = useMutation({
    mutationFn: async () => {
      if (!accessToken) {
        throw new Error('Please sign in again before starting hosted connect.');
      }
      if (!serverId) {
        throw new Error('Missing required server_id for client connect.');
      }
      const nextClientAppId = scope === 'client_app' ? (clientAppId || DEFAULT_CLIENT_APP_ID) : undefined;
      return createClientConnectSession(accessToken, {
        provider_key: providerKey || undefined,
        server_id: serverId,
        tool_name: toolName || undefined,
        tool_id: toolId || undefined,
        client_app_id: nextClientAppId,
        auth_type: authType,
        pending_execution_id: pendingExecutionId || undefined,
      }).then(result => ({ result, nextClientAppId }));
    },
    onSuccess: ({ result, nextClientAppId }) => {
      setError('');
      if (result.auth_type === 'oauth') {
        if (!result.start_url) {
          setClientOAuthStartUrl('');
          setClientCompletionUrl('');
          setError('Hosted approval URL unavailable. Client OAuth cannot continue until the backend returns a start_url.');
          return;
        }
        const completionUrl = buildConnectCompleteUrl({
          actor: 'client',
          session: result.connect_session_id,
          server_id: result.server_id,
          tool_name: result.tool_name ?? undefined,
          auth_type: result.auth_type,
          resume_token: resumeToken || undefined,
          client_app_id: nextClientAppId,
          return_to: returnTo,
        });
        setClientOAuthStartUrl(result.start_url);
        setClientCompletionUrl(completionUrl);
        window.open(result.start_url, '_blank', 'noopener,noreferrer');
        return;
      }
      setClientOAuthStartUrl('');
      setClientCompletionUrl('');
      navigate(
        buildConnectCompleteUrl({
          actor: 'client',
          session: result.connect_session_id,
          server_id: result.server_id,
          tool_name: result.tool_name ?? undefined,
          auth_type: result.auth_type,
          resume_token: resumeToken || undefined,
          client_app_id: nextClientAppId,
          return_to: returnTo,
        }),
      );
    },
    onError: (mutationError: Error) => {
      setError(mutationError.message || 'Failed to create a hosted connect session.');
    },
  });

  const handleClientOAuthStart = () => {
    createSessionMutation.mutate();
  };

  const providerCompleteUrl = buildConnectCompleteUrl({
    actor: 'provider',
    session: existingSessionId || undefined,
    connect_session_id: existingSessionId || undefined,
    server_id: serverId || undefined,
    auth_type: authType,
    state: extractOAuthState(startUrl) || undefined,
    return_to: returnTo,
  });
  const lockClientFlowToApiKey = actor === 'client' && initialAuthType === 'api_key';
  const showClientApiKeyUnavailable = actor === 'client' && authType === 'api_key';
  const showProviderApiKeyUnavailable = actor === 'provider' && authType === 'api_key';

  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-6 flex flex-wrap items-center gap-2">
        {summaryBadges.map(badge => (
          <Badge key={badge} variant="secondary">{badge}</Badge>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-2xl">Connect required</CardTitle>
          <CardDescription>
            {actor === 'provider'
              ? 'Open the provider approval URL if available, then continue into the validation shell before returning to the registration wizard.'
              : 'Create a hosted client connection before resuming the original action.'}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="rounded-lg border border-border bg-secondary/30 p-4 text-sm">
            <p><span className="font-medium text-foreground">Server:</span> {serverId || 'Unknown server'}</p>
            {toolName && <p className="mt-1"><span className="font-medium text-foreground">Tool:</span> {toolName}</p>}
            {existingSessionId && (
              <p className="mt-1 font-mono text-xs text-muted-foreground">Session {existingSessionId}</p>
            )}
          </div>

          {actor === 'client' ? (
            <>
              {!lockClientFlowToApiKey && (
                <div className="space-y-3">
                  <p className="text-sm font-medium text-foreground">Credential type</p>
                  <div className="grid gap-3 sm:grid-cols-2">
                    {[
                      {
                        value: 'oauth',
                        label: 'OAuth approval',
                        description: 'Use the hosted approval ceremony and keep the connection reusable.',
                        disabled: false,
                      },
                      {
                        value: 'api_key',
                        label: 'API key',
                        description: 'Temporarily unavailable: client API-key sessions cannot resume safely yet.',
                        disabled: true,
                      },
                    ].map(option => {
                      const checked = option.value === authType;
                      return (
                        <button
                          key={option.value}
                          type="button"
                          disabled={option.disabled}
                          onClick={() => {
                            if (!option.disabled) {
                              setAuthType(option.value as ClientConnectAuthType);
                            }
                          }}
                          className={`rounded-lg border p-4 text-left transition-colors ${
                            checked ? 'border-primary bg-primary/5' : 'border-border bg-card hover:border-primary/40'
                          } ${option.disabled ? 'cursor-not-allowed opacity-60 hover:border-border' : ''}`}
                        >
                          <div className="font-medium text-foreground">{option.label}</div>
                          <div className="mt-1 text-sm text-muted-foreground">{option.description}</div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {!showClientApiKeyUnavailable && (
                <ConnectScopeSelector value={scope} onChange={setScope} />
              )}

              {showClientApiKeyUnavailable ? (
                <Alert>
                  <AlertTitle>Client API-key flow unavailable</AlertTitle>
                  <AlertDescription>{CLIENT_API_KEY_UNAVAILABLE_COPY}</AlertDescription>
                </Alert>
              ) : clientOAuthStartUrl ? (
                <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
                  <p className="text-sm text-muted-foreground">
                    Open the hosted approval URL first, then continue to the completion shell so the pending execution can resume after approval.
                  </p>
                  <div className="flex flex-wrap gap-3">
                    <Button asChild>
                      <a href={clientOAuthStartUrl} rel="noreferrer" target="_blank">Open hosted approval</a>
                    </Button>
                    <Button asChild variant="outline">
                      <Link to={clientCompletionUrl}>Continue to completion</Link>
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
                  <p className="text-sm text-muted-foreground">
                    Start a hosted OAuth client-connect session, then return to the completion page when the approval step finishes.
                  </p>
                  <div className="flex flex-wrap gap-3">
                    <Button type="button" onClick={handleClientOAuthStart} disabled={createSessionMutation.isPending}>
                      {createSessionMutation.isPending ? 'Creating session…' : 'Start hosted connect'}
                    </Button>
                    <Button asChild variant="outline">
                      <Link to={returnTo}>Cancel</Link>
                    </Button>
                  </div>
                </div>
              )}
            </>
          ) : (
            <>
              {showProviderApiKeyUnavailable ? (
                <Alert>
                  <AlertTitle>Provider API-key flow unavailable</AlertTitle>
                  <AlertDescription>{PROVIDER_API_KEY_UNAVAILABLE_COPY}</AlertDescription>
                </Alert>
              ) : (
                <div className="space-y-4 rounded-lg border border-border bg-card p-4">
                  <p className="text-sm text-muted-foreground">
                    Open the provider approval URL, then continue into the validation shell so the callback receipt can be checked before you return to the registration wizard.
                  </p>
                  <div className="flex flex-wrap gap-3">
                    {startUrl ? (
                      <Button asChild>
                        <a href={startUrl} rel="noreferrer" target="_blank">Open provider approval</a>
                      </Button>
                    ) : (
                      <Button type="button" disabled>Provider approval URL unavailable</Button>
                    )}
                    <Button asChild variant="outline">
                      <Link to={providerCompleteUrl}>Continue to validation shell</Link>
                    </Button>
                  </div>
                </div>
              )}

              {showProviderApiKeyUnavailable && (
                <div className="flex flex-wrap gap-3">
                  <Button asChild variant="outline">
                    <Link to={returnTo}>Return to registration</Link>
                  </Button>
                </div>
              )}
            </>
          )}

          {error && (
            <Alert variant="destructive">
              <AlertTitle>Hosted connect blocked</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
