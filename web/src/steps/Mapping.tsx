import { useMemo, useState } from 'react'
import { CircleHelp, Loader2, Play } from 'lucide-react'
import {
  ApiError,
  analyze,
  type AnalyzeResponse,
  type MappingBody,
  type UploadResponse,
} from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

// The 13 canonical roles (linelens/models.py CanonicalRole) + a plain-words
// hint each — explanations on demand, never a wall of text.
const ROLES: { value: string; hint: string }[] = [
  { value: 'machine_id', hint: 'Which machine the row belongs to' },
  { value: 'timestamp_start', hint: 'When the interval starts — the one role every analysis needs' },
  { value: 'timestamp_end', hint: 'When the interval ends' },
  { value: 'state', hint: 'Running / Stopped / Idle' },
  { value: 'stop_cause', hint: 'Why the line stopped' },
  { value: 'shift', hint: 'Shift label' },
  { value: 'duration_seconds', hint: 'Interval length in seconds' },
  { value: 'good_count', hint: 'Good parts produced' },
  { value: 'reject_count', hint: 'Scrapped parts' },
  { value: 'recipe', hint: 'Product being run' },
  { value: 'speed_target', hint: 'Target bottles per hour for the recipe' },
  { value: 'speed_actual', hint: 'Actual bottles per hour in the interval' },
  { value: 'planned', hint: 'Scheduled-stop flag (changeover, maintenance)' },
]

const NONE = '__none__'

/** Mirrors server/logic._capabilities — kept in sync by hand (6 checks). */
function capabilitiesFor(mappedRoles: Set<string>, nCounters: number): Record<string, boolean> {
  const has = (r: string) => mappedRoles.has(r)
  const time = has('duration_seconds') || (has('timestamp_start') && has('timestamp_end'))
  return {
    'State totals': has('state') && time,
    'Production totals': has('good_count') && has('reject_count'),
    'Downtime by cause': has('stop_cause') && time,
    'Daily grouping': has('timestamp_start'),
    'Shift grouping': has('shift'),
    'Counter findings': nCounters > 0,
  }
}

/** A 422 problem names a column in single quotes — route it onto that card. */
function columnNamed(problem: string, columns: string[]): string | null {
  const quoted = problem.match(/'([^']+)'/)?.[1]
  return quoted && columns.includes(quoted) ? quoted : null
}

export function Mapping({
  upload,
  onAnalyzed,
}: {
  upload: UploadResponse
  onAnalyzed: (deck: AnalyzeResponse, mapping: MappingBody) => void
}) {
  const columns = upload.profile.columns
  const numeric = useMemo(() => new Set(upload.numeric_counter_options), [upload])

  // col -> role value, pre-filled conflict-free from the server's auto-map
  const [assign, setAssign] = useState<Record<string, string | null>>(() => {
    const init: Record<string, string | null> = Object.fromEntries(columns.map((c) => [c, null]))
    for (const [role, col] of Object.entries(upload.auto_roles)) init[col] = role
    return init
  })
  const [counters, setCounters] = useState<Set<string>>(() => new Set(upload.auto_counters))
  const [problems, setProblems] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const mappedRoles = useMemo(
    () => new Set(Object.values(assign).filter((r): r is string => r !== null)),
    [assign],
  )
  const caps = capabilitiesFor(mappedRoles, counters.size)

  const setRole = (col: string, role: string | null) => {
    setAssign((prev) => {
      const next = { ...prev }
      if (role) {
        // one column per role — reassigning steals the role from its old column
        for (const c of Object.keys(next)) if (next[c] === role) next[c] = null
      }
      next[col] = role
      return next
    })
    setProblems([])
  }

  const toggleCounter = (col: string) => {
    setCounters((prev) => {
      const next = new Set(prev)
      if (next.has(col)) next.delete(col)
      else next.add(col)
      return next
    })
  }

  const cardProblems = (col: string) => problems.filter((p) => columnNamed(p, columns) === col)
  const railProblems = problems.filter((p) => columnNamed(p, columns) === null)

  const runAnalyze = async () => {
    setBusy(true)
    setError(null)
    setProblems([])
    const mapping: MappingBody = {
      roles: Object.fromEntries(
        Object.entries(assign).filter((e): e is [string, string] => e[1] !== null).map(([c, r]) => [r, c]),
      ),
      counters: [...counters],
    }
    try {
      const deck = await analyze(upload.dataset_id, mapping)
      onAnalyzed(deck, mapping)
    } catch (e) {
      if (e instanceof ApiError) {
        const ps = e.problems
        if (ps) setProblems(ps)
        else setError(typeof e.detail === 'string' ? e.detail : 'Analyze failed.')
      } else {
        setError('Analyze failed — is the LineLens server running?')
      }
    } finally {
      setBusy(false)
    }
  }

  const canAnalyze = mappedRoles.has('timestamp_start') && !busy

  return (
    <div className="mx-auto grid w-full max-w-6xl flex-1 gap-6 px-6 py-6 lg:grid-cols-[1fr_330px]">
      {/* --- left: the channel strips -------------------------------------- */}
      <section>
        <div className="mb-4 flex items-baseline justify-between">
          <h2 className="eyebrow">Columns · {columns.length}</h2>
          <span className="font-mono text-[0.66rem] text-faint">
            {mappedRoles.size} mapped · {counters.size} counter{counters.size !== 1 ? 's' : ''}
          </span>
        </div>

        <div className="flex flex-col gap-2.5">
          {columns.map((col) => {
            const role = assign[col]
            const samples = [
              ...new Set(
                upload.preview
                  .map((row) => row[col])
                  .filter((v) => v !== null && v !== '')
                  .map(String),
              ),
            ].slice(0, 3)
            const errs = cardProblems(col)
            const isCounter = counters.has(col)
            return (
              <div
                key={col}
                className={cn(
                  'rounded-lg border bg-surface px-4 py-3 transition-colors',
                  errs.length ? 'border-bad/60' : 'border-line hover:border-line-strong',
                )}
              >
                <div className="flex items-center gap-2.5">
                  <span className={cn('led', role ? 'led-lit' : '')} title={role ? `Mapped: ${role}` : 'Unmapped'} />
                  <span className="truncate font-mono text-sm text-ink">{col}</span>
                  <Badge className="ml-auto shrink-0">{upload.profile.dtypes[col] ?? '?'}</Badge>
                </div>

                {samples.length > 0 && (
                  <p className="mt-1.5 truncate pl-[18px] font-mono text-[0.7rem] text-faint">
                    {samples.join(' · ')}
                  </p>
                )}

                <div className="mt-2.5 flex items-center gap-2 pl-[18px]">
                  <Select
                    value={role ?? NONE}
                    onValueChange={(v) => setRole(col, v === NONE ? null : v)}
                  >
                    <SelectTrigger className="flex-1" aria-label={`Role for ${col}`}>
                      <SelectValue placeholder="(none)" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NONE}>(none)</SelectItem>
                      {ROLES.map((r) => (
                        <SelectItem key={r.value} value={r.value}>
                          {r.value}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className="text-faint hover:text-dim">
                        <CircleHelp className="size-3.5" />
                      </span>
                    </TooltipTrigger>
                    <TooltipContent side="top">
                      {role ? ROLES.find((r) => r.value === role)?.hint : 'Pick the role this column plays, or leave it unmapped.'}
                    </TooltipContent>
                  </Tooltip>
                  {numeric.has(col) && (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          variant={isCounter ? 'default' : 'outline'}
                          size="sm"
                          onClick={() => toggleCounter(col)}
                          aria-pressed={isCounter}
                        >
                          counter
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent side="top">
                        An odometer column — LineLens differences it, never sums it.
                      </TooltipContent>
                    </Tooltip>
                  )}
                </div>

                {errs.map((p) => (
                  <p key={p} className="mt-2 pl-[18px] text-xs text-bad">
                    {p}
                  </p>
                ))}
              </div>
            )
          })}
        </div>
      </section>

      {/* --- right: the instrument rail ------------------------------------- */}
      <aside className="flex flex-col gap-4 self-start lg:sticky lg:top-6">
        <section className="rounded-lg border border-line bg-surface px-4 py-3.5">
          <h3 className="eyebrow mb-3">This mapping enables</h3>
          <ul className="flex flex-col gap-1.5">
            {Object.entries(caps).map(([label, on]) => (
              <li key={label} className="flex items-center gap-2.5 text-xs">
                <span className={cn('led', on ? 'led-ok' : '')} />
                <span className={on ? 'text-ink' : 'text-faint'}>{label}</span>
              </li>
            ))}
          </ul>
        </section>

        {(railProblems.length > 0 || error) && (
          <section className="rounded-lg border border-bad/50 bg-bad/10 px-4 py-3">
            {railProblems.map((p) => (
              <p key={p} className="text-xs leading-relaxed text-bad">
                {p}
              </p>
            ))}
            {error && <p className="text-xs leading-relaxed text-bad">{error}</p>}
          </section>
        )}

        <Button size="lg" className="w-full" disabled={!canAnalyze} onClick={runAnalyze}>
          {busy ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />}
          Analyze
        </Button>
        {!mappedRoles.has('timestamp_start') && (
          <p className="-mt-2 text-center text-[0.7rem] text-faint">
            Map a start timestamp to analyze.
          </p>
        )}
      </aside>
    </div>
  )
}
