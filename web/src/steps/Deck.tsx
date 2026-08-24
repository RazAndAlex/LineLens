import { useEffect, useState } from 'react'
import type { AnalyzeResponse, MappingBody, OEEDict, UploadResponse } from '@/api'
import { HeroBar } from '@/deck/HeroBar'
import { AnchorNav, SECTIONS } from '@/deck/AnchorNav'
import { Diagnosis } from '@/deck/Diagnosis'
import { Now } from '@/deck/Now'
import { Loss } from '@/deck/Loss'
import { Future } from '@/deck/Future'
import { Health } from '@/deck/Health'
import { ExportSection } from '@/deck/ExportSection'
import { ToastHost } from '@/deck/toast'

/**
 * The command deck: sticky OEE hero + scroll-spy anchor nav over six sections.
 * The hero's what-if badge is fed by the Future section's levers via onHypo.
 */
export function Deck({
  upload,
  mapping,
  deck,
}: {
  upload: UploadResponse
  mapping: MappingBody
  deck: AnalyzeResponse
  onRemap?: () => void
}) {
  const [hypo, setHypo] = useState<OEEDict | null>(null)
  const [active, setActive] = useState<string>('diagnosis')

  // Scroll-spy: the section nearest the top (below the sticky bars) is active.
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const hit = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0]
        if (hit) setActive(hit.target.getAttribute('data-section') ?? 'diagnosis')
      },
      { rootMargin: '-20% 0px -65% 0px' },
    )
    for (const s of SECTIONS) {
      const el = document.querySelector(`[data-section="${s.id}"]`)
      if (el) observer.observe(el)
    }
    return () => observer.disconnect()
  }, [])

  return (
    <div className="flex-1">
      <HeroBar oee={deck.oee} hypo={hypo} />
      <AnchorNav active={active} />

      <div className="mx-auto flex w-full max-w-7xl flex-col gap-10 px-6 py-8">
        <Diagnosis deck={deck} />
        <Now deck={deck} mapping={mapping} datasetId={upload.dataset_id} />
        <Loss deck={deck} />
        <Future deck={deck} mapping={mapping} datasetId={upload.dataset_id} onHypo={setHypo} />
        <Health deck={deck} />
        <ExportSection deck={deck} datasetId={upload.dataset_id} />
      </div>

      <ToastHost />
    </div>
  )
}
