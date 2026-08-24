import { useEffect, useMemo, useRef, useState } from 'react'
import { RotateCcw } from 'lucide-react'
import {
  ApiError,
  scope as apiScope,
  type AnalyzeResponse,
  type MappingBody,
  type RecordRow,
  type ReportDict,
  type StateInterval,
} from '@/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, EmptyState, SectionHead } from '@/deck/SectionCard'
import { Chart, CHART } from '@/deck/Chart'
import { fmtNum, fmtPct, fmtSeconds } from '@/deck/format'
import { toastError } from '@/deck/toast'

// Machine states keep the semantic colors — this is where green/red live.
const STATE_COLOR: Record<string, string> = {
  Running: '#2fa97c',
  Stopped: '#e0533d',
  Idle: '#5a6572',
}
const stateColor = (s: string) => STATE_COLOR[s] ?? '#8b96a3'

// Downtime-by-cause categorical palette (the old app's validated colorway —
// distinguishable at small bar sizes); planned causes override to muted grey.
const CAUSE_COLORS = ['#f5a524', '#e0533d', '#5aa9ff', '#2fa97c', '#9085e9', '#c98500', '#d55181', '#199e70']
const PLANNED_COLOR = '#5a6572'

// app.py _TIMELINE_MAX_GANTT_DAYS: wider windows render daily composition.
const GANTT_MAX_DAYS = 14
const DAY_MS = 86400_000

const zoomStyle = {
  height: 16,
  bottom: 4,
  borderColor: 'rgba(255,255,255,0.14)',
  backgroundColor: 'rgba(255,255,255,0.03)',
  fillerColor: 'rgba(245,165,36,0.12)',
  handleStyle: { color: '#f5a524' },
  textStyle: { color: '#5a6572', fontSize: 9, fontFamily: 'JetBrains Mono, monospace' },
} as const

/** The Now-charts zoom: inside drag/scroll + a slider, like the forecast. */
const dataZoom = [
  { type: 'inside', xAxisIndex: 0 },
  { type: 'slider', xAxisIndex: 0, ...zoomStyle },
] as never[]

export function Now({
  deck,
  mapping,
  datasetId,
}: {
  deck: AnalyzeResponse
  mapping: MappingBody
  datasetId: string
}) {
  const span = deck.date_span
  const [lo, setLo] = useState<string | null>(span?.[0] ?? null)
  const [hi, setHi] = useState<string | null>(span?.[1] ?? null)
  const [scoped, setScoped] = useState<ReportDict>(deck.report)
  const [narrowed, setNarrowed] = useState(false)
  const [busy, setBusy] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // The date window scopes the takeaway numbers and totals tables via /scope.
  // The CHARTS show the full daily series and zoom locally (dataZoom) — the
  // two never fight each other.
  useEffect(() => {
    if (!span || !lo || !hi || lo > hi) return
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(async () => {
      setBusy(true)
      try {
        const r = await apiScope(datasetId, mapping, lo, hi)
        setScoped(r.report)
        setNarrowed(r.narrowed)
      } catch (e) {
        toastError(e instanceof ApiError ? e.message : 'Could not scope the window.')
      } finally {
        setBusy(false)
      }
    }, 350)
    return () => {
      if (timer.current) clearTimeout(timer.current)
    }
  }, [lo, hi, span, datasetId, mapping])

  const takeaway = useMemo(() => runningTakeaway(scoped), [scoped])

  return (
    <div className="flex scroll-mt-32 flex-col gap-4" data-section="now">
      <SectionHead id="now" eyebrow="Now">{takeaway}</SectionHead>

      {/* sticky control bar: the window picker scopes numbers, not charts */}
      {span && (
        <div className="sticky top-[104px] z-20 flex flex-wrap items-center gap-3 rounded-lg border border-line bg-bg/95 px-4 py-2.5 backdrop-blur-sm">
          <span className="eyebrow">Window</span>
          <input
            type="date"
            value={lo ?? ''}
            min={span[0]}
            max={span[1]}
            onChange={(e) => setLo(e.target.value || null)}
            className="h-8 rounded-md border border-line bg-surface-2 px-2 font-mono text-xs text-ink [color-scheme:dark] focus:outline-amber"
            aria-label="Window start"
          />
          <span className="text-faint">→</span>
          <input
            type="date"
            value={hi ?? ''}
            min={span[0]}
            max={span[1]}
            onChange={(e) => setHi(e.target.value || null)}
            className="h-8 rounded-md border border-line bg-surface-2 px-2 font-mono text-xs text-ink [color-scheme:dark] focus:outline-amber"
            aria-label="Window end"
          />
          {narrowed && (
            <>
              <Badge variant="amber">scoped</Badge>
              <Button variant="ghost" size="sm" onClick={() => { setLo(span[0]); setHi(span[1]) }}>
                <RotateCcw className="size-3.5" /> full range
              </Button>
            </>
          )}
          {busy && <span className="ml-auto font-mono text-[0.66rem] text-faint">scoping…</span>}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          title="What the line did, in order"
          hint="The daily Running/Stopped/Idle split (an interval strip for very short files). Green is running, red is stopped, grey is idle. Drag or scroll to zoom; the slider below moves the window."
          className="lg:col-span-2"
        >
          <StateTimeline intervals={deck.state_intervals} />
        </Card>

        <Card
          title={busy ? 'Production' : productionTakeaway(scoped)}
          hint="Good bottles (amber) and rejects (red) per day, from the same totals the tables show. Reject days are a thin red cap — the value is on hover."
        >
          <ProductionChart report={deck.report} />
        </Card>

        <Card
          title={busy ? 'Downtime by cause' : downtimeTakeaway(scoped)}
          hint="Stopped seconds per day, stacked by cause. Planned stops (changeovers, service) are grey — scheduled, not a loss. Drag or scroll to zoom."
        >
          <DowntimeChart report={deck.report} planned={deck.planned_causes} />
        </Card>
      </div>

      <TotalsTables report={scoped} />
    </div>
  )
}

// --- derivations ------------------------------------------------------------

function runningTakeaway(report: ReportDict): string {
  const rows = report.state_totals.filter((r) => r.scope === 'overall')
  const total = rows.reduce((a, r) => a + Number(r.seconds ?? 0), 0)
  const running = rows.find((r) => r.state === 'Running')
  if (!running || total <= 0) return 'Where the time went'
  const share = Number(running.seconds) / total
  const stopped = rows.find((r) => r.state === 'Stopped')
  const stoppedTxt = stopped ? ` — ${fmtSeconds(Number(stopped.seconds))} stopped` : ''
  return `Running ${fmtPct(share)} of the window${stoppedTxt}`
}

function productionTakeaway(report: ReportDict): string {
  const rows = report.production_totals.filter((r) => r.scope === 'overall')
  const good = rows.find((r) => r.metric === 'good')
  const reject = rows.find((r) => r.metric === 'reject')
  if (!good) return 'Production'
  const g = Number(good.value)
  const rj = reject ? Number(reject.value) : 0
  const q = g + rj > 0 ? g / (g + rj) : 1
  return `${fmtNum(g)} good bottles in the window — ${fmtPct(q)} first-pass`
}

function downtimeTakeaway(report: ReportDict): string {
  const rows = report.downtime_by_reason.filter((r) => r.scope === 'overall')
  if (rows.length === 0) return 'Downtime by cause'
  const top = rows.reduce((a, b) => (Number(b.seconds) > Number(a.seconds) ? b : a))
  return `${top.reason} leads the stops — ${fmtSeconds(Number(top.seconds))}`
}

/** Day-scope rows when the dataset has a time axis, else the overall rows. */
function dailyOrOverall(frame: RecordRow[]): RecordRow[] {
  const day = frame.filter((r) => r.scope === 'day')
  return day.length > 0 ? day : frame.filter((r) => r.scope === 'overall')
}

const labelOf = (r: RecordRow) => (r.scope_value === null ? 'overall' : String(r.scope_value))

// --- charts -------------------------------------------------------------------

function StateTimeline({ intervals }: { intervals: StateInterval[] }) {
  const prepared = useMemo(() => {
    const ivs = intervals
      .filter((i) => i.start && i.end)
      .map((i) => ({ ...i, s: Date.parse(i.start!), e: Date.parse(i.end!), state: String(i.state) }))
      .filter((i) => !Number.isNaN(i.s) && !Number.isNaN(i.e) && i.e >= i.s)
      .sort((a, b) => a.s - b.s)
    if (ivs.length === 0) return { ivs, mode: 'empty' as const }
    const days = (ivs[ivs.length - 1].e - ivs[0].s) / DAY_MS
    return { ivs, mode: days > GANTT_MAX_DAYS ? ('composition' as const) : ('gantt' as const) }
  }, [intervals])

  if (prepared.mode === 'empty')
    return <EmptyState>No state timeline — needs a start timestamp, a state column, and an end or duration.</EmptyState>

  if (prepared.mode === 'gantt') return <Gantt ivs={prepared.ivs} />
  return <Composition ivs={prepared.ivs} />
}

type Iv = StateInterval & { s: number; e: number; state: string }

function Gantt({ ivs }: { ivs: Iv[] }) {
  const lanes = [...new Set(ivs.map((i) => i.machine ?? 'State'))]
  return (
    <Chart
      className="h-56"
      option={{
        ...CHART,
        tooltip: {
          ...CHART.tooltip,
          formatter: (p) => {
            const v = (p as { value: (string | number)[] }).value
            return `${v[3]} · ${fmtSeconds(Number(v[2]) - Number(v[1]))}<br/>${new Date(Number(v[1])).toLocaleString('en-US')}`
          },
        },
        grid: { ...CHART.grid, left: 90 },
        xAxis: { type: 'time', ...CHART.axis },
        yAxis: { type: 'category', data: lanes, ...CHART.axis },
        series: [
          {
            type: 'custom',
            renderItem: (_params, api) => {
              const lane = api.value(0)
              const start = api.coord([api.value(1), lane])
              const end = api.coord([api.value(2), lane])
              const sizeFn = api.size as (v: number[]) => number[]
              const laneH = sizeFn([0, 1])[1] ?? 20
              const height = laneH * 0.62
              return {
                type: 'rect',
                shape: {
                  x: start[0],
                  y: start[1] - height / 2,
                  width: Math.max(end[0] - start[0], 1.5),
                  height,
                  r: 1.5,
                },
                style: api.style(),
              }
            },
            encode: { x: [1, 2], y: 0 },
            data: ivs.map((i) => ({
              value: [lanes.indexOf(i.machine ?? 'State'), i.s, i.e, i.state],
              itemStyle: { color: stateColor(i.state) },
            })),
          },
        ],
      }}
    />
  )
}

function Composition({ ivs }: { ivs: Iv[] }) {
  const { days, states, grid } = useMemo(() => {
    const perDay = new Map<string, Map<string, number>>()
    for (const i of ivs) {
      const day = new Date(i.s).toISOString().slice(0, 10)
      const m = perDay.get(day) ?? new Map<string, number>()
      m.set(i.state, (m.get(i.state) ?? 0) + (i.e - i.s) / 1000)
      perDay.set(day, m)
    }
    const days = [...perDay.keys()].sort()
    const states = [...new Set(ivs.map((i) => i.state))]
    const grid = states.map((s) => days.map((d) => Math.round(perDay.get(d)?.get(s) ?? 0)))
    return { days, states, grid }
  }, [ivs])

  return (
    <Chart
      className="h-64"
      option={{
        ...CHART,
        tooltip: { ...CHART.tooltip, trigger: 'axis', valueFormatter: (v) => fmtSeconds(Number(v)) },
        legend: { ...CHART.legend, bottom: 30 },
        grid: { ...CHART.grid, bottom: 72 },
        dataZoom,
        xAxis: { type: 'category', data: days, ...CHART.axis },
        yAxis: { type: 'value', ...CHART.axis, axisLabel: { ...CHART.axis.axisLabel, formatter: (v: number) => fmtSeconds(v) } },
        series: states.map((s, i) => ({
          name: s,
          type: 'bar' as const,
          stack: 'state',
          data: grid[i],
          itemStyle: { color: stateColor(s) },
          barMaxWidth: 26,
        })),
      }}
    />
  )
}

function ProductionChart({ report }: { report: ReportDict }) {
  const rows = dailyOrOverall(report.production_totals)
  if (rows.length === 0) return <EmptyState>No production totals for this dataset.</EmptyState>
  const labels = [...new Set(rows.map(labelOf))]
  const val = (metric: string, label: string) =>
    Number(rows.find((r) => r.metric === metric && labelOf(r) === label)?.value ?? 0)
  return (
    <Chart
      className="h-72"
      option={{
        ...CHART,
        tooltip: { ...CHART.tooltip, trigger: 'axis', valueFormatter: (v) => fmtNum(Number(v)) },
        legend: { ...CHART.legend, bottom: 30 },
        grid: { ...CHART.grid, bottom: 72 },
        dataZoom,
        xAxis: { type: 'category', data: labels, ...CHART.axis },
        yAxis: { type: 'value', ...CHART.axis },
        series: [
          { name: 'good', type: 'bar', stack: 'prod', data: labels.map((l) => val('good', l)), itemStyle: { color: '#f5a524' }, barMaxWidth: 26 },
          {
            name: 'reject',
            type: 'bar',
            stack: 'prod',
            data: labels.map((l) => val('reject', l)),
            itemStyle: { color: '#e0533d' },
            barMaxWidth: 26,
            // rejects run ~0.4% of good — a 4px floor keeps the red cap visible
            // without touching the data (the tooltip carries the true value).
            barMinHeight: 4,
          },
        ],
      }}
    />
  )
}

function DowntimeChart({ report, planned }: { report: ReportDict; planned: string[] }) {
  const prepared = useMemo(() => {
    const rows = dailyOrOverall(report.downtime_by_reason)
    const labels = [...new Set(rows.map(labelOf))]
    const causes = [...new Set(rows.map((r) => String(r.reason)))].sort()
    const plannedSet = new Set(planned)
    const unplanned = causes.filter((c) => !plannedSet.has(c))
    const colorOf = (c: string) =>
      plannedSet.has(c) ? PLANNED_COLOR : CAUSE_COLORS[unplanned.indexOf(c) % CAUSE_COLORS.length]
    const val = (cause: string, label: string) =>
      rows
        .filter((r) => String(r.reason) === cause && labelOf(r) === label)
        .reduce((a, r) => a + Number(r.seconds ?? 0), 0)
    return { labels, causes, colorOf, val, empty: rows.length === 0 }
  }, [report, planned])

  if (prepared.empty) return <EmptyState>No stopped time in this dataset.</EmptyState>
  const { labels, causes, colorOf, val } = prepared
  return (
    <Chart
      className="h-72"
      option={{
        ...CHART,
        tooltip: { ...CHART.tooltip, trigger: 'axis', valueFormatter: (v) => fmtSeconds(Number(v)) },
        legend: { ...CHART.legend, bottom: 30, type: 'scroll' },
        grid: { ...CHART.grid, bottom: 72 },
        dataZoom,
        xAxis: { type: 'category', data: labels, ...CHART.axis },
        yAxis: { type: 'value', ...CHART.axis, axisLabel: { ...CHART.axis.axisLabel, formatter: (v: number) => fmtSeconds(v) } },
        series: causes.map((c) => ({
          name: c,
          type: 'bar' as const,
          stack: 'down',
          data: labels.map((l) => val(c, l)),
          itemStyle: { color: colorOf(c) },
          barMaxWidth: 26,
        })),
      }}
    />
  )
}

// --- compact totals tables ----------------------------------------------------

function TotalsTables({ report }: { report: ReportDict }) {
  const [open, setOpen] = useState(false)
  const tables: { title: string; rows: RecordRow[]; cols: string[] }[] = [
    { title: 'State totals', rows: report.state_totals, cols: ['scope', 'scope_value', 'state', 'seconds'] },
    { title: 'Production totals', rows: report.production_totals, cols: ['scope', 'scope_value', 'metric', 'value'] },
    { title: 'Downtime by reason', rows: report.downtime_by_reason, cols: ['scope', 'scope_value', 'reason', 'seconds'] },
  ]
  return (
    <details open={open} onToggle={(e) => setOpen(e.currentTarget.open)} className="rounded-lg border border-line bg-surface">
      <summary className="cursor-pointer list-none px-4 py-3 text-xs text-dim [&::-webkit-details-marker]:hidden">
        The same numbers as tables {open ? '▾' : '▸'}
      </summary>
      {open && (
        <div className="grid gap-4 border-t border-line px-4 py-4 lg:grid-cols-3">
          {tables.map((t) => (
            <div key={t.title}>
              <p className="eyebrow mb-2">{t.title}</p>
              <div className="max-h-56 overflow-auto">
                <table className="w-full font-mono text-[0.68rem]">
                  <tbody>
                    {t.rows.map((r, i) => (
                      <tr key={i} className="odd:bg-surface-2/40">
                        {t.cols.map((c) => (
                          <td key={c} className="px-2 py-1 text-dim">
                            {c === 'scope_value'
                              ? r[c] === null
                                ? 'overall'
                                : String(r[c])
                              : typeof r[c] === 'number'
                                ? fmtNum(r[c] as number)
                                : String(r[c] ?? '')}
                          </td>
                        ))}
                      </tr>
                    ))}
                    {t.rows.length === 0 && (
                      <tr>
                        <td className="px-2 py-1 text-faint">no rows</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}
    </details>
  )
}
