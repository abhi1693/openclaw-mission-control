import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em]",
  {
    variants: {
      variant: {
        default: "bg-[color:var(--surface-muted)] text-strong",
        outline:
          "border border-[color:var(--border-strong)] text-[color:var(--text-muted)]",
        accent:
          "bg-[color:var(--accent-soft)] text-[color:var(--accent-strong)]",
        success: "bg-[color:rgba(15,118,110,0.14)] text-[color:var(--success)]",
        warning: "bg-[color:rgba(180,83,9,0.15)] text-[color:var(--warning)]",
        danger: "bg-[color:rgba(180,35,24,0.15)] text-[color:var(--danger)]",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends
    React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
