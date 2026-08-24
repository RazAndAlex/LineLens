import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors cursor-pointer disabled:pointer-events-none disabled:opacity-45 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 shrink-0 [&_svg]:shrink-0 focus-visible:outline-2 focus-visible:outline-amber focus-visible:outline-offset-2",
  {
    variants: {
      variant: {
        default:
          'bg-amber text-[#17110a] font-semibold hover:bg-[#ffb63d] active:bg-amber-deep shadow-[0_0_18px_rgba(245,165,36,0.22)]',
        outline: 'border border-line-strong bg-transparent text-ink hover:bg-surface-2 hover:border-dim',
        ghost: 'text-dim hover:text-ink hover:bg-surface-2',
        destructive: 'border border-bad/50 bg-bad/10 text-bad hover:bg-bad/20',
      },
      size: {
        default: 'h-9 px-4 py-2',
        sm: 'h-7 rounded-md px-2.5 text-xs',
        lg: 'h-11 rounded-md px-6 text-base',
        icon: 'size-9',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)

function Button({
  className,
  variant,
  size,
  ...props
}: React.ComponentProps<'button'> & VariantProps<typeof buttonVariants>) {
  return <button className={cn(buttonVariants({ variant, size, className }))} {...props} />
}

export { Button, buttonVariants }
