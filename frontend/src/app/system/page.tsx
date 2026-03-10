'use client'
import { useEffect, useState, useCallback } from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import { Progress } from '@/components/ui/progress'
import { Badge } from '@/components/ui/badge'
import { Cpu, MemoryStick, HardDrive, Clock, Monitor, Zap, RefreshCw, Bot, Coins, MessageSquare } from 'lucide-react'
import { DashboardPageLayout } from '@/components/templates/DashboardPageLayout'

// ─── Types ────────────────────────────────────────────────────────────────────

interface HardwareData {
  cpu: string; cores: number
  ramTotal: number; ramUsed: number; ramPct: number
  diskTotal: number; diskUsed: number; diskFree: number; diskUsedPct: number
  uptime: string; osVersion: string; model: string
}

interface ModelStat {
  id: string; name: string; provider: string
  inputTokens: number; outputTokens: number; totalTokens: number
  cost: number; sessions: number
}

interface UsageData {
  models: ModelStat[]
  totalTokens: number
  totalCost: number
}

// ─── Helper components ───────────────────────────────────────────────────────

function StatCard({
  icon: Icon, label, value, sub, accent, children
}: {
  icon: React.ElementType; label: string; value: string; sub?: string
  accent?: boolean; children?: React.ReactNode
}) {
  return (
    <div className={`relative rounded-xl border bg-[hsl(var(--card))] p-4 overflow-hidden transition-all hover:border-[hsl(var(--border)/1.5)] ${accent ? 'border-[hsl(var(--primary)/0.3)] shadow-[0_0_24px_hsl(var(--primary)/0.06)]' : 'border-[hsl(var(--border))]'}`}>
      {accent && <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[hsl(var(--primary)/0.5)] to-transparent" />}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <p className="text-[10px] uppercase tracking-widest text-[hsl(var(--muted-foreground))] font-semibold">{label}</p>
          <p className={`text-xl font-bold mt-1 leading-tight ${accent ? 'text-[hsl(var(--primary))]' : 'text-[hsl(var(--foreground))]'}`}>{value}</p>
          {sub && <p className="text-sm text-[hsl(var(--muted-foreground))] mt-0.5">{sub}</p>}
        </div>
        <div className={`p-2 rounded-lg flex-shrink-0 ${accent ? 'bg-[hsl(var(--primary)/0.12)]' : 'bg-[hsl(var(--secondary))]'}`}>
          <Icon className={`w-4 h-4 ${accent ? 'text-[hsl(var(--primary))]' : 'text-[hsl(var(--muted-foreground))]'}`} />
        </div>
      </div>
      {children && <div className="mt-3">{children}</div>}
    </div>
  )
}

function UsageBar({ pct, warn = 70, danger = 88 }: { pct: number; warn?: number; danger?: number }) {
  const color = pct >= danger ? 'bg-[hsl(var(--zv-red))]' : pct >= warn ? 'bg-[hsl(var(--zv-amber))]' : 'bg-[hsl(var(--primary))]'
  return (
    <div className="w-full bg-[hsl(var(--secondary))] rounded-full h-1.5 overflow-hidden mt-2">
      <div className={`h-full rounded-full transition-all duration-700 ${color}`} style={{ width: `${Math.min(pct, 100)}%` }} />
    </div>
  )
}

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000)     return `${(n / 1_000).toFixed(0)}K`
  return String(n)
}

// ─── Page ─────────────────────────────────────────────────────────────────────

function SystemPageContent() {
  const [hw,  setHw]  = useState<HardwareData | null>(null)
  const [usage, setUsage] = useState<UsageData | null>(null)
  const [hwLoading,    setHwLoading]    = useState(true)
  const [usageLoading, setUsageLoading] = useState(true)
  const [lastRefresh,  setLastRefresh]  = useState<Date>(new Date())

  const loadHardware = useCallback(async () => {
    try {
      const res = await fetch('/api/system/hardware')
      if (res.ok) setHw(await res.json())
    } catch { /* ignore */ }
    finally { setHwLoading(false) }
  }, [])

  const loadUsage = useCallback(async () => {
    try {
      const res = await fetch('/api/system/model-usage')
      if (res.ok) setUsage(await res.json())
    } catch { /* ignore */ }
    finally { setUsageLoading(false) }
  }, [])

  useEffect(() => {
    loadHardware()
    loadUsage()
  }, [loadHardware, loadUsage])

  // Auto-refresh hardware every 30s
  useEffect(() => {
    const t = setInterval(() => {
      loadHardware()
      setLastRefresh(new Date())
    }, 30_000)
    return () => clearInterval(t)
  }, [loadHardware])

  const handleRefresh = () => {
    setHwLoading(true)
    setUsageLoading(true)
    loadHardware()
    loadUsage()
    setLastRefresh(new Date())
  }

  const maxTokens = usage?.models[0]?.totalTokens ?? 1

  return (
    <div className="space-y-8 max-w-6xl mx-auto">

        {/* ── Header ── */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-[hsl(var(--foreground))]">System</h1>
            <p className="text-sm text-[hsl(var(--muted-foreground))] mt-0.5">硬件监控 & AI 模型用量</p>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-[hsl(var(--primary))] animate-pulse" />
              <span className="text-[10px] text-[hsl(var(--muted-foreground))]">
                Live · {lastRefresh.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
              </span>
            </div>
            <button
              onClick={handleRefresh}
              className="p-1.5 rounded-lg hover:bg-[hsl(var(--secondary))] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* ── Section: Mac Hardware ── */}
        <section>
          <div className="flex items-center gap-2 mb-4">
            <Monitor className="w-4 h-4 text-[hsl(var(--primary))]" />
            <h2 className="text-base font-semibold text-[hsl(var(--foreground))] uppercase tracking-wider">Mac Hardware</h2>
            <div className="h-px flex-1 bg-[hsl(var(--border))]" />
            {hw && <Badge variant="outline" className="text-[9px] px-1.5 h-4 border-[hsl(var(--primary)/0.3)] text-[hsl(var(--primary))]">macOS {hw.osVersion}</Badge>}
          </div>

          {hwLoading ? (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
              {[...Array(6)].map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)}
            </div>
          ) : hw ? (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
              {/* CPU */}
              <div className="col-span-2 lg:col-span-2">
                <StatCard
                  icon={Cpu} label="处理器" accent
                  value={hw.cpu.replace('Apple ', '').replace('(TM)', '™').replace('(R)', '®')}
                  sub={`${hw.cores} 逻辑核心`}
                />
              </div>

              {/* Model */}
              <StatCard
                icon={Monitor} label="机型"
                value={hw.model.replace('Mac', 'Mac ')}
                sub={`运行 ${hw.uptime}`}
              />

              {/* RAM */}
              <StatCard
                icon={MemoryStick} label="内存"
                value={`${hw.ramUsed} GB`}
                sub={`共 ${hw.ramTotal} GB · ${hw.ramPct}% 已用`}
                accent={hw.ramPct >= 88}
              >
                <UsageBar pct={hw.ramPct} />
              </StatCard>

              {/* Disk */}
              <StatCard
                icon={HardDrive} label="磁盘"
                value={`${hw.diskFree} GB 可用`}
                sub={`共 ${hw.diskTotal} GB · ${hw.diskUsedPct}% 已用`}
                accent={hw.diskUsedPct >= 85}
              >
                <UsageBar pct={hw.diskUsedPct} warn={75} danger={88} />
              </StatCard>

              {/* Uptime */}
              <StatCard
                icon={Clock} label="运行时长"
                value={hw.uptime}
                sub="自上次重启"
              />
            </div>
          ) : (
            <p className="text-base text-[hsl(var(--muted-foreground))]">无法获取硬件信息</p>
          )}
        </section>

        {/* ── Section: Model Usage ── */}
        <section>
          <div className="flex items-center gap-2 mb-4">
            <Bot className="w-4 h-4 text-[hsl(var(--zv-blue))]" />
            <h2 className="text-base font-semibold text-[hsl(var(--foreground))] uppercase tracking-wider">AI 模型用量</h2>
            <div className="h-px flex-1 bg-[hsl(var(--border))]" />
            {usage && (
              <span className="text-[10px] text-[hsl(var(--muted-foreground))]">
                累计 {fmt(usage.totalTokens)} tokens · 估算 ${usage.totalCost.toFixed(2)}
              </span>
            )}
          </div>

          {usageLoading ? (
            <div className="space-y-2">
              {[...Array(6)].map((_, i) => <Skeleton key={i} className="h-12 rounded-xl" />)}
            </div>
          ) : usage && usage.models.length > 0 ? (
            <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
              {/* Table header */}
              <div className="grid grid-cols-[2fr_80px_1fr_1fr_1fr_1fr_110px] gap-3 px-4 py-2.5 border-b border-[hsl(var(--border))] bg-[hsl(var(--secondary)/0.5)]">
                {['模型', 'Provider', '输入', '输出', '总计', '会话', '占比'].map(h => (
                  <span key={h} className="text-[10px] font-semibold uppercase tracking-wider text-[hsl(var(--muted-foreground))]">{h}</span>
                ))}
              </div>

              {/* Rows */}
              {usage.models.map((m, i) => {
                const used = m.totalTokens > 0
                const pct  = used ? Math.round((m.totalTokens / maxTokens) * 100) : 0
                const providerColor: Record<string, string> = {
                  Anthropic: 'text-[hsl(var(--zv-amber))] bg-[hsl(var(--zv-amber)/0.1)]',
                  Google:    'text-[hsl(217_91%_65%)] bg-[hsl(217_91%_60%/0.1)]',
                  OpenAI:    'text-[hsl(142_71%_50%)] bg-[hsl(142_71%_45%/0.1)]',
                }
                const pColor = providerColor[m.provider] ?? 'text-[hsl(var(--muted-foreground))] bg-[hsl(var(--secondary))]'

                return (
                  <div
                    key={m.id}
                    className={`grid grid-cols-[2fr_80px_1fr_1fr_1fr_1fr_110px] gap-3 px-4 py-3 items-center transition-colors hover:bg-[hsl(var(--secondary)/0.3)] ${i < usage.models.length - 1 ? 'border-b border-[hsl(var(--border)/0.5)]' : ''} ${!used ? 'opacity-40' : ''}`}
                  >
                    {/* Name */}
                    <div className="flex items-center gap-2 min-w-0">
                      <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${used ? 'bg-[hsl(var(--primary))]' : 'bg-[hsl(var(--muted-foreground))]'}`} />
                      <span className="text-base font-medium text-[hsl(var(--foreground))] truncate">{m.name}</span>
                    </div>
                    {/* Provider badge */}
                    <span className={`text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded-md w-fit ${pColor}`}>
                      {m.provider}
                    </span>
                    {/* Input */}
                    <span className="text-sm text-[hsl(var(--muted-foreground))] tabular-nums">{used ? fmt(m.inputTokens) : '—'}</span>
                    {/* Output */}
                    <span className="text-sm text-[hsl(var(--muted-foreground))] tabular-nums">{used ? fmt(m.outputTokens) : '—'}</span>
                    {/* Total */}
                    <span className={`text-sm font-semibold tabular-nums ${used ? 'text-[hsl(var(--foreground))]' : 'text-[hsl(var(--muted-foreground))]'}`}>
                      {used ? fmt(m.totalTokens) : '—'}
                    </span>
                    {/* Sessions */}
                    <div className="flex items-center gap-1">
                      <MessageSquare className="w-3 h-3 text-[hsl(var(--muted-foreground))]" />
                      <span className="text-sm text-[hsl(var(--muted-foreground))] tabular-nums">{used ? m.sessions : '0'}</span>
                    </div>
                    {/* Usage bar */}
                    <div className="flex items-center gap-2">
                      <div className="flex-1 bg-[hsl(var(--secondary))] rounded-full h-1.5 overflow-hidden">
                        <div
                          className="h-full bg-[hsl(var(--primary))] rounded-full transition-all duration-700"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <span className="text-[10px] text-[hsl(var(--muted-foreground))] w-8 text-right tabular-nums">{pct}%</span>
                    </div>
                  </div>
                )
              })}

              {/* Total row */}
              <div className="grid grid-cols-[2fr_1fr_1fr_1fr_1fr_120px] gap-4 px-4 py-3 border-t border-[hsl(var(--border))] bg-[hsl(var(--secondary)/0.3)]">
                <div className="flex items-center gap-2">
                  <Coins className="w-3.5 h-3.5 text-[hsl(var(--zv-amber))]" />
                  <span className="text-sm font-bold text-[hsl(var(--foreground))]">总计</span>
                </div>
                <span className="text-sm font-semibold text-[hsl(var(--foreground))] tabular-nums">
                  {fmt(usage.models.reduce((s, m) => s + m.inputTokens, 0))}
                </span>
                <span className="text-sm font-semibold text-[hsl(var(--foreground))] tabular-nums">
                  {fmt(usage.models.reduce((s, m) => s + m.outputTokens, 0))}
                </span>
                <span className="text-base font-bold text-[hsl(var(--primary))] tabular-nums">{fmt(usage.totalTokens)}</span>
                <span className="text-sm font-semibold text-[hsl(var(--foreground))] tabular-nums">
                  {usage.models.reduce((s, m) => s + m.sessions, 0)}
                </span>
                <div className="flex items-center gap-1">
                  <Zap className="w-3 h-3 text-[hsl(var(--zv-amber))]" />
                  <span className="text-sm font-bold text-[hsl(var(--zv-amber))]">${usage.totalCost.toFixed(3)}</span>
                </div>
              </div>
            </div>
          ) : (
            <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-8 text-center">
              <Bot className="w-8 h-8 mx-auto text-[hsl(var(--muted-foreground))] mb-2 opacity-40" />
              <p className="text-base text-[hsl(var(--muted-foreground))]">暂无模型用量数据</p>
            </div>
          )}
        </section>

    </div>
  )
}
export default function SystemPage() {
  return (
    <DashboardPageLayout
      signedOut={{ message: 'Sign in to view system', forceRedirectUrl: '/system' }}
      title="System"
      description="系统与模型用量"
    >
      <SystemPageContent />
    </DashboardPageLayout>
  )
}
