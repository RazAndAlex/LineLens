import { useEffect, useMemo, useRef, useState } from 'react'
import { RotateCcw } from 'lucide-react'
import {
  ApiError,
  whatif as apiWhatif,
  type AnalyzeResponse,
  type MappingBody,
  type OEEDict,
  type WhatIfResponse,
} from '@/api'
import { Button } from '@/components/ui/button'
import { Card, EmptyState, SectionHead, Skeleton } from '@/deck/SectionCard'
import { Chart, CHART } from '@/deck/Chart'
import { fmtDay, fmtNum, fmtPct } from '@/deck/format'
import { toastError } from '@/deck/toast'
import { cn } from '@/lib/utils'

// server.logic._WHATIF_TOP_N — the Pareto's top causes become levers.
const TOP_N = 5
// The future chart opens future-majority: ~7 observed days + the 14-day
// horizon (1/3 past, 2/3 future). The slider below zooms out to full history.
const DEFAULT_PAST_DAYS = 7

const HONESTY: Record<string, { title: string; body: string }> = {
  too_few: {
    title: 'Not enough history for an honest forecast',
    body: 'A trend needs at least 7 daily totals. The chart declines rather than invent a trajectory.',
  },
  zero_scatter: {
    title: 'Output is too steady to forecast honestly',
    body: 'Every day lands on a perfect line, so the uncertainty band would collapse to zero and read as a promise. No forecast is drawn.',
  },
  no_series: {
    title: 'No dated daily output to forecast',
    body: 'Map a start timestamp and production counts to see the future line.',
  },
}

export function Future({
  deck,
  mapping,
  datasetId,
  onHypo,
}: {
  deck: AnalyzeResponse
  mapping: MappingBody
  datasetId: string
  onHypo: (hypo: OEEDict | null) => void
}) {
  const { forecast, daily_good } = deck
  const view = forecast.view
  const horizon = view ? view.band_dates.length - 1 : 0

  // The what-if state lives here so the forecast chart (baseline vs what-if
  // path) and the levers/waterfall read the same result.
  const [reductions, setReductions] = useState<Record<string, number>>({})
  const [result, setResult] = useState<WhatIfResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const active = Object.values(reductions).some((r) => r > 0)

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current)
    if (!active) {
      setResult(null)
      onHypo(null)
      return
    }
    timer.current = setTimeout(async () => {
      setBusy(true)
      try {
        const r = await apiWhatif(datasetId, mapping, reductions)
        setResult(r)
        onHypo(r.hypo)
      } catch (e) {
        toastError(e instanceof ApiError ? e.message : 'The what-if recompute failed.')
      } finally {
        setBusy(false)
      }
    }, 300)
    return () => {
      if (timer.current) clearTimeout(timer.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reductions, active, datasetId, mapping])

  const reset = () => {
    setReductions({})
    setResult(null)
    onHypo(null)
  }

  const takeaway = useMemo(() => {
    if (!view) return `The next ${horizon} days`
    const last = view.central[view.central.length - 1]
    const lastDate = view.line_dates[view.line_dates.length - 1]
    return `Most likely path: ${fmtNum(last)} bottles/day by ${fmtDay(lastDate)}`
  }, [view, horizon])

  const showForecast = forecast.reason === 'ok' && view && daily_good

  return (
    <div className="flex scroll-mt-32 flex-col gap-4" data-section="future">
      <SectionHead id="future" eyebrow="Future Line">{takeaway}</SectionHead>

      <div className="grid items-start gap-4 lg:grid-cols-[1fr_340px]">
        {/* left: forecast + waterfall (scrolls) */}
        <div className="flex flex-col gap-4">
          {!showForecast ? (
            <Card title={HONESTY[forecast.reason]?.title ?? 'No forecast'}>
              <EmptyState>{HONESTY[forecast.reason]?.body ?? 'No forecast available.'}</EmptyState>
            </Card>
          ) : (
            <ForecastCard deck={deck} lift={result?.forecast_lift ?? null} />
          )}

          <Card
            title="Where the recovered bottles come from"
            hint="Each bar is one lever's contribution; they sum exactly to the recovered total — the bridge always closes."
          >
            {busy ? (
              <Skeleton className="h-64" />
            ) : !active || !result || result.lever_deltas.length === 0 ? (
              <EmptyState>Move a lever to see the breakdown.</EmptyState>
            ) : (
              <Waterfall result={result} />
            )}
          </Card>
        </div>

        {/* right: the levers — sticky, so they follow while scrolling */}
        <div className="lg:sticky lg:top-[120px]">
          <Levers
            deck={deck}
            reductions={reductions}
            setReductions={setReductions}
            active={active}
            result={result}
            onReset={reset}
          />
        </div>
      </div>
    </div>
  )
}

// --- the banded forecast --------------------------------------------------------

function ForecastCard({
  deck,
  lift,
}: {
  deck: AnalyzeResponse
  lift: { dates: string[]; values: number[] } | null
}) {
  const view = deck.forecast.view!
  const good = deck.daily_good!
  const technique = view.technique
  const horizon = view.band_dates.length - 1
  // Band honesty phrasing: the learned band is calibrated to 80% coverage
  // (linelens/forecast_ml _DEFAULT_COVERAGE); the deterministic band is ±1σ.
  const bandPhrase =
    technique === 'gradient-boosted'
      ? '8 out of 10 days land inside the expected range'
      : 'Roughly 7 in 10 days land inside the expected range'

  const n = good.dates.length
  const windowStart = good.dates[Math.max(0, n - DEFAULT_PAST_DAYS)]
  const bandLo = view.lower
  const bandWidth = view.upper.map((u, i) => +(u - bandLo[i]).toFixed(6))
  // Default the window to ~1/3 past, 2/3 future (percentages of the axis span —
  // startValue strings on a time axis proved unreliable).
  const axisMin = Date.parse(good.dates[0])
  const axisMax = Date.parse(view.band_dates[view.band_dates.length - 1])
  const zoomStart = Math.max(0, ((Date.parse(windowStart) - axisMin) / (axisMax - axisMin)) * 100)

  const legendItems = ['good bottles / day', 'most likely path', 'expected range']
  if (lift) legendItems.push('what-if path')

  return (
    <Card
      title={`Daily output, continued ${horizon} days ahead`}
      hint={`The line is the ${technique === 'gradient-boosted' ? 'learned' : 'trend'} forecast's central estimate; the band is where reality is expected to land. It widens because the far future is less certain. Methodology: ${technique === 'gradient-boosted' ? 'gradient-boosted median with a conformal-calibrated band (80% coverage).' : 'least-squares trend with a ±1σ band.'}`}
      actions={
        <span className="hidden max-w-56 text-right text-[0.68rem] leading-snug text-faint sm:block">
          {bandPhrase} — it widens because the far future is less certain
        </span>
      }
    >
      <Chart
        className="h-80"
        option={{
          ...CHART,
          tooltip: {
            ...CHART.tooltip,
            trigger: 'axis',
            formatter: (params) => {
              const ps = params as unknown as { seriesName: string; value: [string, number]; dataIndex: number }[]
              const day = ps[0] ? fmtDay(String(ps[0].value[0])) : ''
              const lines: string[] = [`<b>${day}</b>`]
              for (const p of ps) {
                if (p.seriesName === 'good bottles / day') lines.push(`good: ${fmtNum(p.value[1])}`)
                if (p.seriesName === 'most likely path') lines.push(`path: ${fmtNum(p.value[1])}`)
                if (p.seriesName === 'what-if path') lines.push(`what-if: ${fmtNum(p.value[1])}`)
                if (p.seriesName === 'expected range') {
                  const lo = bandLo[p.dataIndex]
                  const hi = lo + p.value[1]
                  lines.push(`range: ${fmtNum(lo)} – ${fmtNum(hi)}`)
                }
              }
              return lines.join('<br/>')
            },
          },
          legend: { ...CHART.legend, bottom: 34, data: legendItems },
          grid: { ...CHART.grid, bottom: 96 },
          xAxis: { type: 'time', ...CHART.axis },
          yAxis: { type: 'value', ...CHART.axis, axisLabel: { ...CHART.axis.axisLabel, formatter: (v: number) => fmtNum(v) } },
          dataZoom: [
            { type: 'inside', xAxisIndex: 0, start: zoomStart, end: 100 },
            {
              type: 'slider',
              xAxisIndex: 0,
              start: zoomStart,
              end: 100,
              height: 18,
              bottom: 8,
              borderColor: 'rgba(255,255,255,0.14)',
              backgroundColor: 'rgba(255,255,255,0.03)',
              fillerColor: 'rgba(245,165,36,0.12)',
              handleStyle: { color: '#f5a524' },
              textStyle: { color: '#5a6572', fontSize: 9, fontFamily: 'JetBrains Mono, monospace' },
            },
          ],
          series: [
            {
              name: 'good bottles / day',
              type: 'bar',
              data: good.dates.map((d, i) => [d, good.values[i]]),
              itemStyle: { color: '#3e4854' },
              barMaxWidth: 18,
            },
            {
              name: 'most likely path',
              type: 'line',
              data: view.line_dates.map((d, i) => [d, view.central[i]]),
              lineStyle: { color: '#f5a524', width: 2, type: 'dashed' },
              itemStyle: { color: '#f5a524' },
              symbol: 'none',
              z: 3,
            },
            {
              // invisible base of the band (stack trick for a filled range)
              name: '_band_base',
              type: 'line',
              data: view.band_dates.map((d, i) => [d, bandLo[i]]),
              stack: 'expected',
              lineStyle: { opacity: 0 },
              symbol: 'none',
              silent: true,
            } as never,
            {
              name: 'expected range',
              type: 'line',
              data: view.band_dates.map((d, i) => [d, bandWidth[i]]),
              stack: 'expected',
              lineStyle: { opacity: 0 },
              itemStyle: { color: 'rgba(245,165,36,0.4)' },
              areaStyle: { color: 'rgba(245,165,36,0.13)' },
              symbol: 'none',
            },
            ...(lift
              ? [
                  {
                    name: 'what-if path',
                    type: 'line' as const,
                    data: lift.dates.map((d, i) => [d, lift.values[i]]),
                    lineStyle: { color: '#2fa97c', width: 2.5, type: 'dotted' as const },
                    itemStyle: { color: '#2fa97c' },
                    symbol: 'none',
                    z: 4,
                  },
                ]
              : []),
          ],
        }}
      />
    </Card>
  )
}

// --- the levers (sticky panel) ---------------------------------------------------

function Levers({
  deck,
  reductions,
  setReductions,
  active,
  result,
  onReset,
}: {
  deck: AnalyzeResponse
  reductions: Record<string, number>
  setReductions: React.Dispatch<React.SetStateAction<Record<string, number>>>
  active: boolean
  result: WhatIfResponse | null
  onReset: () => void
}) {
  const levers = (deck.oee?.bottles_lost ?? []).slice(0, TOP_N)

  if (levers.length === 0)
    return (
      <Card title="What if the stops shrank?">
        <EmptyState>No priced unplanned stops to cut — the what-if levers need downtime priced at target speed.</EmptyState>
      </Card>
    )

  return (
    <Card
      title="What if the stops shrank?"
      hint="Drag a lever to cut that cause's unplanned downtime. The freed time runs at the line's current speed — Availability and OEE move, Performance and Quality stay honest. The result lands in the hero bar and on the forecast as you drag."
      actions={
        active ? (
          <Button variant="ghost" size="sm" onClick={onReset}>
            <RotateCcw className="size-3.5" /> reset
          </Button>
        ) : undefined
      }
    >
      <div className="flex flex-col gap-4 py-1">
        {levers.map((b) => {
          const pct = Math.round((reductions[b.cause] ?? 0) * 100)
          return (
            <div key={b.cause}>
              <div className="mb-1 flex items-baseline justify-between">
                <span className="text-xs font-medium text-ink">{b.cause}</span>
                <span className="font-mono text-xs text-dim">
                  <span className={cn(pct > 0 && 'font-semibold text-amber')}>{pct}%</span>
                  <span className="text-faint"> · {fmtNum(b.bottles)} at stake</span>
                </span>
              </div>
              <input
                type="range"
                min={0}
                max={100}
                value={pct}
                onChange={(e) =>
                  setReductions((prev) => ({ ...prev, [b.cause]: Number(e.target.value) / 100 }))
                }
                className="ll-slider w-full"
                aria-label={`Cut ${b.cause} downtime`}
              />
            </div>
          )
        })}
        {active && result && (
          <p className="text-xs text-dim">
            <span className="font-semibold text-ok">{fmtNum(result.recovered)} bottles</span>{' '}
            recovered over the horizon — OEE {fmtPct(result.baseline?.oee)} →{' '}
            <span className="text-ok">{fmtPct(result.hypo?.oee)}</span>
          </p>
        )}
      </div>
    </Card>
  )
}

// --- the waterfall ----------------------------------------------------------------

function Waterfall({ result }: { result: WhatIfResponse }) {
  const deltas = result.lever_deltas
  let run = 0
  const base: number[] = []
  const bars: { value: number; itemStyle: { color: string } }[] = []
  for (const d of deltas) {
    base.push(run)
    bars.push({ value: Math.round(d.bottles), itemStyle: { color: '#2fa97c' } })
    run += d.bottles
  }
  base.push(0)
  bars.push({ value: Math.round(result.recovered), itemStyle: { color: '#1c6b4f' } })

  return (
    <Chart
      className="h-64"
      option={{
        ...CHART,
        tooltip: { ...CHART.tooltip, trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v) => fmtNum(Number(v)) },
        legend: { show: false },
        grid: { ...CHART.grid, left: 72 },
        xAxis: { type: 'category', data: [...deltas.map((d) => d.cause), 'recovered'], ...CHART.axis },
        yAxis: { type: 'value', ...CHART.axis, axisLabel: { ...CHART.axis.axisLabel, formatter: (v: number) => fmtNum(v) } },
        series: [
          { name: '_base', type: 'bar', stack: 'wf', data: base, itemStyle: { color: 'transparent' }, silent: true } as never,
          { name: 'bottles recovered', type: 'bar', stack: 'wf', data: bars, barMaxWidth: 42 },
        ],
      }}
    />
  )
}
