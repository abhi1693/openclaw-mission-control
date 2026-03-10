'use client'

import { useState, useEffect, useCallback } from 'react'
import { RefreshCw, DollarSign, TrendingUp, Megaphone, Leaf, AlertTriangle, Plus } from 'lucide-react'
import { cn } from '@/lib/utils'
import { DashboardPageLayout } from '@/components/templates/DashboardPageLayout'

// ─── Types ─────────────────────────────────────────────────────────────────────

interface ProfitItem {
  sku: string
  asin: string
  productName: string
  revenue: number
  unitsSold: number
  landedCost: number
  fbaFee: number
  referralFee: number
  adSpend: number
  netProfit: number
  profitMargin: number
}

interface ProfitSummary {
  totalRevenue: number
  totalCost: number
  totalProfit: number
  profitMargin: number
  totalAdSpend: number
  tacos: number
  organicRatio: number
}

interface ProfitData {
  summary: ProfitSummary
  items: ProfitItem[]
  cachedAt?: string
  fromCache?: boolean
  warnings?: string[]
}

interface CostItem {
  sku: string
  asin: string
  productName: string
  unitCost: number
  shippingToPort: number
  freight: number
  customs: number
  dutyRate: number
  lastMile: number
  prep: number
  otherCost: number
  totalLandedCost: number
  currency: string
  updatedAt: string
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtUSD(n: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n)
}

function fmtPct(n: number) {
  return `${n.toFixed(1)}%`
}

function minutesAgo(iso?: string) {
  if (!iso) return null
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (diff < 1) return '刚刚'
  if (diff < 60) return `${diff} 分钟前`
  return `${Math.floor(diff / 60)} 小时前`
}

function marginColor(pct: number) {
  if (pct >= 30) return 'text-emerald-600'
  if (pct >= 15) return 'text-amber-600'
  return 'text-rose-600'
}

function calcLanded(item: CostItem) {
  return item.unitCost + item.shippingToPort + item.freight + item.customs + item.lastMile + item.prep + item.otherCost
}

// ─── Summary Card ─────────────────────────────────────────────────────────────

function SummaryCard({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub?: string }) {
  return (
    <div className="bg-[hsl(var(--card))] border border-[hsl(var(--border))] rounded-xl px-5 py-4 flex items-center gap-4 flex-1 min-w-0">
      <div className="w-10 h-10 rounded-lg bg-[hsl(var(--primary)/0.15)] flex items-center justify-center flex-shrink-0 text-[hsl(var(--primary))]">
        {icon}
      </div>
      <div className="min-w-0">
        <p className="text-[11px] text-[hsl(var(--muted-foreground))] uppercase tracking-wider">{label}</p>
        <p className="text-xl font-bold text-slate-900 truncate">{value}</p>
        {sub && <p className="text-[10px] text-[hsl(var(--muted-foreground))]">{sub}</p>}
      </div>
    </div>
  )
}

// ─── Dashboard Tab ─────────────────────────────────────────────────────────────

function DashboardTab() {
  const [data, setData] = useState<ProfitData | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const load = useCallback(async (force = false) => {
    if (force) setRefreshing(true)
    else setLoading(true)
    try {
      const res = await fetch('/api/profit', { method: force ? 'POST' : 'GET' })
      const json = await res.json() as ProfitData
      setData(json)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-[hsl(var(--muted-foreground))]">
        <RefreshCw className="w-5 h-5 animate-spin mr-2" /> 加载中…
      </div>
    )
  }

  const s = data?.summary
  const items = (data?.items || []).slice().sort((a, b) => b.netProfit - a.netProfit)

  return (
    <div className="space-y-6">
      {/* Warnings */}
      {data?.warnings?.length ? (
        <div className="flex items-center gap-2 px-4 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-600 text-sm">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          {data.warnings.join(' · ')}
        </div>
      ) : null}

      {/* Summary Cards */}
      <div className="flex gap-3 flex-wrap">
        <SummaryCard icon={<DollarSign className="w-5 h-5" />} label="总利润" value={fmtUSD(s?.totalProfit ?? 0)} sub={`收入 ${fmtUSD(s?.totalRevenue ?? 0)}`} />
        <SummaryCard icon={<TrendingUp className="w-5 h-5" />} label="利润率" value={fmtPct(s?.profitMargin ?? 0)} />
        <SummaryCard icon={<Megaphone className="w-5 h-5" />} label="TACoS" value={fmtPct(s?.tacos ?? 0)} sub={`广告 ${fmtUSD(s?.totalAdSpend ?? 0)}`} />
        <SummaryCard icon={<Leaf className="w-5 h-5" />} label="自然占比" value={fmtPct(s?.organicRatio ?? 0)} />
      </div>

      {/* Table */}
      <div className="bg-[hsl(var(--card))] border border-[hsl(var(--border))] rounded-xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[hsl(var(--border))]">
          <h2 className="font-semibold text-slate-900">SKU 利润明细 <span className="text-[hsl(var(--muted-foreground))] text-sm font-normal">· 近 30 天</span></h2>
          <div className="flex items-center gap-3">
            {data?.cachedAt && (
              <span className="text-[11px] text-[hsl(var(--muted-foreground))]">更新于 {minutesAgo(data.cachedAt)}</span>
            )}
            <button
              onClick={() => load(true)}
              disabled={refreshing}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[hsl(var(--secondary))] text-sm text-[hsl(var(--foreground))] hover:bg-[hsl(var(--primary)/0.15)] hover:text-[hsl(var(--primary))] transition-colors disabled:opacity-50"
            >
              <RefreshCw className={cn('w-3.5 h-3.5', refreshing && 'animate-spin')} />
              刷新
            </button>
          </div>
        </div>

        {items.length === 0 ? (
          <div className="py-16 text-center text-[hsl(var(--muted-foreground))]">
            暂无数据 — 请先在 COGS Editor 录入产品成本
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="text-[11px] text-[hsl(var(--muted-foreground))] uppercase tracking-wider border-b border-[hsl(var(--border))]">
                  <th className="px-5 py-3 text-left">产品名</th>
                  <th className="px-4 py-3 text-right">售价收入</th>
                  <th className="px-4 py-3 text-right">Landed Cost</th>
                  <th className="px-4 py-3 text-right">Amazon Fees</th>
                  <th className="px-4 py-3 text-right">Ad Spend</th>
                  <th className="px-4 py-3 text-right">净利润</th>
                  <th className="px-4 py-3 text-right">利润率</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item, i) => (
                  <tr
                    key={item.sku + i}
                    className={cn(
                      'border-b border-[hsl(var(--border))] last:border-0 hover:bg-[hsl(var(--secondary)/0.5)] transition-colors',
                      item.netProfit < 0 && 'bg-rose-500/10'
                    )}
                  >
                    <td className="px-5 py-3">
                      <p className="font-medium text-slate-900 truncate max-w-[220px]">{item.productName || item.sku}</p>
                      <p className="text-[10px] text-[hsl(var(--muted-foreground))]">{item.sku} · {item.unitsSold} units</p>
                    </td>
                    <td className="px-4 py-3 text-right text-slate-900">{fmtUSD(item.revenue)}</td>
                    <td className="px-4 py-3 text-right text-[hsl(var(--muted-foreground))]">{fmtUSD(item.landedCost)}</td>
                    <td className="px-4 py-3 text-right text-[hsl(var(--muted-foreground))]">{fmtUSD(item.fbaFee + item.referralFee)}</td>
                    <td className="px-4 py-3 text-right text-[hsl(var(--muted-foreground))]">{fmtUSD(item.adSpend)}</td>
                    <td className={cn('px-4 py-3 text-right font-semibold', item.netProfit >= 0 ? 'text-emerald-600' : 'text-rose-600')}>
                      {fmtUSD(item.netProfit)}
                    </td>
                    <td className={cn('px-4 py-3 text-right font-medium', marginColor(item.profitMargin))}>
                      {fmtPct(item.profitMargin)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── COGS Editor Tab ───────────────────────────────────────────────────────────

interface Product {
  sku: string
  asin: string
  title?: string
  productName?: string
}

function CogsEditorTab() {
  const [items, setItems] = useState<CostItem[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [loadingProducts, setLoadingProducts] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')

  useEffect(() => {
    fetch('/api/profit/cogs')
      .then(r => r.json())
      .then(d => { setItems(d.items || []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  const loadProducts = async () => {
    setLoadingProducts(true)
    try {
      const res = await fetch('/api/content/products')
      const d = await res.json() as { products?: Product[]; items?: Product[] }
      const products: Product[] = d.products || d.items || []
      const newItems: CostItem[] = products.map(p => ({
        sku: p.sku,
        asin: p.asin,
        productName: p.title || p.productName || p.sku,
        unitCost: 0, shippingToPort: 0, freight: 0, customs: 0,
        dutyRate: 0, lastMile: 0, prep: 0, otherCost: 0,
        totalLandedCost: 0,
        currency: 'USD',
        updatedAt: new Date().toISOString(),
      }))
      setItems(newItems)
    } catch (e) {
      console.error(e)
    } finally {
      setLoadingProducts(false)
    }
  }

  const updateField = (idx: number, field: keyof CostItem, value: string) => {
    setItems(prev => prev.map((item, i) => {
      if (i !== idx) return item
      const updated = { ...item, [field]: field === 'currency' || field === 'sku' || field === 'asin' || field === 'productName' || field === 'updatedAt'
        ? value
        : parseFloat(value) || 0
      }
      updated.totalLandedCost = calcLanded(updated)
      return updated
    }))
  }

  const save = async () => {
    setSaving(true)
    setSaveMsg('')
    try {
      const withDate = items.map(i => ({ ...i, updatedAt: new Date().toISOString() }))
      await fetch('/api/profit/cogs', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items: withDate }),
      })
      setSaveMsg('✓ 已保存')
      setTimeout(() => setSaveMsg(''), 3000)
    } catch (e) {
      setSaveMsg('保存失败')
      console.error(e)
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-[hsl(var(--muted-foreground))]">
        <RefreshCw className="w-5 h-5 animate-spin mr-2" /> 加载中…
      </div>
    )
  }

  if (items.length === 0) {
    return (
      <div className="bg-[hsl(var(--card))] border border-[hsl(var(--border))] rounded-xl p-12 text-center space-y-4">
        <p className="text-[hsl(var(--muted-foreground))]">请先录入产品成本数据</p>
        <button
          onClick={loadProducts}
          disabled={loadingProducts}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-[hsl(var(--primary))] text-black font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
        >
          <Plus className="w-4 h-4" />
          {loadingProducts ? '加载中…' : '加载产品列表'}
        </button>
      </div>
    )
  }

  const numInput = 'w-20 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded px-2 py-1 text-right text-sm text-slate-900 focus:outline-none focus:ring-1 focus:ring-[hsl(var(--primary))]'

  return (
    <div className="space-y-4">
      <div className="bg-[hsl(var(--card))] border border-[hsl(var(--border))] rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-[hsl(var(--border))] flex items-center justify-between">
          <h2 className="font-semibold text-slate-900">成本录入 <span className="text-[hsl(var(--muted-foreground))] text-sm font-normal">· {items.length} 个产品</span></h2>
          <button
            onClick={loadProducts}
            disabled={loadingProducts}
            className="text-xs text-[hsl(var(--muted-foreground))] hover:text-slate-900 transition-colors disabled:opacity-50"
          >
            重新加载产品列表
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="text-[10px] text-[hsl(var(--muted-foreground))] uppercase tracking-wider border-b border-[hsl(var(--border))] bg-[hsl(var(--secondary)/0.3)]">
                <th className="px-4 py-3 text-left">产品名</th>
                <th className="px-3 py-3 text-left">SKU</th>
                <th className="px-3 py-3 text-right">出厂价</th>
                <th className="px-3 py-3 text-right">运港</th>
                <th className="px-3 py-3 text-right">海运</th>
                <th className="px-3 py-3 text-right">关税</th>
                <th className="px-3 py-3 text-right">税率%</th>
                <th className="px-3 py-3 text-right">Last Mile</th>
                <th className="px-3 py-3 text-right">Prep</th>
                <th className="px-3 py-3 text-right">其他</th>
                <th className="px-3 py-3 text-right">Landed Cost</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, i) => (
                <tr key={item.sku + i} className="border-b border-[hsl(var(--border))] last:border-0 hover:bg-[hsl(var(--secondary)/0.3)] transition-colors">
                  <td className="px-4 py-2.5 max-w-[160px]">
                    <p className="text-slate-900 truncate">{item.productName || item.sku}</p>
                  </td>
                  <td className="px-3 py-2.5 text-[hsl(var(--muted-foreground))] text-xs">{item.sku}</td>
                  {(['unitCost', 'shippingToPort', 'freight', 'customs'] as const).map(f => (
                    <td key={f} className="px-3 py-2.5 text-right">
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        value={item[f]}
                        onChange={e => updateField(i, f, e.target.value)}
                        className={numInput}
                      />
                    </td>
                  ))}
                  <td className="px-3 py-2.5 text-right">
                    <input
                      type="number"
                      min="0"
                      max="100"
                      step="0.1"
                      value={(item.dutyRate * 100).toFixed(1)}
                      onChange={e => updateField(i, 'dutyRate', String(parseFloat(e.target.value) / 100))}
                      className={numInput}
                    />
                  </td>
                  {(['lastMile', 'prep', 'otherCost'] as const).map(f => (
                    <td key={f} className="px-3 py-2.5 text-right">
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        value={item[f]}
                        onChange={e => updateField(i, f, e.target.value)}
                        className={numInput}
                      />
                    </td>
                  ))}
                  <td className="px-3 py-2.5 text-right font-semibold text-[hsl(var(--primary))]">
                    ${calcLanded(item).toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="flex items-center justify-end gap-4">
        {saveMsg && <span className="text-sm text-emerald-600">{saveMsg}</span>}
        <button
          onClick={save}
          disabled={saving}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-[hsl(var(--primary))] text-black font-semibold hover:opacity-90 transition-opacity disabled:opacity-50"
        >
          {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : null}
          {saving ? '保存中…' : '保存 COGS'}
        </button>
      </div>
    </div>
  )
}

// ─── Page ──────────────────────────────────────────────────────────────────────

type Tab = 'dashboard' | 'cogs'

function ProfitPageContent() {
  const [tab, setTab] = useState<Tab>('dashboard')

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Tabs */}
      <div className="flex-shrink-0 px-6 pt-2 pb-0">
        <div className="flex gap-1 border-b border-[hsl(var(--border))]">
          {(['dashboard', 'cogs'] as Tab[]).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                'px-5 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px',
                tab === t
                  ? 'border-[hsl(var(--primary))] text-[hsl(var(--primary))]'
                  : 'border-transparent text-[hsl(var(--muted-foreground))] hover:text-slate-900'
              )}
            >
              {t === 'dashboard' ? '📊 Profit Dashboard' : '✏️ COGS Editor'}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        {tab === 'dashboard' ? <DashboardTab /> : <CogsEditorTab />}
      </div>
    </div>
  )
}
export default function ProfitPage() {
  return (
    <DashboardPageLayout
      signedOut={{ message: 'Sign in to view profit', forceRedirectUrl: '/profit' }}
      title="Profit"
      description="利润分析"
    >
      <ProfitPageContent />
    </DashboardPageLayout>
  )
}
