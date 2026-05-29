import type { HostedConnectReuseScope } from '@/types/database';
import { Label } from '@/components/ui/label';

interface ConnectScopeSelectorProps {
  value: HostedConnectReuseScope;
  onChange: (value: HostedConnectReuseScope) => void;
}

const OPTIONS: Array<{ value: HostedConnectReuseScope; label: string; description: string }> = [
  {
    value: 'user',
    label: 'Reuse across all my MLP clients',
    description: 'Keep the connection reusable for the same signed-in end user across every MLP client.',
  },
  {
    value: 'client_app',
    label: 'Only this client app',
    description: 'Restrict reuse to the current app integration when the credential should stay app-specific.',
  },
];

export default function ConnectScopeSelector({ value, onChange }: ConnectScopeSelectorProps) {
  return (
    <fieldset className="space-y-3">
      <legend className="text-sm font-medium text-foreground">Connection reuse scope</legend>
      <div className="grid gap-3">
        {OPTIONS.map(option => {
          const checked = option.value === value;
          return (
            <Label
              key={option.value}
              className={`flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition-colors ${
                checked ? 'border-primary bg-primary/5' : 'border-border bg-card hover:border-primary/40'
              }`}
            >
              <input
                type="radio"
                name="connect-scope"
                value={option.value}
                checked={checked}
                onChange={() => onChange(option.value)}
                className="mt-1"
              />
              <span className="space-y-1">
                <span className="block text-sm font-medium text-foreground">{option.label}</span>
                <span className="block text-sm text-muted-foreground">{option.description}</span>
              </span>
            </Label>
          );
        })}
      </div>
    </fieldset>
  );
}
