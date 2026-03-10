import { NextResponse } from 'next/server'
import { readFileSync, existsSync } from 'fs'
import { join } from 'path'
import { homedir } from 'os'

const RANKINGS_DIR = join(homedir(), '.openclaw', 'workspace', 'cache', 'rankings')
const CONFIG_FILE = join(homedir(), '.openclaw', 'workspace', 'config', 'keywords.json')

interface DayRanking {
  keyword: string
  asin: string
  organicRank: number
  adRank: number
}

interface DayFile {
  [key: string]: DayRanking
}

function readKeywords() {
  if (!existsSync(CONFIG_FILE)) return []
  try {
    return JSON.parse(readFileSync(CONFIG_FILE, 'utf-8')).keywords || []
  } catch { return [] }
}

function getLast30Days(): string[] {
  const days: string[] = []
  for (let i = 29; i >= 0; i--) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    days.push(d.toISOString().slice(0, 10))
  }
  return days
}

export async function GET() {
  const keywords = readKeywords()
  const days = getLast30Days()

  // Build a map: "asin|keyword" -> history[]
  const historyMap: Record<string, { date: string; organicRank: number; adRank: number }[]> = {}

  for (const day of days) {
    const file = join(RANKINGS_DIR, `${day}.json`)
    if (!existsSync(file)) continue
    try {
      const data: DayFile = JSON.parse(readFileSync(file, 'utf-8'))
      for (const entry of Object.values(data)) {
        const key = `${entry.asin}|${entry.keyword}`
        if (!historyMap[key]) historyMap[key] = []
        historyMap[key].push({ date: day, organicRank: entry.organicRank, adRank: entry.adRank })
      }
    } catch { /* skip bad files */ }
  }

  const rankings = keywords.map((kw: { asin: string; keyword: string }) => {
    const key = `${kw.asin}|${kw.keyword}`
    const history = historyMap[key] || []
    const currentRank = history.length > 0 ? history[history.length - 1].organicRank : null

    // 7-day change: compare current vs 7 days ago
    let change7d = 0
    let trend: 'up' | 'down' | 'stable' = 'stable'
    if (history.length >= 2) {
      const recent = history[history.length - 1].organicRank
      const old = history.length >= 7 ? history[history.length - 7].organicRank : history[0].organicRank
      change7d = old - recent // positive = rank improved (lower number)
      trend = change7d > 0 ? 'up' : change7d < 0 ? 'down' : 'stable'
    }

    return {
      keyword: kw.keyword,
      asin: kw.asin,
      history,
      currentRank,
      change7d,
      trend,
    }
  })

  const lastCrawlDate = days.slice().reverse().find(d => existsSync(join(RANKINGS_DIR, `${d}.json`)))

  return NextResponse.json({ rankings, lastCrawled: lastCrawlDate || null })
}

export async function POST() {
  // Trigger a single test crawl for the first keyword
  const keywords = readKeywords()
  if (keywords.length === 0) {
    return NextResponse.json({ message: 'No keywords configured' })
  }
  // Return mock for first keyword
  const kw = keywords[0]
  const result = {
    keyword: kw.keyword,
    asin: kw.asin,
    organicRank: Math.floor(Math.random() * 50) + 1,
    adRank: Math.floor(Math.random() * 10) + 1,
  }
  return NextResponse.json({ result })
}
