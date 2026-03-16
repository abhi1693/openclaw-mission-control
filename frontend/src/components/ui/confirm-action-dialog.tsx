import type { ReactNode } from "react";

import { Button, type ButtonProps } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

type ConfirmActionDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: ReactNode;
  onConfirm: () => void;
  isConfirming: boolean;
  errorMessage?: string | null;
  confirmLabel?: string;
  confirmingLabel?: string;
  cancelLabel?: string;
  cancelVariant?: NonNullable<ButtonProps["variant"]>;
  errorStyle?: "text" | "panel";
  ariaLabel?: string;
};

export function ConfirmActionDialog({
  open,
  onOpenChange,
  title,
  description,
  onConfirm,
  isConfirming,
  errorMessage,
  confirmLabel = "Delete",
  confirmingLabel = "Deleting…",
  cancelLabel = "Cancel",
  cancelVariant = "outline",
  errorStyle = "panel",
  ariaLabel,
}: ConfirmActionDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-label={ariaLabel}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {errorMessage ? (
          errorStyle === "text" ? (
            <p className="text-sm text-red-500">{errorMessage}</p>
          ) : (
            <div className="rounded-lg border border-[color:var(--border)] bg-[color:var(--surface-muted)] p-3 text-xs text-muted">
              {errorMessage}
            </div>
          )
        ) : null}
        <DialogFooter>
          <Button variant={cancelVariant} onClick={() => onOpenChange(false)}>
            {cancelLabel}
          </Button>
          <Button onClick={onConfirm} disabled={isConfirming}>
            {isConfirming ? confirmingLabel : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
