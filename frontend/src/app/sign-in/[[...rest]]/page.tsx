"use client";

import { SignIn } from "@clerk/nextjs";

export default function SignInPage() {
  // Dedicated sign-in route for Cypress E2E.
  // Avoids modal/iframe auth flows and gives Cypress a stable top-level page.
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 p-6">
      <SignIn routing="path" path="/sign-in" forceRedirectUrl="/activity" />
    </main>
  );
}
