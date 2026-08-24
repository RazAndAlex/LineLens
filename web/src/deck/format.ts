/** Number formatting for the command deck — en-US everywhere, tabular numerals. */

/** 87,000 / 75 / 96.4 — compact tabular number (mirrors server.logic._fmt_num). */
export function fmtNum(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  if (Math.abs(n) >= 1000) return Math.round(n).toLocaleString('en-US')
  return Number.isInteger(n) ? String(n) : n.toLocaleString('en-US', { maximumFractionDigits: 1 })
}

/** Ratio → "80.0%" (1 decimal, the KPI readout). */
export function fmtPct(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined || Number.isNaN(ratio)) return '—'
  return `${(ratio * 100).toFixed(1)}%`
}

/** Signed point delta → "+2.9 pts". */
export function fmtPts(delta: number): string {
  const pts = delta * 100
  return `${pts >= 0 ? '+' : ''}${pts.toFixed(1)} pts`
}

/** Seconds → "2h 15m" / "45m" / "30s" (mirrors server.logic._fmt_seconds). */
export function fmtSeconds(s: number | null | undefined): string {
  if (s === null || s === undefined || Number.isNaN(s)) return '—'
  if (s < 60) return `${Math.round(s)}s`
  if (s < 3600) return `${Math.round(s / 60)}m`
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return `${h}h ${String(m).padStart(2, '0')}m`
}

/** Seconds → MTBF-scale span "15.8h" / "2.3d" (mirrors server.logic._fmt_span). */
export function fmtSpan(s: number | null | undefined): string {
  if (s === null || s === undefined || Number.isNaN(s)) return '—'
  if (s < 60) return `${Math.round(s)}s`
  if (s < 3600) return `${Math.round(s / 60)}m`
  if (s < 2 * 86400) return `${(s / 3600).toFixed(1)}h`
  return `${(s / 86400).toFixed(1)}d`
}

/** ISO date → "Dec 19" (short axis/label form, en-US). */
export function fmtDay(iso: string): string {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}
