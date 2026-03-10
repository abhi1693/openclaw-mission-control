'use client'

import { useState, useEffect, useCallback } from 'react'
import { Package, AlertTriangle, Clock, CheckCircle, Save } from 'lucide-react'
import { cn } from '@/lib/utils'
import { DashboardPageLayout } from '@/components/templates/DashboardPageLayout'

// ─── Types ────────────────────────────────────────────────────────────────────

type Urgency = 'critical' | 'warning' | 'ok'

interface RestockItem {
  asin: string
  productName: string
  currentStock: number
  dailySales: number
  daysUntilStockout: number
  suggestedRestock: number
  urgency: Urgency
}

interface RestockConfig {
  asin: string
  productName: string
  leadTimeDays: number
  fbaPrepDays: number
  safetyStockDays: number
}

// ─── Urgency helpers ──────────────────────────────────────────────────────────

const urgencyOrder: Record<Urgency, number> = { critical: 0, warning: 1, ok: 2 }

function UrgencyBadge({ urgency }: { urgency: Urgency }) {
  const map: Record<Urgency, { label: string; cls: string }> = {
    critical: { label: '🔴 紧急', cls: 'bg-rose-500/20 text-rose-600 border border-rose-500/30' },
    warning:  { label: '🟡 预警', cls: 'bg-amber-500/20 text-amber-600 border border-amber-500/30' },
    ok:       { label: '🟢 充足', cls: 'bg-emerald-500/20 text-emerald-600 border border-emerald-500/30' },
  }
  const { label, cls } = map[urgency]
  return (
    <span className={cn('text-[11px] font-semibold px-2 py-0.5 rounded-full', cls)}>{label}</span>
  )
}

// ─── Dashboard Tab ────────────────────────────────────────────────────────────

function DashboardTab() {
  const [items, setItems] = useState<RestockItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/restock')
      const json = await res.json()
      if (json.success && Array.isArray(json.data)) {
        setItems(json.data)
      } else {
        setError(json.error ?? 'Failed to load restock data')
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Fetch failed')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const sorted = [...items].sort((a, b) => urgencyOrder[a.urgency] - urgencyOrder[b.urgency])
  const criticalCount = items.filter(i => i.urgency === 'critical').length
  const warningCount  = items.filter(i => i.urgency === 'warning').length
  const okCount       = items.filter(i => i.urgency === 'ok').length

  return (
    <div className="space-y-6">
      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: '紧急补货', value: criticalCount, icon: '🔴', cls: 'border-rose-500/30 bg-rose-500/5' },
          { label: '即将断货', value: warningCount,  icon: '🟡', cls: 'border-amber-500/30 bg-amber-500/5' },
          { label: '库存充足', value: okCount,        icon: '🟢', cls: 'border-emerald-500/30 bg-emerald-500/5' },
        ].map(({ label, value, icon, cls }) => (
          <div key={label} className={cn('rounded-xl border p-4', cls)}>
            <p className="text-2xl mb-1">{icon}</p>
            <p className="text-2xl font-bold text-[hsl(var(--foreground))]">{value}</p>
            <p className="text-xs text-[hsl(var(--muted-foreground))] mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-[hsl(var(--destructive)/0.1)] border border-[hsl(var(--destructive)/0.3)] text-sm text-[hsl(var(--destructive))]">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && items.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 gap-3">
          <div className="w-10 h-10 rounded-full border-2 border-[hsl(var(--primary)/0.3)] border-t-[hsl(var(--primary))] animate-spin" />
          <p className="text-sm text-[hsl(var(--muted-foreground))]">加载补货数据中…</p>
        </div>
      )}

      {/* Table */}
      {!loading && sorted.length > 0 && (
        <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-[hsl(var(--border))]">
            <h3 className="text-sm font-semibold text-[hsl(var(--foreground))]">补货建议列表</h3>
            <p className="text-xs text-[hsl(var(--muted-foreground))] mt-0.5">按紧急度排序 · critical 行红色高亮 · warning 行黄色高亮</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] text-xs uppercase tracking-wide">
                  <th className="px-4 py-2.5 text-left font-medium">产品名</th>
                  <th className="px-4 py-2.5 text-left font-medium">ASIN</th>
                  <th className="px-4 py-2.5 text-right font-medium">当前库存</th>
                  <th className="px-4 py-2.5 text-right font-medium">日销量</th>
                  <th className="px-4 py-2.5 text-right font-medium">预计断货天数</th>
                  <th className="px-4 py-2.5 text-right font-medium">建议补货量</th>
                  <th className="px-4 py-2.5 text-center font-medium">紧急度</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((item) => (
                  <tr
                    key={item.asin}
                    className={cn(
                      'border-b border-[hsl(var(--border)/0.5)] transition-colors',
                      item.urgency === 'critical'
                        ? 'bg-rose-500/8 hover:bg-rose-500/12'
                        : item.urgency === 'warning'
                        ? 'bg-amber-500/8 hover:bg-amber-500/12'
                        : 'hover:bg-[hsl(var(--secondary))]'
                    )}
                  >
                    <td className="px-4 py-3 font-medium text-[hsl(var(--foreground))] max-w-[200px] truncate">{item.productName}</td>
                    <td className="px-4 py-3 font-mono text-xs text-[hsl(var(--muted-foreground))]">{item.asin}</td>
                    <td className="px-4 py-3 text-right">{item.currentStock.toLocaleString()}</td>
                    <td className="px-4 py-3 text-right">{item.dailySales.toFixed(1)}</td>
                    <td className={cn('px-4 py-3 text-right font-semibold',
                      item.urgency === 'critical' ? 'text-rose-600' : item.urgency === 'warning' ? 'text-amber-600' : 'text-emerald-600'
                    )}>
                      {item.daysUntilStockout}
                    </td>
                    <td className="px-4 py-3 text-right font-semibold text-[hsl(var(--foreground))]">{item.suggestedRestock.toLocaleString()}</td>
                    <td className="px-4 py-3 text-center"><UrgencyBadge urgency={item.urgency} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Empty */}
      {!loading && sorted.length === 0 && !error && (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Package className="w-10 h-10 text-[hsl(var(--muted-foreground))] mb-3 opacity-40" />
          <p className="text-sm text-[hsl(var(--muted-foreground))]">暂无补货数据</p>
        </div>
      )}
    </div>
  )
}

// ─── Config Tab ───────────────────────────────────────────────────────────────

function ConfigTab() {
  const [configs, setConfigs] = useState<RestockConfig[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/restock/config')
      const json = await res.json()
      if (json.success && Array.isArray(json.data)) {
        setConfigs(json.data)
      } else {
        setError(json.error ?? 'Failed to load config')
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Fetch failed')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const updateField = (index: number, field: keyof RestockConfig, value: string | number) => {
    setConfigs(prev => prev.map((c, i) => i === index ? { ...c, [field]: value } : c))
  }

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    setSuccess(false)
    try {
      const res = await fetch('/api/restock/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: configs }),
      })
      const json = await res.json()
      if (json.success) {
        setSuccess(true)
        setTimeout(() => setSuccess(false), 3000)
      } else {
        setError(json.error ?? 'Save failed')
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      {error && (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-[hsl(var(--destructive)/0.1)] border border-[hsl(var(--destructive)/0.3)] text-sm text-[hsl(var(--destructive))]">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {success && (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-sm text-emerald-600">
          <CheckCircle className="w-4 h-4 flex-shrink-0" />
          配置已保存
        </div>
      )}

      {loading && configs.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 gap-3">
          <div className="w-10 h-10 rounded-full border-2 border-[hsl(var(--primary)/0.3)] border-t-[hsl(var(--primary))] animate-spin" />
          <p className="text-sm text-[hsl(var(--muted-foreground))]">加载配置中…</p>
        </div>
      )}

      {configs.length > 0 && (
        <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-[hsl(var(--border))]">
            <h3 className="text-sm font-semibold text-[hsl(var(--foreground))]">补货参数配置</h3>
            <p className="text-xs text-[hsl(var(--muted-foreground))] mt-0.5">直接编辑数值 · 点击「保存配置」提交</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] text-xs uppercase tracking-wide">
                  <th className="px-4 py-2.5 text-left font-medium">ASIN</th>
                  <th className="px-4 py-2.5 text-left font-medium">产品名</th>
                  <th className="px-4 py-2.5 text-center font-medium">Lead Time (天)</th>
                  <th className="px-4 py-2.5 text-center font-medium">FBA Prep (天)</th>
                  <th className="px-4 py-2.5 text-center font-medium">安全库存 (天)</th>
                </tr>
              </thead>
              <tbody>
                {configs.map((cfg, i) => (
                  <tr key={cfg.asin} className="border-b border-[hsl(var(--border)/0.5)] hover:bg-[hsl(var(--secondary)/0.5)]">
                    <td className="px-4 py-2.5 font-mono text-xs text-[hsl(var(--muted-foreground))]">{cfg.asin}</td>
                    <td className="px-4 py-2.5 text-[hsl(var(--foreground))] max-w-[200px] truncate">{cfg.productName}</td>
                    {(['leadTimeDays', 'fbaPrepDays', 'safetyStockDays'] as const).map((field) => (
                      <td key={field} className="px-4 py-2.5 text-center">
                        <input
                          type="number"
                          min={0}
                          value={cfg[field]}
                          onChange={e => updateField(i, field, Number(e.target.value))}
                          className="w-16 text-center bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-md px-2 py-1 text-sm text-[hsl(var(--foreground))] focus:outline-none focus:ring-1 focus:ring-[hsl(var(--primary))]"
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {configs.length > 0 && (
        <div className="flex justify-end">
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 px-5 py-2.5 text-sm font-medium rounded-lg bg-[hsl(var(--primary))] text-black hover:opacity-90 disabled:opacity-50 transition-all"
          >
            <Save className="w-4 h-4" />
            {saving ? '保存中…' : '保存配置'}
          </button>
        </div>
      )}

      {!loading && configs.length === 0 && !error && (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Clock className="w-10 h-10 text-[hsl(var(--muted-foreground))] mb-3 opacity-40" />
          <p className="text-sm text-[hsl(var(--muted-foreground))]">暂无配置数据</p>
        </div>
      )}
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

type Tab = 'dashboard' | 'config'

function RestockPageContent() {
  const [activeTab, setActiveTab] = useState<Tab>('dashboard')

  const tabs: { id: Tab; label: string }[] = [
    { id: 'dashboard', label: 'Restock Dashboard' },
    { id: 'config', label: 'Config' },
  ]

  return (
    <div className="space-y-6">
      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-slate-100 rounded-lg w-fit">
        {tabs.map(({ id, label }) => (
          <button
            key={id}
            onClick={() => setActiveTab(id)}
            className={cn(
              'px-4 py-1.5 text-sm font-medium rounded-md transition-all',
              activeTab === id
                ? 'bg-[hsl(var(--card))] text-[hsl(var(--foreground))] shadow-sm'
                : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="mt-6">
        {activeTab === 'dashboard' ? <DashboardTab /> : <ConfigTab />}
      </div>
    </div>
  )
}
export default function RestockPage() {
  return (
    <DashboardPageLayout
      signedOut={{ message: 'Sign in to view restock', forceRedirectUrl: '/restock' }}
      title="Restock"
      description="补货预测"
    >
      <RestockPageContent />
    </DashboardPageLayout>
  )
}
