import { useState } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';

export default function Login() {
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { signInWithGoogle } = useAuth();
  const [searchParams] = useSearchParams();

  const message = searchParams.get('message');
  const redirect = searchParams.get('redirect') || '/dashboard';

  const handleGoogleSignIn = async () => {
    setError('');
    setLoading(true);
    const { error } = await signInWithGoogle(redirect);
    if (error) {
      setError(error);
      setLoading(false);
      return;
    }
    setLoading(false);
  };

  return (
    <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center px-4">
      <Card className="w-full max-w-md border-border">
        <CardHeader className="text-center">
          <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-primary text-primary-foreground font-bold">M</div>
          <CardTitle className="text-xl">MCP Discovery</CardTitle>
          <CardDescription>Continue with Google to access the provider dashboard.</CardDescription>
        </CardHeader>
        <CardContent>
          {message === 'session_expired' && (
            <div className="mb-4 rounded-md bg-warning/10 p-3 text-sm text-warning">
              Session expired. Please sign in again.
            </div>
          )}

          {error && <p className="mb-4 text-sm text-destructive">{error}</p>}

          <Button type="button" className="w-full" disabled={loading} onClick={handleGoogleSignIn}>
            {loading ? 'Redirecting...' : 'Continue with Google'}
          </Button>

          <p className="mt-4 text-center text-sm text-muted-foreground">
            <Link to="/servers" className="text-primary hover:underline">Back to Registry</Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
