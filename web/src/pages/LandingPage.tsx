import { Link } from "react-router-dom"

import { Hero07 } from "@/components/ui/hero-07"
import { Separator } from "@/components/ui/separator"

const pillars = [
  {
    title: "Classify, then decide",
    body: "AST risk gating before anything runs. Safe and autopilot commands execute silently in a hologram. Anomalies wait for Approve. Critical stays blocked.",
  },
  {
    title: "Shadow, don’t touch origin",
    body: "COW holographic workspaces and ephemeral Docker sandboxes. Promote only what you accept—Deny & Revert wipes the shadow and syncs agent memory.",
  },
  {
    title: "Intercept at the edge",
    body: "PATH shims and optional Invisible mode catch built-in Shell, not just MCP. Whitelist egress filters the network; the console and IDE status bar keep you in the loop.",
  },
] as const

export function LandingPage() {
  return (
    <div className="min-h-svh bg-background text-foreground">
      <header className="mx-auto flex max-w-7xl items-center justify-between px-6 py-5">
        <Link
          to="/"
          className="font-heading text-sm font-semibold tracking-[0.2em] text-foreground"
        >
          AGENTVIGILANTE
        </Link>
        <nav className="flex items-center gap-5 font-heading text-sm tracking-wide text-muted-foreground">
          <a href="#how" className="hover:text-foreground">
            How it works
          </a>
          <Link to="/console" className="hover:text-foreground">
            Console
          </Link>
        </nav>
      </header>

      <Hero07
        tagline="Local containment for coding agents"
        title="Give agents room to work—without giving them the keys."
        description="AgentVigilante sits between your AI and your machine: risk gating, holographic sandboxes, PATH interception, and whitelist egress—with a live console when you want the front seat, or Invisible mode when you don’t."
        landscapeImage="/hero-landscape.png"
        landscapeAlt="A traveler on a high ridge above clouds, framed by a digital grid overlay"
        animation="subtle"
        primaryCTA={{
          ctaEnabled: true,
          text: "Open the console",
          link: "/console",
          variant: "default",
          size: "lg",
        }}
        secondaryCTA={{
          ctaEnabled: true,
          text: "How it works",
          link: "#how",
          variant: "link",
          size: "lg",
        }}
      />

      <section id="how" className="mx-auto max-w-7xl px-6 pb-24">
        <div className="mb-10 max-w-2xl">
          <p className="font-heading text-sm tracking-[0.16em] text-muted-foreground uppercase">
            Defense in depth
          </p>
          <h2 className="mt-3 font-heading text-2xl tracking-tight text-foreground sm:text-3xl">
            A quieter way to run ambitious agents
          </h2>
          <p className="mt-4 max-w-xl text-sm leading-relaxed text-muted-foreground sm:text-base">
            Interactive by default—or enable Invisible for background autopilot
            with IDE Approve/Block only on anomalies. Same gate either way.
          </p>
        </div>

        <div className="grid gap-8 sm:grid-cols-3">
          {pillars.map((pillar, index) => (
            <article key={pillar.title} className="flex flex-col gap-3">
              <span className="font-mono text-[11px] text-muted-foreground">
                {String(index + 1).padStart(2, "0")}
              </span>
              <h3 className="font-heading text-lg tracking-tight text-foreground">
                {pillar.title}
              </h3>
              <p className="text-sm leading-relaxed text-muted-foreground">
                {pillar.body}
              </p>
            </article>
          ))}
        </div>

        <Separator className="my-14" />

        <div className="grid gap-8 lg:grid-cols-12 lg:items-end">
          <div className="lg:col-span-5">
            <h2 className="font-heading text-2xl tracking-tight text-foreground">
              Built for people who still want to stay in the loop
            </h2>
          </div>
          <div className="lg:col-span-6 lg:col-start-7">
            <p className="text-sm leading-relaxed text-muted-foreground sm:text-base">
              Approve anomalies, stream output, inspect diffs, promote holograms,
              and E-Stop when needed. MCP, PATH wrap, or Invisible shell
              integration—Cursor and Claude Code hit the same perimeter.
            </p>
            <div className="mt-6">
              <Link
                to="/console"
                className="font-heading text-sm tracking-wide text-foreground underline underline-offset-4"
              >
                Enter the console
              </Link>
            </div>
          </div>
        </div>
      </section>

      <footer className="border-t border-border/60 px-6 py-8">
        <div className="mx-auto flex max-w-7xl flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <span className="font-heading text-xs tracking-[0.18em] text-muted-foreground">
            AGENTVIGILANTE
          </span>
          <span className="font-mono text-[11px] text-muted-foreground">
            Hologram · PATH wrap · autopilot · whitelist egress
          </span>
        </div>
      </footer>
    </div>
  )
}
