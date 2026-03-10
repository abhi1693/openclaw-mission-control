'use client'
import { useEffect, useState, useCallback } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Separator } from '@/components/ui/separator'
import { DashboardPageLayout } from '@/components/templates/DashboardPageLayout'
import {
  RefreshCw, ChevronDown, ChevronUp, TrendingDown, TrendingUp,
  Star, MessageSquare, Tag, AlertTriangle, Swords, BarChart3
} from 'lucide-react'

// ─── Types ───────────────────────────────────────────────────────────────────

interface CompetitorSnapshot {
  asin: string
  name: string
  brand: string
  category: string
  price: number | null
  currency: string
  bsr: number | null
  rating: number | null
  reviewCount: number | null
  imageUrl: string | null
  hasDeal: boolean
  couponText: string | null
  timestamp: string
}

interface CompetitorAlert {
  asin: string
  name: string
  type: 'price_drop' | 'price_increase' | 'bsr_improvement' | 'deal_active' | 'review_surge'
  message: string
  oldValue: number | string | null
  newValue: number | string | null
  timestamp: string
}

interface HistoryEntry {
  asin: string
  price: number | null
  bsr: number | null
  snapshotTime: string
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fmtPrice(price: number | null, currency = 'USD') {
  if (price === null) return 'N/A'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(price)
}

function fmtNumber(n: number | null) {
  if (n === null) return 'N/A'
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`
  return n.toString()
}

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

function alertTypeColor(type: CompetitorAlert['type']) {
  switch (type) {
    case 'price_drop': return 'text-rose-600'
    case 'price_increase': return 'text-yellow-600'
    case 'bsr_improvement': return 'text-blue-600'
    case 'deal_active': return 'text-orange-400'
    case 'review_surge': return 'text-purple-400'
    default: return 'text-slate-500'
  }
}

function alertTypeLabel(type: CompetitorAlert['type']) {
  switch (type) {
    case 'price_drop': return '📉 Price Drop'
    case 'price_increase': return '📈 Price Rise'
    case 'bsr_improvement': return '🚀 BSR Up'
    case 'deal_active': return '🏷️ Deal'
    case 'review_surge': return '⭐ Review Surge'
    default: return type
  }
}

// ─── Mini Trend SVG ──────────────────────────────────────────────────────────

function MiniTrend({ data, color = '#22c55e' }: { data: number[]; color?: string }) {
  if (data.length < 2) {
    return <div className="h-8 flex items-center text-xs text-[hsl(var(--muted-foreground))]">Not enough data</div>
  }
  const w = 120, h = 32, pad = 2
  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const points = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * (w - pad * 2)
    const y = pad + ((max - v) / range) * (h - pad * 2)
    return `${x},${y}`
  }).join(' ')
  return (
    <svg width={w} height={h} className="overflow-visible">
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

// ─── Competitor Card ─────────────────────────────────────────────────────────

function CompetitorCard({
  snapshot,
  history,
}: {
  snapshot: CompetitorSnapshot
  history: HistoryEntry[]
}) {
  const myHistory = history.filter(h => h.asin === snapshot.asin)
  const priceHistory = myHistory.map(h => h.price).filter((p): p is number => p !== null)

  const prevPrice = priceHistory.length > 1 ? priceHistory[priceHistory.length - 2] : null
  const priceChange = prevPrice && snapshot.price ? snapshot.price - prevPrice : null
  const priceChangePct = prevPrice && priceChange ? (priceChange / prevPrice) * 100 : null

  return (
    <div className="bg-[hsl(var(--card))] border border-[hsl(var(--border))] rounded-xl p-4 flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-[hsl(var(--foreground))] truncate">{snapshot.name}</p>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">{snapshot.brand} · {snapshot.asin}</p>
        </div>
        {snapshot.imageUrl ? (
          <img src={snapshot.imageUrl} alt={snapshot.name} className="w-12 h-12 object-contain rounded bg-white/5 flex-shrink-0" />
        ) : (
          <div className="w-12 h-12 rounded bg-[hsl(var(--secondary))] flex-shrink-0 flex items-center justify-center">
            <BarChart3 className="w-5 h-5 text-[hsl(var(--muted-foreground))]" />
          </div>
        )}
      </div>

      <Separator className="bg-[hsl(var(--border))]" />

      {/* Price */}
      <div className="flex items-end justify-between">
        <div>
          <p className="text-xs text-[hsl(var(--muted-foreground))] mb-0.5">Price</p>
          <p className="text-2xl font-bold text-[hsl(var(--foreground))]">{fmtPrice(snapshot.price, snapshot.currency)}</p>
        </div>
        {priceChangePct !== null && (
          <div className={`flex items-center gap-1 text-sm font-medium ${priceChangePct < 0 ? 'text-rose-600' : 'text-green-600'}`}>
            {priceChangePct < 0 ? <TrendingDown className="w-4 h-4" /> : <TrendingUp className="w-4 h-4" />}
            {Math.abs(priceChangePct).toFixed(1)}%
          </div>
        )}
      </div>

      {/* BSR + Rating + Reviews */}
      <div className="grid grid-cols-3 gap-2">
        <div className="bg-[hsl(var(--secondary))] rounded-lg p-2">
          <p className="text-[9px] text-[hsl(var(--muted-foreground))] uppercase tracking-wider mb-0.5">BSR</p>
          <p className="text-sm font-semibold text-[hsl(var(--foreground))]">
            {snapshot.bsr ? `#${fmtNumber(snapshot.bsr)}` : 'N/A'}
          </p>
        </div>
        <div className="bg-[hsl(var(--secondary))] rounded-lg p-2">
          <p className="text-[9px] text-[hsl(var(--muted-foreground))] uppercase tracking-wider mb-0.5">Rating</p>
          <div className="flex items-center gap-0.5">
            <Star className="w-3 h-3 text-yellow-600 fill-yellow-400" />
            <p className="text-sm font-semibold text-[hsl(var(--foreground))]">
              {snapshot.rating?.toFixed(1) ?? 'N/A'}
            </p>
          </div>
        </div>
        <div className="bg-[hsl(var(--secondary))] rounded-lg p-2">
          <p className="text-[9px] text-[hsl(var(--muted-foreground))] uppercase tracking-wider mb-0.5">Reviews</p>
          <div className="flex items-center gap-0.5">
            <MessageSquare className="w-3 h-3 text-[hsl(var(--muted-foreground))]" />
            <p className="text-sm font-semibold text-[hsl(var(--foreground))]">{fmtNumber(snapshot.reviewCount)}</p>
          </div>
        </div>
      </div>

      {/* Deal badge */}
      {snapshot.hasDeal && (
        <div className="flex items-center gap-2">
          <Badge variant="danger" className="text-[10px] flex items-center gap-1">
            <Tag className="w-2.5 h-2.5" />
            DEAL ACTIVE
          </Badge>
          {snapshot.couponText && (
            <span className="text-[10px] text-orange-400">{snapshot.couponText}</span>
          )}
        </div>
      )}

      {/* Mini trend */}
      {priceHistory.length >= 2 && (
        <div>
          <p className="text-[9px] text-[hsl(var(--muted-foreground))] mb-1 uppercase tracking-wider">Price trend</p>
          <MiniTrend data={priceHistory} color={priceChangePct && priceChangePct < 0 ? '#f87171' : '#22c55e'} />
        </div>
      )}

      <p className="text-[9px] text-[hsl(var(--muted-foreground))] opacity-60 mt-auto">Updated {timeAgo(snapshot.timestamp)}</p>
    </div>
  )
}

// ─── History Charts ───────────────────────────────────────────────────────────

function HistoryChart({ history, field, label, color }: {
  history: HistoryEntry[]
  field: 'price' | 'bsr'
  label: string
  color: string
}) {
  // Group by ASIN
  const asinMap: Record<string, HistoryEntry[]> = {}
  for (const h of history) {
    if (!asinMap[h.asin]) asinMap[h.asin] = []
    asinMap[h.asin].push(h)
  }

  const asinColors = ['#22c55e', '#3b82f6', '#f59e0b', '#ec4899', '#8b5cf6']
  const asins = Object.keys(asinMap)

  if (asins.length === 0 || history.length === 0) {
    return (
      <div className="bg-[hsl(var(--card))] border border-[hsl(var(--border))] rounded-xl p-4">
        <p className="text-sm font-semibold text-[hsl(var(--foreground))] mb-2">{label}</p>
        <div className="h-24 flex items-center justify-center text-sm text-[hsl(var(--muted-foreground))]">
          No data yet — run Refresh Snapshot to populate
        </div>
      </div>
    )
  }

  const allValues = history.map(h => h[field]).filter((v): v is number => v !== null)
  if (allValues.length === 0) {
    return (
      <div className="bg-[hsl(var(--card))] border border-[hsl(var(--border))] rounded-xl p-4">
        <p className="text-sm font-semibold text-[hsl(var(--foreground))] mb-2">{label}</p>
        <div className="h-24 flex items-center justify-center text-xs text-[hsl(var(--muted-foreground))]">
          {field === 'bsr' ? 'BSR data not available (requires Product Advertising API)' : 'No price data yet'}
        </div>
      </div>
    )
  }

  const min = Math.min(...allValues)
  const max = Math.max(...allValues)
  const range = max - min || 1

  const W = 600, H = 100, PAD = 8

  // All timestamps sorted
  const allTimes = [...new Set(history.map(h => h.snapshotTime))].sort()

  return (
    <div className="bg-[hsl(var(--card))] border border-[hsl(var(--border))] rounded-xl p-4">
      <p className="text-sm font-semibold text-[hsl(var(--foreground))] mb-3">{label}</p>
      <div className="overflow-x-auto">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ minWidth: 300, height: 100 }}>
          {asins.map((asin, ai) => {
            const entries = asinMap[asin]
            const pts = entries
              .map(e => {
                const v = e[field]
                if (v === null) return null
                const xi = allTimes.indexOf(e.snapshotTime)
                const x = PAD + (xi / Math.max(allTimes.length - 1, 1)) * (W - PAD * 2)
                const y = PAD + ((max - v) / range) * (H - PAD * 2)
                return `${x},${y}`
              })
              .filter(Boolean)
            if (pts.length < 2) return null
            return (
              <polyline
                key={asin}
                points={pts.join(' ')}
                fill="none"
                stroke={asinColors[ai % asinColors.length]}
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            )
          })}
        </svg>
      </div>
      {/* Legend */}
      <div className="flex flex-wrap gap-3 mt-2">
        {asins.map((asin, ai) => (
          <div key={asin} className="flex items-center gap-1.5">
            <div className="w-3 h-0.5 rounded" style={{ backgroundColor: asinColors[ai % asinColors.length] }} />
            <span className="text-[10px] text-[hsl(var(--muted-foreground))]">
              {asinMap[asin][0]?.asin ?? asin}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Page ────────────────────────────────────────────────────────────────────

function CompetitorsPageContent() {
  const [snapshots, setSnapshots] = useState<CompetitorSnapshot[]>([])
  const [alerts, setAlerts] = useState<CompetitorAlert[]>([])
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [alertsOpen, setAlertsOpen] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)

  const loadData = useCallback(async () => {
    try {
      const [snapRes, alertRes, histRes] = await Promise.all([
        fetch('/api/competitors'),
        fetch('/api/competitors/alerts'),
        fetch('/api/competitors/history?days=30'),
      ])
      const snapData = await snapRes.json()
      const alertData = await alertRes.json()
      const histData = await histRes.json()

      setSnapshots(snapData.data ?? [])
      setAlerts(alertData.alerts ?? [])
      setHistory(histData.data ?? [])

      if (snapData.data?.length > 0) {
        setLastUpdated(snapData.data[0].timestamp)
      }
    } catch (err) {
      console.error('Failed to load competitor data:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadData() }, [loadData])

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      const res = await fetch('/api/competitors/snapshot', { method: 'POST' })
      const data = await res.json()
      if (data.snapshot) {
        setSnapshots(data.snapshot)
        if (data.alerts?.length > 0) {
          setAlerts(prev => [...data.alerts, ...prev].slice(0, 100))
          setAlertsOpen(true)
        }
        setLastUpdated(data.timestamp)
        // Reload history
        const histRes = await fetch('/api/competitors/history?days=30')
        const histData = await histRes.json()
        setHistory(histData.data ?? [])
      }
    } catch (err) {
      console.error('Refresh failed:', err)
    } finally {
      setRefreshing(false)
    }
  }

  const recentAlerts = alerts.slice(-20).reverse()

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
      {/* Controls */}
      <div className="flex items-center justify-end gap-3 flex-wrap">
          {lastUpdated && (
            <span className="text-xs text-[hsl(var(--muted-foreground))]">
              Last updated: {timeAgo(lastUpdated)}
            </span>
          )}
          <Button
            size="sm"
            onClick={handleRefresh}
            disabled={refreshing}
            className="flex items-center gap-2"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} />
            {refreshing ? 'Refreshing…' : 'Refresh Snapshot'}
          </Button>
        </div>

      {/* Alert Banner */}
      {recentAlerts.length > 0 && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 shadow-sm overflow-hidden">
          <button
            onClick={() => setAlertsOpen(o => !o)}
            className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-rose-100 transition-colors"
          >
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-rose-600" />
              <span className="text-sm font-semibold text-rose-600">
                {recentAlerts.length} Alert{recentAlerts.length !== 1 ? 's' : ''} Detected
              </span>
            </div>
            {alertsOpen ? <ChevronUp className="w-4 h-4 text-rose-600" /> : <ChevronDown className="w-4 h-4 text-rose-600" />}
          </button>
          {alertsOpen && (
            <div className="px-4 pb-3 space-y-2">
              {recentAlerts.slice(0, 5).map((alert, i) => (
                <div key={i} className="flex items-start justify-between gap-3 py-1.5 border-t border-rose-100">
                  <div className="flex items-start gap-2">
                    <span className={`text-xs font-medium ${alertTypeColor(alert.type)} mt-0.5`}>
                      {alertTypeLabel(alert.type)}
                    </span>
                    <span className="text-xs text-[hsl(var(--muted-foreground))]">
                      <span className="text-slate-900 font-medium">{alert.name}</span> — {alert.message}
                    </span>
                  </div>
                  <span className="text-[10px] text-[hsl(var(--muted-foreground))] flex-shrink-0">{timeAgo(alert.timestamp)}</span>
                </div>
              ))}
              {recentAlerts.length > 5 && (
                <p className="text-xs text-[hsl(var(--muted-foreground))] pt-1">+ {recentAlerts.length - 5} more alerts</p>
              )}
            </div>
          )}
        </div>
      )}

      {/* Competitor Cards */}
      <div>
        <h2 className="text-sm font-semibold text-[hsl(var(--muted-foreground))] uppercase tracking-wider mb-3">Competitor Snapshots</h2>
        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1, 2, 3].map(i => (
              <div key={i} className="bg-[hsl(var(--card))] border border-[hsl(var(--border))] rounded-xl p-4 space-y-3">
                <Skeleton className="h-5 w-2/3" />
                <Skeleton className="h-4 w-1/2" />
                <Skeleton className="h-8 w-1/3" />
                <div className="grid grid-cols-3 gap-2">
                  <Skeleton className="h-12 rounded-lg" />
                  <Skeleton className="h-12 rounded-lg" />
                  <Skeleton className="h-12 rounded-lg" />
                </div>
              </div>
            ))}
          </div>
        ) : snapshots.length === 0 ? (
          <div className="bg-[hsl(var(--card))] border border-[hsl(var(--border))] rounded-xl p-8 text-center">
            <Swords className="w-8 h-8 text-[hsl(var(--muted-foreground))] mx-auto mb-3" />
            <p className="text-sm font-medium text-[hsl(var(--foreground))] mb-1">No snapshot data yet</p>
            <p className="text-xs text-[hsl(var(--muted-foreground))]">
              Click &ldquo;Refresh Snapshot&rdquo; to fetch competitor data from Amazon SP-API.
              <br />
              Make sure to update ASIN placeholders in <code className="text-[hsl(var(--primary))]">src/lib/competitors.ts</code>.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {snapshots.map(snapshot => (
              <CompetitorCard key={snapshot.asin} snapshot={snapshot} history={history} />
            ))}
          </div>
        )}
      </div>

      {/* History Charts */}
      <div>
        <h2 className="text-sm font-semibold text-[hsl(var(--muted-foreground))] uppercase tracking-wider mb-3">历史趋势 (30天)</h2>
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <HistoryChart history={history} field="price" label="Price Trend" color="#22c55e" />
          <HistoryChart history={history} field="bsr" label="BSR Trend" color="#3b82f6" />
        </div>
      </div>
    </div>
  )
}
export default function CompetitorsPage() {
  return (
    <DashboardPageLayout
      signedOut={{ message: 'Sign in to view competitors', forceRedirectUrl: '/competitors' }}
      title="Competitors"
      description="竞品监控"
    >
      <CompetitorsPageContent />
    </DashboardPageLayout>
  )
}
