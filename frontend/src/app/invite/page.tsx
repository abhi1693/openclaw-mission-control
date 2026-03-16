"use client";

export const dynamic = "force-dynamic";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { SignInButton, SignedIn, SignedOut, useAuth } from "@/auth/clerk";

import { ApiError } from "@/api/mutator";
import { useAcceptOrgInviteApiV1OrganizationsInvitesAcceptPost } from "@/api/generated/organizations/organizations";
import { BrandMark } from "@/components/atoms/BrandMark";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

function InviteContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { isSignedIn } = useAuth();

  const tokenFromQuery = (searchParams.get("token") ?? "").trim();
  const [token, setToken] = useState(tokenFromQuery);
  const [error, setError] = useState<string | null>(null);
  const [accepted, setAccepted] = useState(false);

  useEffect(() => {
    setToken(tokenFromQuery);
  }, [tokenFromQuery]);

  const acceptInviteMutation =
    useAcceptOrgInviteApiV1OrganizationsInvitesAcceptPost<ApiError>({
      mutation: {
        onSuccess: (result) => {
          if (result.status === 200) {
            setAccepted(true);
            setError(null);
            setTimeout(() => router.push("/organization"), 800);
          }
        },
        onError: (err) => {
          setError(err.message || "Unable to accept invite.");
        },
      },
    });

  const handleAccept = (event?: React.FormEvent) => {
    event?.preventDefault();
    if (!isSignedIn) return;
    const trimmed = token.trim();
    if (!trimmed) {
      setError("Invite token is required.");
      return;
    }
    setError(null);
    acceptInviteMutation.mutate({ data: { token: trimmed } });
  };

  const isSubmitting = acceptInviteMutation.isPending;
  const isReady = Boolean(token.trim());
  const helperText = useMemo(() => {
    if (accepted) {
      return "Invite accepted. Redirecting to your organization…";
    }
    if (!token.trim()) {
      return "Paste the invite token or open the invite link you were sent.";
    }
    return "Accept the invite to join the organization.";
  }, [accepted, token]);

  return (
    <div className="min-h-screen bg-app text-strong">
      <header className="border-b border-[color:var(--border)] bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <BrandMark />
        </div>
      </header>

      <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-16">
        <div className="rounded-2xl border border-[color:var(--border)] bg-[color:var(--surface)] p-4 md:p-8 shadow-sm">
          <div className="flex flex-col gap-3">
            <p className="text-xs font-semibold uppercase tracking-[0.3em] text-quiet">
              Organization Invite
            </p>
            <h1 className="text-2xl font-semibold text-strong">
              Join your team in OpenClaw
            </h1>
            <p className="text-sm text-muted">{helperText}</p>
          </div>

          <div className="mt-6 flex flex-col gap-4">
            <label className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
              Invite Token
            </label>
            <Input
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="Paste invite token"
              disabled={accepted || isSubmitting}
            />

            {error ? (
              <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-600">
                {error}
              </div>
            ) : null}

            <SignedOut>
              <div className="flex flex-col gap-3 rounded-xl border border-dashed border-[color:var(--border)] bg-[color:var(--surface-muted)] p-4 text-sm text-muted">
                <p>Sign in to accept your invite.</p>
                <SignInButton mode="modal">
                  <Button size="md">Sign in</Button>
                </SignInButton>
              </div>
            </SignedOut>

            <SignedIn>
              <form
                className="flex flex-wrap items-center gap-3"
                onSubmit={handleAccept}
              >
                <Button
                  type="submit"
                  size="md"
                  disabled={!isReady || isSubmitting || accepted}
                >
                  {accepted
                    ? "Invite accepted"
                    : isSubmitting
                      ? "Accepting…"
                      : "Accept invite"}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="md"
                  onClick={() => router.push("/")}
                  disabled={isSubmitting}
                >
                  Go back
                </Button>
              </form>
            </SignedIn>
          </div>
        </div>
      </main>
    </div>
  );
}

export default function InvitePage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-app text-strong">
          <header className="border-b border-[color:var(--border)] bg-white">
            <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
              <BrandMark />
            </div>
          </header>
          <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-16">
            <div className="rounded-2xl border border-[color:var(--border)] bg-[color:var(--surface)] p-4 md:p-8 shadow-sm">
              <div className="text-sm text-muted">Loading invite…</div>
            </div>
          </main>
        </div>
      }
    >
      <InviteContent />
    </Suspense>
  );
}
