import { cn } from '@/lib/utils';
import type { ReactNode } from 'react';

interface SectionProps {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}

/**
 * Section primitive — the only allowed chrome wrapper for content blocks
 * on the redesigned DashboardToolDetail page. Provides consistent spacing,
 * eyebrow label, title hierarchy, and optional description.
 */
export default function Section({
  eyebrow,
  title,
  description,
  actions,
  children,
  className,
}: SectionProps) {
  return (
    <section className={cn('space-y-5', className)}>
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1.5">
          {eyebrow && (
            <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
              {eyebrow}
            </p>
          )}
          <h2 className="text-2xl font-semibold tracking-tight text-foreground">
            {title}
          </h2>
          {description && (
            <p className="max-w-2xl text-sm text-muted-foreground">{description}</p>
          )}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </header>
      {children}
    </section>
  );
}
