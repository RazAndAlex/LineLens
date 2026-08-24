import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded border px-1.5 py-0.5 font-mono text-[0.66rem] font-medium tracking-wide',
  {
    variants: {
      variant: {
        default: 'border-line bg-surface-2 text-dim',
        amber: 'border-amber/40 bg-amber-ghost text-amber',
        ok: 'border-ok/40 bg-ok/10 text-ok',
        bad: 'border-bad/40 bg-bad/10 text-bad',
        warn: 'border-warn/40 bg-warn/10 text-warn',
        info: 'border-info/40 bg-info/10 text-info',
      },
    },
    defaultVariants: { variant: 'default' },
  },
)

function Badge({
  className,
  variant,
  ...props
}: React.ComponentProps<'span'> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant, className }))} {...props} />
}

export { Badge, badgeVariants }
