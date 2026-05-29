import { useEffect, useMemo, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useAuth } from '@/contexts/AuthContext';
import { resumePendingExecution, validateProviderConnectCallback } from '@/lib/api';
import type { ClientConnectAuthType } from '@/types/database';

function readHashParams(hash: string): URLSearchParams {
  const normalized = hash.startsWith('#') ? hash.slice(1) : hash;
  return new URLSearchParams(normalized);
}

export default function ConnectComplete() {
  const [searchParams] = useSearchParams();
  const { session } = useAuth();
  const accessToken = session?.access_token ?? '';

  const actor = searchParams.get('actor') === 'provider' ? 'provider' : 'client';
  const returnTo = searchParams.get('return_to') ?? '/dashboard';
  const sessionId = searchParams.get('session') ?? searchParams.get('connect_session_id') ?? '';
  const serverId = searchParams.get('server_id') ?? '';
  const toolName = searchParams.get('tool_name') ?? '';
  const resumeToken = searchParams.get('resume_token') ?? '';
  const clientAppId = searchParams.get('client_app_id') ?? '';
  const oauthState = searchParams.get('state') ?? '';
  const headerName = searchParams.get('header_name') ?? '';
  const apiKeyCaptured = searchParams.get('api_key_captured') === '1';
  const authType = (searchParams.get('auth_type') === 'api_key' ? 'api_key' : 'oauth') as ClientConnectAuthType;
  const [statusMessage, setStatusMessage] = useState('');
  const [providerCallbackValidated, setProviderCallbackValidated] = useState(false);
  const hashParams = useMemo(() => readHashParams(window.location.hash), []);
  const accessTokenFromHash = hashParams.get('access_token') ?? searchParams.get('access_token') ?? '';
  const providerReturnUrl = `${returnTo}?providerConnect=shell&serverId=${encodeURIComponent(serverId)}`;

  const resumeMutation = useMutation({
    mutationFn: () => {
      if (!resumeToken) {
        throw new Error('Missing resume_token for pending execution.');
      }
      return resumePendingExecution(accessToken, resumeToken, { client_app_id: clientAppId || undefined });
    },
    onSuccess: result => {
      setStatusMessage(
        result.status === 'resumed'
          ? 'Pending execution resumed successfully.'
          : `Pending execution is now ${result.status}.`,
      );
    },
    onError: (error: Error) => {
      setStatusMessage(error.message || 'Failed to resume the pending execution.');
    },
  });

  const validateProviderMutation = useMutation({
    mutationFn: async () => {
      if (!accessToken) {
        throw new Error('Please sign in again before validating the provider callback receipt.');
      }
      if (!sessionId || !oauthState) {
        throw new Error('Provider callback is missing connect session state.');
      }
      const callbackParams = new URLSearchParams();
      callbackParams.set('connect_session_id', sessionId);
      callbackParams.set('state', oauthState);
      return validateProviderConnectCallback(accessToken, callbackParams);
    },
    onSuccess: () => {
      setProviderCallbackValidated(true);
      setStatusMessage('Provider callback receipt validated. Browser finalize is still unavailable, so return to the registration wizard in shell mode.');
    },
    onError: (error: Error) => {
      setProviderCallbackValidated(false);
      setStatusMessage(error.message || 'Could not validate the provider callback receipt.');
    },
  });

  useEffect(() => {
    if (actor !== 'provider' || !accessToken || !sessionId || !oauthState) {
      return;
    }
    validateProviderMutation.mutate();
  }, [accessToken, actor, oauthState, sessionId]);

  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-6 flex flex-wrap items-center gap-2">
        <Badge variant="secondary">{actor === 'provider' ? 'Provider completion' : 'Client completion'}</Badge>
        {serverId && <Badge variant="secondary">{serverId}</Badge>}
        {toolName && <Badge variant="secondary">{toolName}</Badge>}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-2xl">Connect complete</CardTitle>
          <CardDescription>
            {actor === 'provider'
              ? 'Use this validation shell to check the provider callback receipt before returning to the registration wizard.'
              : 'Resume the original client action once the hosted connect ceremony is complete.'}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {actor === 'client' ? (
            <div className="space-y-4 rounded-lg border border-border bg-card p-4">
              {authType === 'api_key' ? (
                <p className="text-sm text-muted-foreground">
                  Client API-key hosted connect is still a shell-only flow. The backend cannot resume pending executions from browser-captured API keys yet.
                </p>
              ) : (
                <>
                  <p className="text-sm text-muted-foreground">
                    Resume the pending execution after the hosted connect step finishes.
                  </p>
                  {apiKeyCaptured && (
                    <p className="text-sm text-muted-foreground">
                      API key shell captured locally{headerName ? ` via ${headerName}` : ''}.
                    </p>
                  )}
                </>
              )}
              {authType === 'api_key' ? (
                <Button asChild variant="outline">
                  <Link to={returnTo}>Back</Link>
                </Button>
              ) : (
                <div className="flex flex-wrap gap-3">
                  <Button type="button" onClick={() => resumeMutation.mutate()} disabled={resumeMutation.isPending || !resumeToken}>
                    {resumeMutation.isPending ? 'Resuming…' : 'Resume pending action'}
                  </Button>
                  <Button asChild variant="outline">
                    <Link to={returnTo}>Back</Link>
                  </Button>
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-4 rounded-lg border border-border bg-card p-4">
              <p className="text-sm text-muted-foreground">
                This page can validate the provider callback receipt, but it cannot finalize a provider connection in the browser. The backend still requires an access_token POST from a trusted channel.
              </p>
              {accessTokenFromHash && (
                <p className="text-sm text-muted-foreground">
                  For safety, this shell ignored any browser-returned token material and only validates the callback receipt.
                </p>
              )}
              <div className="flex flex-wrap gap-3">
                <Button
                  type="button"
                  onClick={() => validateProviderMutation.mutate()}
                  disabled={validateProviderMutation.isPending || !oauthState || !sessionId}
                >
                  {validateProviderMutation.isPending ? 'Validating…' : providerCallbackValidated ? 'Re-check approval receipt' : 'Validate approval receipt'}
                </Button>
                <Button asChild variant="outline">
                  <Link to={providerReturnUrl}>Return to registration</Link>
                </Button>
              </div>
            </div>
          )}

          {statusMessage && (
            <Alert>
              <AlertTitle>Hosted connect status</AlertTitle>
              <AlertDescription>{statusMessage}</AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
