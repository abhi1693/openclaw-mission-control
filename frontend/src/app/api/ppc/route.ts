import { NextResponse } from 'next/server'
import fs from 'fs'
import path from 'path'
import os from 'os'

const CACHE_DIR = path.join(os.homedir(), '.openclaw/skills/amazon-advertising/cache')

function getLatestMatchingFile(prefix: string, requireDateRange = false): string | null {
  try {
    const files = fs.readdirSync(CACHE_DIR)
      .filter(f => {
        if (!f.startsWith(prefix) || !f.endsWith('.json')) return false
        if (requireDateRange) return f.includes('_to_')
        return true
      })
      .sort()
      .reverse()
    return files.length ? path.join(CACHE_DIR, files[0]) : null
  } catch {
    return null
  }
}

// ─── Types (shared with page) ────────────────────────────────────────────────

interface AddKeyword {
  searchTerm: string
  impressions: number
  clicks: number
  orders: number
  sales: number
  spend: number
  acos: number
  suggestedMatchType: string
  suggestedBid?: number
  campaigns?: string[]
}

interface NegativeKeyword {
  searchTerm: string
  impressions: number
  clicks: number
  spend: number
  campaigns: string[]
  level: 'warn' | 'flag'
  action?: string
}

interface MatchUpgrade {
  keyword: string
  currentMatch: string
  orders: number
  acos: number
  suggestion: string
}

interface LongTailItem {
  searchTerm: string
  orders: number
  impressions: number
  clicks: number
  spend: number
  acos: number
  suggestion: string
}

interface DuplicateItem {
  keyword: string
  matchType?: string
  campaigns: string[]
  riskNote?: string
}

interface AnalysisSummary {
  totalSpend?: number
  totalSales?: number
  overallAcos?: number
  totalOrders?: number
  addKeywordCount: number
  negativeCount: number
  negWarnCount: number
  negFlagCount: number
  upgradeCount: number
  longTailCount: number
  duplicateGroupCount: number
  estMonthlySavings?: number
  estMonthlySalesGain?: number
}

interface AnalysisResult {
  source: string
  empty: boolean
  startDate?: string
  endDate?: string
  targetAcos?: number
  message?: string
  derivedFrom?: string
  summary: AnalysisSummary | null
  addKeywords: AddKeyword[]
  negativeKeywords: NegativeKeyword[]
  matchUpgrades: MatchUpgrade[]
  longTail: LongTailItem[]
  duplicateTargeting: DuplicateItem[]
}

// ─── Normalize keyword-analysis JSON ─────────────────────────────────────────

function normalizeKeywordAnalysis(raw: Record<string, unknown>, filename: string): AnalysisResult {
  // addKeywords — already in the right shape, just ensure defaults
  const addKeywords: AddKeyword[] = ((raw.addKeywords as AddKeyword[]) ?? []).map(k => ({
    searchTerm: k.searchTerm,
    impressions: k.impressions ?? 0,
    clicks: k.clicks ?? 0,
    orders: k.orders ?? 0,
    sales: k.sales ?? 0,
    spend: k.spend ?? 0,
    acos: k.acos ?? 0,
    suggestedMatchType: k.suggestedMatchType ?? 'broad',
    suggestedBid: k.suggestedBid,
    campaigns: k.campaigns,
  })).sort((a, b) => b.orders - a.orders)

  // negativeKeywords — raw is { warn: [...], flag: [...] }
  const rawNegs = (raw.negativeKeywords as { warn?: RawNeg[]; flag?: RawNeg[] }) ?? {}
  const negativeKeywords: NegativeKeyword[] = [
    ...(rawNegs.warn ?? []).map(n => ({ ...n, campaigns: n.campaigns ?? [], level: 'warn' as const })),
    ...(rawNegs.flag ?? []).map(n => ({ ...n, campaigns: n.campaigns ?? [], level: 'flag' as const })),
  ].sort((a, b) => b.spend - a.spend)

  // matchUpgrades — raw has currentMatchType + suggestedAction
  const matchUpgrades: MatchUpgrade[] = ((raw.matchUpgrades as RawMatchUpgrade[]) ?? []).map(m => ({
    keyword: m.keyword,
    currentMatch: m.currentMatchType ?? m.currentMatch ?? '—',
    orders: m.orders ?? 0,
    acos: m.acos ?? 0,
    suggestion: m.suggestedAction ?? m.suggestion ?? '—',
  }))

  // longTail — raw is longTailOpportunities
  const rawLong = (raw.longTailOpportunities ?? raw.longTail ?? []) as RawLongTail[]
  const longTail: LongTailItem[] = rawLong.map(l => ({
    searchTerm: l.searchTerm,
    orders: l.orders ?? 0,
    impressions: l.impressions ?? 0,
    clicks: l.clicks ?? 0,
    spend: l.spend ?? 0,
    acos: l.acos ?? 0,
    suggestion: l.suggestedAction ?? l.suggestion ?? '添加为精确匹配关键词',
  })).sort((a, b) => b.orders - a.orders)

  // duplicates — raw is duplicates array
  const rawDups = ((raw.duplicates ?? raw.duplicateTargeting ?? []) as RawDuplicate[])
  const duplicateTargeting: DuplicateItem[] = rawDups.map(d => ({
    keyword: d.keyword,
    matchType: d.matchType,
    campaigns: d.campaigns ?? [],
    riskNote: d.riskNote,
  }))

  // summary
  const rawSum = (raw.summary as Record<string, number> | undefined) ?? {}
  const negCount = (rawNegs.warn?.length ?? 0) + (rawNegs.flag?.length ?? 0)
  const summary: AnalysisSummary = {
    addKeywordCount: rawSum.addCount ?? addKeywords.length,
    negativeCount: rawSum.negCount ?? negCount,
    negWarnCount: rawSum.negWarnCount ?? (rawNegs.warn?.length ?? 0),
    negFlagCount: rawSum.negFlagCount ?? (rawNegs.flag?.length ?? 0),
    upgradeCount: rawSum.matchUpgradeCount ?? matchUpgrades.length,
    longTailCount: rawSum.longTailCount ?? longTail.length,
    duplicateGroupCount: rawSum.duplicateGroupCount ?? duplicateTargeting.length,
    estMonthlySavings: rawSum.estMonthlySavings,
    estMonthlySalesGain: rawSum.estMonthlySalesGain,
  }

  return {
    source: 'keyword-analysis',
    empty: false,
    startDate: raw.startDate as string | undefined,
    endDate: raw.endDate as string | undefined,
    targetAcos: raw.targetAcos as number | undefined,
    derivedFrom: filename,
    summary,
    addKeywords,
    negativeKeywords,
    matchUpgrades,
    longTail,
    duplicateTargeting,
  }
}

// ─── Raw Types (local) ───────────────────────────────────────────────────────

interface RawNeg {
  searchTerm: string
  impressions: number
  clicks: number
  spend: number
  campaigns?: string[]
  action?: string
}

interface RawMatchUpgrade {
  keyword: string
  currentMatchType?: string
  currentMatch?: string
  orders?: number
  acos?: number
  suggestedAction?: string
  suggestion?: string
}

interface RawLongTail {
  searchTerm: string
  orders?: number
  impressions?: number
  clicks?: number
  spend?: number
  acos?: number
  suggestedAction?: string
  suggestion?: string
}

interface RawDuplicate {
  keyword: string
  matchType?: string
  campaigns?: string[]
  riskNote?: string
}

// ─── Fallback: derive from search-terms JSON ─────────────────────────────────

interface SearchTermRaw {
  q: string
  impressions: number
  clicks: number
  cost: number
  orders: number
  sales: number
  acos: number
}

function deriveFromSearchTerms(data: Record<string, unknown>, filename: string): AnalysisResult {
  const topConverting = (data.topConverting as SearchTermRaw[]) ?? []
  const highSpend = (data.highSpendLowConvert as SearchTermRaw[]) ?? []
  const highAcos = (data.highAcos as SearchTermRaw[]) ?? []

  const addKeywords: AddKeyword[] = topConverting.map(t => ({
    searchTerm: t.q,
    impressions: t.impressions,
    clicks: t.clicks,
    orders: t.orders,
    sales: +t.sales.toFixed(2),
    spend: +t.cost.toFixed(2),
    acos: +t.acos.toFixed(1),
    suggestedMatchType: t.orders >= 10 ? 'EXACT' : t.orders >= 5 ? 'PHRASE' : 'BROAD',
  })).sort((a, b) => b.orders - a.orders)

  const negMap = new Map<string, NegativeKeyword>()
  for (const t of highSpend) {
    negMap.set(t.q, {
      searchTerm: t.q,
      impressions: t.impressions,
      clicks: t.clicks,
      spend: +t.cost.toFixed(2),
      campaigns: [],
      level: t.cost >= 15 ? 'warn' : 'flag',
    })
  }
  for (const t of highAcos) {
    if (!negMap.has(t.q) && t.cost > 10) {
      negMap.set(t.q, {
        searchTerm: t.q,
        impressions: t.impressions,
        clicks: t.clicks,
        spend: +t.cost.toFixed(2),
        campaigns: [],
        level: 'flag',
      })
    }
  }
  const negativeKeywords = Array.from(negMap.values()).sort((a, b) => b.spend - a.spend)
  const warnCount = negativeKeywords.filter(n => n.level === 'warn').length
  const flagCount = negativeKeywords.filter(n => n.level === 'flag').length

  return {
    source: 'search-terms-derived',
    empty: false,
    derivedFrom: filename,
    summary: {
      addKeywordCount: addKeywords.length,
      negativeCount: negativeKeywords.length,
      negWarnCount: warnCount,
      negFlagCount: flagCount,
      upgradeCount: 0,
      longTailCount: 0,
      duplicateGroupCount: 0,
    },
    addKeywords,
    negativeKeywords,
    matchUpgrades: [],
    longTail: [],
    duplicateTargeting: [],
  }
}

// ─── Handler ─────────────────────────────────────────────────────────────────

export async function GET() {
  // 1. Try keyword-analysis-*_to_*.json first (new date-range format), fall back to any keyword-analysis
  const analysisFile = getLatestMatchingFile('keyword-analysis-', true)
    ?? getLatestMatchingFile('keyword-analysis-')
  if (analysisFile) {
    try {
      const raw = JSON.parse(fs.readFileSync(analysisFile, 'utf-8')) as Record<string, unknown>
      return NextResponse.json(normalizeKeywordAnalysis(raw, path.basename(analysisFile)))
    } catch {
      // fall through
    }
  }

  // 2. Derive from search-terms-*.json
  const searchTermsFile = getLatestMatchingFile('search-terms-')
  if (searchTermsFile) {
    try {
      const raw = JSON.parse(fs.readFileSync(searchTermsFile, 'utf-8')) as Record<string, unknown>
      return NextResponse.json(deriveFromSearchTerms(raw, path.basename(searchTermsFile)))
    } catch {
      // fall through
    }
  }

  // 3. Empty state
  return NextResponse.json({
    empty: true,
    source: 'none',
    message: '暂无分析数据，等待下次分析运行',
    summary: null,
    addKeywords: [],
    negativeKeywords: [],
    matchUpgrades: [],
    longTail: [],
    duplicateTargeting: [],
  } as AnalysisResult)
}
