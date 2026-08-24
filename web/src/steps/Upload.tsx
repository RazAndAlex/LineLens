import { useEffect, useRef, useState } from 'react'
import { FileUp, Loader2, AlertTriangle } from 'lucide-react'
import { ApiError, uploadCsv, type UploadResponse } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

type Phase =
  | { kind: 'idle' }
  | { kind: 'busy'; name: string }
  | { kind: 'done'; upload: UploadResponse }
  | { kind: 'error'; message: string }

/** The preview_summary comes back with ** markers for the Streamlit renderer. */
function plain(s: string): string {
  return s.replaceAll('**', '')
}

export function Upload({ onUploaded }: { onUploaded: (u: UploadResponse) => void }) {
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' })
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current)
  }, [])

  const send = async (file: File) => {
    setPhase({ kind: 'busy', name: file.name })
    try {
      const upload = await uploadCsv(file)
      setPhase({ kind: 'done', upload })
      // a beat to read the auto-detect badges, then advance
      timerRef.current = setTimeout(() => onUploaded(upload), 1400)
    } catch (e) {
      const message =
        e instanceof ApiError && typeof e.detail === 'string'
          ? e.detail
          : 'Upload failed — is the LineLens server running?'
      setPhase({ kind: 'error', message })
    }
  }

  const pick = (files: FileList | null) => {
    const file = files?.[0]
    if (file) void send(file)
  }

  return (
    <div
      className="relative flex flex-1 flex-col items-center justify-center px-6 py-10"
      onDragOver={(e) => {
        e.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragOver(false)
        pick(e.dataTransfer.files)
      }}
    >
      {/* splash statement — one sentence, not a paragraph */}
      <div className="mb-10 max-w-2xl text-center">
        <p className="eyebrow mb-4">Machine-data diagnostics</p>
        <h1 className="display text-4xl leading-tight font-semibold tracking-tight sm:text-5xl">
          See what the line <span className="text-amber">actually</span> did.
        </h1>
        <p className="mt-4 text-sm leading-relaxed text-dim">
          Drop a machine CSV export — LineLens checks the data for lies, prices every stop in
          bottles, and totals what your dashboard can't.
        </p>
      </div>

      {/* dropzone */}
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        className={cn(
          'flex w-full max-w-xl cursor-pointer flex-col items-center gap-3 rounded-xl border border-dashed px-8 py-14 transition-all duration-200 focus-visible:outline-amber',
          dragOver
            ? 'border-amber bg-amber-ghost shadow-[0_0_40px_rgba(245,165,36,0.15)]'
            : 'border-line-strong bg-surface/60 hover:border-dim hover:bg-surface',
        )}
      >
        {phase.kind === 'busy' ? (
          <Loader2 className="size-8 animate-spin text-amber" />
        ) : (
          <FileUp className={cn('size-8 transition-colors', dragOver ? 'text-amber' : 'text-faint')} />
        )}
        <span className="text-sm text-dim">
          {phase.kind === 'busy' ? (
            <>
              Reading <span className="font-mono text-ink">{phase.name}</span>…
            </>
          ) : (
            <>
              Drop the CSV anywhere — or <span className="text-amber underline underline-offset-4">browse</span>
            </>
          )}
        </span>
        <span className="font-mono text-[0.66rem] tracking-widest text-faint uppercase">
          .csv · .tsv · .txt
        </span>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept=".csv,.tsv,.txt"
        className="hidden"
        onChange={(e) => {
          pick(e.target.files)
          e.target.value = ''
        }}
      />

      {/* auto-detect readout after a successful parse */}
      {phase.kind === 'done' && (
        <div className="mt-6 flex max-w-xl flex-col items-center gap-2.5 animate-in fade-in-0 slide-in-from-bottom-2">
          <div className="flex flex-wrap items-center justify-center gap-2">
            <Badge variant="amber">{phase.upload.profile.row_count.toLocaleString('en-US')} rows</Badge>
            <Badge>{phase.upload.profile.columns.length} columns</Badge>
            <Badge variant="ok">
              {Object.keys(phase.upload.auto_roles).length} roles recognized
            </Badge>
          </div>
          <p className="text-center text-xs leading-relaxed text-dim">
            {plain(phase.upload.preview_summary)}
          </p>
        </div>
      )}

      {/* scrubbed parse error, with a way back */}
      {phase.kind === 'error' && (
        <div className="mt-6 w-full max-w-xl rounded-lg border border-bad/50 bg-bad/10 px-5 py-4 animate-in fade-in-0">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-bad" />
            <div className="flex-1">
              <p className="text-sm font-medium text-bad">Could not parse that file</p>
              <p className="mt-1 text-xs leading-relaxed text-dim">{phase.message}</p>
              <Button
                variant="outline"
                size="sm"
                className="mt-3"
                onClick={() => {
                  setPhase({ kind: 'idle' })
                  inputRef.current?.click()
                }}
              >
                Choose another file
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
