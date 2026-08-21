"use client"

import * as React from "react"
import { Popover as PopoverPrimitive } from "radix-ui"

import { cn } from "@/lib/utils"

function Popover({ ...props }: React.ComponentProps<typeof PopoverPrimitive.Root>) {
  return <PopoverPrimitive.Root data-slot="popover" {...props} />
}

function PopoverTrigger({ ...props }: React.ComponentProps<typeof PopoverPrimitive.Trigger>) {
  return <PopoverPrimitive.Trigger data-slot="popover-trigger" {...props} />
}

function PopoverContent({
  className,
  align = "start",
  sideOffset = 4,
  portal = true,
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Content> & { portal?: boolean }) {
  const content = (
    <PopoverPrimitive.Content
      data-slot="popover-content"
      align={align}
      sideOffset={sideOffset}
      className={cn(
        "z-50 w-(--radix-popover-trigger-width) rounded-lg bg-popover p-0 text-popover-foreground shadow-md ring-1 ring-foreground/10 outline-none data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
        className
      )}
      {...props}
    />
  )

  // `portal={false}` existe por causa do Dialog: o react-remove-scroll que o
  // Radix Dialog usa so permite rolar dentro do elemento travado
  // (handleScroll.js: `endTarget.contains(target)`), e conteudo portalado para
  // o body fica fora dele — o dropdown abre mas nao rola. Sem portal, o
  // conteudo vira descendente do DialogContent e o scroll volta a funcionar.
  return portal ? <PopoverPrimitive.Portal>{content}</PopoverPrimitive.Portal> : content
}

export { Popover, PopoverTrigger, PopoverContent }
