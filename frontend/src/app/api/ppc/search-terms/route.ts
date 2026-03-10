import { NextResponse } from 'next/server'
import { exec } from 'child_process'
import { promisify } from 'util'
import path from 'path'
import fs from 'fs'

const execAsync = promisify(exec)
const GUARD_PATH = path.resolve(require('os').homedir(), '.openclaw/skills/amazon-advertising/guard.js')
const CACHE_DIR = '/tmp/zoviro-ppc-cache'

function getCachePath(days: number) {
  return path.join(CACHE_DIR, `search-terms-${days}d.json`)
}

function isCacheFresh(filepath: string, maxAgeMs = 6 * 3600 * 1000): boolean {
  try {
    const stat = fs.statSync(filepath)
    return Date.now() - stat.mtimeMs < maxAgeMs
  } catch { return false }
}

function enrichRows(rows: any[]) {
  return rows.map((r: any) => {
    const impressions = r.impressions ?? 0
    const clicks = r.clicks ?? 0
    const cost = r.cost ?? 0
    const sales = r.sales7d ?? 0
    const orders = r.purchases7d ?? 0
    return {
      searchTerm: r.searchTerm ?? '—',
      targeting: r.targeting ?? '—',
      matchType: r.matchType ?? '—',
      campaignName: r.campaignName ?? '—',
      impressions,
      clicks,
      ctr: impressions > 0 ? +(clicks / impressions * 100).toFixed(2) : 0,
      cpc: clicks > 0 ? +(cost / clicks).toFixed(2) : 0,
      cost: +cost.toFixed(2),
      sales: +sales.toFixed(2),
      orders,
      acos: sales > 0 ? +(cost / sales * 100).toFixed(1) : (cost > 0 ? 999 : 0),
      convRate: clicks > 0 ? +(orders / clicks * 100).toFixed(2) : 0,
    }
  }).sort((a: any, b: any) => b.cost - a.cost)
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const days = parseInt(searchParams.get('days') || '7', 10)

  const cachePath = getCachePath(days)
  if (isCacheFresh(cachePath)) {
    try {
      const cached = JSON.parse(fs.readFileSync(cachePath, 'utf-8'))
      return NextResponse.json({ ...cached, cached: true })
    } catch { /* fall through */ }
  }

  try {
    const { stdout } = await execAsync(
      `node ${GUARD_PATH} search-terms --days ${days}`,
      { timeout: 180_000 }
    )
    const lines = stdout.split('\n').filter(l => !l.startsWith('[Auth]') && !l.startsWith('[Report]') && !l.startsWith('[dotenv') && l.trim())
    const data = JSON.parse(lines.join('\n'))

    const terms = enrichRows(data.rows ?? [])

    const result = {
      days,
      startDate: data.startDate,
      endDate: data.endDate,
      count: terms.length,
      terms,
    }

    try {
      fs.mkdirSync(CACHE_DIR, { recursive: true })
      fs.writeFileSync(cachePath, JSON.stringify(result))
    } catch { /* ok */ }

    return NextResponse.json(result)
  } catch (err: any) {
    try {
      const stale = JSON.parse(fs.readFileSync(cachePath, 'utf-8'))
      return NextResponse.json({ ...stale, cached: true, stale: true })
    } catch { /* no cache */ }

    console.error('PPC search-terms API error:', err?.stderr || err)
    return NextResponse.json({
      days, count: 0, terms: [],
      error: true,
      message: '搜索词报告生成失败',
    }, { status: 503 })
  }
}
