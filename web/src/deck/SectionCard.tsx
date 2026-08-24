import type { ReactNode } from 'react'
import { CircleHelp } from 'lucide-react'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

/** One deck card: a takeaway title that SAYS something (never a grey
 *  paragraph), an optional on-demand explanation, and the content. */
export function Card({
  title,
  hint,
  actions,
  children,
  className,
}: {
  title: ReactNode
  hint?: string
  actions?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={cn('rounded-lg border border-line bg-surface px-5 py-4', className)}>
      <header className="mb-3 flex items-start gap-2">
        <h3 className="text-sm leading-snug font-medium text-ink">{title}</h3>
        {hint && (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="mt-0.5 shrink-0 cursor-help text-faint hover:text-dim">
                <CircleHelp className="size-3.5" />
              </span>
            </TooltipTrigger>
            <TooltipContent side="top">{hint}</TooltipContent>
          </Tooltip>
        )}
        {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
      </header>
      {children}
    </section>
  )
}

/** A section heading — the section's eyebrow label over a hairline divider,
 *  then the big takeaway sentence. The divider is the visual separation
 *  between deck sections; the eyebrow is the section's name. */
export function SectionHead({
  children,
  id,
  eyebrow,
}: {
  children: ReactNode
  id: string
  eyebrow: string
}) {
  return (
    <div id={id} className="scroll-mt-32 border-t border-line pt-5">
      <p className="mb-1 font-mono text-[0.7rem] tracking-widest uppercase text-amber">{eyebrow}</p>
      <h2 className="display text-xl tracking-tight text-ink">{children}</h2>
    </div>
  )
}

/** Honest empty state — never a broken chart. */
export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-40 flex-col items-center justify-center gap-1.5 rounded-md border border-dashed border-line-strong px-6 text-center">
      <p className="text-sm text-dim">{children}</p>
    </div>
  )
}

/** Pulse placeholder while a round-trip is in flight. */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('animate-pulse rounded-md bg-surface-2', className ?? 'h-64')} />
}
