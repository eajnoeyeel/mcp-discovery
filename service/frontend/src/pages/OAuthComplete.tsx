import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useAuth } from '@/contexts/AuthContext';
import { config } from '@/lib/config';

function buildCallbackUrl(redirectUri: string, code: string, state: string) {
  const separator = redirectUri.includes('?') ? '&' : '?';
  return `${redirectUri}${separator}code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`;
}

export default function OAuthComplete() {
  const [searchParams] = useSearchParams();
  const { session, loading } = useAuth();
  const [error, setError] = useState('');

  useEffect(() => {
    if (loading || !session?.access_token) {
      return;
    }

    const redirectUri = searchParams.get('redirect_uri') ?? '';
    const state = searchParams.get('state') ?? '';
    if (!redirectUri || !state) {
      setError('Missing redirect_uri or state.');
      return;
    }

    let cancelled = false;

    const run = async () => {
      try {
        const response = await fetch(`${config.mcp.url}/oauth/issue-code`, {
          method: 'POST',
          headers: {
            authorization: `Bearer ${session.access_token}`,
          },
        });
        if (!response.ok) {
          throw new Error(`Failed to issue authorization code (${response.status})`);
        }
        const body = (await response.json()) as { code?: string };
        if (!body.code) {
          throw new Error('Authorization code missing from issue-code response.');
        }
        if (!cancelled) {
          window.location.assign(buildCallbackUrl(redirectUri, body.code, state));
        }
      } catch (nextError) {
        if (!cancelled) {
          setError(nextError instanceof Error ? nextError.message : 'OAuth completion failed.');
        }
      }
    };

    void run();

    return () => {
      cancelled = true;
    };
  }, [loading, searchParams, session?.access_token]);

  return (
    <div className="mx-auto max-w-xl px-4 py-10">
      <Card>
        <CardHeader>
          <CardTitle className="text-2xl">Finishing Claude authentication</CardTitle>
          <CardDescription>
            After platform login, this page issues a local development auth code and returns you to the MCP client callback.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          {error ? <p>{error}</p> : <p>Completing sign-in…</p>}
        </CardContent>
      </Card>
    </div>
  );
}
