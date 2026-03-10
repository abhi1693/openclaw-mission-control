import { NextResponse } from 'next/server'
import { exec } from 'child_process'
import { promisify } from 'util'
import path from 'path'
import fs from 'fs/promises'

const execAsync = promisify(exec)
const GUARD_PATH = path.resolve(process.env.HOME || '', '.openclaw/skills/amazon-sp-api/guard.js')
const CACHE_PATH = path.resolve(process.env.HOME || '', '.openclaw/workspace/cache/inventory-cache.json')
const CACHE_MAX_AGE_MS = 4 * 60 * 60 * 1000 // 4 hours

// ─── Types ─────────────────────────────────────────────────────────────────────

export interface InventoryItem {
  sku: string
  fnsku: string
  asin: string
  productName: string
  condition: string
  yourPrice: number
  afnListingExists: string
  afnWarehouseQuantity: number
  afnFulfillableQuantity: number
  afnUnsellableQuantity: number
  afnReservedQuantity: number
  afnTotalQuantity: number
  afnInboundWorkingQuantity: number
  afnInboundShippedQuantity: number
  afnInboundReceivingQuantity: number
  afnResearchingQuantity: number
  afnReservedFutureSupply: number
  afnFutureSupplyBuyable: number
  perUnitVolume: number
}

export interface InventorySummary {
  totalFulfillable: number
  totalReserved: number
  totalUnsellable: number
  totalWarehouse: number
  totalInboundWorking: number
  totalInboundShipped: number
  totalInboundReceiving: number
  totalResearching: number
}

export interface InventoryStatusData {
  reportType: string
  totalSkus: number
  summary: InventorySummary
  items: InventoryItem[]
  error?: boolean
  errorMessage?: string
  cachedAt?: string
  fromCache?: boolean
}

// ─── Cache Helpers ─────────────────────────────────────────────────────────────

interface CacheFile {
  cachedAt: string
  data: InventoryStatusData
}

async function readCache(): Promise<CacheFile | null> {
  try {
    const raw = await fs.readFile(CACHE_PATH, 'utf-8')
    return JSON.parse(raw) as CacheFile
  } catch {
    return null
  }
}

async function writeCache(data: InventoryStatusData): Promise<string> {
  const cachedAt = new Date().toISOString()
  const payload: CacheFile = { cachedAt, data }
  await fs.mkdir(path.dirname(CACHE_PATH), { recursive: true })
  await fs.writeFile(CACHE_PATH, JSON.stringify(payload), 'utf-8')
  return cachedAt
}

// ─── SP-API Fetch ─────────────────────────────────────────────────────────────

async function fetchFromSpApi(filterSku?: string | null, filterAsin?: string | null): Promise<InventoryStatusData> {
  const args: string[] = ['inventory-status']
  if (filterSku)  args.push('--sku',  filterSku)
  if (filterAsin) args.push('--asin', filterAsin)

  const cmd = `node ${GUARD_PATH} ${args.join(' ')}`
  const { stdout, stderr } = await execAsync(cmd, { timeout: 300_000 /* 5 min */ })

  if (stderr) {
    for (const line of stderr.split('\n').filter(Boolean)) {
      console.error('[inventory-status]', line)
    }
  }

  const clean = stdout
    .split('\n')
    .filter(l => !l.startsWith('[dotenv'))
    .join('\n')

  return JSON.parse(clean) as InventoryStatusData
}

// ─── Empty Response ────────────────────────────────────────────────────────────

function emptyResponse(msg: string): InventoryStatusData {
  return {
    error: true,
    errorMessage: msg.slice(0, 300),
    reportType: 'GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA',
    totalSkus: 0,
    summary: {
      totalFulfillable: 0,
      totalReserved: 0,
      totalUnsellable: 0,
      totalWarehouse: 0,
      totalInboundWorking: 0,
      totalInboundShipped: 0,
      totalInboundReceiving: 0,
      totalResearching: 0,
    },
    items: [],
  }
}

// ─── GET Handler (cache-first) ─────────────────────────────────────────────────

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url)
  const filterSku  = searchParams.get('sku')
  const filterAsin = searchParams.get('asin')

  // Only use cache for unfiltered requests
  const hasFilter = filterSku || filterAsin

  if (!hasFilter) {
    const cached = await readCache()
    if (cached) {
      const ageMs = Date.now() - new Date(cached.cachedAt).getTime()
      if (ageMs < CACHE_MAX_AGE_MS) {
        console.log('[inventory-status] Cache hit, age:', Math.round(ageMs / 60000), 'min')
        return NextResponse.json({
          ...cached.data,
          cachedAt: cached.cachedAt,
          fromCache: true,
        })
      }
      console.log('[inventory-status] Cache expired, fetching fresh')
    } else {
      console.log('[inventory-status] No cache, fetching fresh')
    }
  }

  try {
    const data = await fetchFromSpApi(filterSku, filterAsin)

    // Write cache only for unfiltered full fetch
    if (!hasFilter) {
      const cachedAt = await writeCache(data)
      return NextResponse.json({ ...data, cachedAt, fromCache: false })
    }

    return NextResponse.json(data)
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    console.error('[inventory-status] API error:', msg)
    return NextResponse.json(emptyResponse(msg), { status: 200 })
  }
}

// ─── POST Handler (force refresh) ─────────────────────────────────────────────

export async function POST() {
  console.log('[inventory-status] Force refresh requested')
  try {
    const data = await fetchFromSpApi()
    const cachedAt = await writeCache(data)
    return NextResponse.json({ ...data, cachedAt, fromCache: false })
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    console.error('[inventory-status] Force refresh error:', msg)
    return NextResponse.json(emptyResponse(msg), { status: 200 })
  }
}
