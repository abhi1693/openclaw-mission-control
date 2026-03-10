'use client'

import { useState, useEffect, useCallback } from 'react'
import { Search, TrendingUp, TrendingDown, Minus, ChevronDown, ChevronRight, Trash2, Plus, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

interface KeywordEntry {
  asin: string
  keyword: string
  addedAt: string
}

interface RankHistory {
  date: string
  organicRank: number
  adRank: number
}

interface RankingRow {
  keyword: string
  asin: string
  history: RankHistory[]
  currentRank: number | null
  change7d: number
  trend: 'up' | 'down' | 'stable'
}

interface Product {
  asin: string
  name: string
}

export default function KeywordsPage() {
  const [activeTab, setActiveTab] = useState<'tracker' | 'manager'>('tracker')
  const [rankings, setRankings] = useState<RankingRow[]>([])
  const [lastCrawled, setLastCrawled] = useState<string | null>(null)
  const [keywords, setKeywords] = useState<KeywordEntry[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [expandedRow, setExpandedRow] = useState<string | null>(null)
  const [crawling, setCrawling] = useState(false)
  const [newAsin, setNewAsin] = useState('')
  const [newKeyword, setNewKeyword] = useState('')
  const [adding, setAdding] = useState(false)

  const fetchRankings = useCallback(async () => {
    const res = await fetch('/api/keywords/rankings')
    const data = await res.json()
    setRankings(data.rankings || [])
    setLastCrawled(data.lastCrawled || null)
  }, [])

  const fetchKeywords = useCallback(async () => {
    const res = await fetch('/api/keywords/config')
    const data = await res.json()
    setKeywords(data.keywords || [])
  }, [])

  const fetchProducts = useCallback(async () => {
    const res = await fetch('/api/content/products')
    const data = await res.json()
    setProducts(data.products || [])
  }, [])

  useEffect(() => {
    fetchRankings()
    fetchKeywords()
    fetchProducts()
  }, [fetchRankings, fetchKeywords, fetchProducts])

  async function handleCrawl() {
    setCrawling(true)
    await fetch('/api/keywords/crawl', { method: 'POST' })
    await fetchRankings()
    setCrawling(false)
  }

  async function handleAddKeyword() {
    if (!newAsin || !newKeyword.trim()) return
    setAdding(true)
    await fetch('/api/keywords/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ asin: newAsin, keyword: newKeyword.trim() }),
    })
    setNewKeyword('')
    await fetchKeywords()
    setAdding(false)
  }

  async function handleDelete(asin: string, keyword: string) {
    await fetch(`/api/keywords/config?asin=${encodeURIComponent(asin)}&keyword=${encodeURIComponent(keyword)}`, { method: 'DELETE' })
    await fetchKeywords()
  }

  const upCount = rankings.filter(r => r.trend === 'up').length
  const downCount = rankings.filter(r => r.trend === 'down').length

  // Group keywords by ASIN for manager tab
  const keywordsByAsin: Record<string, KeywordEntry[]> = {}
  for (const kw of keywords) {
    if (!keywordsByAsin[kw.asin]) keywordsByAsin[kw.asin] = []
    keywordsByAsin[kw.asin].push(kw)
  }

  const getProductName = (asin: string) => {
    const p = products.find(p => p.asin === asin)
    return p ? p.name : asin
  }

  return (
    <div className="flex-1 overflow-auto bg-[hsl(var(--background))] p-6">
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-3 mb-1">
          <Search className="w-5 h-5 text-[hsl(var(--primary))]" />
          <h1 className="text-xl font-bold text-white">Keywords</h1>
        </div>
        <p className="text-sm text-[hsl(var(--muted-foreground))] ml-8">关键词排名追踪</p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 border-b border-[hsl(var(--border))]">
        {(['tracker', 'manager'] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              'px-4 py-2 text-sm font-medium transition-colors relative',
              activeTab === tab
                ? 'text-[hsl(var(--primary))]'
                : 'text-[hsl(var(--muted-foreground))] hover:text-white'
            )}
          >
            {tab === 'tracker' ? 'Rank Tracker' : 'Keyword Manager'}
            {activeTab === tab && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-[hsl(var(--primary))]" />
            )}
          </button>
        ))}
      </div>

      {/* RANK TRACKER TAB */}
      {activeTab === 'tracker' && (
        <div>
          {/* Summary bar */}
          <div className="flex items-center gap-4 mb-5 flex-wrap">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-[hsl(var(--secondary))] text-sm">
              <Search className="w-3.5 h-3.5 text-[hsl(var(--muted-foreground))]" />
              <span className="text-white font-medium">{rankings.length}</span>
              <span className="text-[hsl(var(--muted-foreground))]">关键词</span>
            </div>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-[hsl(var(--secondary))] text-sm">
              <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
              <span className="text-emerald-400 font-medium">{upCount}</span>
              <span className="text-[hsl(var(--muted-foreground))]">排名上升</span>
            </div>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-[hsl(var(--secondary))] text-sm">
              <TrendingDown className="w-3.5 h-3.5 text-red-400" />
              <span className="text-red-400 font-medium">{downCount}</span>
              <span className="text-[hsl(var(--muted-foreground))]">排名下降</span>
            </div>
            {lastCrawled && (
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-[hsl(var(--secondary))] text-sm">
                <RefreshCw className="w-3.5 h-3.5 text-[hsl(var(--muted-foreground))]" />
                <span className="text-[hsl(var(--muted-foreground))]">最近爬取：{lastCrawled}</span>
              </div>
            )}
            <div className="ml-auto">
              <Button
                size="sm"
                onClick={handleCrawl}
                disabled={crawling}
                className="gap-1.5"
              >
                <RefreshCw className={cn('w-3.5 h-3.5', crawling && 'animate-spin')} />
                {crawling ? '爬取中...' : '立即爬取'}
              </Button>
            </div>
          </div>

          {/* Rankings table */}
          {rankings.length === 0 ? (
            <div className="text-center py-16 text-[hsl(var(--muted-foreground))]">
              <Search className="w-10 h-10 mx-auto mb-3 opacity-30" />
              <p className="text-sm">暂无关键词数据</p>
              <p className="text-xs mt-1">前往 Keyword Manager 添加关键词</p>
            </div>
          ) : (
            <div className="rounded-lg border border-[hsl(var(--border))] overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-[hsl(var(--secondary))] border-b border-[hsl(var(--border))]">
                    <th className="text-left px-4 py-3 text-[hsl(var(--muted-foreground))] font-medium text-xs uppercase tracking-wider w-8"></th>
                    <th className="text-left px-4 py-3 text-[hsl(var(--muted-foreground))] font-medium text-xs uppercase tracking-wider">关键词</th>
                    <th className="text-left px-4 py-3 text-[hsl(var(--muted-foreground))] font-medium text-xs uppercase tracking-wider">ASIN</th>
                    <th className="text-left px-4 py-3 text-[hsl(var(--muted-foreground))] font-medium text-xs uppercase tracking-wider">产品</th>
                    <th className="text-right px-4 py-3 text-[hsl(var(--muted-foreground))] font-medium text-xs uppercase tracking-wider">当前排名</th>
                    <th className="text-right px-4 py-3 text-[hsl(var(--muted-foreground))] font-medium text-xs uppercase tracking-wider">7日变化</th>
                    <th className="text-center px-4 py-3 text-[hsl(var(--muted-foreground))] font-medium text-xs uppercase tracking-wider">趋势</th>
                  </tr>
                </thead>
                <tbody>
                  {rankings.map(row => {
                    const key = `${row.asin}|${row.keyword}`
                    const expanded = expandedRow === key
                    const lowRank = row.currentRank !== null && row.currentRank > 50
                    return (
                      <>
                        <tr
                          key={key}
                          onClick={() => setExpandedRow(expanded ? null : key)}
                          className={cn(
                            'border-b border-[hsl(var(--border))] cursor-pointer transition-colors',
                            lowRank ? 'opacity-30' : '',
                            expanded ? 'bg-[hsl(var(--secondary)/0.5)]' : 'hover:bg-[hsl(var(--secondary)/0.3)]'
                          )}
                        >
                          <td className="px-4 py-3 text-[hsl(var(--muted-foreground))]">
                            {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                          </td>
                          <td className="px-4 py-3 text-white font-medium">{row.keyword}</td>
                          <td className="px-4 py-3 text-[hsl(var(--muted-foreground))] font-mono text-xs">{row.asin}</td>
                          <td className="px-4 py-3 text-[hsl(var(--muted-foreground))] max-w-[200px] truncate">{getProductName(row.asin)}</td>
                          <td className="px-4 py-3 text-right">
                            {row.currentRank !== null ? (
                              <span className="text-white font-semibold">#{row.currentRank}</span>
                            ) : (
                              <span className="text-[hsl(var(--muted-foreground))]">—</span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-right">
                            {row.change7d !== 0 ? (
                              <span className={row.change7d > 0 ? 'text-emerald-400 font-medium' : 'text-red-400 font-medium'}>
                                {row.change7d > 0 ? '+' : ''}{row.change7d}
                              </span>
                            ) : (
                              <span className="text-[hsl(var(--muted-foreground))]">—</span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-center">
                            {row.trend === 'up' && <TrendingUp className="w-4 h-4 text-emerald-400 mx-auto" />}
                            {row.trend === 'down' && <TrendingDown className="w-4 h-4 text-red-400 mx-auto" />}
                            {row.trend === 'stable' && <Minus className="w-4 h-4 text-[hsl(var(--muted-foreground))] mx-auto" />}
                          </td>
                        </tr>
                        {expanded && (
                          <tr key={`${key}-expanded`} className="bg-[hsl(var(--secondary)/0.2)]">
                            <td colSpan={7} className="px-8 py-4">
                              <p className="text-xs text-[hsl(var(--muted-foreground))] mb-2 font-medium uppercase tracking-wider">30天排名历史</p>
                              {row.history.length === 0 ? (
                                <p className="text-xs text-[hsl(var(--muted-foreground))]">暂无历史数据</p>
                              ) : (
                                <div className="overflow-x-auto">
                                  <table className="text-xs w-auto">
                                    <thead>
                                      <tr className="text-[hsl(var(--muted-foreground))]">
                                        <th className="text-left pr-8 pb-1">日期</th>
                                        <th className="text-right pr-8 pb-1">自然排名</th>
                                        <th className="text-right pb-1">广告排名</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {[...row.history].reverse().map(h => (
                                        <tr key={h.date} className="text-white">
                                          <td className="pr-8 py-0.5 text-[hsl(var(--muted-foreground))]">{h.date}</td>
                                          <td className="pr-8 py-0.5 text-right">#{h.organicRank}</td>
                                          <td className="py-0.5 text-right">#{h.adRank}</td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              )}
                            </td>
                          </tr>
                        )}
                      </>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* KEYWORD MANAGER TAB */}
      {activeTab === 'manager' && (
        <div>
          {/* Add form */}
          <div className="bg-[hsl(var(--card))] border border-[hsl(var(--border))] rounded-lg p-5 mb-6">
            <h2 className="text-sm font-semibold text-white mb-4">添加关键词</h2>
            <div className="flex gap-3 items-end flex-wrap">
              <div className="flex flex-col gap-1.5">
                <label className="text-xs text-[hsl(var(--muted-foreground))]">ASIN</label>
                <select
                  value={newAsin}
                  onChange={e => setNewAsin(e.target.value)}
                  className="bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-md px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-[hsl(var(--primary))] min-w-[260px]"
                >
                  <option value="">选择产品 ASIN...</option>
                  {products.map(p => (
                    <option key={p.asin} value={p.asin}>
                      {p.asin} — {p.name.slice(0, 40)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col gap-1.5 flex-1 min-w-[200px]">
                <label className="text-xs text-[hsl(var(--muted-foreground))]">关键词</label>
                <input
                  type="text"
                  value={newKeyword}
                  onChange={e => setNewKeyword(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleAddKeyword()}
                  placeholder="e.g. foaming hand sanitizer"
                  className="bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-md px-3 py-2 text-sm text-white placeholder:text-[hsl(var(--muted-foreground))] focus:outline-none focus:ring-1 focus:ring-[hsl(var(--primary))]"
                />
              </div>
              <Button
                onClick={handleAddKeyword}
                disabled={adding || !newAsin || !newKeyword.trim()}
                size="sm"
                className="gap-1.5"
              >
                <Plus className="w-3.5 h-3.5" />
                {adding ? '添加中...' : '添加'}
              </Button>
            </div>
          </div>

          {/* Keyword list by ASIN */}
          {Object.keys(keywordsByAsin).length === 0 ? (
            <div className="text-center py-16 text-[hsl(var(--muted-foreground))]">
              <Search className="w-10 h-10 mx-auto mb-3 opacity-30" />
              <p className="text-sm">暂无关键词</p>
              <p className="text-xs mt-1">使用上方表单添加关键词</p>
            </div>
          ) : (
            <div className="space-y-4">
              {Object.entries(keywordsByAsin).map(([asin, kwList]) => (
                <div key={asin} className="bg-[hsl(var(--card))] border border-[hsl(var(--border))] rounded-lg overflow-hidden">
                  <div className="px-4 py-3 bg-[hsl(var(--secondary))] border-b border-[hsl(var(--border))] flex items-center gap-2">
                    <Badge variant="outline" className="font-mono text-xs">{asin}</Badge>
                    <span className="text-sm text-[hsl(var(--muted-foreground))] truncate">{getProductName(asin)}</span>
                    <span className="ml-auto text-xs text-[hsl(var(--muted-foreground))]">{kwList.length} 个关键词</span>
                  </div>
                  <div className="divide-y divide-[hsl(var(--border))]">
                    {kwList.map(kw => (
                      <div key={kw.keyword} className="flex items-center px-4 py-3 group hover:bg-[hsl(var(--secondary)/0.3)] transition-colors">
                        <span className="text-sm text-white flex-1">{kw.keyword}</span>
                        <span className="text-xs text-[hsl(var(--muted-foreground))] mr-4">
                          {new Date(kw.addedAt).toLocaleDateString('zh-CN')}
                        </span>
                        <button
                          onClick={() => handleDelete(kw.asin, kw.keyword)}
                          className="opacity-0 group-hover:opacity-100 transition-opacity text-[hsl(var(--muted-foreground))] hover:text-red-400"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
