'use client'

import { useState, useEffect, useCallback } from 'react'
import { KpiCard } from '@/components/shared/KpiCard'
import { Star, MessageSquare, AlertTriangle, Clock, RefreshCw, ChevronDown, ChevronUp } from 'lucide-react'
import { cn } from '@/lib/utils'
import { DashboardPageLayout } from '@/components/templates/DashboardPageLayout'

// ─── Types ────────────────────────────────────────────────────────────────────

interface ReviewItem {
  title: string
  rating: number
  date: string
  text: string
  verified: boolean
}

interface ReviewCache {
  asin: string
  productName: string
  rating: number
  totalReviews: number
  ratingDistribution: Record<string, number>
  recentReviews: ReviewItem[]
  lastCrawled: string
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function StarRating({ rating }: { rating: number }) {
  return (
    <span className="flex items-center gap-0.5">
      {[1, 2, 3, 4, 5].map((s) => (
        <Star
          key={s}
          className={cn('w-3 h-3', s <= Math.round(rating) ? 'fill-amber-400 text-amber-400' : 'text-[hsl(var(--muted-foreground))] opacity-30')}
        />
      ))}
    </span>
  )
}

function RatingBar({ distribution, total }: { distribution: Record<string, number>; total: number }) {
  return (
    <div className="flex flex-col gap-0.5 min-w-[120px]">
      {[5, 4, 3, 2, 1].map((star) => {
        const count = distribution[String(star)] ?? 0
        const pct = total > 0 ? (count / total) * 100 : 0
        return (
          <div key={star} className="flex items-center gap-1.5">
            <span className="text-[10px] text-[hsl(var(--muted-foreground))] w-3">{star}</span>
            <div className="flex-1 h-1.5 rounded-full bg-[hsl(var(--secondary))] overflow-hidden">
              <div
                className="h-full rounded-full bg-amber-400"
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="text-[10px] text-[hsl(var(--muted-foreground))] w-5 text-right">{count}</span>
          </div>
        )
      })}
    </div>
  )
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  } catch {
    return iso
  }
}

function formatCrawlTime(iso: string): string {
  try {
    const diff = Date.now() - new Date(iso).getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return '刚刚'
    if (mins < 60) return `${mins} 分钟前`
    const hrs = Math.floor(mins / 60)
    return `${hrs} 小时前`
  } catch {
    return iso
  }
}

// ─── Row component ────────────────────────────────────────────────────────────

function ProductRow({ product }: { product: ReviewCache }) {
  const [expanded, setExpanded] = useState(false)
  const isLow = product.rating < 4.0
  const negReviews = product.recentReviews.filter((r) => r.rating < 3)
  const latestNeg = negReviews[0]

  return (
    <>
      <tr
        onClick={() => setExpanded((e) => !e)}
        className={cn(
          'border-b border-[hsl(var(--border)/0.5)] cursor-pointer transition-colors',
          isLow
            ? 'bg-[hsl(0_72%_51%/0.07)] hover:bg-[hsl(0_72%_51%/0.12)]'
            : 'hover:bg-[hsl(var(--secondary))]'
        )}
      >
        {/* Product name */}
        <td className="px-4 py-3">
          <div className="flex items-center gap-2">
            {isLow && <AlertTriangle className="w-3.5 h-3.5 text-[hsl(var(--destructive))] flex-shrink-0" />}
            <span className={cn('text-sm font-medium', isLow ? 'text-[hsl(var(--destructive))]' : 'text-[hsl(var(--foreground))]')}>
              {product.productName}
            </span>
          </div>
        </td>
        {/* ASIN */}
        <td className="px-4 py-3">
          <span className="font-mono text-xs text-[hsl(var(--muted-foreground))]">{product.asin}</span>
        </td>
        {/* Rating */}
        <td className="px-4 py-3">
          <div className="flex items-center gap-2">
            <span className={cn('text-sm font-bold', isLow ? 'text-[hsl(var(--destructive))]' : 'text-[hsl(var(--foreground))]')}>
              {product.rating.toFixed(1)}
            </span>
            <StarRating rating={product.rating} />
          </div>
        </td>
        {/* Review count */}
        <td className="px-4 py-3 text-sm text-[hsl(var(--foreground))]">
          {product.totalReviews.toLocaleString()}
        </td>
        {/* Rating distribution */}
        <td className="px-4 py-3">
          <RatingBar distribution={product.ratingDistribution} total={product.totalReviews} />
        </td>
        {/* Latest negative review */}
        <td className="px-4 py-3">
          {latestNeg ? (
            <div className="max-w-[220px]">
              <p className="text-xs font-medium text-[hsl(var(--destructive))] truncate">{latestNeg.title}</p>
              <p className="text-[10px] text-[hsl(var(--muted-foreground))] truncate mt-0.5">{latestNeg.text}</p>
            </div>
          ) : (
            <span className="text-xs text-[hsl(var(--muted-foreground))] opacity-50">—</span>
          )}
        </td>
        {/* Expand toggle */}
        <td className="px-3 py-3 text-right">
          {expanded
            ? <ChevronUp className="w-4 h-4 text-[hsl(var(--muted-foreground))] inline" />
            : <ChevronDown className="w-4 h-4 text-[hsl(var(--muted-foreground))] inline" />}
        </td>
      </tr>

      {/* Expanded: recent 5 reviews */}
      {expanded && (
        <tr className="border-b border-[hsl(var(--border)/0.5)]">
          <td colSpan={7} className="px-4 py-3 bg-[hsl(var(--secondary)/0.5)]">
            <p className="text-xs font-semibold text-[hsl(var(--muted-foreground))] uppercase tracking-wide mb-2">
              最近 {product.recentReviews.slice(0, 5).length} 条 Reviews
            </p>
            <div className="space-y-2">
              {product.recentReviews.slice(0, 5).map((review, i) => (
                <div
                  key={i}
                  className={cn(
                    'rounded-lg border p-3 text-sm',
                    review.rating < 3
                      ? 'border-[hsl(var(--destructive)/0.3)] bg-[hsl(0_72%_51%/0.05)]'
                      : 'border-[hsl(var(--border))] bg-[hsl(var(--card))]'
                  )}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <StarRating rating={review.rating} />
                    <span className="text-xs font-medium text-[hsl(var(--foreground))]">{review.title}</span>
                    <span className="text-[10px] text-[hsl(var(--muted-foreground))] ml-auto">{formatDate(review.date)}</span>
                    {review.verified && (
                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))]">✓ Verified</span>
                    )}
                  </div>
                  <p className="text-xs text-[hsl(var(--muted-foreground))]">{review.text}</p>
                </div>
              ))}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

function ReviewsPageContent() {
  const [products, setProducts] = useState<ReviewCache[]>([])
  const [loading, setLoading] = useState(false)
  const [crawling, setCrawling] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/reviews')
      const json = await res.json()
      if (json.success && Array.isArray(json.data)) {
        setProducts(json.data)
      } else {
        setError('Failed to load reviews data')
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Fetch failed')
    } finally {
      setLoading(false)
    }
  }, [])

  const handleCrawl = async () => {
    setCrawling(true)
    setError(null)
    try {
      await fetch('/api/reviews/crawl', { method: 'POST' })
      await fetchData()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Crawl failed')
    } finally {
      setCrawling(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [fetchData])

  // ── Summary stats ──
  const avgRating = products.length
    ? products.reduce((s, p) => s + p.rating, 0) / products.length
    : 0
  const totalReviews = products.reduce((s, p) => s + p.totalReviews, 0)
  const negReviewCount = products.reduce(
    (s, p) => s + p.recentReviews.filter((r) => r.rating < 3).length,
    0
  )
  const lastCrawled = products.length
    ? products.reduce((latest, p) =>
        new Date(p.lastCrawled) > new Date(latest) ? p.lastCrawled : latest,
        products[0].lastCrawled
      )
    : null

  return (
    <div className="flex flex-col">
      {/* ── Header ── */}
      <div className="border-b border-[hsl(var(--border))] py-4 flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-[hsl(var(--primary)/0.15)]">
            <MessageSquare className="w-5 h-5 text-[hsl(var(--primary))]" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-[hsl(var(--foreground))]">Reviews</h1>
            <p className="text-xs text-[hsl(var(--muted-foreground))]">评价监控 · Product Review Monitor</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleCrawl}
            disabled={crawling || loading}
            className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg bg-[hsl(var(--primary))] text-black hover:opacity-90 disabled:opacity-50 transition-all"
          >
            <RefreshCw className={cn('w-3.5 h-3.5', crawling && 'animate-spin')} />
            {crawling ? '爬取中…' : '立即爬取'}
          </button>
        </div>
      </div>

      {/* ── Error ── */}
      {error && (
        <div className="mt-4 flex items-center gap-2 p-3 rounded-lg bg-[hsl(var(--destructive)/0.1)] border border-[hsl(var(--destructive)/0.3)] text-sm text-[hsl(var(--destructive))]">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* ── Loading ── */}
      {loading && products.length === 0 && (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 py-20">
          <div className="w-10 h-10 rounded-full border-2 border-[hsl(var(--primary)/0.3)] border-t-[hsl(var(--primary))] animate-spin" />
          <p className="text-sm text-[hsl(var(--muted-foreground))]">加载评价数据中…</p>
        </div>
      )}

      {/* ── Main content ── */}
      {!loading && products.length > 0 && (
        <div className="space-y-6 pt-6">
          {/* ── KPI cards ── */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <KpiCard
              label="平均评分"
              value={`⭐ ${avgRating.toFixed(2)}`}
              sub={`共 ${products.length} 个产品`}
              icon={<Star />}
              highlight
            />
            <KpiCard
              label="总 Reviews 数"
              value={totalReviews.toLocaleString()}
              sub="所有产品合计"
              icon={<MessageSquare />}
            />
            <KpiCard
              label="负评数"
              value={String(negReviewCount)}
              sub="rating < 3 的 reviews"
              icon={<AlertTriangle />}
            />
            <KpiCard
              label="最近爬取"
              value={lastCrawled ? formatCrawlTime(lastCrawled) : '—'}
              sub={lastCrawled ? formatDate(lastCrawled) : '暂无数据'}
              icon={<Clock />}
            />
          </div>

          {/* ── Product table ── */}
          <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
            <div className="px-4 py-3 border-b border-[hsl(var(--border))]">
              <h3 className="text-sm font-semibold text-[hsl(var(--foreground))]">产品评分一览</h3>
              <p className="text-xs text-[hsl(var(--muted-foreground))] mt-0.5">评分 &lt; 4.0 时红色高亮 · 点击行展开最近 Reviews</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] text-xs uppercase tracking-wide">
                    <th className="px-4 py-2.5 text-left font-medium">产品名</th>
                    <th className="px-4 py-2.5 text-left font-medium">ASIN</th>
                    <th className="px-4 py-2.5 text-left font-medium">评分</th>
                    <th className="px-4 py-2.5 text-left font-medium">Review 数</th>
                    <th className="px-4 py-2.5 text-left font-medium">评分分布</th>
                    <th className="px-4 py-2.5 text-left font-medium">最近负评摘要</th>
                    <th className="px-3 py-2.5" />
                  </tr>
                </thead>
                <tbody>
                  {products.map((product) => (
                    <ProductRow key={product.asin} product={product} />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ── Empty ── */}
      {!loading && products.length === 0 && !error && (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <MessageSquare className="w-10 h-10 text-[hsl(var(--muted-foreground))] mb-3 opacity-40" />
          <p className="text-sm text-[hsl(var(--muted-foreground))]">暂无评价数据，点击「立即爬取」获取数据</p>
        </div>
      )}
    </div>
  )
}
export default function ReviewsPage() {
  return (
    <DashboardPageLayout
      signedOut={{ message: 'Sign in to view reviews', forceRedirectUrl: '/reviews' }}
      title="Reviews"
      description="评价分析"
    >
      <ReviewsPageContent />
    </DashboardPageLayout>
  )
}
