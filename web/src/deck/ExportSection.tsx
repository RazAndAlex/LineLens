import { Download, FileJson, FileSpreadsheet, FileText } from 'lucide-react'
import { exportUrl, type AnalyzeResponse } from '@/api'
import { buttonVariants } from '@/components/ui/button'
import { Card, SectionHead } from '@/deck/SectionCard'

const EXPORTS = [
  {
    kind: 'cleaned.csv' as const,
    icon: FileSpreadsheet,
    title: 'Cleaned CSV',
    body: 'The parsed dataset — timestamps typed, numerics coerced — ready for Power BI or Excel.',
  },
  {
    kind: 'findings.json' as const,
    icon: FileJson,
    title: 'Findings JSON',
    body: 'Every diagnostic as a versioned, machine-readable blob for downstream tooling.',
  },
  {
    kind: 'findings.csv' as const,
    icon: FileText,
    title: 'Findings CSV',
    body: 'One row per finding — the spreadsheet-friendly version of the diagnosis.',
  },
]

export function ExportSection({ deck, datasetId }: { deck: AnalyzeResponse; datasetId: string }) {
  return (
    <div className="flex scroll-mt-32 flex-col gap-4" data-section="export">
      <SectionHead id="export" eyebrow="Export">Take the numbers with you</SectionHead>
      <div className="grid gap-4 lg:grid-cols-3">
        {EXPORTS.map((e) => (
          <Card key={e.kind} title={e.title}>
            <div className="flex h-28 flex-col justify-between gap-3">
              <p className="text-xs leading-relaxed text-dim">{e.body}</p>
              <a
                href={exportUrl(datasetId, e.kind, deck.fingerprint)}
                download
                className={buttonVariants({ variant: 'outline', size: 'sm', className: 'w-fit' })}
              >
                <Download className="size-3.5" />
                {e.kind}
              </a>
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}
