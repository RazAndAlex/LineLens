import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'

/** Minimal toast bus: API failures surface as a card bottom-right, auto-dismiss. */

type Toast = { id: number; message: string }
let push: ((message: string) => void) | null = null

export function toastError(message: string) {
  push?.(message)
}

export function ToastHost() {
  const [toasts, setToasts] = useState<Toast[]>([])

  useEffect(() => {
    push = (message) => {
      const id = Date.now() + Math.random()
      setToasts((t) => [...t, { id, message }])
      setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000)
    }
    return () => {
      push = null
    }
  }, [])

  if (toasts.length === 0) return null
  return (
    <div className="fixed right-4 bottom-4 z-[60] flex w-80 flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className="flex items-start gap-2.5 rounded-lg border border-bad/50 bg-surface-3 px-4 py-3 shadow-[0_12px_32px_rgba(0,0,0,0.55)] animate-in fade-in-0 slide-in-from-bottom-2"
          role="alert"
        >
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-bad" />
          <p className="text-xs leading-relaxed text-ink">{t.message}</p>
        </div>
      ))}
    </div>
  )
}
