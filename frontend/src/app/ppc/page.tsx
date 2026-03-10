'use client'
import { useEffect, useState, useMemo } from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { DashboardPageLayout } from '@/components/templates/DashboardPageLayout'
import {
  Target, RefreshCw, DollarSign, TrendingUp, TrendingDown, PauseCircle,
  PlayCircle, ChevronDown, ChevronRight, ChevronUp, BarChart3, Zap, Filter,
  AlertTriangle, Lightbulb, Search, ArrowUpDown, Eye, MousePointerClick,
  ShoppingCart, Percent, ArrowUp, ArrowDown, Plus, Minus, XCircle,
  Building2, CreditCard, Layers, List, Activity, LayoutDashboard, CheckSquare,
} from 'lucide-react'

// ─── Types ────────────────────────────────────────────────────────────────────

type Period = 7 | 30
type TopTab = 'ai-insights' | 'overview' | 'keywords-opt' | 'campaign-structure' | 'bid-budget' | 'kw-performance' | 'search-discovery'

interface KPI {
  spend: number; sales: number; clicks: number; orders: number
  impressions: number; acos: number; roas: number; cpc: number
  ctr: number; convRate: number
}

interface Keyword {
  keyword: string; matchType: string; campaignName: string; adGroupName: string
  impressions: number; clicks: number; ctr: number; cpc: number
  cost: number; sales: number; orders: number; acos: number; convRate: number; roas: number
}

interface SearchTerm {
  searchTerm: string; targeting: string; matchType: string; campaignName: string
  impressions: number; clicks: number; ctr: number; cpc: number
  cost: number; sales: number; orders: number; acos: number; convRate: number
}

interface Campaign {
  campaignId: string; name: string; state: 'ENABLED' | 'PAUSED' | 'ARCHIVED'
  budget: { budget: number; budgetType: string }
  targetingType: 'AUTO' | 'MANUAL'
  dynamicBidding?: { strategy: string; placementBidding?: { percentage: number; placement: string }[] }
  startDate?: string
}

type SortKey = 'keyword' | 'impressions' | 'clicks' | 'ctr' | 'cpc' | 'cost' | 'sales' | 'orders' | 'acos' | 'convRate'
type SortDir = 'asc' | 'desc'

// ─── Keyword Analysis Types ───────────────────────────────────────────────────

interface AnalysisSummary {
  addKeywordCount: number; negativeCount: number; negWarnCount: number; negFlagCount: number
  upgradeCount: number; longTailCount: number; duplicateGroupCount: number
  estMonthlySavings?: number; estMonthlySalesGain?: number
}
interface AddKeywordItem {
  searchTerm: string; impressions: number; clicks: number; orders: number
  sales: number; spend: number; acos: number; suggestedMatchType: string; campaigns?: string[]
}
interface NegativeKeywordItem {
  searchTerm: string; impressions: number; clicks: number; spend: number
  campaigns: string[]; level: 'warn' | 'flag'; action?: string
}
interface MatchUpgradeItem { keyword: string; currentMatch: string; orders: number; acos: number; suggestion: string }
interface LongTailItem { searchTerm: string; orders: number; impressions: number; clicks: number; spend: number; acos: number; suggestion: string }
interface DuplicateItem { keyword: string; matchType?: string; campaigns: string[]; riskNote?: string }
interface AnalysisData {
  empty: boolean; source: string; message?: string; derivedFrom?: string
  startDate?: string; endDate?: string; targetAcos?: number
  summary: AnalysisSummary | null
  addKeywords: AddKeywordItem[]; negativeKeywords: NegativeKeywordItem[]
  matchUpgrades: MatchUpgradeItem[]; longTail: LongTailItem[]; duplicateTargeting: DuplicateItem[]
}

// ─── Campaign Analysis Types ──────────────────────────────────────────────────

interface CampaignAnalysis {
  empty: boolean; source?: string; message?: string
  summary?: {
    totalCampaigns: number; activeCampaigns: number; duplicateGroups: number
    uncoveredAsins: number; zombieCampaigns: number; namingIssues: number
  }
  duplicates?: { keyword: string; matchType: string; campaigns: string[]; occurrences: number }[]
  asinCoverage?: { whitelist: string[]; covered: string[]; uncovered: string[]; note: string }
  typeDistribution?: {
    sp: { total: number; active: number; paused: number; dailyBudget: number; budgetShare: number }
    sb: { total: number; active: number; paused: number; dailyBudget: number; budgetShare: number }
    totalDailyBudget: number
  }
  zombieCampaigns?: { name: string; type: string; dailyBudget: number; startDaysAgo: number; reason: string }[]
  naming?: {
    dominantPattern: string; issueCount: number; totalChecked: number
    issues: { name: string; type: string; issues: string[] }[]
  }
  recommendations?: { priority: string; category: string; action: string; detail: string }[]
}

// ─── Bid/Budget Analysis Types ────────────────────────────────────────────────

interface BidAnalysis {
  empty: boolean; source?: string; message?: string
  targetAcos?: number; breakevenAcos?: number
  summary?: {
    overbiddingCount: number; underbiddingCount: number; cappedCampaigns: number
    underutilizedCampaigns: number; acosWorseningCount: number; breakevenAlerts: number
  }
  bidEfficiency?: {
    overbidding: { keyword: string; matchType: string; campaignName: string; bid: number; actualCpc: number; cpcRatio: number; spend: number; suggestion: string }[]
    underbidding: { keyword: string; matchType: string; campaignName: string; bid: number; actualCpc: number; acos: number; orders: number; suggestion: string }[]
    wellBidCount: number; totalAnalyzed: number
  }
  budgetUtilization?: {
    campaigns: { name: string; dailyBudget: number; avgDailySpend: number | null; utilization: number | null; totalSpend: number | null; totalSales: number | null; acos: number | null; roas: number | null; status: string }[]
    capped: { name: string; utilization: number; dailyBudget: number }[]
    underutilized: { name: string; utilization: number; dailyBudget: number }[]
    dormant: { name: string }[]
  }
  acosAnalysis?: {
    targetAcos: number; breakevenAcos: number
    deteriorating: { name: string; acos: number; gap: number; spend: number }[]
    breakeven: { name: string; acos: number; spend: number; severity: string }[]
  }
  performers?: {
    top5: { name: string; roas: number; acos: number | null; spend: number }[]
    bottom5: { name: string; roas: number; acos: number | null; spend: number }[]
  }
  reallocations?: { fromCampaign?: string; currentBudget?: number; suggestedBudget?: number; freedBudget?: number; reason?: string; action?: string; targetCampaigns?: string[]; budgetToDistribute?: number }[]
}

// ─── Weekly Report Types ──────────────────────────────────────────────────────

interface WeeklyReport {
  empty: boolean; source?: string; message?: string; reportDate?: string
  dateRange?: { start: string | null; end: string | null }
  overview: { totalSpend: number | null; totalSales: number | null; totalOrders: number | null; acos: number | null; roas: number | null }
  moneyKeywords: { searchTerm: string; orders: number; sales: number; spend: number; acos: number; roas: number }[]
  burnKeywords: { searchTerm: string; spend: number; clicks: number; impressions: number; level: string }[]
  actionItems: { priority: string; category: string; action: string; detail?: string; source: string }[]
  riskAlerts: { severity: string; type: string; message: string; campaigns?: string[] }[]
  summary: { highPriorityActions: number; mediumPriorityActions: number; criticalAlerts: number; warningAlerts: number }
}

// ─── AI Insights Types ────────────────────────────────────────────────────────

interface AiTermStrategy { term: string; strategy: string }
interface AiNegativeRisk { term: string; spend: number; verdict: '否定' | '观察' | '优化listing'; reason: string }
interface AiAnomaly { campaign: string; issue: string; rootCause: string; fix: string }
interface AiAction { priority: number; action: string; impact: string; reason: string }

interface AiInsights {
  empty: boolean
  message?: string
  hint?: string
  generatedAt?: string
  dateRange?: { start: string; end: string }
  model?: string
  keywordGrouping?: {
    brandTerms: AiTermStrategy[]
    categoryTerms: AiTermStrategy[]
    competitorTerms: AiTermStrategy[]
    problemSolvingTerms: AiTermStrategy[]
  }
  negativeRiskAssessment?: AiNegativeRisk[]
  anomalyAnalysis?: AiAnomaly[]
  weeklyActionPlan?: AiAction[]
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toFixed(0)
}

function acosColor(acos: number): string {
  if (acos <= 0) return 'text-[hsl(var(--muted-foreground))]'
  if (acos < 25) return 'text-[hsl(var(--primary))]'
  if (acos < 40) return 'text-[hsl(var(--zv-amber))]'
  return 'text-[hsl(var(--destructive))]'
}

function convColor(conv: number): string {
  if (conv >= 15) return 'text-[hsl(var(--primary))]'
  if (conv >= 5) return 'text-[hsl(var(--zv-amber))]'
  return 'text-[hsl(var(--destructive))]'
}

function acosBg(acos: number): string {
  if (acos <= 0) return ''
  if (acos < 25) return 'bg-[hsl(var(--primary)/0.08)]'
  if (acos < 40) return 'bg-[hsl(var(--zv-amber)/0.08)]'
  return 'bg-[hsl(var(--destructive)/0.08)]'
}

// ─── Period Selector ──────────────────────────────────────────────────────────

function PeriodSelector({ value, onChange }: { value: Period; onChange: (p: Period) => void }) {
  return (
    <div className="flex items-center gap-1 p-0.5 rounded-lg bg-[hsl(var(--secondary))]">
      {([7, 30] as Period[]).map(p => (
        <button key={p} onClick={() => onChange(p)}
          className={`px-3 py-1.5 text-sm font-medium rounded-md transition-all ${
            value === p ? 'bg-[hsl(var(--primary))] text-black shadow-sm' : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'
          }`}
        >{p === 7 ? '周 (7天)' : '月 (30天)'}</button>
      ))}
    </div>
  )
}

// ─── KPI Card ─────────────────────────────────────────────────────────────────

function KPICard({ label, value, sub, icon, accent }: {
  label: string; value: string; sub?: string; icon: React.ReactNode; accent?: boolean
}) {
  return (
    <div className={`relative rounded-xl border p-4 overflow-hidden transition-all ${
      accent ? 'border-[hsl(var(--primary)/0.3)] bg-[hsl(var(--card))] shadow-[0_0_24px_hsl(var(--primary)/0.06)]' : 'border-[hsl(var(--border))] bg-[hsl(var(--card))]'
    }`}>
      {accent && <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[hsl(var(--primary)/0.5)] to-transparent" />}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <p className="text-[10px] uppercase tracking-widest text-[hsl(var(--muted-foreground))] font-semibold">{label}</p>
          <p className={`text-xl font-bold mt-1 leading-tight ${accent ? 'text-[hsl(var(--primary))]' : 'text-[hsl(var(--foreground))]'}`}>{value}</p>
          {sub && <p className="text-[10px] text-[hsl(var(--muted-foreground))] mt-0.5">{sub}</p>}
        </div>
        <div className={`p-2 rounded-lg flex-shrink-0 ${accent ? 'bg-[hsl(var(--primary)/0.12)]' : 'bg-[hsl(var(--secondary))]'}`}>
          {icon}
        </div>
      </div>
    </div>
  )
}

// ─── Empty State ──────────────────────────────────────────────────────────────

function EmptyState({ message, hint }: { message: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-10 text-center">
      <p className="text-base text-[hsl(var(--muted-foreground))]">⏳ {message}</p>
      {hint && <p className="text-xs text-[hsl(var(--muted-foreground)/0.6)] mt-2 font-mono">{hint}</p>}
    </div>
  )
}

// ─── Tab 1: Overview ─────────────────────────────────────────────────────────

function OverviewTab({ report }: { report: WeeklyReport | null }) {
  if (!report) {
    return (
      <div className="space-y-4">
        {[...Array(3)].map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)}
      </div>
    )
  }

  if (report.empty) {
    return (
      <EmptyState
        message={report.message ?? '暂无周报数据'}
        hint="node ~/.openclaw/skills/amazon-advertising/ppc-weekly-report.js"
      />
    )
  }

  const o = report.overview
  const priorityIcon = (p: string) => p === 'high' ? '🔴' : p === 'medium' ? '🟡' : '🟢'
  const alertIcon = (s: string) => s === 'critical' ? '🔴' : s === 'warning' ? '🟡' : 'ℹ️'

  return (
    <div className="space-y-6">
      {/* Overview KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <KPICard label="总花费" value={o.totalSpend !== null ? `$${fmtNum(o.totalSpend)}` : '—'}
          icon={<DollarSign className="w-4 h-4 text-[hsl(var(--zv-amber))]" />} />
        <KPICard label="广告销售额" value={o.totalSales !== null ? `$${fmtNum(o.totalSales)}` : '—'}
          icon={<ShoppingCart className="w-4 h-4 text-[hsl(var(--primary))]" />} accent />
        <KPICard label="总订单" value={o.totalOrders !== null ? String(o.totalOrders) : '—'}
          icon={<CheckSquare className="w-4 h-4 text-[hsl(var(--primary))]" />} accent={!!o.totalOrders} />
        <KPICard label="ACOS" value={o.acos !== null ? `${o.acos}%` : '—'}
          icon={<Percent className="w-4 h-4 text-[hsl(var(--zv-amber))]" />} accent={o.acos !== null && o.acos < 25} />
        <KPICard label="ROAS" value={o.roas !== null ? `${o.roas}x` : '—'}
          icon={<TrendingUp className="w-4 h-4 text-[hsl(var(--primary))]" />} accent={o.roas !== null && o.roas > 4} />
      </div>

      {/* Data period */}
      {report.dateRange?.start && (
        <p className="text-[10px] text-[hsl(var(--muted-foreground))] -mt-2">
          数据范围: {report.dateRange.start} → {report.dateRange.end}
        </p>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Risk alerts */}
        {report.riskAlerts.length > 0 && (
          <div className="rounded-xl border border-[hsl(var(--destructive)/0.3)] bg-[hsl(var(--card))] p-5">
            <div className="flex items-center gap-2 mb-4">
              <AlertTriangle className="w-4 h-4 text-[hsl(var(--destructive))]" />
              <h3 className="text-base font-semibold text-[hsl(var(--foreground))]">风险预警</h3>
              <Badge className="text-[9px] bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--destructive))] border-0 ml-auto">
                {report.summary.criticalAlerts} 紧急
              </Badge>
            </div>
            <div className="space-y-2.5">
              {report.riskAlerts.map((alert, i) => (
                <div key={i} className={`rounded-lg border p-3 ${
                  alert.severity === 'critical' ? 'border-[hsl(var(--destructive)/0.3)] bg-[hsl(var(--destructive)/0.05)]'
                    : alert.severity === 'warning' ? 'border-[hsl(var(--zv-amber)/0.3)] bg-[hsl(var(--zv-amber)/0.05)]'
                    : 'border-[hsl(var(--border))] bg-[hsl(var(--card))]'
                }`}>
                  <div className="flex items-start gap-2">
                    <span className="text-base">{alertIcon(alert.severity)}</span>
                    <div>
                      <p className="text-sm font-semibold text-[hsl(var(--foreground))]">{alert.type}</p>
                      <p className="text-xs text-[hsl(var(--muted-foreground))] mt-0.5">{alert.message}</p>
                      {alert.campaigns && alert.campaigns.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1.5">
                          {alert.campaigns.map((c, j) => (
                            <Badge key={j} variant="outline" className="text-[9px] h-4 px-1">{c}</Badge>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Action list */}
        <div className="rounded-xl border border-[hsl(var(--zv-amber)/0.3)] bg-[hsl(var(--card))] p-5">
          <div className="flex items-center gap-2 mb-4">
            <Lightbulb className="w-4 h-4 text-[hsl(var(--zv-amber))]" />
            <h3 className="text-base font-semibold text-[hsl(var(--foreground))]">关键行动清单</h3>
            <Badge className="text-[9px] bg-[hsl(var(--zv-amber)/0.15)] text-[hsl(var(--zv-amber))] border-0 ml-auto">
              {report.actionItems.length} 条
            </Badge>
          </div>
          {report.actionItems.length === 0 ? (
            <p className="text-sm text-[hsl(var(--muted-foreground))] text-center py-4">暂无行动项</p>
          ) : (
            <div className="space-y-2 max-h-[360px] overflow-y-auto">
              {report.actionItems.map((item, i) => (
                <div key={i} className={`flex items-start gap-2.5 p-2.5 rounded-lg border ${
                  item.priority === 'high' ? 'border-[hsl(var(--destructive)/0.25)] bg-[hsl(var(--destructive)/0.04)]'
                    : item.priority === 'medium' ? 'border-[hsl(var(--zv-amber)/0.25)] bg-[hsl(var(--zv-amber)/0.04)]'
                    : 'border-[hsl(var(--border))] bg-[hsl(var(--card))]'
                }`}>
                  <span className="text-sm mt-0.5">{priorityIcon(item.priority)}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <Badge variant="outline" className="text-[9px] h-4 px-1">{item.category}</Badge>
                      <span className="text-sm font-medium text-[hsl(var(--foreground))]">{item.action}</span>
                    </div>
                    {item.detail && <p className="text-[10px] text-[hsl(var(--muted-foreground))] mt-0.5 line-clamp-2">{item.detail}</p>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Money vs burn keywords */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="rounded-xl border border-[hsl(var(--primary)/0.3)] bg-[hsl(var(--card))] p-4">
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp className="w-4 h-4 text-[hsl(var(--primary))]" />
            <h3 className="text-base font-semibold">Top 5 赚钱词</h3>
          </div>
          {report.moneyKeywords.length === 0 ? (
            <p className="text-sm text-[hsl(var(--muted-foreground))] text-center py-4">暂无数据</p>
          ) : (
            <div className="space-y-1.5">
              {report.moneyKeywords.map((kw, i) => (
                <div key={i} className="flex items-center justify-between px-3 py-2 rounded-lg bg-[hsl(var(--primary)/0.06)]">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">"{kw.searchTerm}"</p>
                    <p className="text-[9px] text-[hsl(var(--muted-foreground))]">{kw.orders} 单 · ${kw.sales.toFixed(0)} 销售额</p>
                  </div>
                  <div className="text-right ml-2">
                    <p className="text-xs font-bold text-[hsl(var(--primary))]">ROAS {kw.roas}x</p>
                    <p className="text-[9px] text-[hsl(var(--muted-foreground))]">ACOS {kw.acos}%</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-xl border border-[hsl(var(--destructive)/0.3)] bg-[hsl(var(--card))] p-4">
          <div className="flex items-center gap-2 mb-3">
            <TrendingDown className="w-4 h-4 text-[hsl(var(--destructive))]" />
            <h3 className="text-base font-semibold">Top 5 烧钱词</h3>
          </div>
          {report.burnKeywords.length === 0 ? (
            <p className="text-sm text-[hsl(var(--muted-foreground))] text-center py-4">暂无数据</p>
          ) : (
            <div className="space-y-1.5">
              {report.burnKeywords.map((kw, i) => (
                <div key={i} className="flex items-center justify-between px-3 py-2 rounded-lg bg-[hsl(var(--destructive)/0.06)]">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">"{kw.searchTerm}"</p>
                    <p className="text-[9px] text-[hsl(var(--muted-foreground))]">{kw.clicks} 点击 · 0 转化</p>
                  </div>
                  <div className="text-right ml-2">
                    <p className="text-xs font-bold text-[hsl(var(--destructive))]">${kw.spend.toFixed(0)}</p>
                    <Badge variant="danger" className="text-[8px]">{kw.level}</Badge>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Tab 2: Keyword Optimization ─────────────────────────────────────────────

function KeywordsOptTab({ analysisData, analysisLoading }: {
  analysisData: AnalysisData | null; analysisLoading: boolean
}) {
  const [analysisTab, setAnalysisTab] = useState<'add-kw' | 'neg-kw' | 'match-upgrade' | 'long-tail' | 'duplicate'>('add-kw')

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      {analysisData && !analysisData.empty && analysisData.summary && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-3">
          {[
            { label: '建议加词', value: `${analysisData.summary.addKeywordCount}`, accent: true },
            { label: '否词 ⚠️ 警告', value: `${analysisData.summary.negWarnCount}` },
            { label: '否词 📋 标记', value: `${analysisData.summary.negFlagCount}` },
            { label: '匹配升级', value: `${analysisData.summary.upgradeCount}` },
            { label: '长尾机会', value: `${analysisData.summary.longTailCount}` },
            { label: '重复投放组', value: `${analysisData.summary.duplicateGroupCount}` },
            ...(analysisData.summary.estMonthlySavings != null
              ? [{ label: '预估月节省', value: `$${analysisData.summary.estMonthlySavings.toFixed(0)}` }]
              : []),
          ].map(({ label, value, accent }) => (
            <div key={label} className={`rounded-xl border p-3 ${accent ? 'border-[hsl(var(--primary)/0.4)] bg-[hsl(var(--primary)/0.06)]' : 'border-[hsl(var(--border))] bg-[hsl(var(--card))]'}`}>
              <p className="text-[10px] uppercase tracking-wider text-[hsl(var(--muted-foreground))] font-semibold">{label}</p>
              <p className={`text-lg font-bold mt-1 ${accent ? 'text-[hsl(var(--primary))]' : 'text-[hsl(var(--foreground))]'}`}>{value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Sub-tabs */}
      <div className="flex items-center gap-1 border-b border-[hsl(var(--border))]">
        {([
          { key: 'add-kw' as const, label: '加词建议', count: analysisData?.addKeywords.length ?? 0 },
          { key: 'neg-kw' as const, label: '否词建议', count: analysisData?.negativeKeywords.length ?? 0 },
          { key: 'match-upgrade' as const, label: '匹配升级', count: analysisData?.matchUpgrades.length ?? 0 },
          { key: 'long-tail' as const, label: '长尾机会', count: analysisData?.longTail.length ?? 0 },
          { key: 'duplicate' as const, label: '重复投放', count: analysisData?.duplicateTargeting.length ?? 0 },
        ]).map(tab => (
          <button key={tab.key} onClick={() => setAnalysisTab(tab.key)}
            className={`flex items-center gap-1.5 px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
              analysisTab === tab.key
                ? 'border-[hsl(var(--primary))] text-[hsl(var(--primary))]'
                : 'border-transparent text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'
            }`}
          >
            {tab.label}
            {tab.count > 0 && <Badge variant="outline" className="text-[8px] h-4 px-1">{tab.count}</Badge>}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {analysisLoading ? (
        <div className="space-y-2">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
      ) : analysisData?.empty ? (
        <EmptyState message={analysisData.message ?? '暂无分析数据'} hint="node ppc-keyword-analyzer.js" />
      ) : (
        <>
          {analysisTab === 'add-kw' && (
            <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
              <div className="px-4 py-3 border-b border-[hsl(var(--border)/0.5)] flex items-center gap-2">
                <Plus className="w-3.5 h-3.5 text-[hsl(var(--primary))]" />
                <h3 className="text-base font-semibold">加词建议</h3>
                <span className="text-[10px] text-[hsl(var(--muted-foreground))]">有转化、未作为关键词的搜索词</span>
              </div>
              {!analysisData?.addKeywords.length ? (
                <p className="text-sm text-[hsl(var(--muted-foreground))] text-center py-8">暂无加词建议</p>
              ) : (
                <>
                  <div className="flex items-center gap-2 px-4 py-2 text-[10px] uppercase tracking-wider text-[hsl(var(--muted-foreground))] font-semibold border-b border-[hsl(var(--border)/0.3)]">
                    <div className="flex-1">搜索词</div>
                    <div className="w-20 text-right">展示</div><div className="w-16 text-right">点击</div>
                    <div className="w-16 text-right">订单</div><div className="w-20 text-right">销售额</div>
                    <div className="w-16 text-right">ACOS</div><div className="w-24 text-right">建议匹配</div>
                  </div>
                  <div className="max-h-[500px] overflow-y-auto">
                    {analysisData?.addKeywords.map((item, i) => (
                      <div key={i} className="flex items-center gap-2 px-4 py-2.5 border-b border-[hsl(var(--border)/0.2)] hover:bg-[hsl(var(--secondary)/0.2)] transition-colors">
                        <div className="flex-1 min-w-0"><p className="text-sm font-medium truncate">{item.searchTerm}</p></div>
                        <div className="w-20 text-right text-sm">{fmtNum(item.impressions)}</div>
                        <div className="w-16 text-right text-sm">{item.clicks}</div>
                        <div className="w-16 text-right text-sm font-medium">{item.orders}</div>
                        <div className="w-20 text-right text-sm font-medium text-[hsl(var(--primary))]">${item.sales.toFixed(0)}</div>
                        <div className={`w-16 text-right text-sm font-bold ${item.acos <= 20 ? 'text-[hsl(var(--primary))]' : item.acos <= 35 ? 'text-[hsl(var(--zv-amber))]' : 'text-[hsl(var(--destructive))]'}`}>{item.acos}%</div>
                        <div className="w-24 text-right"><Badge variant="outline" className="text-[9px] uppercase">{item.suggestedMatchType}</Badge></div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {analysisTab === 'neg-kw' && <MergedNegativeTable items={analysisData?.negativeKeywords ?? []} />}

          {analysisTab === 'match-upgrade' && (
            <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
              <div className="px-4 py-3 border-b border-[hsl(var(--border)/0.5)] flex items-center gap-2">
                <ArrowUpDown className="w-3.5 h-3.5 text-[hsl(var(--zv-blue))]" />
                <h3 className="text-base font-semibold">匹配升级</h3>
                <span className="text-[10px] text-[hsl(var(--muted-foreground))]">建议从 broad → phrase/exact 升级</span>
              </div>
              {!analysisData?.matchUpgrades.length ? (
                <p className="text-sm text-[hsl(var(--muted-foreground))] text-center py-8">暂无匹配升级建议</p>
              ) : (
                <>
                  <div className="flex items-center gap-2 px-4 py-2 text-[10px] uppercase tracking-wider text-[hsl(var(--muted-foreground))] font-semibold border-b border-[hsl(var(--border)/0.3)]">
                    <div className="flex-1">关键词</div><div className="w-24 text-right">当前匹配</div>
                    <div className="w-16 text-right">订单</div><div className="w-16 text-right">ACOS</div><div className="flex-1 text-right">建议</div>
                  </div>
                  <div className="max-h-[500px] overflow-y-auto">
                    {analysisData?.matchUpgrades.map((item, i) => (
                      <div key={i} className="flex items-center gap-2 px-4 py-2.5 border-b border-[hsl(var(--border)/0.2)] hover:bg-[hsl(var(--secondary)/0.2)] transition-colors">
                        <div className="flex-1 min-w-0"><p className="text-sm font-medium truncate">{item.keyword}</p></div>
                        <div className="w-24 text-right"><Badge variant="outline" className="text-[9px] uppercase">{item.currentMatch}</Badge></div>
                        <div className="w-16 text-right text-sm">{item.orders}</div>
                        <div className={`w-16 text-right text-sm font-bold ${acosColor(item.acos)}`}>{item.acos}%</div>
                        <div className="flex-1 text-right text-sm text-[hsl(var(--primary))]">{item.suggestion}</div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {analysisTab === 'long-tail' && <LongTailTab items={analysisData?.longTail ?? []} />}

          {analysisTab === 'duplicate' && (
            <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
              <div className="px-4 py-3 border-b border-[hsl(var(--border)/0.5)] flex items-center gap-2">
                <BarChart3 className="w-3.5 h-3.5 text-[hsl(var(--zv-amber))]" />
                <h3 className="text-base font-semibold">重复投放</h3>
                <span className="text-[10px] text-[hsl(var(--muted-foreground))]">同一关键词出现在多个 Campaign</span>
              </div>
              {!analysisData?.duplicateTargeting.length ? (
                <p className="text-sm text-[hsl(var(--muted-foreground))] text-center py-8">暂无重复投放数据</p>
              ) : (
                <div className="max-h-[500px] overflow-y-auto divide-y divide-[hsl(var(--border)/0.3)]">
                  {analysisData?.duplicateTargeting.map((item, i) => (
                    <div key={i} className="px-4 py-3 hover:bg-[hsl(var(--secondary)/0.2)] transition-colors">
                      <p className="text-sm font-semibold mb-1.5">{item.keyword}</p>
                      <div className="flex flex-wrap gap-1.5">
                        {item.campaigns.map((c, j) => (
                          <Badge key={j} variant="outline" className="text-[9px]">{c}</Badge>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ─── Tab 3: Campaign Structure ────────────────────────────────────────────────

function CampaignStructureTab({ data }: { data: CampaignAnalysis | null }) {
  const [subTab, setSubTab] = useState<'duplicates' | 'asin' | 'zombies' | 'naming'>('duplicates')

  if (!data) {
    return (
      <div className="space-y-4">
        {[...Array(3)].map((_, i) => <Skeleton key={i} className="h-20 rounded-xl" />)}
      </div>
    )
  }

  if (data.empty) {
    return (
      <EmptyState
        message={data.message ?? '暂无 Campaign 结构分析数据'}
        hint="node ~/.openclaw/skills/amazon-advertising/ppc-campaign-analyzer.js"
      />
    )
  }

  const s = data.summary
  const subTabs = [
    { key: 'duplicates' as const, label: '重复投放', count: data.duplicates?.length ?? 0 },
    { key: 'asin' as const, label: 'ASIN 覆盖', count: data.asinCoverage?.uncovered.length ?? 0, countLabel: '未覆盖' },
    { key: 'zombies' as const, label: '僵尸 Campaign', count: data.zombieCampaigns?.length ?? 0 },
    { key: 'naming' as const, label: '命名检查', count: data.naming?.issueCount ?? 0, countLabel: '不规范' },
  ]

  return (
    <div className="space-y-4">
      {/* Summary bar */}
      {s && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {[
            { label: '总 Campaign', value: s.totalCampaigns, sub: `${s.activeCampaigns} 活跃` },
            { label: '重复投放组', value: s.duplicateGroups, alert: s.duplicateGroups > 0 },
            { label: '僵尸 Campaign', value: s.zombieCampaigns, alert: s.zombieCampaigns > 0 },
            { label: '命名不规范', value: s.namingIssues, alert: s.namingIssues > 0 },
          ].map(({ label, value, sub, alert }) => (
            <div key={label} className={`rounded-xl border p-3 ${alert ? 'border-[hsl(var(--zv-amber)/0.4)] bg-[hsl(var(--zv-amber)/0.05)]' : 'border-[hsl(var(--border))] bg-[hsl(var(--card))]'}`}>
              <p className="text-[10px] uppercase tracking-wider text-[hsl(var(--muted-foreground))] font-semibold">{label}</p>
              <p className={`text-2xl font-bold mt-1 ${alert ? 'text-[hsl(var(--zv-amber))]' : 'text-[hsl(var(--foreground))]'}`}>{value}</p>
              {sub && <p className="text-[10px] text-[hsl(var(--muted-foreground))]">{sub}</p>}
            </div>
          ))}
        </div>
      )}

      {/* Type distribution */}
      {data.typeDistribution && (
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
          <div className="flex items-center gap-2 mb-3">
            <Layers className="w-3.5 h-3.5 text-[hsl(var(--primary))]" />
            <h3 className="text-sm font-semibold">Campaign 类型分布</h3>
          </div>
          <div className="grid grid-cols-2 gap-4">
            {[
              { label: 'Sponsored Products (SP)', data: data.typeDistribution.sp, color: 'var(--primary)' },
              { label: 'Sponsored Brands (SB)', data: data.typeDistribution.sb, color: 'var(--zv-amber)' },
            ].map(({ label, data: d, color }) => (
              <div key={label} className="space-y-1">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium" style={{ color: `hsl(${color})` }}>{label}</span>
                  <span className="text-xs text-[hsl(var(--muted-foreground))]">{d.budgetShare}% 预算占比</span>
                </div>
                <div className="h-1.5 rounded-full bg-[hsl(var(--secondary))] overflow-hidden">
                  <div className="h-full rounded-full transition-all" style={{ width: `${d.budgetShare}%`, backgroundColor: `hsl(${color})` }} />
                </div>
                <p className="text-xs text-[hsl(var(--muted-foreground))]">
                  {d.active} 活跃 · {d.total} 总 · ${d.dailyBudget}/天
                </p>
              </div>
            ))}
          </div>
          <p className="text-xs text-[hsl(var(--muted-foreground))] mt-3">总日预算: ${data.typeDistribution.totalDailyBudget}</p>
        </div>
      )}

      {/* Sub-tabs */}
      <div className="flex items-center gap-1 border-b border-[hsl(var(--border))]">
        {subTabs.map(tab => (
          <button key={tab.key} onClick={() => setSubTab(tab.key)}
            className={`flex items-center gap-1.5 px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
              subTab === tab.key ? 'border-[hsl(var(--primary))] text-[hsl(var(--primary))]' : 'border-transparent text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'
            }`}
          >
            {tab.label}
            {tab.count > 0 && (
              <Badge variant="outline" className={`text-[8px] h-4 px-1 ${tab.countLabel ? 'border-[hsl(var(--zv-amber)/0.4)]' : ''}`}>{tab.count}</Badge>
            )}
          </button>
        ))}
      </div>

      {/* Sub-tab content */}
      {subTab === 'duplicates' && (
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
          <div className="px-4 py-3 border-b border-[hsl(var(--border)/0.5)] flex items-center gap-2">
            <BarChart3 className="w-3.5 h-3.5 text-[hsl(var(--zv-amber))]" />
            <h3 className="text-sm font-semibold">Campaign 间重复关键词</h3>
          </div>
          {!data.duplicates?.length ? (
            <p className="text-sm text-[hsl(var(--muted-foreground))] text-center py-8">✅ 未发现重复投放</p>
          ) : (
            <div className="max-h-[400px] overflow-y-auto divide-y divide-[hsl(var(--border)/0.3)]">
              {data.duplicates.map((item, i) => (
                <div key={i} className="px-4 py-3 hover:bg-[hsl(var(--secondary)/0.2)]">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-sm font-semibold">"{item.keyword}"</span>
                    <Badge variant="outline" className="text-[9px]">{item.matchType}</Badge>
                    <Badge className="text-[9px] bg-[hsl(var(--zv-amber)/0.15)] text-[hsl(var(--zv-amber))] border-0">{item.occurrences}x</Badge>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {item.campaigns.map((c, j) => <Badge key={j} variant="outline" className="text-[9px]">{c}</Badge>)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {subTab === 'asin' && (
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
          <div className="flex items-center gap-2 mb-4">
            <Target className="w-3.5 h-3.5 text-[hsl(var(--primary))]" />
            <h3 className="text-sm font-semibold">ASIN 广告覆盖检查</h3>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div>
              <p className="text-xs text-[hsl(var(--primary))] font-semibold mb-2">✅ 已覆盖 ({data.asinCoverage?.covered.length})</p>
              <div className="flex flex-wrap gap-2">
                {data.asinCoverage?.covered.map(asin => (
                  <Badge key={asin} className="text-[10px] bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))] border-[hsl(var(--primary)/0.3)]">{asin}</Badge>
                ))}
                {!data.asinCoverage?.covered.length && <p className="text-sm text-[hsl(var(--muted-foreground))]">无</p>}
              </div>
            </div>
            <div>
              <p className="text-xs text-[hsl(var(--destructive))] font-semibold mb-2">⚠️ 未覆盖 ({data.asinCoverage?.uncovered.length})</p>
              <div className="flex flex-wrap gap-2">
                {data.asinCoverage?.uncovered.map(asin => (
                  <Badge key={asin} variant="danger" className="text-[10px]">{asin}</Badge>
                ))}
                {!data.asinCoverage?.uncovered.length && <p className="text-sm text-[hsl(var(--muted-foreground))]">全部已覆盖</p>}
              </div>
            </div>
          </div>
          {data.asinCoverage?.note && (
            <p className="text-[10px] text-[hsl(var(--muted-foreground))] mt-4 italic">{data.asinCoverage.note}</p>
          )}
        </div>
      )}

      {subTab === 'zombies' && (
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
          <div className="px-4 py-3 border-b border-[hsl(var(--border)/0.5)] flex items-center gap-2">
            <PauseCircle className="w-3.5 h-3.5 text-[hsl(var(--muted-foreground))]" />
            <h3 className="text-sm font-semibold">僵尸 Campaign</h3>
            <span className="text-[10px] text-[hsl(var(--muted-foreground))]">有预算但近期无流量</span>
          </div>
          {!data.zombieCampaigns?.length ? (
            <p className="text-sm text-[hsl(var(--muted-foreground))] text-center py-8">✅ 未发现僵尸 Campaign</p>
          ) : (
            <div className="max-h-[400px] overflow-y-auto divide-y divide-[hsl(var(--border)/0.3)]">
              {data.zombieCampaigns.map((camp, i) => (
                <div key={i} className="px-4 py-3 hover:bg-[hsl(var(--secondary)/0.2)]">
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <p className="text-sm font-medium">{camp.name}</p>
                      <p className="text-[10px] text-[hsl(var(--muted-foreground))] mt-0.5">
                        {camp.type} · 启动 {camp.startDaysAgo} 天前 · 日预算 ${camp.dailyBudget}
                      </p>
                      <p className="text-[10px] text-[hsl(var(--zv-amber))] mt-0.5">{camp.reason}</p>
                    </div>
                    <Badge variant="outline" className="text-[9px] text-[hsl(var(--zv-amber))] border-[hsl(var(--zv-amber)/0.4)] flex-shrink-0">
                      待审查
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {subTab === 'naming' && (
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
          <div className="px-4 py-3 border-b border-[hsl(var(--border)/0.5)] flex items-center gap-2">
            <Filter className="w-3.5 h-3.5 text-[hsl(var(--muted-foreground))]" />
            <h3 className="text-sm font-semibold">命名规范检查</h3>
            {data.naming?.dominantPattern && (
              <Badge variant="outline" className="text-[9px] ml-auto">{data.naming.dominantPattern}</Badge>
            )}
          </div>
          {!data.naming?.issues.length ? (
            <p className="text-sm text-[hsl(var(--muted-foreground))] text-center py-8">✅ 命名规范一致</p>
          ) : (
            <div className="max-h-[400px] overflow-y-auto divide-y divide-[hsl(var(--border)/0.3)]">
              {data.naming.issues.map((item, i) => (
                <div key={i} className="px-4 py-3 hover:bg-[hsl(var(--secondary)/0.2)]">
                  <p className="text-sm font-medium">{item.name}</p>
                  <div className="flex items-center gap-1.5 mt-1">
                    <Badge variant="outline" className="text-[9px]">{item.type}</Badge>
                    {item.issues.map((issue, j) => (
                      <Badge key={j} className="text-[9px] bg-[hsl(var(--zv-amber)/0.12)] text-[hsl(var(--zv-amber))] border-0">{issue}</Badge>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Recommendations */}
      {data.recommendations && data.recommendations.length > 0 && (
        <div className="rounded-xl border border-[hsl(var(--zv-amber)/0.3)] bg-[hsl(var(--card))] p-5">
          <div className="flex items-center gap-2 mb-3">
            <Lightbulb className="w-4 h-4 text-[hsl(var(--zv-amber))]" />
            <h3 className="text-sm font-semibold">Campaign 结构建议</h3>
          </div>
          <div className="space-y-2">
            {data.recommendations.map((rec, i) => (
              <div key={i} className={`rounded-lg border p-3 ${
                rec.priority === 'high' ? 'border-[hsl(var(--destructive)/0.25)] bg-[hsl(var(--destructive)/0.04)]'
                  : rec.priority === 'medium' ? 'border-[hsl(var(--zv-amber)/0.25)] bg-[hsl(var(--zv-amber)/0.04)]'
                  : 'border-[hsl(var(--border))]'
              }`}>
                <div className="flex items-center gap-2 mb-1">
                  <Badge variant="outline" className="text-[9px]">{rec.category}</Badge>
                  <span className="text-sm font-medium">{rec.action}</span>
                </div>
                <p className="text-[10px] text-[hsl(var(--muted-foreground))]">{rec.detail}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Tab 4: Bid & Budget ──────────────────────────────────────────────────────

function BidBudgetTab({ data }: { data: BidAnalysis | null }) {
  const [subTab, setSubTab] = useState<'efficiency' | 'utilization' | 'acos' | 'performers' | 'realloc'>('efficiency')

  if (!data) {
    return <div className="space-y-4">{[...Array(3)].map((_, i) => <Skeleton key={i} className="h-20 rounded-xl" />)}</div>
  }

  if (data.empty) {
    return (
      <EmptyState
        message={data.message ?? '暂无 Bid/Budget 分析数据'}
        hint="node ~/.openclaw/skills/amazon-advertising/ppc-bid-analyzer.js"
      />
    )
  }

  const s = data.summary
  const subTabs = [
    { key: 'efficiency' as const, label: 'Bid 效率', count: (data.bidEfficiency?.overbidding.length ?? 0) + (data.bidEfficiency?.underbidding.length ?? 0) },
    { key: 'utilization' as const, label: 'Budget 利用率', count: data.budgetUtilization?.capped.length ?? 0, countLabel: '满载' },
    { key: 'acos' as const, label: 'ACOS 分析', count: data.acosAnalysis?.breakeven.length ?? 0, countLabel: '亏损' },
    { key: 'performers' as const, label: 'Top/Bottom', count: 0 },
    { key: 'realloc' as const, label: '重分配建议', count: data.reallocations?.length ?? 0 },
  ]

  return (
    <div className="space-y-4">
      {/* Summary bar */}
      {s && (
        <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3">
          {[
            { label: 'Overbidding', value: s.overbiddingCount, alert: s.overbiddingCount > 0 },
            { label: 'Underbidding', value: s.underbiddingCount, accent: s.underbiddingCount > 0 },
            { label: '预算满载', value: s.cappedCampaigns, alert: s.cappedCampaigns > 0 },
            { label: '未充分利用', value: s.underutilizedCampaigns },
            { label: 'ACOS 恶化', value: s.acosWorseningCount, alert: s.acosWorseningCount > 0 },
            { label: '亏损预警', value: s.breakevenAlerts, alert: s.breakevenAlerts > 0 },
          ].map(({ label, value, alert, accent }) => (
            <div key={label} className={`rounded-xl border p-3 ${alert ? 'border-[hsl(var(--destructive)/0.4)] bg-[hsl(var(--destructive)/0.05)]' : accent ? 'border-[hsl(var(--primary)/0.3)] bg-[hsl(var(--primary)/0.05)]' : 'border-[hsl(var(--border))] bg-[hsl(var(--card))]'}`}>
              <p className="text-[10px] uppercase tracking-wider text-[hsl(var(--muted-foreground))] font-semibold">{label}</p>
              <p className={`text-2xl font-bold mt-1 ${alert ? 'text-[hsl(var(--destructive))]' : accent ? 'text-[hsl(var(--primary))]' : ''}`}>{value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Sub-tabs */}
      <div className="flex items-center gap-1 border-b border-[hsl(var(--border))] overflow-x-auto">
        {subTabs.map(tab => (
          <button key={tab.key} onClick={() => setSubTab(tab.key)}
            className={`flex items-center gap-1.5 px-3 py-2 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
              subTab === tab.key ? 'border-[hsl(var(--primary))] text-[hsl(var(--primary))]' : 'border-transparent text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'
            }`}
          >
            {tab.label}
            {tab.count > 0 && <Badge variant="outline" className="text-[8px] h-4 px-1">{tab.count}</Badge>}
          </button>
        ))}
      </div>

      {/* Bid efficiency */}
      {subTab === 'efficiency' && (
        <div className="space-y-4">
          {!data.bidEfficiency?.overbidding.length && !data.bidEfficiency?.underbidding.length ? (
            <EmptyState message="暂无 Bid 效率分析数据（需要关键词级别 CPC 数据）" />
          ) : (
            <>
              {data.bidEfficiency?.overbidding.length > 0 && (
                <div className="rounded-xl border border-[hsl(var(--destructive)/0.3)] bg-[hsl(var(--card))] overflow-hidden">
                  <div className="px-4 py-3 border-b border-[hsl(var(--border)/0.5)] flex items-center gap-2">
                    <ArrowDown className="w-3.5 h-3.5 text-[hsl(var(--destructive))]" />
                    <h3 className="text-sm font-semibold">出价过高 (Overbidding)</h3>
                    <Badge className="text-[9px] bg-[hsl(var(--destructive)/0.12)] text-[hsl(var(--destructive))] border-0">{data.bidEfficiency.overbidding.length}</Badge>
                  </div>
                  <div className="max-h-[300px] overflow-y-auto divide-y divide-[hsl(var(--border)/0.2)]">
                    {data.bidEfficiency.overbidding.map((kw, i) => (
                      <div key={i} className="px-4 py-3 hover:bg-[hsl(var(--secondary)/0.2)]">
                        <div className="flex items-center justify-between gap-2">
                          <div>
                            <p className="text-sm font-medium">"{kw.keyword}"</p>
                            <p className="text-[10px] text-[hsl(var(--muted-foreground))]">{kw.campaignName} · {kw.matchType}</p>
                          </div>
                          <div className="text-right">
                            <p className="text-sm"><span className="text-[hsl(var(--destructive))]">${kw.bid}</span> 出价 → <span className="text-[hsl(var(--primary))]">${kw.actualCpc}</span> 实际</p>
                            <p className="text-[10px] text-[hsl(var(--muted-foreground))]">花费 ${kw.spend}</p>
                          </div>
                        </div>
                        <p className="text-[10px] text-[hsl(var(--zv-amber))] mt-1">{kw.suggestion}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {data.bidEfficiency?.underbidding.length > 0 && (
                <div className="rounded-xl border border-[hsl(var(--primary)/0.3)] bg-[hsl(var(--card))] overflow-hidden">
                  <div className="px-4 py-3 border-b border-[hsl(var(--border)/0.5)] flex items-center gap-2">
                    <ArrowUp className="w-3.5 h-3.5 text-[hsl(var(--primary))]" />
                    <h3 className="text-sm font-semibold">出价不足 (Underbidding)</h3>
                    <Badge className="text-[9px] bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))] border-0">{data.bidEfficiency.underbidding.length}</Badge>
                  </div>
                  <div className="max-h-[300px] overflow-y-auto divide-y divide-[hsl(var(--border)/0.2)]">
                    {data.bidEfficiency.underbidding.map((kw, i) => (
                      <div key={i} className="px-4 py-3 hover:bg-[hsl(var(--secondary)/0.2)]">
                        <div className="flex items-center justify-between gap-2">
                          <div>
                            <p className="text-sm font-medium">"{kw.keyword}"</p>
                            <p className="text-[10px] text-[hsl(var(--muted-foreground))]">{kw.campaignName}</p>
                          </div>
                          <div className="text-right">
                            <p className="text-xs font-medium text-[hsl(var(--primary))]">ACOS {kw.acos}% · {kw.orders} 单</p>
                          </div>
                        </div>
                        <p className="text-[10px] text-[hsl(var(--primary))] mt-1">{kw.suggestion}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Budget utilization */}
      {subTab === 'utilization' && (
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
          <div className="px-4 py-3 border-b border-[hsl(var(--border)/0.5)] flex items-center gap-2">
            <CreditCard className="w-3.5 h-3.5 text-[hsl(var(--zv-blue))]" />
            <h3 className="text-sm font-semibold">Budget 利用率</h3>
            <div className="ml-auto flex items-center gap-2 text-[9px]">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[hsl(var(--destructive))] inline-block"/> 满载 &gt;90%</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[hsl(var(--primary))] inline-block"/> 健康 60-90%</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[hsl(var(--muted-foreground))] inline-block"/> 低利用</span>
            </div>
          </div>
          {!data.budgetUtilization?.campaigns.length ? (
            <p className="text-sm text-[hsl(var(--muted-foreground))] text-center py-8">暂无数据（需要性能报告）</p>
          ) : (
            <div className="max-h-[400px] overflow-y-auto divide-y divide-[hsl(var(--border)/0.2)]">
              {data.budgetUtilization.campaigns.map((camp, i) => {
                const util = camp.utilization ?? 0
                const barColor = util >= 90 ? 'hsl(var(--destructive))' : util >= 60 ? 'hsl(var(--primary))' : 'hsl(var(--muted-foreground))'
                return (
                  <div key={i} className="px-4 py-3 hover:bg-[hsl(var(--secondary)/0.2)]">
                    <div className="flex items-center justify-between gap-3 mb-1.5">
                      <p className="text-sm font-medium truncate flex-1">{camp.name}</p>
                      <div className="flex items-center gap-3 text-sm flex-shrink-0">
                        <span className="text-[hsl(var(--muted-foreground))]">${camp.dailyBudget}/天</span>
                        <span className="font-bold" style={{ color: barColor }}>
                          {camp.utilization !== null ? `${camp.utilization}%` : '—'}
                        </span>
                      </div>
                    </div>
                    {camp.utilization !== null && (
                      <div className="h-1 rounded-full bg-[hsl(var(--secondary))] overflow-hidden">
                        <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(camp.utilization, 100)}%`, backgroundColor: barColor }} />
                      </div>
                    )}
                    {camp.acos !== null && (
                      <p className="text-[9px] text-[hsl(var(--muted-foreground))] mt-1">
                        花费 ${camp.totalSpend} · 销售 ${camp.totalSales} · ACOS {camp.acos}% · ROAS {camp.roas}x
                      </p>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* ACOS analysis */}
      {subTab === 'acos' && (
        <div className="space-y-4">
          {data.acosAnalysis?.breakeven.length === 0 && data.acosAnalysis?.deteriorating.length === 0 ? (
            <EmptyState message="ACOS 表现良好，暂无预警" />
          ) : (
            <>
              {data.acosAnalysis?.breakeven && data.acosAnalysis.breakeven.length > 0 && (
                <div className="rounded-xl border border-[hsl(var(--destructive)/0.4)] bg-[hsl(var(--destructive)/0.04)] p-5">
                  <div className="flex items-center gap-2 mb-3">
                    <AlertTriangle className="w-4 h-4 text-[hsl(var(--destructive))]" />
                    <h3 className="text-sm font-semibold">亏损 Campaign (ACOS &gt; {data.acosAnalysis.breakevenAcos}%)</h3>
                  </div>
                  <div className="space-y-2">
                    {data.acosAnalysis.breakeven.map((c, i) => (
                      <div key={i} className="flex items-center justify-between px-3 py-2.5 rounded-lg bg-[hsl(var(--card))] border border-[hsl(var(--destructive)/0.2)]">
                        <div>
                          <p className="text-sm font-medium">{c.name}</p>
                          <p className="text-[10px] text-[hsl(var(--muted-foreground))]">花费 ${c.spend}</p>
                        </div>
                        <div className="text-right">
                          <p className="text-base font-bold text-[hsl(var(--destructive))]">ACOS {c.acos}%</p>
                          <Badge className="text-[8px] bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--destructive))] border-0">
                            {c.severity === 'critical' ? '严重' : '预警'}
                          </Badge>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {data.acosAnalysis?.deteriorating && data.acosAnalysis.deteriorating.length > 0 && (
                <div className="rounded-xl border border-[hsl(var(--zv-amber)/0.3)] bg-[hsl(var(--card))] p-5">
                  <div className="flex items-center gap-2 mb-3">
                    <TrendingDown className="w-4 h-4 text-[hsl(var(--zv-amber))]" />
                    <h3 className="text-sm font-semibold">ACOS 恶化 (超目标 {data.acosAnalysis.targetAcos}% 50%+)</h3>
                  </div>
                  <div className="space-y-2">
                    {data.acosAnalysis.deteriorating.map((c, i) => (
                      <div key={i} className="flex items-center justify-between px-3 py-2.5 rounded-lg bg-[hsl(var(--zv-amber)/0.05)] border border-[hsl(var(--zv-amber)/0.2)]">
                        <p className="text-sm font-medium">{c.name}</p>
                        <div className="text-right">
                          <p className="text-sm font-bold text-[hsl(var(--zv-amber))]">ACOS {c.acos}%</p>
                          <p className="text-[9px] text-[hsl(var(--muted-foreground))]">超目标 +{c.gap}%</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Performers */}
      {subTab === 'performers' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="rounded-xl border border-[hsl(var(--primary)/0.3)] bg-[hsl(var(--card))] p-4">
            <div className="flex items-center gap-2 mb-3">
              <TrendingUp className="w-4 h-4 text-[hsl(var(--primary))]" />
              <h3 className="text-sm font-semibold">Top 5 高绩效 Campaign</h3>
            </div>
            {!data.performers?.top5.length ? (
              <p className="text-sm text-[hsl(var(--muted-foreground))] text-center py-4">暂无数据</p>
            ) : (
              <div className="space-y-2">
                {data.performers.top5.map((c, i) => (
                  <div key={i} className="flex items-center justify-between px-3 py-2.5 rounded-lg bg-[hsl(var(--primary)/0.06)]">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium truncate">{c.name}</p>
                      <p className="text-[9px] text-[hsl(var(--muted-foreground))]">花费 ${c.spend}</p>
                    </div>
                    <div className="text-right ml-2">
                      <p className="text-sm font-bold text-[hsl(var(--primary))]">ROAS {c.roas}x</p>
                      {c.acos !== null && <p className="text-[9px] text-[hsl(var(--muted-foreground))]">ACOS {c.acos}%</p>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="rounded-xl border border-[hsl(var(--destructive)/0.3)] bg-[hsl(var(--card))] p-4">
            <div className="flex items-center gap-2 mb-3">
              <TrendingDown className="w-4 h-4 text-[hsl(var(--destructive))]" />
              <h3 className="text-sm font-semibold">Bottom 5 低绩效 Campaign</h3>
            </div>
            {!data.performers?.bottom5.length ? (
              <p className="text-sm text-[hsl(var(--muted-foreground))] text-center py-4">暂无数据</p>
            ) : (
              <div className="space-y-2">
                {data.performers.bottom5.map((c, i) => (
                  <div key={i} className="flex items-center justify-between px-3 py-2.5 rounded-lg bg-[hsl(var(--destructive)/0.06)]">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium truncate">{c.name}</p>
                      <p className="text-[9px] text-[hsl(var(--muted-foreground))]">花费 ${c.spend}</p>
                    </div>
                    <div className="text-right ml-2">
                      <p className="text-sm font-bold text-[hsl(var(--destructive))]">ROAS {c.roas}x</p>
                      {c.acos !== null && <p className="text-[9px] text-[hsl(var(--muted-foreground))]">ACOS {c.acos}%</p>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Reallocation */}
      {subTab === 'realloc' && (
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
          <div className="flex items-center gap-2 mb-4">
            <Activity className="w-4 h-4 text-[hsl(var(--zv-blue))]" />
            <h3 className="text-sm font-semibold">Budget 重分配建议</h3>
          </div>
          {!data.reallocations?.length ? (
            <p className="text-sm text-[hsl(var(--muted-foreground))] text-center py-4">暂无重分配建议</p>
          ) : (
            <div className="space-y-3">
              {data.reallocations.map((r, i) => (
                <div key={i} className={`rounded-lg border p-4 ${r.fromCampaign ? 'border-[hsl(var(--destructive)/0.25)] bg-[hsl(var(--destructive)/0.03)]' : 'border-[hsl(var(--primary)/0.25)] bg-[hsl(var(--primary)/0.03)]'}`}>
                  {r.fromCampaign ? (
                    <>
                      <div className="flex items-center gap-2 mb-1">
                        <ArrowDown className="w-3.5 h-3.5 text-[hsl(var(--destructive))]" />
                        <span className="text-sm font-medium">{r.fromCampaign}</span>
                        <span className="text-sm text-[hsl(var(--muted-foreground))]">${r.currentBudget} → ${r.suggestedBudget}/天</span>
                        <Badge className="text-[9px] bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))] border-0 ml-auto">释放 ${r.freedBudget}</Badge>
                      </div>
                      <p className="text-[10px] text-[hsl(var(--muted-foreground))]">{r.reason}</p>
                    </>
                  ) : (
                    <>
                      <div className="flex items-center gap-2 mb-2">
                        <ArrowUp className="w-3.5 h-3.5 text-[hsl(var(--primary))]" />
                        <span className="text-sm font-medium">{r.action}</span>
                        <Badge className="text-[9px] bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))] border-0 ml-auto">${r.budgetToDistribute} 可分配</Badge>
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {r.targetCampaigns?.map((c, j) => <Badge key={j} variant="outline" className="text-[9px]">{c}</Badge>)}
                      </div>
                      <p className="text-[10px] text-[hsl(var(--muted-foreground))] mt-1">{r.reason}</p>
                    </>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Tab 5: Keywords Table ────────────────────────────────────────────────────

function KeywordsTable({ keywords, loading }: { keywords: Keyword[]; loading: boolean }) {
  const [sortKey, setSortKey] = useState<SortKey>('cost')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [search, setSearch] = useState('')
  const [limit, setLimit] = useState(50)

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  const filtered = useMemo(() => {
    let list = keywords
    if (search) list = list.filter(k => k.keyword.toLowerCase().includes(search.toLowerCase()))
    list = [...list].sort((a, b) => {
      const av = a[sortKey] ?? 0, bv = b[sortKey] ?? 0
      if (typeof av === 'string') return sortDir === 'asc' ? (av as string).localeCompare(bv as string) : (bv as string).localeCompare(av as string)
      return sortDir === 'asc' ? (av as number) - (bv as number) : (bv as number) - (av as number)
    })
    return list
  }, [keywords, search, sortKey, sortDir])

  const cols: { key: SortKey; label: string; align?: string; width?: string }[] = [
    { key: 'keyword', label: '关键词/投放', width: 'flex-1 min-w-[200px]' },
    { key: 'impressions', label: '展示', align: 'text-right', width: 'w-20' },
    { key: 'clicks', label: '点击', align: 'text-right', width: 'w-16' },
    { key: 'ctr', label: 'CTR', align: 'text-right', width: 'w-16' },
    { key: 'cpc', label: 'CPC', align: 'text-right', width: 'w-16' },
    { key: 'cost', label: '花费', align: 'text-right', width: 'w-20' },
    { key: 'sales', label: '销售额', align: 'text-right', width: 'w-20' },
    { key: 'orders', label: '订单', align: 'text-right', width: 'w-16' },
    { key: 'acos', label: 'ACOS', align: 'text-right', width: 'w-18' },
    { key: 'convRate', label: '转化率', align: 'text-right', width: 'w-18' },
  ]

  function SortHeader({ col }: { col: typeof cols[0] }) {
    const active = sortKey === col.key
    return (
      <button onClick={() => toggleSort(col.key)}
        className={`flex items-center gap-0.5 text-[10px] uppercase tracking-wider font-semibold ${col.align ?? ''} ${
          active ? 'text-[hsl(var(--primary))]' : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'
        }`}
      >
        {col.label}
        {active && (sortDir === 'desc' ? <ChevronDown className="w-2.5 h-2.5" /> : <ChevronUp className="w-2.5 h-2.5" />)}
      </button>
    )
  }

  if (loading) return <div className="space-y-2">{[...Array(10)].map((_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>

  return (
    <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-base font-semibold">关键词/投放表现</h2>
          <p className="text-[10px] text-[hsl(var(--muted-foreground))]">按花费排序 · 点击列头可排序</p>
        </div>
        <Badge variant="outline" className="text-[9px]">{keywords.length} 个关键词</Badge>
      </div>
      <div className="mb-3">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[hsl(var(--muted-foreground))]" />
          <input value={search} onChange={e => setSearch(e.target.value)}
            placeholder="搜索关键词…" className="w-full pl-9 pr-3 py-2 rounded-lg bg-[hsl(var(--secondary)/0.5)] border border-[hsl(var(--border))] text-base text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))] focus:outline-none focus:border-[hsl(var(--primary)/0.5)]"
          />
        </div>
      </div>
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[hsl(var(--border))]">
        {cols.map(col => (
          <div key={col.key} className={col.width}><SortHeader col={col} /></div>
        ))}
      </div>
      <div className="max-h-[600px] overflow-y-auto">
        {filtered.length === 0 ? (
          <p className="text-sm text-[hsl(var(--muted-foreground))] text-center py-8">暂无关键词数据</p>
        ) : (
          filtered.slice(0, limit).map((k, i) => (
            <div key={i} className={`flex items-center gap-2 px-3 py-2 border-b border-[hsl(var(--border)/0.3)] hover:bg-[hsl(var(--secondary)/0.2)] transition-colors ${acosBg(k.acos)}`}>
              <div className="flex-1 min-w-[200px]">
                <p className="text-sm font-medium truncate">{k.keyword}</p>
                <p className="text-[9px] text-[hsl(var(--muted-foreground))] truncate">{k.matchType} · {k.campaignName}</p>
              </div>
              <div className="w-20 text-right text-sm">{fmtNum(k.impressions)}</div>
              <div className="w-16 text-right text-sm">{fmtNum(k.clicks)}</div>
              <div className="w-16 text-right text-sm text-[hsl(var(--muted-foreground))]">{k.ctr}%</div>
              <div className="w-16 text-right text-sm">${k.cpc}</div>
              <div className="w-20 text-right text-sm font-medium">${k.cost.toFixed(0)}</div>
              <div className="w-20 text-right text-sm font-medium text-[hsl(var(--primary))]">${k.sales.toFixed(0)}</div>
              <div className="w-16 text-right text-sm">{k.orders}</div>
              <div className={`w-18 text-right text-sm font-bold ${acosColor(k.acos)}`}>{k.acos > 900 ? '∞' : `${k.acos}%`}</div>
              <div className={`w-18 text-right text-sm font-medium ${convColor(k.convRate)}`}>{k.convRate}%</div>
            </div>
          ))
        )}
      </div>
      {filtered.length > limit && (
        <button onClick={() => setLimit(l => l + 50)} className="w-full py-2 text-sm text-[hsl(var(--primary))] hover:underline">
          加载更多 ({filtered.length - limit} 条剩余)
        </button>
      )}
    </div>
  )
}

// ─── Tab 6: Search Terms ──────────────────────────────────────────────────────

function SearchTermsPanel({ period }: { period: Period }) {
  const [terms, setTerms] = useState<SearchTerm[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    setLoading(true)
    fetch(`/api/ppc/search-terms?days=${period}`)
      .then(r => r.json())
      .then(d => { setTerms(d.terms ?? []); setError(!!d.error) })
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [period])

  const goodTerms = terms.filter(t => t.orders >= 2 && t.acos < 30).slice(0, 8)
  const badTerms = terms.filter(t => t.clicks >= 5 && t.orders === 0 && t.cost > 3).slice(0, 8)

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div className="rounded-xl border border-[hsl(var(--primary)/0.3)] bg-[hsl(var(--card))] p-4">
        <div className="flex items-center gap-2 mb-3">
          <Plus className="w-4 h-4 text-[hsl(var(--primary))]" />
          <h3 className="text-base font-semibold">优质搜索词</h3>
          <span className="text-[10px] text-[hsl(var(--muted-foreground))]">建议添加为关键词</span>
        </div>
        {loading ? (
          <div className="space-y-2">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
        ) : error ? (
          <p className="text-sm text-[hsl(var(--muted-foreground))] text-center py-4">搜索词报告加载失败</p>
        ) : goodTerms.length ? (
          <div className="space-y-1.5">
            {goodTerms.map((t, i) => (
              <div key={i} className="flex items-center justify-between px-3 py-2 rounded-lg bg-[hsl(var(--primary)/0.06)]">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium truncate">"{t.searchTerm}"</p>
                  <p className="text-[9px] text-[hsl(var(--muted-foreground))]">{t.orders} 单 · ${t.sales.toFixed(0)} 销售额</p>
                </div>
                <Badge className="text-[8px] bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))] border-0">ACOS {t.acos}%</Badge>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-[hsl(var(--muted-foreground))] text-center py-4">暂无数据</p>
        )}
      </div>

      <div className="rounded-xl border border-[hsl(var(--destructive)/0.3)] bg-[hsl(var(--card))] p-4">
        <div className="flex items-center gap-2 mb-3">
          <Minus className="w-4 h-4 text-[hsl(var(--destructive))]" />
          <h3 className="text-base font-semibold">浪费搜索词</h3>
          <span className="text-[10px] text-[hsl(var(--muted-foreground))]">建议添加为否词</span>
        </div>
        {loading ? (
          <div className="space-y-2">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
        ) : error ? (
          <p className="text-sm text-[hsl(var(--muted-foreground))] text-center py-4">搜索词报告加载失败</p>
        ) : badTerms.length ? (
          <div className="space-y-1.5">
            {badTerms.map((t, i) => (
              <div key={i} className="flex items-center justify-between px-3 py-2 rounded-lg bg-[hsl(var(--destructive)/0.06)]">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium truncate">"{t.searchTerm}"</p>
                  <p className="text-[9px] text-[hsl(var(--muted-foreground))]">{t.clicks} 点击 · 浪费 ${t.cost.toFixed(0)}</p>
                </div>
                <Badge variant="danger" className="text-[8px]">0 转化</Badge>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-[hsl(var(--muted-foreground))] text-center py-4">暂无数据</p>
        )}
      </div>
    </div>
  )
}

// ─── Long Tail Tab ────────────────────────────────────────────────────────────

function LongTailTab({ items }: { items: LongTailItem[] }) {
  const [limit, setLimit] = useState(50)
  if (items.length === 0) {
    return (
      <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-8 text-center">
        <p className="text-sm text-[hsl(var(--muted-foreground))]">暂无长尾机会数据</p>
      </div>
    )
  }
  return (
    <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
      <div className="px-4 py-3 border-b border-[hsl(var(--border)/0.5)] flex items-center gap-2">
        <Search className="w-3.5 h-3.5 text-[hsl(var(--primary))]" />
        <h3 className="text-base font-semibold">长尾机会</h3>
        <Badge variant="outline" className="text-[8px] ml-auto">{items.length} 条</Badge>
      </div>
      <div className="flex items-center gap-2 px-4 py-2 text-[10px] uppercase tracking-wider text-[hsl(var(--muted-foreground))] font-semibold border-b border-[hsl(var(--border)/0.3)]">
        <div className="flex-1">搜索词</div>
        <div className="w-16 text-right">订单</div><div className="w-20 text-right">展示</div>
        <div className="w-16 text-right">点击</div><div className="w-16 text-right">ACOS</div>
        <div className="flex-1 text-right">建议</div>
      </div>
      <div className="max-h-[500px] overflow-y-auto">
        {items.slice(0, limit).map((item, i) => (
          <div key={i} className="flex items-center gap-2 px-4 py-2.5 border-b border-[hsl(var(--border)/0.2)] hover:bg-[hsl(var(--secondary)/0.2)] transition-colors">
            <div className="flex-1 min-w-0"><p className="text-sm font-medium truncate">{item.searchTerm}</p></div>
            <div className="w-16 text-right text-sm">{item.orders}</div>
            <div className="w-20 text-right text-sm">{fmtNum(item.impressions)}</div>
            <div className="w-16 text-right text-sm">{item.clicks}</div>
            <div className={`w-16 text-right text-sm font-medium ${item.acos > 0 && item.acos <= 20 ? 'text-[hsl(var(--primary))]' : item.acos <= 35 ? 'text-[hsl(var(--zv-amber))]' : item.acos > 35 ? 'text-[hsl(var(--destructive))]' : 'text-[hsl(var(--muted-foreground))]'}`}>
              {item.acos > 0 ? `${item.acos.toFixed(1)}%` : '—'}
            </div>
            <div className="flex-1 text-right text-sm text-[hsl(var(--primary))]">{item.suggestion}</div>
          </div>
        ))}
      </div>
      {items.length > limit && (
        <button onClick={() => setLimit(l => l + 50)} className="w-full py-2.5 text-sm text-[hsl(var(--primary))] hover:underline border-t border-[hsl(var(--border)/0.3)]">
          加载更多 ({items.length - limit} 条剩余)
        </button>
      )}
    </div>
  )
}

// ─── Merged Negative Table ────────────────────────────────────────────────────

function MergedNegativeTable({ items }: { items: NegativeKeywordItem[] }) {
  const [showFlags, setShowFlags] = useState(false)

  if (items.length === 0) {
    return (
      <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-8 text-center">
        <p className="text-base text-[hsl(var(--muted-foreground))]">暂无否词建议</p>
      </div>
    )
  }

  const sorted = [...items].sort((a, b) => b.spend - a.spend)
  const warnItems = sorted.filter(n => n.level === 'warn')
  const flagItems = sorted.filter(n => n.level === 'flag')
  const visibleItems = showFlags ? sorted : warnItems
  const maxSpend = Math.max(...sorted.map(i => i.spend), 1)

  return (
    <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
      <div className="px-4 py-3 border-b border-[hsl(var(--border)/0.5)] flex items-center gap-2">
        <AlertTriangle className="w-3.5 h-3.5 text-[hsl(var(--destructive))]" />
        <h3 className="text-base font-semibold">否词建议</h3>
        <div className="ml-auto flex items-center gap-2">
          <Badge className="text-[10px] bg-[hsl(var(--destructive)/0.12)] text-[hsl(var(--destructive))] border-0">⚠️ 警告 {warnItems.length}</Badge>
          <Badge className="text-[10px] bg-[hsl(var(--zv-amber)/0.12)] text-[hsl(var(--zv-amber))] border-0">📋 标记 {flagItems.length}</Badge>
        </div>
      </div>
      <div className="flex items-center gap-2 px-4 py-2 text-[10px] uppercase tracking-wider text-[hsl(var(--muted-foreground))] font-semibold border-b border-[hsl(var(--border)/0.3)] bg-[hsl(var(--secondary)/0.3)]">
        <div className="w-16 flex-shrink-0">级别</div>
        <div className="flex-1">搜索词</div>
        <div className="w-20 text-right">展示</div>
        <div className="w-16 text-right">点击</div>
        <div className="w-20 text-right">花费</div>
        <div className="flex-[2] pl-4">受影响 Campaign</div>
      </div>
      <div className="max-h-[500px] overflow-y-auto">
        {visibleItems.map((item, i) => {
          const isWarn = item.level === 'warn'
          const intensity = item.spend / maxSpend
          const r = Math.round(220 + 35 * intensity)
          const g = Math.round(80 * (1 - intensity))
          const b = Math.round(60 * (1 - intensity))
          return (
            <div key={i} className={`flex items-start gap-2 px-4 py-2.5 border-b border-[hsl(var(--border)/0.2)] transition-colors ${
              isWarn ? 'bg-[hsl(var(--destructive)/0.04)] hover:bg-[hsl(var(--destructive)/0.08)]' : 'bg-[hsl(var(--zv-amber)/0.03)] hover:bg-[hsl(var(--zv-amber)/0.07)]'
            }`}>
              <div className="w-16 flex-shrink-0 pt-0.5">
                {isWarn ? (
                  <span className="inline-flex items-center gap-0.5 text-[10px] font-semibold text-[hsl(var(--destructive))] bg-[hsl(var(--destructive)/0.12)] px-1.5 py-0.5 rounded-md">⚠️ 警告</span>
                ) : (
                  <span className="inline-flex items-center gap-0.5 text-[10px] font-semibold text-[hsl(var(--zv-amber))] bg-[hsl(var(--zv-amber)/0.12)] px-1.5 py-0.5 rounded-md">📋 标记</span>
                )}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-base font-medium truncate">{item.searchTerm}</p>
                {item.action && <p className="text-[10px] text-[hsl(var(--muted-foreground))] mt-0.5">{item.action}</p>}
              </div>
              <div className="w-20 text-right text-base pt-0.5">{fmtNum(item.impressions)}</div>
              <div className="w-16 text-right text-base pt-0.5">{item.clicks}</div>
              <div className="w-20 text-right text-base font-bold pt-0.5" style={{ color: `rgb(${r}, ${g}, ${b})` }}>${item.spend.toFixed(0)}</div>
              <div className="flex-[2] pl-4 flex flex-wrap gap-1">
                {(item.campaigns ?? []).slice(0, 3).map((c, j) => (
                  <Badge key={j} variant="outline" className="text-[9px] h-4 px-1 max-w-[140px] truncate">{c}</Badge>
                ))}
                {(item.campaigns?.length ?? 0) > 3 && (
                  <span className="text-[9px] text-[hsl(var(--muted-foreground))] self-center">+{(item.campaigns?.length ?? 0) - 3}</span>
                )}
              </div>
            </div>
          )
        })}
      </div>
      {flagItems.length > 0 && (
        <button onClick={() => setShowFlags(f => !f)}
          className={`w-full py-2.5 text-base font-medium transition-colors border-t border-[hsl(var(--border)/0.3)] flex items-center justify-center gap-1.5 ${
            showFlags ? 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]' : 'text-[hsl(var(--zv-amber))] hover:text-[hsl(var(--zv-amber)/0.8)]'
          }`}>
          {showFlags ? <><ChevronUp className="w-3.5 h-3.5" /> 收起标记项</> : <><ChevronDown className="w-3.5 h-3.5" /> 显示标记项 ({flagItems.length})</>}
        </button>
      )}
    </div>
  )
}

// ─── AI Insights Tab ──────────────────────────────────────────────────────────

function AiInsightsTab({ data }: { data: AiInsights | null }) {
  if (!data) {
    return (
      <div className="space-y-4">
        {[...Array(3)].map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)}
      </div>
    )
  }

  if (data.empty) {
    return (
      <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-12 text-center space-y-3">
        <p className="text-4xl">🤖</p>
        <p className="text-base font-semibold text-[hsl(var(--foreground))]">{data.message ?? '暂无 AI 洞察'}</p>
        <p className="text-xs text-[hsl(var(--muted-foreground))]">
          先生成洞察输入数据，再让 PPC agent 分析并输出结果
        </p>
        {data.hint && (
          <div className="inline-block mt-2 px-4 py-2 rounded-lg bg-[hsl(var(--secondary))] font-mono text-[10px] text-[hsl(var(--muted-foreground))]">
            {data.hint}
          </div>
        )}
      </div>
    )
  }

  const verdictColor = (v: string) => {
    if (v === '否定')        return 'bg-[hsl(var(--destructive)/0.12)] text-[hsl(var(--destructive))] border-[hsl(var(--destructive)/0.3)]'
    if (v === '观察')        return 'bg-[hsl(var(--zv-amber)/0.12)] text-[hsl(var(--zv-amber))] border-[hsl(var(--zv-amber)/0.3)]'
    if (v === '优化listing') return 'bg-[hsl(var(--zv-blue,220,90%,55%)/0.12)] text-blue-600 border-blue-400/30'
    return 'bg-[hsl(var(--secondary))] text-[hsl(var(--muted-foreground))] border-[hsl(var(--border))]'
  }

  const priorityLabel = (p: number) => {
    if (p <= 0) return { label: 'P0', cls: 'bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--destructive))]' }
    if (p === 1) return { label: 'P1', cls: 'bg-[hsl(var(--zv-amber)/0.15)] text-[hsl(var(--zv-amber))]' }
    return { label: `P${p}`, cls: 'bg-[hsl(var(--secondary))] text-[hsl(var(--muted-foreground))]' }
  }

  const kg = data.keywordGrouping

  return (
    <div className="space-y-6">
      {/* ── Info bar ── */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-4 py-3">
        <div className="flex items-center gap-1.5 text-[10px] text-[hsl(var(--muted-foreground))]">
          <span className="font-semibold text-[hsl(var(--foreground))]">生成时间</span>
          {data.generatedAt ? new Date(data.generatedAt).toLocaleString('zh-CN') : '—'}
        </div>
        {data.dateRange && (
          <div className="flex items-center gap-1.5 text-[10px] text-[hsl(var(--muted-foreground))]">
            <span className="font-semibold text-[hsl(var(--foreground))]">数据范围</span>
            {data.dateRange.start} → {data.dateRange.end}
          </div>
        )}
        {data.model && (
          <div className="flex items-center gap-1.5 text-[10px] text-[hsl(var(--muted-foreground))]">
            <span className="font-semibold text-[hsl(var(--foreground))]">模型</span>
            {data.model}
          </div>
        )}
      </div>

      {/* ── Keyword Grouping ── */}
      {kg && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-base">🔑</span>
            <h2 className="text-base font-semibold">关键词语义分组</h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {([
              { key: 'brandTerms',         label: '品牌词',   color: 'var(--primary)',          icon: '🏷️' },
              { key: 'categoryTerms',      label: '品类词',   color: 'var(--zv-amber)',         icon: '📦' },
              { key: 'competitorTerms',    label: '竞品词',   color: 'var(--destructive)',      icon: '⚔️' },
              { key: 'problemSolvingTerms',label: '问题解决', color: 'var(--muted-foreground)', icon: '🔧' },
            ] as const).map(({ key, label, color, icon }) => {
              const items = (kg[key] ?? []) as AiTermStrategy[]
              return (
                <div key={key} className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
                  <div className="flex items-center gap-2 px-4 py-3 border-b border-[hsl(var(--border)/0.5)]" style={{ borderLeftWidth: 3, borderLeftColor: `hsl(${color})` }}>
                    <span>{icon}</span>
                    <h3 className="text-sm font-semibold" style={{ color: `hsl(${color})` }}>{label}</h3>
                    <Badge variant="outline" className="text-[8px] h-4 px-1 ml-auto">{items.length}</Badge>
                  </div>
                  {items.length === 0 ? (
                    <p className="text-xs text-[hsl(var(--muted-foreground))] text-center py-4">暂无词汇</p>
                  ) : (
                    <div className="divide-y divide-[hsl(var(--border)/0.3)] max-h-[240px] overflow-y-auto">
                      {items.map((item, i) => (
                        <div key={i} className="px-4 py-2.5 hover:bg-[hsl(var(--secondary)/0.3)] transition-colors">
                          <p className="text-sm font-medium">{item.term}</p>
                          <p className="text-[10px] text-[hsl(var(--muted-foreground))] mt-0.5 leading-relaxed">{item.strategy}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ── Negative Risk Assessment ── */}
      {data.negativeRiskAssessment && data.negativeRiskAssessment.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-base">⚠️</span>
            <h2 className="text-base font-semibold">否词风险评估</h2>
            <Badge className="text-[9px] bg-[hsl(var(--destructive)/0.12)] text-[hsl(var(--destructive))] border-0">{data.negativeRiskAssessment.length} 词</Badge>
          </div>
          <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
            <div className="flex items-center gap-2 px-4 py-2 text-[10px] uppercase tracking-wider text-[hsl(var(--muted-foreground))] font-semibold border-b border-[hsl(var(--border)/0.3)] bg-[hsl(var(--secondary)/0.3)]">
              <div className="flex-1">搜索词</div>
              <div className="w-20 text-right">花费</div>
              <div className="w-24 text-center">建议</div>
              <div className="flex-[2] pl-4">理由</div>
            </div>
            <div className="max-h-[400px] overflow-y-auto divide-y divide-[hsl(var(--border)/0.2)]">
              {data.negativeRiskAssessment.map((item, i) => (
                <div key={i} className="flex items-start gap-2 px-4 py-3 hover:bg-[hsl(var(--secondary)/0.2)] transition-colors">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium">{item.term}</p>
                  </div>
                  <div className="w-20 text-right text-sm font-medium pt-0.5">
                    ${(item.spend ?? 0).toFixed(0)}
                  </div>
                  <div className="w-24 flex justify-center pt-0.5">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border ${verdictColor(item.verdict)}`}>
                      {item.verdict}
                    </span>
                  </div>
                  <div className="flex-[2] pl-4 text-[11px] text-[hsl(var(--muted-foreground))] leading-relaxed pt-0.5">
                    {item.reason}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── Anomaly Analysis ── */}
      {data.anomalyAnalysis && data.anomalyAnalysis.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-base">🔍</span>
            <h2 className="text-base font-semibold">异常归因分析</h2>
            <Badge className="text-[9px] bg-[hsl(var(--zv-amber)/0.12)] text-[hsl(var(--zv-amber))] border-0">{data.anomalyAnalysis.length} 个</Badge>
          </div>
          <div className="space-y-3">
            {data.anomalyAnalysis.map((item, i) => (
              <div key={i} className="rounded-xl border border-[hsl(var(--zv-amber)/0.3)] bg-[hsl(var(--card))] p-4">
                <div className="flex items-start justify-between gap-3 mb-3">
                  <div>
                    <p className="text-sm font-semibold text-[hsl(var(--foreground))]">{item.campaign}</p>
                    <p className="text-xs text-[hsl(var(--destructive))] mt-0.5">{item.issue}</p>
                  </div>
                  <Badge className="text-[9px] bg-[hsl(var(--zv-amber)/0.12)] text-[hsl(var(--zv-amber))] border-0 flex-shrink-0">异常</Badge>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div className="rounded-lg bg-[hsl(var(--secondary)/0.5)] p-3">
                    <p className="text-[10px] font-semibold text-[hsl(var(--muted-foreground))] uppercase tracking-wider mb-1">根因</p>
                    <p className="text-xs text-[hsl(var(--foreground))] leading-relaxed">{item.rootCause}</p>
                  </div>
                  <div className="rounded-lg bg-[hsl(var(--primary)/0.06)] border border-[hsl(var(--primary)/0.2)] p-3">
                    <p className="text-[10px] font-semibold text-[hsl(var(--primary))] uppercase tracking-wider mb-1">修复建议</p>
                    <p className="text-xs text-[hsl(var(--foreground))] leading-relaxed">{item.fix}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Weekly Action Plan ── */}
      {data.weeklyActionPlan && data.weeklyActionPlan.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-base">✅</span>
            <h2 className="text-base font-semibold">本周行动清单</h2>
            <Badge className="text-[9px] bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))] border-0">{data.weeklyActionPlan.length} 项</Badge>
          </div>
          <div className="space-y-3">
            {data.weeklyActionPlan.map((item, i) => {
              const { label, cls } = priorityLabel(item.priority)
              return (
                <div key={i} className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
                  <div className="flex items-start gap-3">
                    <div className="flex-shrink-0 flex items-center gap-2">
                      <span className="text-lg font-bold text-[hsl(var(--muted-foreground))]">
                        {String(item.priority).padStart(2, '0')}
                      </span>
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${cls}`}>{label}</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-[hsl(var(--foreground))]">{item.action}</p>
                      <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2">
                        <div>
                          <p className="text-[9px] uppercase tracking-wider font-semibold text-[hsl(var(--primary))] mb-0.5">预期影响</p>
                          <p className="text-[11px] text-[hsl(var(--muted-foreground))] leading-relaxed">{item.impact}</p>
                        </div>
                        <div>
                          <p className="text-[9px] uppercase tracking-wider font-semibold text-[hsl(var(--zv-amber))] mb-0.5">优先理由</p>
                          <p className="text-[11px] text-[hsl(var(--muted-foreground))] leading-relaxed">{item.reason}</p>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Top Tab Navigation ───────────────────────────────────────────────────────

const TOP_TABS: { key: TopTab; label: string; icon: string }[] = [
  { key: 'ai-insights',       label: 'AI 洞察',    icon: '🤖' },
  { key: 'overview',          label: '概览',       icon: '📊' },
  { key: 'keywords-opt',      label: '关键词优化', icon: '🔑' },
  { key: 'campaign-structure',label: 'Campaign 结构', icon: '🏗️' },
  { key: 'bid-budget',        label: 'Bid & Budget', icon: '💰' },
  { key: 'kw-performance',    label: '关键词表现', icon: '📈' },
  { key: 'search-discovery',  label: '搜索词发现', icon: '🔍' },
]

// ─── Page ─────────────────────────────────────────────────────────────────────

function PPCPageContent() {
  const [period, setPeriod]     = useState<Period>(7)
  const [topTab, setTopTab]     = useState<TopTab>('overview')
  const [kpi, setKpi]           = useState<KPI | null>(null)
  const [keywords, setKeywords] = useState<Keyword[]>([])
  const [kwLoading, setKwLoading] = useState(true)
  const [error, setError]       = useState<string | null>(null)

  // Keyword analysis (tab 2)
  const [analysisData, setAnalysisData]       = useState<AnalysisData | null>(null)
  const [analysisLoading, setAnalysisLoading] = useState(true)

  // Campaign analysis (tab 3)
  const [campData, setCampData]   = useState<CampaignAnalysis | null>(null)
  const [campLoading, setCampLoading] = useState(true)

  // Bid analysis (tab 4)
  const [bidData, setBidData]   = useState<BidAnalysis | null>(null)
  const [bidLoading, setBidLoading] = useState(true)

  // Weekly report (tab 1)
  const [report, setReport]       = useState<WeeklyReport | null>(null)
  const [reportLoading, setReportLoading] = useState(true)

  // AI insights (tab 0)
  const [aiInsights, setAiInsights]       = useState<AiInsights | null>(null)
  const [aiInsightsLoading, setAiInsightsLoading] = useState(true)

  // Load keyword performance
  useEffect(() => {
    setKwLoading(true)
    fetch(`/api/ppc/keywords?days=${period}`)
      .then(r => r.json())
      .then(d => {
        setKpi(d.kpi ?? null); setKeywords(d.keywords ?? [])
        setError(d.error ? d.message : null)
      })
      .catch(() => setError('网络请求失败'))
      .finally(() => setKwLoading(false))
  }, [period])

  // Load AI insights (tab 0)
  useEffect(() => {
    setAiInsightsLoading(true)
    fetch('/api/ppc/ai-insights')
      .then(r => r.json()).then(d => setAiInsights(d)).catch(() => {})
      .finally(() => setAiInsightsLoading(false))
  }, [])

  // Load keyword analysis
  useEffect(() => {
    setAnalysisLoading(true)
    fetch('/api/ppc')
      .then(r => r.json()).then(d => setAnalysisData(d)).catch(() => {})
      .finally(() => setAnalysisLoading(false))
  }, [])

  // Load campaign analysis
  useEffect(() => {
    setCampLoading(true)
    fetch('/api/ppc/campaign-analysis')
      .then(r => r.json()).then(d => setCampData(d)).catch(() => {})
      .finally(() => setCampLoading(false))
  }, [])

  // Load bid analysis
  useEffect(() => {
    setBidLoading(true)
    fetch('/api/ppc/bid-analysis')
      .then(r => r.json()).then(d => setBidData(d)).catch(() => {})
      .finally(() => setBidLoading(false))
  }, [])

  // Load weekly report
  useEffect(() => {
    setReportLoading(true)
    fetch('/api/ppc/weekly-report')
      .then(r => r.json()).then(d => setReport(d)).catch(() => {})
      .finally(() => setReportLoading(false))
  }, [])

  // Badge counts for tabs
  const tabBadges: Partial<Record<TopTab, number>> = {
    'overview': (report?.summary.criticalAlerts ?? 0) + (report?.summary.warningAlerts ?? 0),
    'keywords-opt': (analysisData?.summary?.addKeywordCount ?? 0) + (analysisData?.summary?.negativeCount ?? 0),
    'campaign-structure': (campData?.summary?.zombieCampaigns ?? 0) + (campData?.summary?.duplicateGroups ?? 0),
    'bid-budget': (bidData?.summary?.breakevenAlerts ?? 0) + (bidData?.summary?.cappedCampaigns ?? 0),
    'kw-performance': keywords.length,
  }

  return (
    <div className="flex flex-col">
      {/* ─── Sticky Header ── */}
      <div className="sticky top-0 z-20 bg-[hsl(var(--background))] border-b border-[hsl(var(--border))]">
        {/* Page title + controls */}
        <div className="flex items-center justify-between pt-4 pb-3">
          <div>
            <h1 className="text-xl font-bold">PPC</h1>
            <p className="text-sm text-[hsl(var(--muted-foreground))] mt-0.5">Amazon 广告投放中心</p>
          </div>
          <div className="flex items-center gap-3">
            <Badge variant="outline" className="text-[10px] border-[hsl(var(--primary)/0.5)] text-[hsl(var(--primary))]">
              <Zap className="w-2.5 h-2.5 mr-1" /> Advertising API
            </Badge>
            <PeriodSelector value={period} onChange={setPeriod} />
          </div>
        </div>

        {/* KPI strip */}
        <div className="grid grid-cols-4 lg:grid-cols-7 gap-2 pb-3">
          <KPICard label="广告花费" value={kpi ? `$${fmtNum(kpi.spend)}` : '—'} sub={`日均 $${kpi ? (kpi.spend / period).toFixed(0) : '—'}`}
            icon={<DollarSign className="w-3.5 h-3.5 text-[hsl(var(--zv-amber))]" />} />
          <KPICard label="广告销售额" value={kpi ? `$${fmtNum(kpi.sales)}` : '—'} sub={`${kpi?.orders ?? 0} 订单`}
            icon={<ShoppingCart className="w-3.5 h-3.5 text-[hsl(var(--primary))]" />} accent />
          <KPICard label="ACOS" value={kpi ? `${kpi.acos}%` : '—'}
            icon={<Percent className="w-3.5 h-3.5 text-[hsl(var(--zv-amber))]" />} accent={kpi ? kpi.acos < 25 : false} />
          <KPICard label="ROAS" value={kpi ? `${kpi.roas}x` : '—'}
            icon={<TrendingUp className="w-3.5 h-3.5 text-[hsl(var(--primary))]" />} accent={kpi ? kpi.roas > 4 : false} />
          <KPICard label="总点击" value={kpi ? fmtNum(kpi.clicks) : '—'} sub={`CTR ${kpi?.ctr ?? 0}%`}
            icon={<MousePointerClick className="w-3.5 h-3.5 text-[hsl(var(--zv-blue))]" />} />
          <KPICard label="平均 CPC" value={kpi ? `$${kpi.cpc}` : '—'}
            icon={<Target className="w-3.5 h-3.5 text-[hsl(var(--muted-foreground))]" />} />
          <KPICard label="转化率" value={kpi ? `${kpi.convRate}%` : '—'}
            icon={<BarChart3 className="w-3.5 h-3.5 text-[hsl(var(--primary))]" />} accent={kpi ? kpi.convRate > 10 : false} />
        </div>

        {/* Top-level Tab Nav */}
        <div className="flex items-center gap-0 overflow-x-auto">
          {TOP_TABS.map(tab => {
            const badgeCount = tabBadges[tab.key] ?? 0
            const isActive = topTab === tab.key
            return (
              <button key={tab.key} onClick={() => setTopTab(tab.key)}
                className={`group relative flex items-center gap-2 px-4 py-3 text-sm font-semibold border-b-2 transition-all whitespace-nowrap ${
                  isActive
                    ? 'border-[hsl(var(--primary))] text-[hsl(var(--primary))]'
                    : 'border-transparent text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:border-[hsl(var(--border))]'
                }`}
              >
                <span className="text-base">{tab.icon}</span>
                {tab.label}
                {badgeCount > 0 && (
                  <span className={`inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-[9px] font-bold ${
                    isActive ? 'bg-[hsl(var(--primary)/0.2)] text-[hsl(var(--primary))]' : 'bg-[hsl(var(--secondary))] text-[hsl(var(--muted-foreground))]'
                  }`}>
                    {badgeCount}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      </div>

      {/* ─── Tab Content ── */}
      <div className="max-w-7xl mx-auto pt-6">
        {/* Error banner */}
        {error && (
          <div className="rounded-xl border border-[hsl(var(--zv-amber)/0.3)] bg-[hsl(var(--zv-amber)/0.08)] p-4 mb-4">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-3.5 h-3.5 text-[hsl(var(--zv-amber))]" />
              <p className="text-sm text-[hsl(var(--zv-amber))]">{error}</p>
            </div>
            <p className="text-[10px] text-[hsl(var(--muted-foreground))] mt-1">首次加载需要 1-2 分钟生成报告，请稍后刷新页面</p>
          </div>
        )}

        {topTab === 'ai-insights' && (
          aiInsightsLoading
            ? <div className="space-y-4">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)}</div>
            : <AiInsightsTab data={aiInsights} />
        )}

        {topTab === 'overview' && (
          reportLoading
            ? <div className="space-y-4">{[...Array(3)].map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)}</div>
            : <OverviewTab report={report} />
        )}

        {topTab === 'keywords-opt' && (
          <KeywordsOptTab analysisData={analysisData} analysisLoading={analysisLoading} />
        )}

        {topTab === 'campaign-structure' && (
          campLoading
            ? <div className="space-y-4">{[...Array(3)].map((_, i) => <Skeleton key={i} className="h-20 rounded-xl" />)}</div>
            : <CampaignStructureTab data={campData} />
        )}

        {topTab === 'bid-budget' && (
          bidLoading
            ? <div className="space-y-4">{[...Array(3)].map((_, i) => <Skeleton key={i} className="h-20 rounded-xl" />)}</div>
            : <BidBudgetTab data={bidData} />
        )}

        {topTab === 'kw-performance' && (
          <KeywordsTable keywords={keywords} loading={kwLoading} />
        )}

        {topTab === 'search-discovery' && (
          <SearchTermsPanel period={period} />
        )}
      </div>
    </div>
  )
}
export default function PPCPage() {
  return (
    <DashboardPageLayout
      signedOut={{ message: 'Sign in to view ppc', forceRedirectUrl: '/ppc' }}
      title="PPC"
      description="广告投放"
    >
      <PPCPageContent />
    </DashboardPageLayout>
  )
}
