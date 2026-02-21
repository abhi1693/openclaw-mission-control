"use client";

import { useState } from "react";

import { ApiError } from "@/api/mutator";
import { useSendGatewaySessionMessageApiV1GatewaysSessionsSessionIdMessagePost } from "@/api/generated/gateways/gateways";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface SendMessageDialogProps {
  sessionId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function SendMessageDialog({
  sessionId,
  open,
  onOpenChange,
}: SendMessageDialogProps) {
  const [content, setContent] = useState("");
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sendMutation =
    useSendGatewaySessionMessageApiV1GatewaysSessionsSessionIdMessagePost<ApiError>({
      mutation: {
        onSuccess: () => {
          setSuccess(true);
          setError(null);
        },
        onError: (err) => {
          setError(err.message || "Failed to send message.");
          setSuccess(false);
        },
      },
    });

  const handleSend = () => {
    if (!content.trim()) {
      setError("Message content is required.");
      return;
    }
    setError(null);
    setSuccess(false);
    sendMutation.mutate({
      sessionId,
      data: { content: content.trim() },
    });
  };

  const handleClose = () => {
    onOpenChange(false);
    setContent("");
    setSuccess(false);
    setError(null);
  };

  const isLoading = sendMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent aria-label="Send message">
        <DialogHeader>
          <DialogTitle>Send message</DialogTitle>
          <DialogDescription>
            Send a message to session {sessionId.slice(0, 8)}...
          </DialogDescription>
        </DialogHeader>

        {success ? (
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4">
            <p className="text-sm font-medium text-emerald-800">
              Message sent successfully
            </p>
            <p className="mt-1 text-sm text-emerald-700">
              The message has been delivered to the session.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-900">
                Message content
              </label>
              <Textarea
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder="Enter your message..."
                className="min-h-[120px]"
                disabled={isLoading}
              />
            </div>
          </div>
        )}

        {error ? (
          <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
            {error}
          </div>
        ) : null}

        <DialogFooter>
          <Button variant="outline" onClick={handleClose}>
            {success ? "Close" : "Cancel"}
          </Button>
          {!success ? (
            <Button onClick={handleSend} disabled={isLoading}>
              {isLoading ? "Sending..." : "Send message"}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
