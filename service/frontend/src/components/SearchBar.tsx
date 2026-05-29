import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search as SearchIcon } from 'lucide-react';
import { cn } from '@/lib/utils';

interface SearchBarProps {
  onSearch?: (query: string) => void;
  defaultValue?: string;
  placeholder?: string;
  navigateTo?: string;
  className?: string;
}

export default function SearchBar({ onSearch, defaultValue = '', placeholder = 'Describe what you need, e.g. "search GitHub repositories"', navigateTo, className }: SearchBarProps) {
  const [query, setQuery] = useState(defaultValue);
  const navigate = useNavigate();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;

    if (navigateTo) {
      navigate(`${navigateTo}?q=${encodeURIComponent(q)}`);
    }
    onSearch?.(q);
  };

  return (
    <form onSubmit={handleSubmit} className={cn('relative w-full', className)}>
      <SearchIcon className="absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground" />
      <input
        type="text"
        value={query}
        onChange={e => setQuery(e.target.value)}
        placeholder={placeholder}
        className="h-12 w-full rounded-lg border border-border bg-card pl-12 pr-4 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-shadow"
      />
    </form>
  );
}
