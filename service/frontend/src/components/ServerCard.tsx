import { Link } from 'react-router-dom';
import type { MCPServer } from '@/types/database';

interface ServerCardProps {
  server: MCPServer & { tool_count?: number };
}

export default function ServerCard({ server }: ServerCardProps) {
  return (
    <Link
      to={`/servers/${server.server_id}`}
      className="group block rounded-xl border border-border bg-card p-5 transition-colors hover:border-muted-foreground/30"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-semibold text-foreground group-hover:text-primary transition-colors">{server.name}</h3>
      </div>
      <p className="mt-1.5 line-clamp-2 text-sm text-muted-foreground">{server.description || 'No description'}</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {server.tool_count !== undefined && (
          <span className="rounded-full bg-secondary px-2 py-0.5 text-xs text-secondary-foreground">
            {server.tool_count} tools
          </span>
        )}
        {server.tags?.slice(0, 3).map(tag => (
          <span key={tag} className="rounded-full bg-secondary px-2 py-0.5 text-xs text-muted-foreground">
            {tag}
          </span>
        ))}
      </div>
    </Link>
  );
}
