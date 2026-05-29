import { useState, useEffect } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Search as SearchIcon } from 'lucide-react';
import SearchBar from '@/components/SearchBar';
import ResultCard from '@/components/ResultCard';
import { getPlatformStats, searchTools } from '@/lib/api';
import { config } from '@/lib/config';
import { Badge } from '@/components/ui/badge';

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialQ = searchParams.get('q') || '';
  const [query, setQuery] = useState(initialQ);

  const { data: stats } = useQuery({
    queryKey: ['platformStats'],
    queryFn: getPlatformStats,
    enabled: config.api.isConfigured,
  });

  const { data, isLoading, isError } = useQuery({
    queryKey: ['search', query],
    queryFn: () => searchTools(query, 5),
    enabled: config.api.isConfigured && !!query,
    retry: false,
  });

  const handleSearch = (q: string) => {
    setQuery(q);
    setSearchParams({ q });
  };

  // Auto-search on mount if q param present
  useEffect(() => {
    if (initialQ && !query) setQuery(initialQ);
  }, [initialQ]);

  return (
    <div className="mx-auto max-w-4xl px-4 py-10">
      <SearchBar onSearch={handleSearch} defaultValue={query} />

      {!config.api.isConfigured && query && (
        <div className="mt-6 rounded-lg border border-border bg-card p-6 text-center">
          <p className="text-muted-foreground">Semantic search is coming soon. Browse the registry instead.</p>
          <Link to="/servers" className="mt-2 inline-block text-primary hover:underline">Browse Registry</Link>
        </div>
      )}

      {data && (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <span className="text-sm text-muted-foreground">
            Found {data.results.length} results in {data.latency_ms}ms
          </span>
          <Badge variant="secondary" className="text-xs">{data.strategy ?? data.strategy_used}</Badge>
          {data.degraded && (
            <Badge variant="destructive" className="text-xs" aria-label="Search is degraded">Degraded</Badge>
          )}
          {typeof data.confidence === 'number' && (
            <span className="text-xs text-muted-foreground">Confidence {data.confidence.toFixed(2)}</span>
          )}
        </div>
      )}

      <div className="mt-6 space-y-4">
        {isLoading && (
          <>
            {[1, 2, 3].map(i => (
              <div key={i} className="h-32 animate-pulse rounded-xl bg-card" />
            ))}
          </>
        )}

        {isError && config.api.isConfigured && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-center text-sm text-destructive">
            Search is temporarily unavailable. Please try again.
          </div>
        )}

        {data?.results.map(result => (
          <ResultCard key={result.tool.tool_id} result={result} />
        ))}

        {data && data.results.length === 0 && (
          <div className="rounded-lg border border-border bg-card p-8 text-center">
            <p className="text-muted-foreground">No tools found for '{query}'</p>
            <p className="mt-1 text-sm text-muted-foreground">Try rephrasing your query or browse the registry</p>
            <Link to="/servers" className="mt-3 inline-block text-primary hover:underline">Browse Registry</Link>
          </div>
        )}

        {!query && (
          <div className="flex flex-col items-center py-16 text-center">
            <SearchIcon className="mb-4 h-12 w-12 text-muted-foreground/30" />
            <h2 className="text-lg font-medium text-foreground">
              Search across {stats?.tool_count ?? '...'} MCP tools
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Try: "search GitHub repositories" or "send emails via SMTP"
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
