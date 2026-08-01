import { useCallback, useEffect, useMemo, useState } from "react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { TerminalPane } from "@/components/TerminalPane"
import { api, type EgressEvent, type FsDiff, type Job, type KernelEvent, type SyscallStat } from "@/lib/api"
import { cn } from "@/lib/utils"

function riskVariant(
  level: string | null,
): "default" | "secondary" | "destructive" | "outline" {
  const l = (level ?? "RISKY").toUpperCase()
  if (l === "CRITICAL") return "destructive"
  if (l === "SAFE") return "secondary"
  return "outline"
}

function formatDiff(fs: FsDiff | null) {
  if (!fs) return null
  const sections: { title: string; items: FsDiff["added"]; tone: string }[] = [
    { title: "Added", items: fs.added, tone: "text-emerald-400" },
    { title: "Modified", items: fs.modified, tone: "text-amber-400" },
    { title: "Deleted", items: fs.deleted, tone: "text-rose-400" },
  ]
  if (sections.every((s) => s.items.length === 0)) return null
  return sections
}

export function Dashboard() {
  const [pending, setPending] = useState<Job[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [egress, setEgress] = useState<EgressEvent[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [watchingId, setWatchingId] = useState<string | null>(null)
  const [inspectedJob, setInspectedJob] = useState<Job | null>(null)
  const [fsDiff, setFsDiff] = useState<FsDiff | null>(null)
  const [syscallProfile, setSyscallProfile] = useState<SyscallStat[] | null>(null)
  const [kernelEvents, setKernelEvents] = useState<KernelEvent[] | null>(null)
  const [kernelFilter, setKernelFilter] = useState<"all" | "file" | "net" | "process">("all")
  const [sandboxOk, setSandboxOk] = useState(true)
  const [egressOk, setEgressOk] = useState(true)
  const [tab, setTab] = useState("terminal")
  const [denyOpen, setDenyOpen] = useState(false)
  const [denyReason, setDenyReason] = useState("")
  const [denySubmitting, setDenySubmitting] = useState(false)

  const running = useMemo(
    () => jobs.filter((j) => j.status === "running"),
    [jobs],
  )
  const recent = useMemo(
    () =>
      jobs
        .filter((j) => !["pending", "running"].includes(j.status))
        .slice(0, 8),
    [jobs],
  )

  const refresh = useCallback(async () => {
    try {
      const health = await api.health()
      setSandboxOk(health.status === "ok")
    } catch {
      setSandboxOk(false)
    }
    try {
      const [p, j, e] = await Promise.all([
        api.pending(),
        api.jobs(30),
        api.egress(40),
      ])
      setPending(p)
      setJobs(j)
      setEgress(e)
      setEgressOk(true)
      setActiveId((cur) => {
        if (cur && p.some((x) => x.id === cur)) return cur
        return p[0]?.id ?? null
      })
      setWatchingId((cur) => {
        const live = j.filter((x) => x.status === "running")
        if (cur && live.some((x) => x.id === cur)) return cur
        return live[0]?.id ?? cur
      })
    } catch {
      setEgressOk(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
    const id = window.setInterval(() => void refresh(), 1000)
    return () => window.clearInterval(id)
  }, [refresh])

  const approve = useCallback(async () => {
    if (!activeId) return
    const id = activeId
    try {
      await api.approve(id)
      toast.success("Authorized")
      setWatchingId(id)
      setTab("terminal")
      await refresh()
    } catch (err) {
      toast.error(String(err))
    }
  }, [activeId, refresh])

  const openDenyModal = useCallback(() => {
    if (!activeId) return
    setDenyReason("")
    setDenyOpen(true)
  }, [activeId])

  const submitDeny = useCallback(
    async (revert: boolean) => {
      if (!activeId) return
      const reason = denyReason.trim()
      if (!reason) {
        toast.error("Tell the agent why")
        return
      }
      setDenySubmitting(true)
      try {
        await api.deny(activeId, reason, revert)
        toast.message(revert ? "Denied & hologram wiped" : "Feedback sent to agent")
        setDenyOpen(false)
        setDenyReason("")
        setActiveId(null)
        await refresh()
      } catch (err) {
        toast.error(String(err))
      } finally {
        setDenySubmitting(false)
      }
    },
    [activeId, denyReason, refresh],
  )

  const revertSnapshot = useCallback(async () => {
    const id = inspectedJob?.id
    if (!id || !inspectedJob?.checkpoint_ref) return
    if (!window.confirm("Restore holographic workspace to the pre-run snapshot?")) return
    try {
      await api.revert(id)
      toast.success("Hologram restored")
      setFsDiff(null)
      await refresh()
    } catch (err) {
      toast.error(String(err))
    }
  }, [inspectedJob, refresh])

  const inspectJob = useCallback((job: Job) => {
    setInspectedJob(job)
    setFsDiff(job.result?.fs_diff ?? null)
    setSyscallProfile(job.result?.syscall_profile ?? null)
    setKernelEvents(job.result?.kernel_events ?? null)
  }, [])

  const promoteShadow = useCallback(async () => {
    const id = inspectedJob?.id
    if (!id || !inspectedJob?.shadow_path) return
    if (!window.confirm("Promote hologram changes into your real workspace?")) return
    try {
      const res = await api.promote(id)
      toast.success(`Promoted ${res.promoted.length} path(s)`)
      const job = await api.job(id)
      inspectJob(job)
      await refresh()
    } catch (err) {
      toast.error(String(err))
    }
  }, [inspectedJob, inspectJob, refresh])

  const estop = useCallback(async () => {
    try {
      const res = await api.estop()
      toast.error(`E-Stop killed ${res.count}`)
      await refresh()
    } catch (err) {
      toast.error(String(err))
    }
  }, [refresh])

  const kill = async (id: string) => {
    try {
      await api.kill(id)
      toast.message("Container killed")
      await refresh()
    } catch (err) {
      toast.error(String(err))
    }
  }

  const onStreamDone = useCallback(async (jobId: string) => {
    try {
      const job = await api.job(jobId)
      inspectJob(job)
    } catch {
      /* ignore */
    }
  }, [inspectJob])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if ((e.key === "a" || e.key === "A") && activeId) {
        e.preventDefault()
        void approve()
      } else if ((e.key === "d" || e.key === "D") && activeId) {
        e.preventDefault()
        openDenyModal()
      } else if (e.key === "Escape" && e.shiftKey) {
        e.preventDefault()
        void estop()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [activeId, approve, openDenyModal, estop])

  const diffSections = formatDiff(fsDiff)
  const maxSyscallCalls = Math.max(
    1,
    ...(syscallProfile ?? []).map((s) => s.calls),
  )
  const filteredKernelEvents = useMemo(() => {
    const events = kernelEvents ?? []
    if (kernelFilter === "all") return events
    return events.filter((e) => e.category === kernelFilter)
  }, [kernelEvents, kernelFilter])

  return (
    <div className="dark relative flex h-svh flex-col overflow-hidden text-foreground">
      <div className="pointer-events-none absolute inset-0 -z-10">
        <img
          src="/lego-front.jpg"
          alt=""
          className="size-full object-cover object-center"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-black/50 via-black/72 to-black/92" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_rgba(251,113,133,0.2),_transparent_55%),radial-gradient(ellipse_at_bottom_right,_rgba(125,211,252,0.14),_transparent_45%)]" />
      </div>

      <header className="flex h-14 shrink-0 items-center justify-between border-b border-white/10 bg-black/40 px-4 backdrop-blur-xl">
        <div className="flex flex-col gap-0.5">
          <div className="flex items-baseline gap-2">
            <span className="font-heading text-base font-semibold tracking-[0.18em] text-white">
              AGENTJAIL
            </span>
            <Badge variant="outline" className="font-mono text-[10px] uppercase">
              containment
            </Badge>
          </div>
          <span className="font-mono text-[10px] text-zinc-400">
            sandboxed agent runtime
          </span>
        </div>

        <div className="flex items-center gap-2">
          <Badge
            variant="secondary"
            className={cn(
              "gap-1.5 font-mono",
              sandboxOk ? "text-emerald-300" : "text-rose-300",
            )}
          >
            <span
              className={cn(
                "size-1.5 rounded-full",
                sandboxOk ? "bg-emerald-400" : "bg-rose-400",
              )}
            />
            {sandboxOk ? "CONTAINED" : "OFFLINE"}
          </Badge>
          <Badge
            variant="secondary"
            className={cn(
              "hidden font-mono sm:inline-flex",
              egressOk ? "text-sky-300" : "text-rose-300",
            )}
          >
            {egressOk ? "EGRESS :8888" : "EGRESS DOWN"}
          </Badge>
          <Button variant="destructive" size="sm" onClick={() => void estop()}>
            E-Stop
            <kbd className="rounded border border-white/20 px-1 font-mono text-[10px]">
              ⇧ESC
            </kbd>
          </Button>
        </div>
      </header>

      <main className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[18rem_minmax(0,1fr)_18rem]">
        <aside className="flex min-h-0 flex-col border-r border-white/10 bg-black/35 backdrop-blur-xl">
          <div className="flex items-center justify-between px-3 py-3">
            <div className="font-heading text-[11px] font-semibold uppercase tracking-[0.2em] text-zinc-400">
              Queue
            </div>
            <Badge variant="outline" className="font-mono text-[10px] text-amber-300">
              {pending.length} pending
            </Badge>
          </div>
          <Separator />
          <ScrollArea className="min-h-0 flex-1">
            <div className="flex flex-col gap-2 p-2">
              {pending.length === 0 ? (
                <Empty className="border-none py-10">
                  <EmptyHeader>
                    <EmptyTitle>Queue clear</EmptyTitle>
                    <EmptyDescription>No pending commands.</EmptyDescription>
                  </EmptyHeader>
                </Empty>
              ) : (
                pending.map((j) => (
                  <button
                    key={j.id}
                    type="button"
                    onClick={() => setActiveId(j.id)}
                    className={cn(
                      "rounded-xl border p-2.5 text-left transition",
                      j.id === activeId
                        ? "border-amber-400/40 bg-amber-500/10"
                        : "border-white/10 bg-black/30 hover:border-white/20",
                    )}
                  >
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <Badge
                        variant={riskVariant(j.risk_level)}
                        className="font-mono text-[10px]"
                      >
                        {j.risk_level ?? "RISKY"}
                      </Badge>
                      <span className="font-mono text-[10px] text-zinc-500">
                        {j.id.slice(0, 8)}
                      </span>
                    </div>
                    <div className="truncate font-mono text-xs text-zinc-100">
                      {j.command}
                    </div>
                    <div className="mt-1 truncate font-mono text-[10px] text-zinc-500">
                      {j.risk_reason}
                    </div>
                  </button>
                ))
              )}
            </div>
          </ScrollArea>
          <Separator />
          <div className="flex flex-col gap-2 p-3">
            <div className="font-heading text-[11px] font-semibold uppercase tracking-[0.2em] text-zinc-500">
              Running
            </div>
            {running.length === 0 ? (
              <p className="font-mono text-[11px] text-zinc-600">Nothing running</p>
            ) : (
              running.map((j) => (
                <Card
                  key={j.id}
                  className="border-sky-400/25 bg-sky-500/5 py-0 shadow-none"
                >
                  <CardContent className="flex flex-col gap-2 p-2.5">
                    <div className="truncate font-mono text-xs">{j.command}</div>
                    <div className="flex gap-1">
                      <Button
                        size="xs"
                        variant="secondary"
                        onClick={() => setWatchingId(j.id)}
                      >
                        Watch
                      </Button>
                      <Button
                        size="xs"
                        variant="destructive"
                        onClick={() => void kill(j.id)}
                      >
                        Kill
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))
            )}
          </div>
        </aside>

        <section className="flex min-h-0 flex-col bg-black/25 backdrop-blur-md">
          <Tabs
            value={tab}
            onValueChange={setTab}
            className="flex min-h-0 flex-1 flex-col"
          >
            <div className="flex h-12 items-center justify-between gap-2 border-b border-white/10 px-3">
              <TabsList>
                <TabsTrigger value="terminal">Stream</TabsTrigger>
                <TabsTrigger value="diff">Diff</TabsTrigger>
                <TabsTrigger value="syscalls">Kernel</TabsTrigger>
              </TabsList>

              {activeId ? (
                <div className="flex items-center gap-2">
                  <span className="hidden font-mono text-[11px] text-amber-300 md:inline">
                    Authorization required
                  </span>
                  <Button size="sm" onClick={() => void approve()}>
                    Approve
                    <kbd className="rounded border border-black/20 px-1 font-mono text-[10px]">
                      A
                    </kbd>
                  </Button>
                  <Button size="sm" variant="outline" onClick={openDenyModal}>
                    Deny
                    <kbd className="rounded border border-white/20 px-1 font-mono text-[10px]">
                      D
                    </kbd>
                  </Button>
                </div>
              ) : null}
            </div>

            <TabsContent
              value="terminal"
              className="mt-0 flex min-h-0 flex-1 flex-col p-2"
            >
              <div className="mb-1 flex items-center justify-between px-1 font-mono text-[10px] text-zinc-500">
                <span>
                  {watchingId
                    ? `stream · ${watchingId.slice(0, 8)}`
                    : "standby · no active stream"}
                </span>
                {watchingId && running.some((j) => j.id === watchingId) ? (
                  <Button
                    size="xs"
                    variant="destructive"
                    onClick={() => void kill(watchingId)}
                  >
                    Kill
                  </Button>
                ) : null}
              </div>
              <Card className="min-h-0 flex-1 overflow-hidden border-white/10 bg-black/60 py-0 shadow-none">
                <CardContent className="size-full min-h-[280px] p-0">
                  <TerminalPane jobId={watchingId} onDone={onStreamDone} />
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent
              value="diff"
              className="mt-0 min-h-0 flex-1 overflow-auto p-4"
            >
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <p className="font-mono text-[11px] text-zinc-500">
                  {inspectedJob?.shadow_path
                    ? "Changes live in the hologram until promoted"
                    : inspectedJob?.checkpoint_ref
                      ? `snapshot · ${inspectedJob.checkpoint_ref.slice(0, 12)}`
                      : "no hologram for this view"}
                </p>
                <div className="flex flex-wrap gap-2">
                  {inspectedJob?.checkpoint_ref ? (
                    <Button size="sm" variant="outline" onClick={() => void revertSnapshot()}>
                      Revert hologram
                    </Button>
                  ) : null}
                  {inspectedJob?.shadow_path ? (
                    <Button size="sm" onClick={() => void promoteShadow()}>
                      Promote to workspace
                    </Button>
                  ) : null}
                </div>
              </div>
              {!diffSections ? (
                <Empty className="border-dashed border-white/10 bg-black/30">
                  <EmptyHeader>
                    <EmptyTitle>No filesystem mutations</EmptyTitle>
                    <EmptyDescription>
                      Diffs appear after a sandboxed run completes.
                    </EmptyDescription>
                  </EmptyHeader>
                </Empty>
              ) : (
                <div className="flex flex-col gap-4 font-mono text-xs">
                  {diffSections.map((section) =>
                    section.items.length === 0 ? null : (
                      <div key={section.title} className="flex flex-col gap-2">
                        <div
                          className={cn(
                            "font-heading text-[11px] uppercase tracking-[0.16em]",
                            section.tone,
                          )}
                        >
                          {section.title} ({section.items.length})
                        </div>
                        {section.items.map((item) => (
                          <Card
                            key={`${section.title}-${item.path}`}
                            className="overflow-hidden border-white/10 bg-black/50 py-0 shadow-none"
                          >
                            <CardHeader className="border-b border-white/10 px-3 py-2">
                              <CardTitle className="font-mono text-xs text-sky-200">
                                {item.path}
                              </CardTitle>
                              {item.binary_or_large ? (
                                <CardDescription>binary or large file</CardDescription>
                              ) : null}
                            </CardHeader>
                            {item.unified_diff ? (
                              <CardContent className="p-3">
                                <pre className="overflow-x-auto whitespace-pre-wrap leading-relaxed text-zinc-300">
                                  {item.unified_diff}
                                </pre>
                              </CardContent>
                            ) : null}
                          </Card>
                        ))}
                      </div>
                    ),
                  )}
                </div>
              )}
            </TabsContent>

            <TabsContent
              value="syscalls"
              className="mt-0 min-h-0 flex-1 overflow-auto p-4"
            >
              {!syscallProfile?.length && !kernelEvents?.length ? (
                <Empty className="border-dashed border-white/10 bg-black/30">
                  <EmptyHeader>
                    <EmptyTitle>No kernel telemetry</EmptyTitle>
                    <EmptyDescription>
                      Profiles appear after a run with the strace-enabled sandbox image.
                    </EmptyDescription>
                  </EmptyHeader>
                </Empty>
              ) : (
                <div className="flex flex-col gap-6">
                  {syscallProfile && syscallProfile.length > 0 ? (
                    <div className="flex flex-col gap-3">
                      <p className="font-heading text-[11px] uppercase tracking-[0.16em] text-zinc-500">
                        Call counts
                      </p>
                      {syscallProfile.map((stat) => {
                        const width = Math.max(
                          4,
                          Math.round((stat.calls / maxSyscallCalls) * 100),
                        )
                        return (
                          <div key={stat.syscall} className="flex flex-col gap-1">
                            <div className="flex items-baseline justify-between font-mono text-[11px]">
                              <span className="text-sky-200">{stat.syscall}</span>
                              <span className="text-zinc-500">
                                {stat.calls} calls
                                {stat.errors > 0 ? ` · ${stat.errors} err` : ""}
                                {` · ${stat.time_pct.toFixed(1)}%`}
                              </span>
                            </div>
                            <div className="h-2 overflow-hidden rounded-sm bg-white/10">
                              <div
                                className="h-full rounded-sm bg-gradient-to-r from-sky-500/80 to-amber-400/70"
                                style={{ width: `${width}%` }}
                              />
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  ) : null}

                  <div className="flex flex-col gap-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="font-heading text-[11px] uppercase tracking-[0.16em] text-zinc-500">
                        Event log
                      </p>
                      <div className="flex gap-1">
                        {(["all", "file", "net", "process"] as const).map((f) => (
                          <Button
                            key={f}
                            size="xs"
                            variant={kernelFilter === f ? "default" : "ghost"}
                            onClick={() => setKernelFilter(f)}
                          >
                            {f}
                          </Button>
                        ))}
                      </div>
                    </div>
                    {filteredKernelEvents.length === 0 ? (
                      <p className="font-mono text-[11px] text-zinc-500">
                        No events in this filter.
                      </p>
                    ) : (
                      <div className="flex max-h-[420px] flex-col gap-1 overflow-auto font-mono text-[11px]">
                        {filteredKernelEvents.map((ev, i) => (
                          <div
                            key={`${ev.ts}-${ev.syscall}-${i}`}
                            className="rounded border border-white/10 bg-black/40 px-2 py-1.5"
                          >
                            <div className="flex flex-wrap gap-x-2 text-zinc-500">
                              <span>{ev.ts}</span>
                              {ev.pid ? <span>pid {ev.pid}</span> : null}
                              <span className="text-amber-300">{ev.syscall}</span>
                              <span className="text-zinc-600">{ev.category}</span>
                              {ev.ret ? <span>= {ev.ret}</span> : null}
                            </div>
                            <div className="truncate text-zinc-300">
                              {ev.path || ev.endpoint || ev.args}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </TabsContent>
          </Tabs>
        </section>

        <aside className="flex min-h-0 flex-col border-l border-white/10 bg-black/35 backdrop-blur-xl">
          <div className="flex items-center justify-between px-3 py-3">
            <div className="font-heading text-[11px] font-semibold uppercase tracking-[0.2em] text-zinc-400">
              Egress
            </div>
            <span className="font-mono text-[10px] text-zinc-500">CONNECT</span>
          </div>
          <Separator />
          <ScrollArea className="min-h-0 flex-1">
            <div className="flex flex-col gap-1.5 p-2">
              {egress.length === 0 ? (
                <Empty className="border-none py-10">
                  <EmptyHeader>
                    <EmptyTitle>Quiet</EmptyTitle>
                    <EmptyDescription>No CONNECT events yet.</EmptyDescription>
                  </EmptyHeader>
                </Empty>
              ) : (
                egress.slice(0, 40).map((ev, i) => {
                  const ok = ev.action === "allowed"
                  return (
                    <div
                      key={`${ev.timestamp}-${ev.host}-${i}`}
                      className={cn(
                        "flex items-center justify-between gap-2 rounded-lg border px-2 py-1.5 font-mono text-[11px]",
                        ok
                          ? "border-white/10 bg-black/25"
                          : "border-rose-500/30 bg-rose-500/10",
                      )}
                    >
                      <span
                        className={cn(
                          "truncate",
                          ok ? "text-zinc-300" : "font-semibold text-rose-300",
                        )}
                      >
                        {ev.host}:{ev.port}
                      </span>
                      <Badge
                        variant={ok ? "secondary" : "destructive"}
                        className="shrink-0 text-[9px]"
                      >
                        {ok ? "PASS" : "BLOCK"}
                      </Badge>
                    </div>
                  )
                })
              )}
            </div>
          </ScrollArea>
          <Separator />
          <div className="flex flex-col gap-2 p-3">
            <div className="font-heading text-[11px] font-semibold uppercase tracking-[0.2em] text-zinc-500">
              Recent
            </div>
            {recent.map((j) => (
              <button
                key={j.id}
                type="button"
                className="rounded-lg border border-white/10 bg-black/25 px-2 py-1.5 text-left hover:border-white/20"
                onClick={() => {
                  inspectJob(j)
                  setTab("diff")
                }}
              >
                <div className="flex justify-between gap-2 font-mono text-[10px]">
                  <span className="text-zinc-400">{j.status}</span>
                  <span className="text-zinc-500">{j.id.slice(0, 8)}</span>
                </div>
                <div className="truncate font-mono text-[11px] text-zinc-200">
                  {j.command}
                </div>
              </button>
            ))}
          </div>
        </aside>
      </main>

      <footer className="flex h-8 shrink-0 items-center justify-between border-t border-white/10 bg-black/50 px-4 font-mono text-[10px] text-zinc-500 backdrop-blur">
        <div className="flex items-center gap-3">
          <span className="font-heading tracking-wide">Hotkeys</span>
          <span>
            <kbd className="rounded border border-white/15 px-1">A</kbd> approve
          </span>
          <span>
            <kbd className="rounded border border-white/15 px-1">D</kbd> deny
          </span>
          <span>
            <kbd className="rounded border border-white/15 px-1">⇧ESC</kbd> e-stop
          </span>
        </div>
        <span className="font-heading tracking-[0.12em] text-sky-300/70">
          Josefin Sans
        </span>
      </footer>

      {denyOpen ? (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-lg border border-white/15 bg-zinc-950/95 p-5 shadow-2xl">
            <h2 className="font-heading text-lg tracking-tight text-white">
              Tell the agent why
            </h2>
            <p className="mt-1 text-sm text-zinc-400">
              This message is injected into the MCP tool result so the model can
              steer on the next attempt.
            </p>
            <textarea
              autoFocus
              value={denyReason}
              onChange={(e) => setDenyReason(e.target.value)}
              rows={4}
              placeholder={'e.g. "Don\'t use npm, use yarn instead."'}
              className="mt-4 w-full resize-none rounded-md border border-white/15 bg-black/50 px-3 py-2 font-mono text-sm text-zinc-100 outline-none focus:border-sky-400/50"
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  e.stopPropagation()
                  setDenyOpen(false)
                }
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                  e.preventDefault()
                  void submitDeny(true)
                }
              }}
            />
            <div className="mt-4 flex flex-wrap justify-end gap-2">
              <Button
                variant="ghost"
                onClick={() => setDenyOpen(false)}
                disabled={denySubmitting}
              >
                Cancel
              </Button>
              <Button
                variant="outline"
                onClick={() => void submitDeny(false)}
                disabled={denySubmitting}
              >
                Deny only
              </Button>
              <Button onClick={() => void submitDeny(true)} disabled={denySubmitting}>
                {denySubmitting ? "Sending…" : "Deny & Revert"}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
