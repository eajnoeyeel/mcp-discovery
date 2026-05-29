import { cn } from '@/lib/utils';
import type { ReactNode } from 'react';

interface StatGridProps {
  cols?: 2 | 3 | 4;
  children: ReactNode;
  className?: string;
}

const colClasses: Record<2 | 3 | 4, string> = {
  2: 'sm:grid-cols-2',
  3: 'sm:grid-cols-2 lg:grid-cols-3',
  4: 'sm:grid-cols-2 lg:grid-cols-4',
};

/**
 * StatGrid primitive — responsive grid wrapper for Stat tiles.
 */
export default function StatGrid({ cols = 3, children, className }: StatGridProps) {
  return (
    <div className={cn('grid grid-cols-1 gap-4', colClasses[cols], className)}>
      {children}
    </div>
  );
}
