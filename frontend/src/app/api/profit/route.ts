import { NextResponse } from 'next/server'
import { exec } from 'child_process'
import { promisify } from 'util'
import fs from 'fs/promises'
import path from 'path'
import type { CostItem } from '@/app/api/profit/cogs/route'

const execAsync = promisify(exec)

const COGS_PATH    = path.resolve(process.env.HOME || '', '.openclaw/workspace/config/cogs.json')
const CACHE_PATH   = path.resolve(process.env.HOME || '', '.openclaw/workspace/cache/profit-cache.json')
const SP_API_PATH  = path.resolve(process.env.HOME || '', '.openclaw/skills/amazon-sp-api/index.js')
const AD_CACHE_DIR = path.resolve(process.env.HOME || '', '.openclaw/skills/amazon-advertising/cache')
const CACHE_MAX_AGE_MS = 4 * 60 * 60 * 1000

// ─── Types ─────────────────────────────────────────────────────────────────────

export interface ProfitItem {
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

export interface ProfitSummary {
  totalRevenue: number
  totalCost: number
  totalProfit: number
  profitMargin: number
  totalAdSpend: number
  tacos: number
  organicRatio: number
}

export interface ProfitData {
  summary: ProfitSummary
  items: ProfitItem[]
  cachedAt: string
  fromCache: boolean
  warnings?: string[]
}

interface CacheFile {
  cachedAt: string
  data: ProfitData
}

// ─── Cache ──────────────────────────────────────────────────────────────────────

async function readCache(): Promise<CacheFile | null> {
  try {
    const raw = await fs.readFile(CACHE_PATH, 'utf-8')
    return JSON.parse(raw) as CacheFile
  } catch {
    return null
  }
}

async function writeCache(data: ProfitData): Promise<string> {
  const cachedAt = new Date().toISOString()
  await fs.mkdir(path.dirname(CACHE_PATH), { recursive: true })
  await fs.writeFile(CACHE_PATH, JSON.stringify({ cachedAt, data }, null, 2), 'utf-8')
  return cachedAt
}

// ─── Data Fetchers ─────────────────────────────────────────────────────────────

async function readCogs(): Promise<Map<string, CostItem>> {
  try {
    const raw = await fs.readFile(COGS_PATH, 'utf-8')
    const { items } = JSON.parse(raw) as { items: CostItem[] }
    const map = new Map<string, CostItem>()
    for (const item of items) map.set(item.sku, item)
    return map
  } catch {
    return new Map()
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function runSpApi(subcommand: string, days: number): Promise<any | null> {
  try {
    const cmd = `node ${SP_API_PATH} ${subcommand} --days ${days}`
    const { stdout, stderr } = await execAsync(cmd, { timeout: 300_000 })
    if (stderr) console.error(`[profit/${subcommand}]`, stderr.slice(0, 200))
    const clean = stdout.split('\n').filter(l => !l.startsWith('[dotenv')).join('\n')
    return JSON.parse(clean)
  } catch (err) {
    console.error(`[profit] SP-API ${subcommand} failed:`, err)
    return null
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function readLatestAdCache(): Promise<any | null> {
  try {
    const entries = await fs.readdir(AD_CACHE_DIR)
    const files = entries
      .filter(f => f.startsWith('performance-campaigns-') && f.endsWith('.json'))
      .sort()
    if (!files.length) return null
    const raw = await fs.readFile(path.join(AD_CACHE_DIR, files[files.length - 1]), 'utf-8')
    return JSON.parse(raw)
  } catch {
    return null
  }
}

// ─── Compute ────────────────────────────────────────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function computeProfit(ordersData: any, financesData: any, adData: any, cogsMap: Map<string, CostItem>): { items: ProfitItem[], warnings: string[] } {
  const warnings: string[] = []
  const skuMap = new Map<string, ProfitItem>()

  // Process orders
  if (ordersData?.orders) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    for (const order of ordersData.orders as any[]) {
      const orderItems = order.orderItems || []
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      for (const item of orderItems as any[]) {
        const sku = item.sellerSKU || item.sku || ''
        const asin = item.asin || ''
        if (!sku) continue

        const existing = skuMap.get(sku)
        const qty = Number(item.quantityOrdered || 0)
        const price = Number(item.itemPrice?.amount || item.unitPrice || 0)
        const revenue = price * qty

        if (existing) {
          existing.unitsSold += qty
          existing.revenue += revenue
        } else {
          const cogs = cogsMap.get(sku)
          skuMap.set(sku, {
            sku,
            asin,
            productName: item.title || cogs?.productName || sku,
            revenue,
            unitsSold: qty,
            landedCost: (cogs?.totalLandedCost || 0) * qty,
            fbaFee: 0,
            referralFee: 0,
            adSpend: 0,
            netProfit: 0,
            profitMargin: 0,
          })
        }
      }
    }
  } else {
    warnings.push('orders data unavailable')
  }

  // Process finances - extract FBA & referral fees
  if (financesData?.financialEvents || financesData?.events) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const events: any[] = financesData.financialEvents || financesData.events || []
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    for (const event of events as any[]) {
      const items = event.shipmentItemList || event.items || []
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      for (const fi of items as any[]) {
        const sku = fi.sellerSKU || fi.sku || ''
        if (!sku) continue
        const entry = skuMap.get(sku)
        if (!entry) continue
        const charges = fi.itemChargeList || fi.charges || []
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        for (const charge of charges as any[]) {
          const type = (charge.chargeType || '').toLowerCase()
          const amt = Math.abs(Number(charge.chargeAmount?.amount || charge.amount || 0))
          if (type.includes('fba') || type.includes('fulfillment')) entry.fbaFee += amt
          if (type.includes('referral') || type.includes('commission')) entry.referralFee += amt
        }
      }
    }
  } else {
    warnings.push('finances data unavailable')
  }

  // Process ad spend
  if (adData) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const campaigns: any[] = adData.campaigns || adData || []
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    for (const campaign of campaigns as any[]) {
      const adGroups = campaign.adGroups || campaign.keywords || []
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      for (const ag of adGroups as any[]) {
        const sku = ag.sku || ''
        if (!sku) continue
        const entry = skuMap.get(sku)
        if (entry) entry.adSpend += Number(ag.spend || ag.cost || 0)
      }
      // also top-level sku
      const sku = campaign.sku || ''
      if (sku && skuMap.has(sku)) {
        skuMap.get(sku)!.adSpend += Number(campaign.spend || campaign.cost || 0)
      }
    }
  } else {
    warnings.push('advertising data unavailable')
  }

  // Final profit calculations
  for (const [sku, item] of skuMap) {
    const cogs = cogsMap.get(sku)
    if (cogs) item.landedCost = cogs.totalLandedCost * item.unitsSold
    item.netProfit = item.revenue - item.landedCost - item.fbaFee - item.referralFee - item.adSpend
    item.profitMargin = item.revenue > 0 ? (item.netProfit / item.revenue) * 100 : 0
  }

  return { items: Array.from(skuMap.values()), warnings }
}

// ─── Build Response ─────────────────────────────────────────────────────────────

function buildResponse(items: ProfitItem[], warnings: string[], cachedAt: string, fromCache: boolean): ProfitData {
  const totalRevenue  = items.reduce((s, i) => s + i.revenue, 0)
  const totalCost     = items.reduce((s, i) => s + i.landedCost + i.fbaFee + i.referralFee, 0)
  const totalProfit   = items.reduce((s, i) => s + i.netProfit, 0)
  const totalAdSpend  = items.reduce((s, i) => s + i.adSpend, 0)
  const profitMargin  = totalRevenue > 0 ? (totalProfit / totalRevenue) * 100 : 0
  const tacos         = totalRevenue > 0 ? (totalAdSpend / totalRevenue) * 100 : 0
  const organicRev    = items.reduce((s, i) => s + Math.max(0, i.revenue - i.adSpend), 0)
  const organicRatio  = totalRevenue > 0 ? (organicRev / totalRevenue) * 100 : 0

  return {
    summary: { totalRevenue, totalCost, totalProfit, profitMargin, totalAdSpend, tacos, organicRatio },
    items,
    cachedAt,
    fromCache,
    warnings: warnings.length ? warnings : undefined,
  }
}

// ─── Handlers ───────────────────────────────────────────────────────────────────

async function fetchFresh(): Promise<ProfitData> {
  const [cogsMap, ordersData, financesData, adData] = await Promise.all([
    readCogs(),
    runSpApi('orders', 30),
    runSpApi('finances', 30),
    readLatestAdCache(),
  ])
  const { items, warnings } = computeProfit(ordersData, financesData, adData, cogsMap)
  const cachedAt = new Date().toISOString()
  const result = buildResponse(items, warnings, cachedAt, false)
  await writeCache(result)
  return result
}

export async function GET() {
  // Cache-first
  const cached = await readCache()
  if (cached) {
    const ageMs = Date.now() - new Date(cached.cachedAt).getTime()
    if (ageMs < CACHE_MAX_AGE_MS) {
      return NextResponse.json({ ...cached.data, cachedAt: cached.cachedAt, fromCache: true })
    }
  }

  try {
    const data = await fetchFresh()
    return NextResponse.json(data)
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    console.error('[profit] GET error:', msg)
    const empty = buildResponse([], ['Failed to fetch data: ' + msg.slice(0, 200)], new Date().toISOString(), false)
    return NextResponse.json(empty, { status: 200 })
  }
}

export async function POST() {
  try {
    const data = await fetchFresh()
    return NextResponse.json(data)
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    console.error('[profit] POST force refresh error:', msg)
    const empty = buildResponse([], ['Force refresh failed: ' + msg.slice(0, 200)], new Date().toISOString(), false)
    return NextResponse.json(empty, { status: 200 })
  }
}
