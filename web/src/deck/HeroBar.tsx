import { fmtPct, fmtPts } from '@/deck/format'
import type { OEEDict } from '@/api'

/**
 * Sticky hero: the OEE readout — 3–4× body size, display font, always visible.
 * Carries ONLY the OEE + its A·P·Q satellites; the what-if delta badge sits
 * inline the moment a lever moves (zero eye movement baseline → delta).
 */
export function HeroBar({
  oee,
  hypo,
}: {
  oee: OEEDict | null
  hypo: OEEDict | null
}) {
  return (
    <div className="sticky top-0 z-40 border-b border-line bg-bg/95 backdrop-blur-sm">
      <div className="mx-auto flex w-full max-w-7xl items-center gap-6 px-6 py-3">
        <div className="flex items-baseline gap-3">
          <span className="display text-5xl leading-none font-semibold tracking-tight text-ink">
            {oee ? fmtPct(oee.oee) : '—'}
          </span>
          <span className="eyebrow">OEE</span>
          {hypo && oee && (
            <span className="ml-1 inline-flex items-center gap-1.5 rounded-md border border-ok/50 bg-ok/10 px-2.5 py-1 font-mono text-sm font-medium text-ok animate-in fade-in-0">
              <span className="text-dim line-through decoration-bad/60 decoration-1">{fmtPct(oee.oee)}</span>
              → {fmtPct(hypo.oee)}
              <span className="font-semibold">({fmtPts(hypo.oee - oee.oee)})</span>
              <span className="ml-1 rounded bg-ok/20 px-1 text-[0.6rem] tracking-widest uppercase">what-if</span>
            </span>
          )}
        </div>

        {oee && (
          <div className="ml-auto flex items-center gap-2">
            <Satellite label="Availability" value={oee.availability} />
            <Satellite label="Performance" value={oee.performance} />
            <Satellite label="Quality" value={oee.quality} />
          </div>
        )}
      </div>
    </div>
  )
}

function Satellite({ label, value }: { label: string; value: number }) {
  return (
    <span className="inline-flex items-baseline gap-1.5 rounded-md border border-line bg-surface px-2.5 py-1">
      <span className="font-mono text-[0.68rem] text-faint">{label}</span>
      <span className="font-mono text-sm font-medium text-ink">{fmtPct(value)}</span>
    </span>
  )
}
