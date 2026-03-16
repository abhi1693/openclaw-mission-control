import { HeroKicker } from "@/components/atoms/HeroKicker";

export function HeroCopy() {
  return (
    <div className="space-y-6">
      <HeroKicker>OpenClaw Mission Control</HeroKicker>
      <div className="space-y-4">
        <h1 className="font-heading text-4xl font-semibold leading-tight text-strong sm:text-5xl lg:text-6xl">
          Command autonomous work.
          <br />
          <span className="relative inline-flex">
            Keep human oversight.
            <span
              className="absolute inset-x-0 bottom-1 -z-10 h-[0.55em] rounded-md bg-[color:var(--accent-soft)]"
              aria-hidden="true"
            />
          </span>
        </h1>
        <p className="max-w-xl text-base text-muted sm:text-lg">
          Track tasks, approvals, and agent health in one calm surface. Get
          realtime signals when work changes, without chasing people for status.
        </p>
      </div>
    </div>
  );
}
