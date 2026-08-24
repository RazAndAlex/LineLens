import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import { cn } from '@/lib/utils'

/** Shared chart furniture: hairline grid, mono ticks, dark tooltip — the
 *  control-room look every deck chart inherits. */
export const CHART = {
  textStyle: { fontFamily: 'JetBrains Mono, monospace' },
  grid: { left: 64, right: 20, top: 32, bottom: 28 },
  axis: {
    axisLine: { lineStyle: { color: 'rgba(255,255,255,0.10)' } },
    axisTick: { show: false },
    axisLabel: { color: '#8b96a3', fontSize: 10.5, fontFamily: 'JetBrains Mono, monospace' },
    splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
  },
  tooltip: {
    backgroundColor: '#1f2630',
    borderColor: 'rgba(255,255,255,0.14)',
    textStyle: { color: '#e6eaef', fontSize: 11.5, fontFamily: 'JetBrains Mono, monospace' },
  },
  legend: {
    textStyle: { color: '#8b96a3', fontSize: 10.5, fontFamily: 'JetBrains Mono, monospace' },
    itemWidth: 14,
    itemHeight: 8,
  },
} as const

export function Chart({
  option,
  className,
  onReady,
}: {
  option: echarts.EChartsOption
  className?: string
  onReady?: (chart: echarts.ECharts) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current, undefined, { renderer: 'canvas' })
    chartRef.current = chart
    const ro = new ResizeObserver(() => chart.resize())
    ro.observe(ref.current)
    return () => {
      ro.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!chartRef.current) return
    chartRef.current.setOption(option, { notMerge: true })
    onReady?.(chartRef.current)
  }, [option, onReady])

  return <div ref={ref} className={cn('h-64 w-full', className)} />
}
