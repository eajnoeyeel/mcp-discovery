import { useEffect, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import ConfirmRegistrationStep from '@/components/register/ConfirmRegistrationStep';
import DiscoveryStep, { type RegistrationDiscoveryFormState } from '@/components/register/DiscoveryStep';
import EditOverridesStep from '@/components/register/EditOverridesStep';
import ReviewToolsStep from '@/components/register/ReviewToolsStep';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/contexts/AuthContext';
import {
  createOAuthProviderManualBootstrap,
  discoverProviderConnect,
  discoverProviderServerMetadata,
  enableOAuthProviderBootstrap,
  registerProviderServer,
} from '@/lib/api';
import { config } from '@/lib/config';
import type {
  ClientAuthConfig,
  ClientAuthScopeMode,
  ParameterMetadataEntry,
  PublishedParameterMetadataEntry,
  RegisterDiscoveryRequest,
  RegisterDiscoveryResponse,
  RegisterServerRequest,
  UpstreamAuthConfig,
} from '@/types/database';

type WizardStep = 'connect' | 'review' | 'edit' | 'confirm';

type WizardToolDraft = {
  tool_name: string;
  description: string;
  upstream_description: string;
  input_schema: Record<string, unknown> | null;
  parameter_metadata: ParameterMetadataEntry[];
  published_parameter_metadata: PublishedParameterMetadataEntry[];
  parameter_notes: string;
  usage_examples: string[];
  usage_hints: string[];
};

type EditableToolField =
  | 'tool_name'
  | 'description'
  | 'upstream_description'
  | 'parameter_notes'
  | 'usage_examples'
  | 'usage_hints';

const STEP_LABELS: Record<WizardStep, string> = {
  connect: 'Connect',
  review: 'Review',
  edit: 'Edit',
  confirm: 'Confirm',
};

const STEP_ORDER: WizardStep[] = ['connect', 'review', 'edit', 'confirm'];

const EMPTY_DISCOVERY_FORM: RegistrationDiscoveryFormState = {
  serverId: '',
  name: '',
  url: '',
  description: '',
  tags: '',
  authType: 'none',
  clientAuthProviderKey: '',
  clientAuthRequiredScopes: '',
  clientAuthScopeMode: 'default',
  clientAuthBootstrapDisplayName: '',
  clientAuthBootstrapAuthorizeUrl: '',
  clientAuthBootstrapTokenUrl: '',
  clientAuthBootstrapClientId: '',
  clientAuthBootstrapClientSecret: '',
  clientAuthBootstrapTokenAuthMethod: 'none',
  bearerToken: '',
  apiKeyHeaderName: '',
  apiKey: '',
  customHeadersText: '',
  oauthTokenEndpoint: '',
  oauthClientId: '',
  oauthClientSecret: '',
  oauthRefreshToken: '',
  oauthScope: '',
};

const EMPTY_TOOL: WizardToolDraft = {
  tool_name: '',
  description: '',
  upstream_description: '',
  input_schema: null,
  parameter_metadata: [],
  published_parameter_metadata: [],
  parameter_notes: '',
  usage_examples: [],
  usage_hints: [],
};

const PROVIDER_CONNECT_DRAFT_STORAGE_KEY = 'mlp:provider-connect-registration-draft';

type ProviderConnectDraft = Pick<
  RegistrationDiscoveryFormState,
  | 'serverId'
  | 'name'
  | 'url'
  | 'description'
  | 'tags'
  | 'authType'
  | 'clientAuthProviderKey'
  | 'clientAuthRequiredScopes'
  | 'clientAuthScopeMode'
>;

const ALLOWED_PROVIDER_CONNECT_AUTH_TYPES = new Set<RegistrationDiscoveryFormState['authType']>([
  'none',
  'bearer',
  'api_key_header',
  'custom_headers',
  'oauth_session',
]);
const ALLOWED_CLIENT_AUTH_SCOPE_MODES = new Set<ClientAuthScopeMode>(['default', 'override']);

function sanitizeProviderConnectDraftFields(
  draft: Partial<RegistrationDiscoveryFormState>,
): ProviderConnectDraft {
  return {
    serverId: typeof draft.serverId === 'string' ? draft.serverId : '',
    name: typeof draft.name === 'string' ? draft.name : '',
    url: typeof draft.url === 'string' ? draft.url : '',
    description: typeof draft.description === 'string' ? draft.description : '',
    tags: typeof draft.tags === 'string' ? draft.tags : '',
    authType:
      typeof draft.authType === 'string' && ALLOWED_PROVIDER_CONNECT_AUTH_TYPES.has(draft.authType)
        ? draft.authType
        : EMPTY_DISCOVERY_FORM.authType,
    clientAuthProviderKey:
      typeof draft.clientAuthProviderKey === 'string' ? draft.clientAuthProviderKey : '',
    clientAuthRequiredScopes:
      typeof draft.clientAuthRequiredScopes === 'string' ? draft.clientAuthRequiredScopes : '',
    clientAuthScopeMode:
      typeof draft.clientAuthScopeMode === 'string' &&
      ALLOWED_CLIENT_AUTH_SCOPE_MODES.has(draft.clientAuthScopeMode)
        ? draft.clientAuthScopeMode
        : EMPTY_DISCOVERY_FORM.clientAuthScopeMode,
  };
}

function sanitizeProviderConnectDraft(form: RegistrationDiscoveryFormState): ProviderConnectDraft {
  return sanitizeProviderConnectDraftFields(form);
}

function persistProviderConnectDraft(form: RegistrationDiscoveryFormState) {
  sessionStorage.setItem(
    PROVIDER_CONNECT_DRAFT_STORAGE_KEY,
    JSON.stringify(sanitizeProviderConnectDraft(form)),
  );
}

function readProviderConnectDraft(): RegistrationDiscoveryFormState | null {
  const raw = sessionStorage.getItem(PROVIDER_CONNECT_DRAFT_STORAGE_KEY);
  if (!raw) {
    return null;
  }

  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') {
      sessionStorage.removeItem(PROVIDER_CONNECT_DRAFT_STORAGE_KEY);
      return null;
    }

    return {
      ...EMPTY_DISCOVERY_FORM,
      ...sanitizeProviderConnectDraftFields(parsed as Partial<RegistrationDiscoveryFormState>),
    };
  } catch {
    sessionStorage.removeItem(PROVIDER_CONNECT_DRAFT_STORAGE_KEY);
    return null;
  }
}

function clearProviderConnectDraft() {
  sessionStorage.removeItem(PROVIDER_CONNECT_DRAFT_STORAGE_KEY);
}

function parseDelimitedLines(value: string): string[] {
  return value
    .split('\n')
    .map(entry => entry.trim())
    .filter(Boolean);
}

function parseCustomHeaders(value: string): Record<string, string> {
  return value
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
    .reduce<Record<string, string>>((headers, line) => {
      const separator = line.indexOf(':');
      if (separator === -1) {
        return headers;
      }
      const key = line.slice(0, separator).trim();
      const headerValue = line.slice(separator + 1).trim();
      if (!key || !headerValue) {
        return headers;
      }
      headers[key] = headerValue;
      return headers;
    }, {});
}

function parseRequiredScopes(value: string): string[] {
  const seen = new Set<string>();

  return value
    .split(/[\n,]/)
    .map(entry => entry.trim())
    .filter(entry => {
      if (!entry || seen.has(entry)) {
        return false;
      }
      seen.add(entry);
      return true;
    });
}

function buildExecutionAuth(form: RegistrationDiscoveryFormState): UpstreamAuthConfig {
  switch (form.authType) {
    case 'bearer':
      return {
        auth_type: 'bearer',
        bearer_token: form.bearerToken.trim(),
      };
    case 'api_key_header':
      return {
        auth_type: 'api_key_header',
        api_key_header_name: form.apiKeyHeaderName.trim(),
        api_key: form.apiKey.trim(),
      };
    case 'custom_headers':
      return {
        auth_type: 'custom_headers',
        headers: parseCustomHeaders(form.customHeadersText),
      };
    case 'oauth_session':
      return {
        auth_type: 'oauth_session',
        oauth_token_endpoint: form.oauthTokenEndpoint.trim(),
        oauth_client_id: form.oauthClientId.trim(),
        oauth_client_secret: form.oauthClientSecret.trim(),
        oauth_refresh_token: form.oauthRefreshToken.trim(),
        oauth_scope: form.oauthScope.trim() || undefined,
      };
    case 'none':
    default:
      return { auth_type: 'none' };
  }
}

function buildClientAuth(form: RegistrationDiscoveryFormState): ClientAuthConfig | undefined {
  const providerKey = form.clientAuthProviderKey.trim();
  if (!providerKey) {
    return undefined;
  }

  return {
    provider_key: providerKey,
    required_scopes: parseRequiredScopes(form.clientAuthRequiredScopes),
    scope_mode: form.clientAuthScopeMode,
  };
}

function hasManualOAuthProviderBootstrap(form: RegistrationDiscoveryFormState): boolean {
  return Boolean(
    form.clientAuthProviderKey.trim() &&
      form.clientAuthBootstrapAuthorizeUrl.trim() &&
      form.clientAuthBootstrapTokenUrl.trim() &&
      form.clientAuthBootstrapClientId.trim(),
  );
}

function buildToolDrafts(discovery: RegisterDiscoveryResponse): WizardToolDraft[] {
  return discovery.tools.map(tool => ({
    tool_name: tool.tool_name,
    description: tool.upstream_description || '',
    upstream_description: tool.upstream_description || '',
    input_schema: tool.input_schema,
    parameter_metadata: tool.parameter_metadata ?? [],
    published_parameter_metadata: [],
    parameter_notes: '',
    usage_examples: [],
    usage_hints: [],
  }));
}

function normalizeToolName(toolName: string): string {
  return toolName.trim().toLowerCase();
}

function hasDuplicateToolNames(tools: Array<Pick<WizardToolDraft, 'tool_name'>>): boolean {
  const seen = new Set<string>();

  for (const tool of tools) {
    const normalized = normalizeToolName(tool.tool_name);
    if (!normalized) {
      continue;
    }
    if (seen.has(normalized)) {
      return true;
    }
    seen.add(normalized);
  }

  return false;
}

export default function RegisterServer() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const { session } = useAuth();
  const accessToken = session?.access_token ?? '';

  const [step, setStep] = useState<WizardStep>('connect');
  const [form, setForm] = useState<RegistrationDiscoveryFormState>(EMPTY_DISCOVERY_FORM);
  const [tools, setTools] = useState<WizardToolDraft[]>([]);
  const [manualMode, setManualMode] = useState(false);
  const [discovery, setDiscovery] = useState<RegisterDiscoveryResponse | null>(null);
  const [discoveryError, setDiscoveryError] = useState('');
  const [error, setError] = useState('');
  const providerConnectAutoResumeRef = useRef(false);
  const providerConnectDraftRestoredRef = useRef(false);

  const discoveryMutation = useMutation({
    mutationFn: (payload: RegisterDiscoveryRequest) => discoverProviderServerMetadata(accessToken, payload),
    onSuccess: result => {
      clearProviderConnectDraft();
      if (searchParams.get('providerConnect') === 'connected') {
        navigate('/dashboard/register', { replace: true });
      }
      setDiscovery(result);
      const discoveredTools = buildToolDrafts(result);
      if (discoveredTools.length === 0) {
        setManualMode(true);
        setTools([{ ...EMPTY_TOOL }]);
      } else {
        setManualMode(false);
        setTools(discoveredTools);
      }
      setDiscoveryError('');
      setError('');
      setStep('review');
    },
    onError: (mutationError: Error) => {
      setDiscoveryError(mutationError.message || 'Failed to discover provider metadata.');
    },
  });

  const registerMutation = useMutation({
    mutationFn: (payload: RegisterServerRequest) => registerProviderServer(accessToken, payload),
    onSuccess: async result => {
      clearProviderConnectDraft();
      await queryClient.invalidateQueries({ queryKey: ['dashboardTools'] });
      navigate(`/dashboard?registration=pending&server=${encodeURIComponent(result.server_id)}`);
    },
    onError: (mutationError: Error) => {
      setError(mutationError.message);
    },
  });

  const providerConnectStatus = searchParams.get('providerConnect');
  const returnedServerId = searchParams.get('serverId') ?? '';

  useEffect(() => {
    if (!providerConnectStatus) {
      return;
    }

    const storedDraft = readProviderConnectDraft();
    if (storedDraft && !providerConnectDraftRestoredRef.current) {
      setForm(storedDraft);
      providerConnectDraftRestoredRef.current = true;
    }

    if (providerConnectStatus === 'shell') {
      setDiscoveryError(
        storedDraft
          ? 'Browser-based provider finalize is not available yet. Review the restored draft and continue manually once a trusted finalize path exists.'
          : 'The provider validation shell returned without a saved draft. Re-enter the server details and try again.',
      );
      return;
    }

    if (providerConnectStatus !== 'connected' || providerConnectAutoResumeRef.current) {
      return;
    }

    if (!storedDraft) {
      setDiscoveryError('The hosted connect draft was not found. Re-enter the server details and try again.');
      return;
    }

    if (returnedServerId && returnedServerId !== storedDraft.serverId.trim()) {
      setDiscoveryError('Hosted connect returned for a different server. Review the draft details before retrying.');
      return;
    }

    if (!accessToken) {
      setDiscoveryError('Please sign in again before resuming metadata discovery.');
      return;
    }

    providerConnectAutoResumeRef.current = true;
    setForm(storedDraft);
    setDiscoveryError('');
    setError('');
    discoveryMutation.mutate({
      server_id: storedDraft.serverId.trim(),
      url: storedDraft.url.trim(),
      execution_auth: { auth_type: 'none' },
    });
  }, [accessToken, discoveryMutation, providerConnectStatus, returnedServerId]);

  if (!config.api.isConfigured) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-10 text-muted-foreground">
        Registration is unavailable until the backend API is configured.
      </div>
    );
  }

  const stepIndex = STEP_ORDER.indexOf(step);

  const handleFormChange = (field: keyof RegistrationDiscoveryFormState, value: string) => {
    setForm(current => ({ ...current, [field]: value }));
  };

  const handleToolChange = (index: number, field: EditableToolField, value: string) => {
    setTools(current =>
      current.map((tool, toolIndex) => {
        if (toolIndex !== index) {
          return tool;
        }

        if (field === 'usage_examples' || field === 'usage_hints') {
          return {
            ...tool,
            [field]: parseDelimitedLines(value),
          };
        }

        return {
          ...tool,
          [field]: value,
        };
      }),
    );
  };

  const handleAddTool = () => {
    setTools(current => [...current, { ...EMPTY_TOOL }]);
  };

  const handlePublishedParameterDescriptionChange = (index: number, path: string, description: string) => {
    setTools(current =>
      current.map((tool, toolIndex) => {
        if (toolIndex !== index) {
          return tool;
        }

        const existingEntry = tool.published_parameter_metadata.find(entry => entry.path === path);
        const nextDescription = description.trim();
        const nextEntries = nextDescription
          ? existingEntry
            ? tool.published_parameter_metadata.map(entry =>
                entry.path === path ? { ...entry, description } : entry,
              )
            : [...tool.published_parameter_metadata, { path, description }]
          : tool.published_parameter_metadata.filter(entry => entry.path !== path);

        return {
          ...tool,
          published_parameter_metadata: nextEntries,
        };
      }),
    );
  };

  const handleRemoveTool = (index: number) => {
    setTools(current => (current.length === 1 ? current : current.filter((_, toolIndex) => toolIndex !== index)));
  };

  const handleFetchMetadata = async () => {
    setError('');
    setDiscoveryError('');

    if (!accessToken) {
      setDiscoveryError('Please sign in again before fetching metadata.');
      return;
    }

    if (!form.serverId.trim()) {
      setDiscoveryError('Server ID is required before discovery.');
      return;
    }

    if (!form.url.trim()) {
      setDiscoveryError('Server URL is required before discovery.');
      return;
    }

    const executionAuth = buildExecutionAuth(form);

    if (
      config.hostedConnect.enabled &&
      executionAuth.auth_type === 'none' &&
      searchParams.get('providerConnect') !== 'connected'
    ) {
      try {
        const session = await discoverProviderConnect(accessToken, {
          server_id: form.serverId.trim(),
          url: form.url.trim(),
        });

        if (session.auth_type !== 'none') {
          persistProviderConnectDraft(form);
          const nextParams = new URLSearchParams({
            actor: 'provider',
            connect_session_id: session.connect_session_id,
            session: session.connect_session_id,
            server_id: session.server_id,
            auth_type: session.auth_type,
            return_to: '/dashboard/register',
          });
          if (session.start_url) {
            nextParams.set('start_url', session.start_url);
          }
          navigate(`/connect?${nextParams.toString()}`);
          return;
        }
      } catch {
        // Hosted-connect probe failed (commonly: backend route not deployed).
        // Fall through to the standard discovery flow rather than hard-blocking
        // registration of auth_type=none servers.
      }
    }

    discoveryMutation.mutate({
      server_id: form.serverId.trim(),
      url: form.url.trim(),
      execution_auth: executionAuth,
    });
  };

  const handleContinueManually = () => {
    setManualMode(true);
    setDiscovery(null);
    setTools(current => (current.length > 0 ? current : [{ ...EMPTY_TOOL }]));
    setError('');
    setStep('review');
  };

  const handleContinueFromReview = () => {
    const hasNamedTool = tools.some(tool => tool.tool_name.trim());
    if (!hasNamedTool) {
      setError('At least one tool name is required before continuing.');
      return;
    }

    if (hasDuplicateToolNames(tools)) {
      setError('Duplicate tool names are not allowed. Each tool name must be unique per server.');
      return;
    }

    setError('');
    setStep('edit');
  };

  const handleContinueFromEdit = () => {
    const hasNamedTool = tools.some(tool => tool.tool_name.trim());
    if (!hasNamedTool) {
      setError('At least one tool name is required before continuing.');
      return;
    }

    if (hasDuplicateToolNames(tools)) {
      setError('Duplicate tool names are not allowed. Each tool name must be unique per server.');
      return;
    }

    setError('');
    setStep('confirm');
  };

  const handleSubmit = async () => {
    setError('');

    if (!accessToken) {
      setError('Please sign in again before registering a server.');
      return;
    }

    if (!form.serverId.trim() || !form.name.trim() || !form.url.trim()) {
      setError('Server ID, server name, and URL are required.');
      return;
    }

    const trimmedTools = tools
      .map(tool => ({
        tool_name: tool.tool_name.trim(),
        description: tool.description.trim(),
        upstream_description: tool.upstream_description.trim(),
        input_schema: tool.input_schema,
        parameter_metadata: tool.parameter_metadata
          .map(entry => ({
            ...entry,
            path: entry.path.trim(),
            name: entry.name.trim(),
            description: entry.description?.trim() || undefined,
          }))
          .filter(entry => entry.path && entry.name),
        published_parameter_metadata: tool.published_parameter_metadata
          .map(entry => ({
            path: entry.path.trim(),
            description: entry.description?.trim() || '',
          }))
          .filter(entry => entry.path && entry.description),
        parameter_notes: tool.parameter_notes.trim(),
        usage_examples: tool.usage_examples.map(example => example.trim()).filter(Boolean),
        usage_hints: tool.usage_hints.map(hint => hint.trim()).filter(Boolean),
      }))
      .filter(tool => tool.tool_name);

    if (trimmedTools.length === 0) {
      setError('At least one tool name is required.');
      return;
    }

    if (hasDuplicateToolNames(trimmedTools)) {
      setError('Duplicate tool names are not allowed. Each tool name must be unique per server.');
      return;
    }

    try {
      const clientAuth = buildClientAuth(form);

      if (clientAuth && hasManualOAuthProviderBootstrap(form)) {
        const bootstrap = await createOAuthProviderManualBootstrap(accessToken, {
          provider_key: clientAuth.provider_key,
          display_name: form.clientAuthBootstrapDisplayName.trim() || clientAuth.provider_key,
          authorize_url: form.clientAuthBootstrapAuthorizeUrl.trim(),
          token_url: form.clientAuthBootstrapTokenUrl.trim(),
          client_id: form.clientAuthBootstrapClientId.trim(),
          client_secret: form.clientAuthBootstrapClientSecret.trim() || undefined,
          token_endpoint_auth_method: form.clientAuthBootstrapTokenAuthMethod as 'none' | 'client_secret_post' | 'client_secret_basic',
          default_scopes: [],
          supports_refresh_token: true,
          pkce_required: form.clientAuthBootstrapTokenAuthMethod === 'none',
        });
        if (bootstrap.draft_id) {
          await enableOAuthProviderBootstrap(accessToken, clientAuth.provider_key, bootstrap.draft_id);
        }
      }

      await registerMutation.mutateAsync({
        server_id: form.serverId.trim(),
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        url: form.url.trim(),
        tags: form.tags
          .split(',')
          .map(tag => tag.trim())
          .filter(Boolean),
        execution_auth: buildExecutionAuth(form),
        ...(clientAuth ? { client_auth: clientAuth } : {}),
        transport_type: 'stateless_http',
        requires_gateway: false,
        tools: trimmedTools.map(tool => ({
          tool_name: tool.tool_name,
          description: tool.description || undefined,
          upstream_description: tool.upstream_description || undefined,
          input_schema: tool.input_schema,
          parameter_metadata: tool.parameter_metadata,
          published_parameter_metadata: tool.published_parameter_metadata,
          parameter_notes: tool.parameter_notes || undefined,
          usage_examples: tool.usage_examples,
          usage_hints: tool.usage_hints,
        })),
      });
    } catch {
      // The mutation onError callback already surfaces the backend error to the wizard.
    }
  };

  return (
    <div className="mx-auto max-w-5xl px-4 py-10">
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Register Server</h1>
          <p className="mt-1 text-muted-foreground">
            Discover upstream MCP metadata first. If the upstream server requires hosted OAuth or API-key setup, the wizard
            now routes you through hosted connect before you publish the final provider-facing copy.
          </p>
        </div>
        <Button asChild variant="outline">
          <Link to="/dashboard">Back to Dashboard</Link>
        </Button>
      </div>

      <Alert className="mb-6 border-primary/30 bg-primary/5">
        <AlertTitle>Wizard flow</AlertTitle>
        <AlertDescription>
          The registration wizard keeps upstream metadata visible while you prepare the final provider-facing tool copy.
        </AlertDescription>
      </Alert>

      <div className="mb-8 flex flex-wrap gap-2">
        {STEP_ORDER.map((stepKey, index) => {
          const isActive = stepKey === step;
          const isComplete = index < stepIndex;

          return (
            <Badge key={stepKey} variant={isActive ? 'default' : 'outline'}>
              {isComplete ? `${index + 1}. ${STEP_LABELS[stepKey]} ✓` : `${index + 1}. ${STEP_LABELS[stepKey]}`}
            </Badge>
          );
        })}
      </div>

      {step === 'connect' && (
        <DiscoveryStep
          value={form}
          onChange={handleFormChange}
          onFetchMetadata={handleFetchMetadata}
          onContinueManually={handleContinueManually}
          isDiscovering={discoveryMutation.isPending}
          discoveryError={discoveryError}
        />
      )}

      {step === 'review' && (
        <ReviewToolsStep
          tools={tools}
          manualMode={manualMode}
          warnings={discovery?.warnings ?? []}
          error={error}
          onToolChange={handleToolChange}
          onAddTool={handleAddTool}
          onRemoveTool={handleRemoveTool}
          onBack={() => {
            setError('');
            setStep('connect');
          }}
          onContinue={handleContinueFromReview}
        />
      )}

      {step === 'edit' && (
        <EditOverridesStep
          tools={tools}
          error={error}
          onToolFieldChange={handleToolChange}
          onPublishedParameterChange={handlePublishedParameterDescriptionChange}
          onBack={() => {
            setError('');
            setStep('review');
          }}
          onContinue={handleContinueFromEdit}
        />
      )}

      {step === 'confirm' && (
        <ConfirmRegistrationStep
          server={{
            serverId: form.serverId.trim(),
            name: form.name.trim(),
            url: form.url.trim(),
            description: form.description.trim(),
            tags: form.tags
              .split(',')
              .map(tag => tag.trim())
              .filter(Boolean),
            clientAuth: buildClientAuth(form),
          }}
          tools={tools.map((tool, index) => ({
            render_key: `confirm-tool-${index}`,
            tool_name: tool.tool_name.trim(),
            description: tool.description.trim(),
            upstream_description: tool.upstream_description.trim(),
            parameter_metadata: tool.parameter_metadata,
            published_parameter_metadata: tool.published_parameter_metadata
              .map(entry => ({
                path: entry.path.trim(),
                description: entry.description?.trim() || '',
              }))
              .filter(entry => entry.path && entry.description),
            parameter_notes: tool.parameter_notes.trim(),
            usage_examples: tool.usage_examples.map(example => example.trim()).filter(Boolean),
            usage_hints: tool.usage_hints.map(hint => hint.trim()).filter(Boolean),
          }))}
          error={error}
          isSubmitting={registerMutation.isPending}
          onBack={() => {
            setError('');
            setStep('edit');
          }}
          onSubmit={handleSubmit}
        />
      )}
    </div>
  );
}
