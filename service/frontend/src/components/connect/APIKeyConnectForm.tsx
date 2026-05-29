import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

export interface APIKeyConnectDraft {
  headerName: string;
  apiKey: string;
}

interface APIKeyConnectFormProps {
  title?: string;
  description?: string;
  submitLabel?: string;
  isSubmitting?: boolean;
  onSubmit?: (draft: APIKeyConnectDraft) => void | Promise<void>;
}

export default function APIKeyConnectForm({
  title = 'API key connection',
  description = 'Capture the header name and key you plan to use for this hosted-connect ceremony.',
  submitLabel = 'Continue',
  isSubmitting = false,
  onSubmit,
}: APIKeyConnectFormProps) {
  const [headerName, setHeaderName] = useState('Authorization');
  const [apiKey, setApiKey] = useState('');

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await onSubmit?.({ headerName: headerName.trim() || 'Authorization', apiKey: apiKey.trim() });
  };

  return (
    <form className="space-y-4 rounded-lg border border-border bg-card p-4" onSubmit={handleSubmit}>
      <div>
        <h2 className="text-base font-semibold text-foreground">{title}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="connect-api-key-header">API key header name</Label>
          <Input
            id="connect-api-key-header"
            value={headerName}
            onChange={event => setHeaderName(event.target.value)}
            placeholder="Authorization"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="connect-api-key-value">API key</Label>
          <Input
            id="connect-api-key-value"
            type="password"
            value={apiKey}
            onChange={event => setApiKey(event.target.value)}
            placeholder="Paste the API key"
          />
        </div>
      </div>

      <div className="flex justify-end">
        <Button type="submit" disabled={isSubmitting || !apiKey.trim()}>
          {isSubmitting ? 'Working…' : submitLabel}
        </Button>
      </div>
    </form>
  );
}
