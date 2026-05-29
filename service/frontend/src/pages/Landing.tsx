import { useQuery } from '@tanstack/react-query';
import { Search, BarChart3, Zap, ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import SearchBar from '@/components/SearchBar';
import { config } from '@/lib/config';
import { getPlatformStats } from '@/lib/api';

export default function Landing() {
  const { data: stats } = useQuery({
    queryKey: ['platformStats'],
    queryFn: getPlatformStats,
    enabled: config.api.isConfigured,
  });

  const features = [
    {
      icon: Search,
      title: 'Semantic Search',
      description:
        'Describe what you need in natural language. Embedding-only retrieval with confidence gating surfaces the best matching tool.',
    },
    {
      icon: BarChart3,
      title: 'GEO Score Diagnostics',
      description:
        '6-dimension quality analysis for every tool description. See exactly what to improve.',
    },
    {
      icon: Zap,
      title: 'MCP Bridge',
      description:
        'Connect your LLM agent to a single endpoint. We route queries to the right tool automatically.',
    },
  ];

  const statPills = [
    config.api.isConfigured
      ? `${stats?.server_count ?? '—'} Servers`
      : '290+ Servers',
    config.api.isConfigured
      ? `${stats?.tool_count ?? '—'} Tools`
      : '2,800+ Tools',
    '6D GEO Scoring',
  ];

  return (
    <div className="relative min-h-screen overflow-hidden bg-background text-foreground">
      {/* Framer Blue aura behind hero — per DESIGN.md decorative depth */}
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-[-140px] h-[540px] w-[980px] -translate-x-1/2 rounded-full bg-primary/15 blur-[160px]"
      />

      <div className="relative mx-auto max-w-[1200px] px-6 sm:px-10">
        {/* Hero */}
        <section className="flex flex-col items-center justify-center pt-28 pb-24 text-center sm:pt-36">
          <span className="mb-8 inline-flex items-center gap-2 rounded-full bg-white/5 px-3 py-1 text-xs font-medium text-muted-foreground ring-1 ring-white/10 backdrop-blur">
            <span className="h-1.5 w-1.5 rounded-full bg-primary shadow-[0_0_8px_hsl(var(--primary))]" />
            Semantic tool discovery
          </span>

          <h1 className="font-display text-[2.75rem] font-medium leading-[0.9] tracking-framer-tight text-foreground sm:text-7xl lg:text-[7.5rem]">
            Discover the right
            <br />
            MCP tool.
          </h1>

          <p className="mt-8 max-w-xl text-base text-muted-foreground sm:text-lg">
            Semantic search engine connecting LLM clients with the best MCP tools.
            Provider analytics show you how to improve your tool's discoverability.
          </p>

          <div className="mt-10 w-full max-w-2xl">
            <SearchBar navigateTo="/search" />
          </div>

          <div className="mt-8 flex flex-wrap items-center justify-center gap-2.5">
            {statPills.map((label) => (
              <span
                key={label}
                className="rounded-full bg-white/5 px-4 py-1.5 text-xs font-medium text-muted-foreground ring-1 ring-white/10 backdrop-blur"
              >
                {label}
              </span>
            ))}
          </div>

          <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
            <Button
              asChild
              size="lg"
              className="group h-11 rounded-full bg-white px-6 text-sm font-medium text-black shadow-framer-elev hover:bg-white/95 hover:text-black active:scale-[0.98]"
            >
              <Link to="/search">
                Search Tools
                <ArrowRight className="ml-2 h-4 w-4 transition-transform group-hover:translate-x-0.5" />
              </Link>
            </Button>
            <Button
              asChild
              size="lg"
              variant="ghost"
              className="h-11 rounded-full bg-white/10 px-6 text-sm font-medium text-foreground backdrop-blur hover:bg-white/15 hover:text-foreground"
            >
              <Link to="/servers">Browse Registry</Link>
            </Button>
          </div>
        </section>

        {/* Features */}
        <section className="grid gap-4 pb-24 sm:grid-cols-3">
          {features.map(({ icon: Icon, title, description }) => (
            <div
              key={title}
              className="group rounded-[14px] bg-card p-6 shadow-framer-ring transition duration-300 hover:shadow-framer-elev"
            >
              <div className="mb-5 inline-flex h-10 w-10 items-center justify-center rounded-full bg-primary/10 text-primary ring-1 ring-primary/25">
                <Icon className="h-5 w-5" />
              </div>
              <h3 className="font-display text-xl font-medium tracking-framer-snug text-foreground">
                {title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                {description}
              </p>
            </div>
          ))}
        </section>

        {/* Footer */}
        <footer className="border-t border-border/80 py-10 text-center text-xs text-muted-foreground">
          MCP Discovery Platform — built for MCP tool providers and LLM developers
        </footer>
      </div>
    </div>
  );
}
