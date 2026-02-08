import { NextResponse } from "next/server";
import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

import { isLikelyValidClerkPublishableKey } from "@/auth/clerkKey";

const isClerkEnabled = () =>
  isLikelyValidClerkPublishableKey(
    process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY,
  );

// Public routes must include Clerk sign-in paths to avoid redirect loops.
// Also keep top-level UI routes like /activity public so the app can render a signed-out state
// (the page itself shows a SignIn button; API routes remain protected elsewhere).
const isPublicRoute = createRouteMatcher(["/sign-in(.*)", "/activity(.*)"]);

export default isClerkEnabled()
  ? clerkMiddleware(async (auth, req) => {
      if (isPublicRoute(req)) return NextResponse.next();

      // In middleware, `auth()` resolves to a session/auth context (Promise in current typings).
      // Use redirectToSignIn() (instead of protect()) for unauthenticated requests.
      const { userId, redirectToSignIn } = await auth();
      if (!userId) {
        return redirectToSignIn({ returnBackUrl: req.url });
      }

      return NextResponse.next();
    })
  : () => NextResponse.next();

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
