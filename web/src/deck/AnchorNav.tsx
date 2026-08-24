import { cn } from '@/lib/utils'

export const SECTIONS = [
  { id: 'diagnosis', label: 'Diagnosis' },
  { id: 'now', label: 'Now' },
  { id: 'loss', label: 'Loss' },
  { id: 'future', label: 'Future' },
  { id: 'health', label: 'Health' },
  { id: 'export', label: 'Export' },
] as const

/** Sticky section links with active-section highlighting (the scroll-spy
 *  itself lives in Deck.tsx via IntersectionObserver). */
export function AnchorNav({ active }: { active: string }) {
  return (
    <nav className="sticky top-[65px] z-30 border-b border-line bg-bg/95 backdrop-blur-sm">
      <div className="mx-auto flex w-full max-w-7xl items-center gap-1 px-6">
        {SECTIONS.map((s) => (
          <a
            key={s.id}
            href={`#${s.id}`}
            className={cn(
              'border-b-2 px-3 py-2.5 font-mono text-[0.7rem] tracking-widest uppercase transition-colors',
              active === s.id
                ? 'border-amber text-amber'
                : 'border-transparent text-faint hover:text-dim',
            )}
          >
            {s.label}
          </a>
        ))}
      </div>
    </nav>
  )
}
