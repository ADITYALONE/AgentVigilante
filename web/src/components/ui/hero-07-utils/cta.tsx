import { Link } from "react-router-dom"
import type { VariantProps } from "class-variance-authority"

import { Button, buttonVariants } from "@/components/ui/button"
import { cn } from "@/lib/utils"

export type CtaProps = {
  ctaEnabled: boolean
  text: string
  link?: string
  variant?: VariantProps<typeof buttonVariants>["variant"]
  size?: VariantProps<typeof buttonVariants>["size"]
  className?: string
  onClick?: () => void
}

export function Cta({
  cta,
}: Readonly<{
  cta: CtaProps
}>) {
  if (!cta.ctaEnabled || !cta.text) return null

  const className = cn(cta.className)
  const variant = cta.variant ?? "default"
  const size = cta.size ?? "lg"

  if (cta.link) {
    const isExternal = /^https?:\/\//i.test(cta.link)
    if (isExternal) {
      return (
        <Button variant={variant} size={size} className={className} asChild>
          <a href={cta.link} target="_blank" rel="noreferrer">
            {cta.text}
          </a>
        </Button>
      )
    }
    return (
      <Button variant={variant} size={size} className={className} asChild>
        <Link to={cta.link}>{cta.text}</Link>
      </Button>
    )
  }

  return (
    <Button
      variant={variant}
      size={size}
      className={className}
      onClick={cta.onClick}
      type="button"
    >
      {cta.text}
    </Button>
  )
}
