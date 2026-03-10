import { cn } from '@/lib/utils'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { ReactNode } from 'react'

interface KpiCardProps {
  label: string
  value: string
  sub?: string
  change?: number      // percent change vs prev period
  icon?: ReactNode
  highlight?: boolean  // green glow for primary metric
  className?: string
}

export function KpiCard({ label, value, sub, change, icon, highlight, className }: KpiCardProps) {
  const positive = change !== undefined && change > 0
  const negative = change !== undefined && change < 0
  const neutral  = change !== undefined && change === 0

  return (
    <div className={cn(
      'relative rounded-xl border bg-[hsl(var(--card))] p-4 overflow-hidden transition-all hover:border-[hsl(var(--border)/1.5)]',
      highlight && 'border-[hsl(var(--primary)/0.4)] shadow-[0_0_30px_hsl(var(--primary)/0.08)]',
      className
    )}>
      {/* Subtle top gradient for highlight cards */}
      {highlight && (
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[hsl(var(--primary)/0.5)] to-transparent" />
      )}

      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <p className="text-sm text-[hsl(var(--muted-foreground))] font-medium uppercase tracking-wide truncate">{label}</p>
          <p className={cn(
            'text-2xl font-bold mt-1.5 leading-none',
            highlight ? 'text-[hsl(var(--primary))] metric-glow' : 'text-[hsl(var(--foreground))]'
          )}>
            {value}
          </p>
          {sub && <p className="text-sm text-[hsl(var(--muted-foreground))] mt-1">{sub}</p>}
        </div>
        {icon && (
          <div className={cn(
            'p-2 rounded-lg flex-shrink-0',
            highlight ? 'bg-[hsl(var(--primary)/0.15)]' : 'bg-[hsl(var(--secondary))]'
          )}>
            <span className={cn('w-4 h-4 block', highlight ? 'text-[hsl(var(--primary))]' : 'text-[hsl(var(--muted-foreground))]')}>
              {icon}
            </span>
          </div>
        )}
      </div>

      {change !== undefined && (
        <div className={cn(
          'flex items-center gap-1 mt-3 text-sm font-medium',
          positive && 'text-[hsl(var(--primary))]',
          negative && 'text-[hsl(var(--destructive))]',
          neutral  && 'text-[hsl(var(--muted-foreground))]',
        )}>
          {positive && <TrendingUp className="w-3 h-3" />}
          {negative && <TrendingDown className="w-3 h-3" />}
          {neutral  && <Minus className="w-3 h-3" />}
          <span>{positive ? '+' : ''}{change.toFixed(1)}% vs 上周</span>
        </div>
      )}
    </div>
  )
}
