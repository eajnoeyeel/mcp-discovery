export const config = {
  supabase: {
    url: import.meta.env.VITE_SUPABASE_URL || '',
    anonKey: import.meta.env.VITE_SUPABASE_ANON_KEY || '',
    get isConfigured() {
      return !!(this.url && this.anonKey);
    },
  },
  api: {
    url: import.meta.env.VITE_API_URL || '',
    key: import.meta.env.VITE_MLP_API_KEY || '',
    get isConfigured() {
      return !!(this.url && this.key);
    },
  },
  mcp: {
    url: import.meta.env.VITE_MCP_URL || 'http://127.0.0.1:8080',
  },
  hostedConnect: {
    // Read lazily via a getter so `vi.stubEnv('VITE_HOSTED_CONNECT_ENABLED', ...)`
    // can flip the value per-test without reloading the module. In production,
    // Vite inlines `import.meta.env.VITE_*` at build time, so flipping this flag
    // requires a container rebuild.
    get enabled(): boolean {
      return import.meta.env.VITE_HOSTED_CONNECT_ENABLED === 'true';
    },
  },
};
