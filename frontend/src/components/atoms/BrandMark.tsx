export function BrandMark() {
  return (
    <div className="flex items-center gap-3">
      <div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-indigo-600 via-blue-600 to-sky-500 text-sm font-semibold text-white shadow-sm">
        <span className="font-heading tracking-[0.18em]">SP</span>
      </div>
      <div className="leading-tight">
        <div className="font-heading text-sm font-semibold uppercase tracking-[0.22em] text-strong">
          Simple Pro
        </div>
        <div className="text-[11px] font-medium text-quiet">
          Mission Control
        </div>
      </div>
    </div>
  );
}
