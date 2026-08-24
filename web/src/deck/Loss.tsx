import { useMemo } from 'react'
import type { AnalyzeResponse } from '@/api'
import { Card, EmptyState, SectionHead } from '@/deck/SectionCard'
import { Chart, CHART } from '@/deck/Chart'
import { fmtNum } from '@/deck/format'

// Loss palette: amber family tiered by cumulative impact (the server.logic
// _loss_color_map idea — vital few / middle / tail at 50%/80% Pareto splits),
// never the old UI's oranges.
const TIER_COLORS = ['#f5a524', '#b97a0f', '#6e4e0b']
const TIER_SPLITS = [0.5, 0.8]

function tierColor(cumShareBefore: number): string {
  return TIER_COLORS[cumShareBefore < TIER_SPLITS[0] ? 0 : cumShareBefore < TIER_SPLITS[1] ? 1 : 2]
}

export function Loss({ deck }: { deck: AnalyzeResponse }) {
  const { pareto } = deck
  const total = useMemo(() => pareto.bottles.reduce((a, b) => a + b, 0), [pareto])
  const top = pareto.causes[0]
  const topShare = top && total > 0 ? (pareto.bottles[0] / total) * 100 : 0

  return (
    <div className="flex scroll-mt-32 flex-col gap-4" data-section="loss">
      <SectionHead id="loss" eyebrow="Loss">
        {top
          ? `${top} costs you ${fmtNum(pareto.bottles[0])} bottles — ${topShare.toFixed(0)}% of all loss`
          : 'No priced loss in this window'}
      </SectionHead>

      {pareto.causes.length === 0 ? (
        <EmptyState>No unplanned downtime priced at target speed — nothing lost to rank.</EmptyState>
      ) : (
        <Card
          title="The vital few stops, priced in bottles"
          hint="Each unplanned stop's seconds are priced at the line's target speed — downtime you can read as bottles not made. The line is the running share of the total; bar color deepens as impact thins out."
        >
          <Chart
            className="h-72"
            option={{
              ...CHART,
              tooltip: {
                ...CHART.tooltip,
                trigger: 'axis',
                axisPointer: { type: 'shadow' },
                // bottles are whole things; the share reads as "39.6%" — never raw floats
                formatter: (params: unknown) => {
                  const list = (Array.isArray(params) ? params : [params]) as {
                    marker: string
                    seriesName: string
                    name: string
                    value: number
                  }[]
                  const rows = list
                    .map((p) => {
                      const text =
                        p.seriesName === 'cumulative %'
                          ? `${Number(p.value).toFixed(1)}%`
                          : fmtNum(Number(p.value))
                      return `${p.marker} ${p.seriesName}&nbsp;&nbsp;<b>${text}</b>`
                    })
                    .join('<br/>')
                  return `<b>${list[0]?.name ?? ''}</b><br/>${rows}`
                },
              },
              // single-line legend, top-right — the default ('auto') lands at
              // the bottom and clips the cause labels
              legend: { ...CHART.legend, top: 0, right: 0 },
              grid: { ...CHART.grid, right: 56, top: 40, bottom: 8, containLabel: true },
              xAxis: { type: 'category', data: pareto.causes, ...CHART.axis },
              yAxis: [
                { type: 'value', ...CHART.axis },
                { type: 'value', max: 100, ...CHART.axis, splitLine: { show: false } },
              ],
              series: [
                {
                  name: 'bottles lost',
                  type: 'bar',
                  itemStyle: { color: '#f5a524' }, // legend marker; bars override per tier below
                  data: pareto.bottles.map((b, i) => ({
                    value: b,
                    itemStyle: {
                      color: tierColor(i === 0 ? 0 : (pareto.cumulative_pct[i - 1] ?? 0) / 100),
                      borderRadius: [3, 3, 0, 0],
                    },
                  })),
                  barMaxWidth: 56,
                },
                {
                  name: 'cumulative %',
                  type: 'line',
                  yAxisIndex: 1,
                  data: pareto.cumulative_pct,
                  symbolSize: 5,
                  lineStyle: { color: '#8b96a3', width: 1.5 },
                  itemStyle: { color: '#8b96a3' },
                },
              ],
            }}
          />
        </Card>
      )}
    </div>
  )
}
