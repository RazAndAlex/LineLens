import { useMemo } from 'react'
import { CheckCircle2 } from 'lucide-react'
import type { AnalyzeResponse, FindingDict } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Card, SectionHead } from '@/deck/SectionCard'
import { Chart, CHART } from '@/deck/Chart'
import { fmtNum } from '@/deck/format'
import { cn } from '@/lib/utils'

const SEV_STYLE = {
  error: { badge: 'bad', label: 'Error', edge: 'border-bad/50' },
  warning: { badge: 'warn', label: 'Warning', edge: 'border-warn/40' },
  info: { badge: 'info', label: 'Info', edge: 'border-line' },
} as const

function takeaway(findings: FindingDict[]): string {
  if (findings.length === 0) return 'The data is clean — no problems detected'
  const errors = findings.filter((f) => f.severity === 'error').length
  const warnings = findings.filter((f) => f.severity === 'warning').length
  const parts = [
    `${findings.length} problem${findings.length !== 1 ? 's' : ''} hide${findings.length === 1 ? 's' : ''} in this file`,
  ]
  if (errors) parts.push(`${errors} ${errors === 1 ? 'is' : 'are'} ${errors === 1 ? 'an' : ''} error${errors !== 1 ? 's' : ''}`)
  else if (warnings) parts.push('none fatal')
  return parts.join(' — ')
}

export function Diagnosis({ deck }: { deck: AnalyzeResponse }) {
  const { findings, contrast_rows } = deck

  const contrast = useMemo(() => {
    if (contrast_rows.length === 0) return null
    const rows = contrast_rows.map((r) => ({
      counter: String(r.counter),
      naive: Number(r['naive sum'] ?? 0),
      honest: Number(r['honest total'] ?? 0),
    }))
    // the loudest overstatement drives the takeaway
    const worst = rows.reduce((a, b) => {
      const ra = a.honest > 0 ? a.naive / a.honest : 0
      const rb = b.honest > 0 ? b.naive / b.honest : 0
      return rb > ra ? b : a
    })
    return { rows, worst }
  }, [contrast_rows])

  const groups = (['error', 'warning', 'info'] as const)
    .map((sev) => ({ sev, items: findings.filter((f) => f.severity === sev) }))
    .filter((g) => g.items.length > 0)

  return (
    <div className="flex scroll-mt-32 flex-col gap-4" data-section="diagnosis">
      <SectionHead id="diagnosis" eyebrow="Diagnosis">{takeaway(findings)}</SectionHead>

      {findings.length === 0 ? (
        <div className="flex items-center gap-3 rounded-lg border border-ok/40 bg-ok/10 px-5 py-4">
          <CheckCircle2 className="size-5 text-ok" />
          <p className="text-sm text-ink">Every validation rule passed. The totals below can be trusted.</p>
        </div>
      ) : (
        <div className="flex items-center gap-2.5 rounded-lg border border-line bg-surface px-5 py-3.5">
          <span className="text-sm text-ink">
            {findings.length} finding{findings.length !== 1 ? 's' : ''}
          </span>
          {groups.map((g) => (
            <Badge key={g.sev} variant={SEV_STYLE[g.sev].badge as 'bad'}>
              {g.items.length} {SEV_STYLE[g.sev].label.toUpperCase()}
            </Badge>
          ))}
        </div>
      )}

      {contrast && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card
            title={
              contrast.worst.honest > 0 && contrast.worst.naive > contrast.worst.honest
                ? `A naive dashboard would overstate ${contrast.worst.counter} ${(contrast.worst.naive / contrast.worst.honest).toFixed(1)}×`
                : `Naive sum vs honest total, per counter`
            }
            hint="Summing a running-total (odometer) column double-counts every restart. The honest increase is last minus first, plus any resets. This is the chart to trust when a dashboard disagrees with reality."
          >
            <Chart
              className="h-56"
              option={{
                ...CHART,
                tooltip: { ...CHART.tooltip, trigger: 'axis', axisPointer: { type: 'shadow' } },
                legend: { ...CHART.legend, bottom: 0 },
                grid: { ...CHART.grid, left: 110, bottom: 40 },
                xAxis: { type: 'value', ...CHART.axis },
                yAxis: { type: 'category', data: contrast.rows.map((r) => r.counter), ...CHART.axis },
                series: [
                  {
                    name: 'naive sum',
                    type: 'bar',
                    data: contrast.rows.map((r) => r.naive),
                    itemStyle: { color: '#e0533d', borderRadius: [0, 3, 3, 0] },
                    barGap: '25%',
                  },
                  {
                    name: 'honest total',
                    type: 'bar',
                    data: contrast.rows.map((r) => r.honest),
                    itemStyle: { color: '#2fa97c', borderRadius: [0, 3, 3, 0] },
                  },
                ],
              }}
            />
          </Card>
        </div>
      )}

      {groups.map((g) => (
        <div key={g.sev} className="flex flex-col gap-2.5">
          <p className="eyebrow">{SEV_STYLE[g.sev].label}s · {g.items.length}</p>
          <div className="grid gap-2.5 lg:grid-cols-2">
            {g.items.map((f, i) => (
              <FindingCard key={`${f.rule_id}-${i}`} finding={f} />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function FindingCard({ finding: f }: { finding: FindingDict }) {
  const style = SEV_STYLE[f.severity]
  const details: [string, string][] = []
  if (f.observed_value !== null) details.push(['observed', fmtNum(f.observed_value)])
  if (f.calculated_value !== null) details.push(['calculated', fmtNum(f.calculated_value)])
  if (f.maximum_possible_value !== null) details.push(['maximum possible', fmtNum(f.maximum_possible_value)])
  if (f.suspected_cause) details.push(['suspected cause', f.suspected_cause])
  if (f.signal) details.push(['signal', f.signal])
  for (const [k, v] of Object.entries(f.evidence)) details.push([k, String(v)])

  return (
    <details className={cn('group rounded-lg border bg-surface px-4 py-3', style.edge)}>
      <summary className="flex cursor-pointer list-none items-center gap-2.5 [&::-webkit-details-marker]:hidden">
        <Badge variant={style.badge as 'bad'}>{style.label}</Badge>
        <span className="flex-1 text-sm font-medium text-ink">{f.title}</span>
        {f.affected_rows.length > 0 && (
          <span className="font-mono text-[0.66rem] text-faint">{f.affected_rows.length} rows</span>
        )}
      </summary>
      {f.description && <p className="mt-2 text-xs leading-relaxed text-dim">{f.description}</p>}
      {details.length > 0 && (
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 border-t border-line pt-2 font-mono text-[0.7rem]">
          {details.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-faint">{k}</dt>
              <dd className="truncate text-dim">{v}</dd>
            </div>
          ))}
        </dl>
      )}
    </details>
  )
}
