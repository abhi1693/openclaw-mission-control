import { NextResponse } from 'next/server'
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs'
import { join } from 'path'
import { homedir } from 'os'

const RANKINGS_DIR = join(homedir(), '.openclaw', 'workspace', 'cache', 'rankings')
const CONFIG_FILE = join(homedir(), '.openclaw', 'workspace', 'config', 'keywords.json')

function readKeywords() {
  if (!existsSync(CONFIG_FILE)) return []
  try {
    return JSON.parse(readFileSync(CONFIG_FILE, 'utf-8')).keywords || []
  } catch { return [] }
}

export async function POST() {
  const keywords = readKeywords()
  if (keywords.length === 0) {
    return NextResponse.json({ message: 'No keywords configured', crawled: 0 })
  }

  // Ensure rankings dir exists
  if (!existsSync(RANKINGS_DIR)) {
    mkdirSync(RANKINGS_DIR, { recursive: true })
  }

  const today = new Date().toISOString().slice(0, 10)
  const outFile = join(RANKINGS_DIR, `${today}.json`)

  // Load existing today's data if any
  let todayData: Record<string, { keyword: string; asin: string; organicRank: number; adRank: number }> = {}
  if (existsSync(outFile)) {
    try { todayData = JSON.parse(readFileSync(outFile, 'utf-8')) } catch { /* */ }
  }

  // Generate mock rankings for all keywords
  for (const kw of keywords) {
    const key = `${kw.asin}|${kw.keyword}`
    todayData[key] = {
      keyword: kw.keyword,
      asin: kw.asin,
      organicRank: Math.floor(Math.random() * 50) + 1,
      adRank: Math.floor(Math.random() * 10) + 1,
    }
  }

  writeFileSync(outFile, JSON.stringify(todayData, null, 2), 'utf-8')

  return NextResponse.json({
    success: true,
    crawled: keywords.length,
    date: today,
    results: Object.values(todayData),
  })
}
