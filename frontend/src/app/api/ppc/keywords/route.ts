import { NextResponse } from 'next/server'
import { exec } from 'child_process'
import { promisify } from 'util'
import path from 'path'
import fs from 'fs'

const execAsync = promisify(exec)
const GUARD_PATH = path.resolve(require('os').homedir(), '.openclaw/skills/amazon-advertising/guard.js')
const CACHE_DIR = '/tmp/zoviro-ppc-cache'

function getCachePath(days: number) {
  return path.join(CACHE_DIR, `keywords-${days}d.json`)
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
      keyword: r.targeting ?? r.keywordText ?? '—',
      matchType: r.matchType ?? '—',
      campaignName: r.campaignName ?? '—',
      adGroupName: r.adGroupName ?? '—',
      impressions,
      clicks,
      ctr: impressions > 0 ? +(clicks / impressions * 100).toFixed(2) : 0,
      cpc: clicks > 0 ? +(cost / clicks).toFixed(2) : 0,
      cost: +cost.toFixed(2),
      sales: +sales.toFixed(2),
      orders,
      acos: sales > 0 ? +(cost / sales * 100).toFixed(1) : (cost > 0 ? 999 : 0),
      convRate: clicks > 0 ? +(orders / clicks * 100).toFixed(2) : 0,
      roas: cost > 0 ? +(sales / cost).toFixed(2) : 0,
    }
  }).sort((a: any, b: any) => b.cost - a.cost)
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const days = parseInt(searchParams.get('days') || '7', 10)

  // Check cache first
  const cachePath = getCachePath(days)
  if (isCacheFresh(cachePath)) {
    try {
      const cached = JSON.parse(fs.readFileSync(cachePath, 'utf-8'))
      return NextResponse.json({ ...cached, cached: true })
    } catch { /* fall through */ }
  }

  try {
    const { stdout } = await execAsync(
      `node ${GUARD_PATH} performance --keywords --days ${days}`,
      { timeout: 180_000 }
    )
    const lines = stdout.split('\n').filter(l => !l.startsWith('[Auth]') && !l.startsWith('[Report]') && !l.startsWith('[dotenv') && l.trim())
    const data = JSON.parse(lines.join('\n'))

    const keywords = enrichRows(data.rows ?? [])

    // Aggregate KPIs
    const totalSpend = keywords.reduce((s: number, k: any) => s + k.cost, 0)
    const totalSales = keywords.reduce((s: number, k: any) => s + k.sales, 0)
    const totalClicks = keywords.reduce((s: number, k: any) => s + k.clicks, 0)
    const totalOrders = keywords.reduce((s: number, k: any) => s + k.orders, 0)
    const totalImpressions = keywords.reduce((s: number, k: any) => s + k.impressions, 0)

    const result = {
      days,
      startDate: data.startDate,
      endDate: data.endDate,
      count: keywords.length,
      kpi: {
        spend: +totalSpend.toFixed(2),
        sales: +totalSales.toFixed(2),
        clicks: totalClicks,
        orders: totalOrders,
        impressions: totalImpressions,
        acos: totalSales > 0 ? +(totalSpend / totalSales * 100).toFixed(1) : 0,
        roas: totalSpend > 0 ? +(totalSales / totalSpend).toFixed(2) : 0,
        cpc: totalClicks > 0 ? +(totalSpend / totalClicks).toFixed(2) : 0,
        ctr: totalImpressions > 0 ? +(totalClicks / totalImpressions * 100).toFixed(2) : 0,
        convRate: totalClicks > 0 ? +(totalOrders / totalClicks * 100).toFixed(2) : 0,
      },
      keywords,
    }

    // Cache
    try {
      fs.mkdirSync(CACHE_DIR, { recursive: true })
      fs.writeFileSync(cachePath, JSON.stringify(result))
    } catch { /* ok */ }

    return NextResponse.json(result)
  } catch (err: any) {
    // Return stale cache if available
    try {
      const stale = JSON.parse(fs.readFileSync(cachePath, 'utf-8'))
      return NextResponse.json({ ...stale, cached: true, stale: true })
    } catch { /* no cache */ }

    console.error('PPC keywords API error:', err?.stderr || err)
    return NextResponse.json({
      days, count: 0, keywords: [],
      kpi: { spend: 0, sales: 0, clicks: 0, orders: 0, impressions: 0, acos: 0, roas: 0, cpc: 0, ctr: 0, convRate: 0 },
      error: true,
      message: err?.stderr?.includes('Report') ? '报告生成中，请稍后再试' : 'Advertising API 连接失败',
    }, { status: 503 })
  }
}
