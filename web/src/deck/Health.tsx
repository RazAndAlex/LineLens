import type { AnalyzeResponse, MaintenanceDict } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Card, EmptyState, SectionHead } from '@/deck/SectionCard'
import { Chart, CHART } from '@/deck/Chart'
import { fmtDay, fmtNum, fmtPct, fmtSpan } from '@/deck/format'

const HONESTY: Record<string, string> = {
  too_few: 'Not enough dated history to trend Performance honestly.',
  zero_scatter:
    'Performance is too steady to forecast — the uncertainty band would collapse and read as a promise.',
  no_series: 'No dated Performance series — needs state, speeds, and a start timestamp.',
}

export function Health({ deck }: { deck: AnalyzeResponse }) {
  const { performance_forecast, performance_concern, performance_crossing, mtbf, maintenance } = deck
  const view = performance_forecast.view
  const floorPct = Math.round(performance_concern * 100)

  const takeaway = view
    ? performance_crossing
      ? `Performance band dips below the ${floorPct}% floor around ${fmtDay(performance_crossing)}`
      : `Performance holds above the ${floorPct}% floor for the next ${view.band_dates.length - 1} days`
    : 'Line health'

  return (
    <div className="flex scroll-mt-32 flex-col gap-4" data-section="health">
      <SectionHead id="health" eyebrow="Health">{takeaway}</SectionHead>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          title="Is the line slowing down?"
          hint={
            deck.degradation_caption ??
            'The daily Performance ratio (actual vs target speed), continued 7 days ahead inside an expected range. The dotted line is the concern floor.'
          }
          className="lg:col-span-2"
        >
          {!view || performance_forecast.reason !== 'ok' ? (
            <EmptyState>{HONESTY[performance_forecast.reason] ?? 'No Performance forecast.'}</EmptyState>
          ) : (
            <PerformanceChart deck={deck} />
          )}
        </Card>

        <Card
          title={mtbf ? `A failure about every ${fmtSpan(mtbf.median)}` : 'Time between failures'}
          hint="Median gap between Fault stops, with the middle-50% band — a range, never a countdown to the next failure."
        >
          {mtbf ? (
            <div className="flex h-40 flex-col justify-center gap-2">
              <p className="display text-4xl text-ink">{fmtSpan(mtbf.median)}</p>
              <p className="font-mono text-xs text-dim">
                typical gap · middle half falls {fmtSpan(mtbf.q1)} – {fmtSpan(mtbf.q3)}
              </p>
            </div>
          ) : (
            <EmptyState>
              Too few Fault events ({deck.fault_interval_count} gaps) for an honest band — the tile
              appears once at least 4 exist.
            </EmptyState>
          )}
        </Card>

        <MaintenanceCard maintenance={maintenance} />
      </div>
    </div>
  )
}

function PerformanceChart({ deck }: { deck: AnalyzeResponse }) {
  const view = deck.performance_forecast.view!
  const perf = deck.daily_performance!
  const floor = deck.performance_concern
  const bandLo = view.lower
  const bandWidth = view.upper.map((u, i) => +(u - bandLo[i]).toFixed(6))

  return (
    <Chart
      className="h-72"
      option={{
        ...CHART,
        tooltip: {
          ...CHART.tooltip,
          trigger: 'axis',
          valueFormatter: (v) => fmtPct(Number(v)),
        },
        legend: { ...CHART.legend, bottom: 0, data: ['performance / day', 'most likely path', 'expected range'] },
        grid: { ...CHART.grid, bottom: 48 },
        xAxis: { type: 'time', ...CHART.axis },
        yAxis: {
          type: 'value',
          max: 1,
          ...CHART.axis,
          axisLabel: { ...CHART.axis.axisLabel, formatter: (v: number) => fmtPct(v) },
        },
        series: [
          {
            name: 'performance / day',
            type: 'bar',
            data: perf.dates.map((d, i) => [d, perf.values[i]]),
            itemStyle: { color: '#3e4854' },
            barMaxWidth: 14,
          },
          {
            name: 'most likely path',
            type: 'line',
            data: view.line_dates.map((d, i) => [d, view.central[i]]),
            lineStyle: { color: '#f5a524', width: 2, type: 'dashed' },
            itemStyle: { color: '#f5a524' },
            symbol: 'none',
            z: 3,
            markLine: {
              silent: true,
              symbol: 'none',
              lineStyle: { color: '#e0533d', type: 'dotted', width: 1.5 },
              label: {
                formatter: `${Math.round(floor * 100)}% concern floor`,
                color: '#e0533d',
                fontFamily: 'JetBrains Mono, monospace',
                fontSize: 9.5,
              },
              data: [{ yAxis: floor }],
            },
          },
          {
            name: '_band_base',
            type: 'line',
            data: view.band_dates.map((d, i) => [d, bandLo[i]]),
            stack: 'perf-band',
            lineStyle: { opacity: 0 },
            symbol: 'none',
            silent: true,
            showInLegend: false,
          } as never,
          {
            name: 'expected range',
            type: 'line',
            data: view.band_dates.map((d, i) => [d, bandWidth[i]]),
            stack: 'perf-band',
            lineStyle: { opacity: 0 },
            itemStyle: { color: 'rgba(245,165,36,0.4)' },
            areaStyle: { color: 'rgba(245,165,36,0.13)' },
            symbol: 'none',
          },
        ],
      }}
    />
  )
}

// --- maintenance due window (mirrors server.logic._due_window_phrasing) ---------

function dueHeadline(m: MaintenanceDict): string {
  const due = m.due
  if (!due) return 'Service rhythm not learned yet'
  if (due.remaining_late <= 0) return 'Service due now'
  if (due.date_early && due.date_late) {
    if (due.date_early === due.date_late) return `${fmtDay(due.date_early)} — a single point so far`
    return `Next service ${fmtDay(due.date_early)} → ${fmtDay(due.date_late)}`
  }
  return `Next service in ${fmtNum(due.remaining_early)}–${fmtNum(due.remaining_late)} bottles`
}

function MaintenanceCard({ maintenance: m }: { maintenance: MaintenanceDict | null }) {
  if (!m)
    return (
      <Card title="Service counter">
        <EmptyState>
          Maintenance needs a start timestamp and bottle counts mapped — the service counter is
          bottle arithmetic.
        </EmptyState>
      </Card>
    )

  return (
    <Card
      title={dueHeadline(m)}
      hint="Bottles are the odometer: a powered-down line accrues no wear. The window comes from the line's own service rhythm — always a window, never a bare date."
      actions={
        m.due?.adjusted_earlier ? <Badge variant="warn">pulled earlier</Badge> : undefined
      }
    >
      <div className="flex flex-col gap-3">
        <div className="flex items-baseline gap-6">
          <div>
            <p className="display text-3xl text-ink">{fmtNum(m.bottles_since_service)}</p>
            <p className="font-mono text-[0.68rem] text-faint">bottles since last service</p>
          </div>
          {m.interval && (
            <div>
              <p className="display text-xl text-dim">
                {fmtNum(m.interval.q1)}–{fmtNum(m.interval.q3)}
              </p>
              <p className="font-mono text-[0.68rem] text-faint">
                learned rhythm ({m.interval.n} gap{m.interval.n !== 1 ? 's' : ''}) · {m.n_service_events} services
              </p>
            </div>
          )}
        </div>
        {m.due && m.due.reasons.length > 0 && (
          <p className="text-xs text-warn">{m.due.reasons.join(' · ')}</p>
        )}
        {m.notes.map((n) => (
          <p key={n} className="text-xs leading-relaxed text-faint">
            {n}
          </p>
        ))}
      </div>
    </Card>
  )
}
