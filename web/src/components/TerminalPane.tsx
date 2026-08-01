import { useEffect, useRef } from "react"
import { Terminal } from "@xterm/xterm"
import { FitAddon } from "@xterm/addon-fit"
import "@xterm/xterm/css/xterm.css"

type Props = {
  jobId: string | null
  onDone?: (jobId: string) => void
}

export function TerminalPane({ jobId, onDone }: Props) {
  const hostRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<Terminal | null>(null)
  const fitRef = useRef<FitAddon | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const attachedRef = useRef<string | null>(null)

  useEffect(() => {
    if (!hostRef.current || termRef.current) return
    const term = new Terminal({
      convertEol: true,
      fontFamily: "IBM Plex Mono, ui-monospace, monospace",
      fontSize: 12,
      lineHeight: 1.4,
      cursorBlink: true,
      theme: {
        background: "#0a0a0c",
        foreground: "#f4f4f5",
        cursor: "#fb7185",
        red: "#fb7185",
        green: "#34d399",
        yellow: "#fbbf24",
        blue: "#7dd3fc",
        magenta: "#c084fc",
        cyan: "#67e8f9",
      },
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(hostRef.current)
    fit.fit()
    term.writeln("\x1b[38;2;148;163;184m[SYSTEM]\x1b[0m AgentJail containment gateway ready.")
    term.writeln("\x1b[38;2;148;163;184m[SYSTEM]\x1b[0m Front visual: modular mosaic landscape.")
    term.writeln("")
    termRef.current = term
    fitRef.current = fit

    const onResize = () => fit.fit()
    window.addEventListener("resize", onResize)
    return () => {
      window.removeEventListener("resize", onResize)
      wsRef.current?.close()
      term.dispose()
      termRef.current = null
    }
  }, [])

  useEffect(() => {
    const term = termRef.current
    if (!term || !jobId) return
    if (attachedRef.current === jobId && wsRef.current?.readyState === WebSocket.OPEN) {
      return
    }

    wsRef.current?.close()
    attachedRef.current = jobId
    term.clear()
    term.writeln(`\x1b[38;2;125;211;252m[ATTACH]\x1b[0m ${jobId.slice(0, 8)}`)

    const proto = location.protocol === "https:" ? "wss" : "ws"
    const ws = new WebSocket(`${proto}://${location.host}/v1/commands/${jobId}/stream`)
    wsRef.current = ws
    ws.onmessage = (ev) => {
      let msg: { type?: string; data?: string; status?: string; exit_code?: number }
      try {
        msg = JSON.parse(ev.data as string)
      } catch {
        return
      }
      if (msg.type === "out" || msg.type === "meta") term.write(msg.data ?? "")
      if (msg.type === "done") {
        term.writeln(
          `\r\n\x1b[38;2;148;163;184m[DONE]\x1b[0m status=${msg.status} exit=${msg.exit_code}`,
        )
        onDone?.(jobId)
        ws.close()
      }
    }
    return () => {
      ws.close()
    }
  }, [jobId, onDone])

  useEffect(() => {
    fitRef.current?.fit()
  })

  return <div ref={hostRef} className="size-full min-h-0" />
}
