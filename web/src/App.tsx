import { useState } from 'react'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { AnalyzeResponse, MappingBody, UploadResponse } from '@/api'
import { Upload } from '@/steps/Upload'
import { Mapping } from '@/steps/Mapping'
import { Deck } from '@/steps/Deck'

type Step = 'upload' | 'mapping' | 'deck'

const STEPS: { id: Step; label: string }[] = [
  { id: 'upload', label: 'Upload' },
  { id: 'mapping', label: 'Map columns' },
  { id: 'deck', label: 'Results' },
]

export default function App() {
  const [step, setStep] = useState<Step>('upload')
  const [upload, setUpload] = useState<UploadResponse | null>(null)
  const [mapping, setMapping] = useState<MappingBody | null>(null)
  const [deck, setDeck] = useState<AnalyzeResponse | null>(null)

  const reset = () => {
    setStep('upload')
    setUpload(null)
    setMapping(null)
    setDeck(null)
  }

  const activeIdx = STEPS.findIndex((s) => s.id === step)

  return (
    <TooltipProvider delayDuration={250}>
      <div className="flex min-h-full flex-col">
        <header className="flex items-center gap-4 border-b border-line px-6 py-3">
          <button
            onClick={reset}
            className="flex cursor-pointer items-center gap-2.5 focus-visible:outline-amber"
            title="Start over with a new file"
          >
            <span className="display text-lg tracking-tight">
              LineLens<span className="text-amber">.</span>
            </span>
          </button>

          <nav className="ml-6 flex items-center gap-1" aria-label="Steps">
            {STEPS.map((s, i) => (
              <div key={s.id} className="flex items-center">
                {i > 0 && <span className="mx-2 h-px w-5 bg-line-strong" aria-hidden />}
                <span
                  className={cn(
                    'font-mono text-[0.7rem] tracking-widest uppercase transition-colors',
                    i === activeIdx ? 'text-amber' : i < activeIdx ? 'text-dim' : 'text-faint',
                  )}
                  aria-current={i === activeIdx ? 'step' : undefined}
                >
                  {s.label}
                </span>
              </div>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            {upload && (
              <span className="hidden font-mono text-xs text-faint sm:inline">{upload.name}</span>
            )}
            {step !== 'upload' && (
              <Button variant="outline" size="sm" onClick={reset}>
                New file
              </Button>
            )}
          </div>
        </header>

        <main className="flex flex-1 flex-col">
          {step === 'upload' && (
            <Upload
              onUploaded={(u) => {
                setUpload(u)
                setStep('mapping')
              }}
            />
          )}
          {step === 'mapping' && upload && (
            <Mapping
              upload={upload}
              onAnalyzed={(d, m) => {
                setDeck(d)
                setMapping(m)
                setStep('deck')
              }}
            />
          )}
          {step === 'deck' && deck && upload && mapping && (
            <Deck upload={upload} mapping={mapping} deck={deck} onRemap={() => setStep('mapping')} />
          )}
        </main>
      </div>
    </TooltipProvider>
  )
}
