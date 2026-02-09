"use client";

export const dynamic = "force-dynamic";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import {
  SignInButton,
  SignedIn,
  SignedOut,
  useAuth,
  useUser,
} from "@/auth/clerk";
import { Globe, Info, RotateCcw, Save, User } from "lucide-react";

import { ApiError } from "@/api/mutator";
import {
  type getMeApiV1UsersMeGetResponse,
  useGetMeApiV1UsersMeGet,
  useUpdateMeApiV1UsersMePatch,
} from "@/api/generated/users/users";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import SearchableSelect from "@/components/ui/searchable-select";
import { isOnboardingComplete } from "@/lib/onboarding";
import { getSupportedTimezones } from "@/lib/timezones";

export default function OnboardingPage() {
  const router = useRouter();
  const { isSignedIn } = useAuth();
  const { user } = useUser();

  const [name, setName] = useState("");
  const [timezone, setTimezone] = useState("");
  const [error, setError] = useState<string | null>(null);

  const meQuery = useGetMeApiV1UsersMeGet<
    getMeApiV1UsersMeGetResponse,
    ApiError
  >({
    query: {
      enabled: Boolean(isSignedIn),
      retry: false,
      refetchOnMount: "always",
    },
  });

  const updateMeMutation = useUpdateMeApiV1UsersMePatch<ApiError>({
    mutation: {
      onSuccess: () => {
        router.replace("/dashboard");
      },
      onError: (err) => {
        setError(err.message || "Something went wrong.");
      },
    },
  });

  const isLoading = meQuery.isLoading || updateMeMutation.isPending;
  const loadError = meQuery.error?.message ?? null;
  const errorMessage = error ?? loadError;
  const profile = meQuery.data?.status === 200 ? meQuery.data.data : null;

  const clerkFallbackName =
    user?.fullName ?? user?.firstName ?? user?.username ?? "";
  const resolvedName = name.trim()
    ? name
    : (profile?.preferred_name ?? profile?.name ?? clerkFallbackName ?? "");
  const resolvedTimezone = timezone.trim()
    ? timezone
    : (profile?.timezone ?? "");

  const requiredMissing = useMemo(
    () => [resolvedName, resolvedTimezone].some((value) => !value.trim()),
    [resolvedName, resolvedTimezone],
  );

  const timezones = useMemo(() => getSupportedTimezones(), []);

  const timezoneOptions = useMemo(
    () => timezones.map((tz) => ({ value: tz, label: tz })),
    [timezones],
  );

  useEffect(() => {
    if (profile && isOnboardingComplete(profile)) {
      router.replace("/dashboard");
    }
  }, [profile, router]);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isSignedIn) return;
    if (requiredMissing) {
      setError("Please complete the required fields.");
      return;
    }
    setError(null);
    try {
      const normalizedName = resolvedName.trim();
      const payload = {
        name: normalizedName,
        preferred_name: normalizedName,
        timezone: resolvedTimezone.trim(),
      };
      await updateMeMutation.mutateAsync({ data: payload });
    } catch {
      // handled by onError
    }
  };

  return (
    <DashboardShell>
      <SignedOut>
        <div className="lg:col-span-2 flex min-h-[70vh] items-center justify-center">
          <div className="w-full max-w-2xl rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="border-b border-slate-100 px-6 py-5">
              <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
                Mission Control profile
              </h1>
              <p className="mt-1 text-sm text-slate-600">
                Sign in to configure your profile and timezone.
              </p>
            </div>
            <div className="px-6 py-6">
              <SignInButton
                mode="modal"
                forceRedirectUrl="/onboarding"
                signUpForceRedirectUrl="/onboarding"
              >
                <Button size="lg">Sign in</Button>
              </SignInButton>
            </div>
          </div>
        </div>
      </SignedOut>
      <SignedIn>
        <div className="lg:col-span-2 flex min-h-[70vh] items-center justify-center">
          <section className="w-full max-w-2xl rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="border-b border-slate-100 px-6 py-5">
              <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
                Mission Control profile
              </h1>
              <p className="mt-1 text-sm text-slate-600">
                Configure your mission control settings and preferences.
              </p>
            </div>
            <div className="px-6 py-6">
              <form onSubmit={handleSubmit} className="space-y-6">
                <div className="grid gap-6 md:grid-cols-2">
                  <div className="space-y-2">
                    <label className="text-sm font-medium text-slate-700 flex items-center gap-2">
                      <User className="h-4 w-4 text-slate-500" />
                      Name
                      <span className="text-red-500">*</span>
                    </label>
                    <Input
                      value={resolvedName}
                      onChange={(event) => setName(event.target.value)}
                      placeholder="Enter your name"
                      disabled={isLoading}
                      className="border-slate-300 text-slate-900 focus-visible:ring-blue-500"
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium text-slate-700 flex items-center gap-2">
                      <Globe className="h-4 w-4 text-slate-500" />
                      Timezone
                      <span className="text-red-500">*</span>
                    </label>
                    <SearchableSelect
                      ariaLabel="Select timezone"
                      value={resolvedTimezone}
                      onValueChange={setTimezone}
                      options={timezoneOptions}
                      placeholder="Select timezone"
                      searchPlaceholder="Search timezones..."
                      emptyMessage="No matching timezones."
                      triggerClassName="w-full h-11 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-900 shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                      contentClassName="rounded-xl border border-slate-200 shadow-lg"
                      itemClassName="px-4 py-3 text-sm text-slate-700 data-[selected=true]:bg-slate-50 data-[selected=true]:text-slate-900"
                    />
                  </div>
                </div>

                <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800 flex items-start gap-3">
                  <Info className="mt-0.5 h-4 w-4 text-blue-600" />
                  <p>
                    <strong>Note:</strong> Your timezone is used to display all
                    timestamps and schedule mission-critical events accurately.
                  </p>
                </div>

                {errorMessage ? (
                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
                    {errorMessage}
                  </div>
                ) : null}

                <div className="flex flex-wrap gap-3 pt-2">
                  <Button
                    type="submit"
                    className="flex-1 bg-blue-600 text-white hover:bg-blue-700 py-2.5"
                    disabled={isLoading || requiredMissing}
                  >
                    <Save className="h-4 w-4" />
                    {isLoading ? "Saving…" : "Save Profile"}
                  </Button>
                  <button
                    type="button"
                    onClick={() => {
                      setName("");
                      setTimezone("");
                      setError(null);
                    }}
                    className="flex-1 rounded-md border border-slate-300 px-4 py-2.5 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50"
                  >
                    <span className="inline-flex items-center gap-2">
                      <RotateCcw className="h-4 w-4" />
                      Reset
                    </span>
                  </button>
                </div>
              </form>
            </div>
          </section>
        </div>
      </SignedIn>
    </DashboardShell>
  );
}
