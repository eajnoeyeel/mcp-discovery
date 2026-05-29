import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { config } from '@/lib/config';
import { getProviderProfile, updateProviderProfile } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useAuth } from '@/contexts/AuthContext';
import { toast } from 'sonner';

export default function DashboardSettings() {
  const { session, user } = useAuth();
  const accessToken = session?.access_token ?? '';
  const authIdentity = user?.id ?? accessToken ?? 'anonymous';
  const queryClient = useQueryClient();

  const [displayName, setDisplayName] = useState('');
  const [orgName, setOrgName] = useState('');
  const [contactEmail, setContactEmail] = useState('');
  const [initialized, setInitialized] = useState(false);

  // Populate form fields after load
  const { data: profileData, isLoading, isError } = useQuery({
    queryKey: ['providerProfile', authIdentity],
    queryFn: () => getProviderProfile(accessToken),
    enabled: config.api.isConfigured && !!accessToken,
  });

  if (!initialized && profileData) {
    const p = profileData as Record<string, unknown>;
    setDisplayName((p.display_name as string) ?? '');
    setOrgName((p.org_name as string) ?? '');
    setContactEmail((p.contact_email as string) ?? '');
    setInitialized(true);
  }

  const mutation = useMutation({
    mutationFn: (formData: Record<string, string>) => updateProviderProfile(accessToken, formData),
    onSuccess: () => {
      toast.success('Profile saved');
      queryClient.invalidateQueries({ queryKey: ['providerProfile'] });
    },
    onError: (err: Error) => {
      toast.error(err.message ?? 'Failed to save profile');
    },
  });

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    mutation.mutate({ display_name: displayName, org_name: orgName, contact_email: contactEmail });
  }

  if (!config.api.isConfigured) {
    return <div className="mx-auto max-w-7xl px-4 py-10 text-muted-foreground">API is not configured yet.</div>;
  }
  if (!accessToken) {
    return <div className="mx-auto max-w-7xl px-4 py-10 text-muted-foreground">Please sign in to view this page.</div>;
  }

  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <h1 className="text-2xl font-bold text-foreground">Settings</h1>
      <p className="mt-1 text-muted-foreground">Manage your provider profile</p>

      <Card className="mt-8">
        <CardHeader>
          <CardTitle>Provider Profile</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              <div className="h-9 animate-pulse rounded bg-secondary" />
              <div className="h-9 animate-pulse rounded bg-secondary" />
              <div className="h-9 animate-pulse rounded bg-secondary" />
            </div>
          ) : isError ? (
            <div role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
              Failed to load settings. Editing is disabled until the profile loads successfully. Try refreshing the page.
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <label htmlFor="display_name" className="text-sm font-medium text-foreground">
                  Display Name
                </label>
                <Input
                  id="display_name"
                  value={displayName}
                  onChange={e => setDisplayName(e.target.value)}
                  placeholder="Your display name"
                />
              </div>

              <div className="space-y-1.5">
                <label htmlFor="org_name" className="text-sm font-medium text-foreground">
                  Organization Name
                </label>
                <Input
                  id="org_name"
                  value={orgName}
                  onChange={e => setOrgName(e.target.value)}
                  placeholder="Your organization"
                />
              </div>

              <div className="space-y-1.5">
                <label htmlFor="contact_email" className="text-sm font-medium text-foreground">
                  Contact Email
                </label>
                <Input
                  id="contact_email"
                  type="email"
                  value={contactEmail}
                  onChange={e => setContactEmail(e.target.value)}
                  placeholder="contact@example.com"
                />
              </div>

              <Button type="submit" disabled={mutation.isPending}>
                {mutation.isPending ? 'Saving…' : 'Save'}
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
