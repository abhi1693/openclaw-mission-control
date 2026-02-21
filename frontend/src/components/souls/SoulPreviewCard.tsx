"use client";

import Link from "next/link";
import { Copy, Eye } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { SoulsDirectorySoulRef } from "@/api/generated/model";

interface SoulPreviewCardProps {
  soul: SoulsDirectorySoulRef;
  onCopy?: (soul: SoulsDirectorySoulRef) => void;
  onApply?: (soul: SoulsDirectorySoulRef) => void;
  showApply?: boolean;
}

export function SoulPreviewCard({
  soul,
  onCopy,
  onApply,
  showApply = false,
}: SoulPreviewCardProps) {
  const handleCopy = () => {
    const refText = `${soul.handle}/${soul.slug}`;
    navigator.clipboard.writeText(refText);
    onCopy?.(soul);
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:shadow-md">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-slate-900 truncate">
            {soul.slug}
          </p>
          <p className="mt-1 text-xs text-slate-500 font-mono">
            @{soul.handle}
          </p>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-2">
        <Button variant="outline" size="sm" asChild>
          <Link href={`/souls/${soul.handle}/${soul.slug}`}>
            <Eye className="mr-1.5 h-3.5 w-3.5" />
            View
          </Link>
        </Button>
        <Button variant="outline" size="sm" onClick={handleCopy}>
          <Copy className="mr-1.5 h-3.5 w-3.5" />
          Copy ref
        </Button>
        {showApply && onApply ? (
          <Button size="sm" onClick={() => onApply(soul)}>
            Apply
          </Button>
        ) : null}
      </div>
    </div>
  );
}
