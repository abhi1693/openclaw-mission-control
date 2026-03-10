import { NextResponse } from 'next/server'
import fs from 'fs'
import path from 'path'
import { exec } from 'child_process'
import { promisify } from 'util'
import { COMPETITOR_ASINS, ALERT_THRESHOLDS } from '@/lib/competitors'

const execAsync = promisify(exec)
const SP_API_PATH = path.resolve(process.env.HOME || '', '.openclaw/skills/amazon-sp-api/index.js')
const COMPETITORS_DIR = path.resolve(process.env.HOME || '', '.openclaw/skills/amazon-sp-api/reports/competitors')

export interface CompetitorSnapshot {
  asin: string
  name: string
  brand: string
  category: string
  price: number | null
  currency: string
  bsr: number | null         // NOTE: BSR not available via listing API — needs Product Advertising API or scraper
  rating: number | null
  reviewCount: number | null
  imageUrl: string | null
  hasDeal: boolean
  couponText: string | null
  timestamp: string
}

export interface CompetitorAlert {
  asin: string
  name: string
  type: 'price_drop' | 'price_increase' | 'bsr_improvement' | 'deal_active' | 'review_surge'
  message: string
  oldValue: number | string | null
  newValue: number | string | null
  timestamp: string
}

function parseJsonOutput(stdout: string): Record<string, unknown> {
  const cleaned = stdout.split('\n').filter(l => !l.startsWith('[dotenv')).join('\n').trim()
  // Find first JSON object/array
  const start = cleaned.search(/[{[]/)
  if (start === -1) return {}
  try {
    return JSON.parse(cleaned.slice(start))
  } catch {
    return {}
  }
}

async function fetchPricing(asin: string): Promise<{ price: number | null; currency: string; hasDeal: boolean; couponText: string | null }> {
  try {
    const { stdout } = await execAsync(`node ${SP_API_PATH} pricing --asin ${asin}`, { timeout: 30000 })
    const data = parseJsonOutput(stdout) as Record<string, unknown>
    // SP-API pricing response shape varies; attempt common paths
    const price = (data.landedPrice as number) ?? (data.listingPrice as number) ?? (data.price as number) ?? null
    const currency = (data.currency as string) ?? 'USD'
    const hasDeal = !!(data.salePrice || data.dealPrice || data.couponDiscount)
    const couponText = (data.couponText as string) ?? null
    return { price, currency, hasDeal, couponText }
  } catch {
    return { price: null, currency: 'USD', hasDeal: false, couponText: null }
  }
}

async function fetchListing(asin: string): Promise<{ rating: number | null; reviewCount: number | null; imageUrl: string | null; bsr: number | null }> {
  try {
    const { stdout } = await execAsync(`node ${SP_API_PATH} listing --asin ${asin}`, { timeout: 30000 })
    const data = parseJsonOutput(stdout) as Record<string, unknown>
    const rating = (data.rating as number) ?? (data.averageRating as number) ?? null
    const reviewCount = (data.reviewCount as number) ?? (data.numberOfReviews as number) ?? null
    const imageUrl = (data.mainImage as string) ?? (data.imageUrl as string) ?? null
    // BSR is not available in listing API — would need Product Advertising API or scraper
    const bsr = (data.bsr as number) ?? (data.salesRank as number) ?? null
    return { rating, reviewCount, imageUrl, bsr }
  } catch {
    return { rating: null, reviewCount: null, imageUrl: null, bsr: null }
  }
}

function generateAlerts(
  prev: CompetitorSnapshot | undefined,
  curr: CompetitorSnapshot
): CompetitorAlert[] {
  const alerts: CompetitorAlert[] = []
  const ts = new Date().toISOString()

  if (prev) {
    // Price drop
    if (prev.price && curr.price && prev.price > 0) {
      const changePct = ((prev.price - curr.price) / prev.price) * 100
      if (changePct >= ALERT_THRESHOLDS.priceDropPercent) {
        alerts.push({
          asin: curr.asin, name: curr.name, type: 'price_drop',
          message: `Price dropped ${changePct.toFixed(1)}% from $${prev.price.toFixed(2)} to $${curr.price.toFixed(2)}`,
          oldValue: prev.price, newValue: curr.price, timestamp: ts,
        })
      } else if (-changePct >= ALERT_THRESHOLDS.priceRisePercent) {
        alerts.push({
          asin: curr.asin, name: curr.name, type: 'price_increase',
          message: `Price rose ${(-changePct).toFixed(1)}% from $${prev.price.toFixed(2)} to $${curr.price.toFixed(2)}`,
          oldValue: prev.price, newValue: curr.price, timestamp: ts,
        })
      }
    }

    // BSR improvement (lower number = better rank)
    if (prev.bsr && curr.bsr && prev.bsr > 0) {
      const bsrChangePct = ((prev.bsr - curr.bsr) / prev.bsr) * 100
      if (bsrChangePct >= ALERT_THRESHOLDS.bsrDropPercent) {
        alerts.push({
          asin: curr.asin, name: curr.name, type: 'bsr_improvement',
          message: `BSR improved ${bsrChangePct.toFixed(1)}% from #${prev.bsr} to #${curr.bsr}`,
          oldValue: prev.bsr, newValue: curr.bsr, timestamp: ts,
        })
      }
    }

    // Deal newly active
    if (!prev.hasDeal && curr.hasDeal) {
      alerts.push({
        asin: curr.asin, name: curr.name, type: 'deal_active',
        message: `New deal/coupon detected${curr.couponText ? ': ' + curr.couponText : ''}`,
        oldValue: null, newValue: curr.couponText ?? 'active', timestamp: ts,
      })
    }

    // Review surge
    if (prev.reviewCount !== null && curr.reviewCount !== null) {
      const newReviews = curr.reviewCount - prev.reviewCount
      if (newReviews >= ALERT_THRESHOLDS.newReviewsPerDay) {
        alerts.push({
          asin: curr.asin, name: curr.name, type: 'review_surge',
          message: `Gained ${newReviews} new reviews (${prev.reviewCount} → ${curr.reviewCount})`,
          oldValue: prev.reviewCount, newValue: curr.reviewCount, timestamp: ts,
        })
      }
    }
  }

  return alerts
}

export async function POST() {
  try {
    fs.mkdirSync(COMPETITORS_DIR, { recursive: true })

    const latestPath = path.join(COMPETITORS_DIR, 'latest.json')
    const historyPath = path.join(COMPETITORS_DIR, 'history.json')
    const alertsPath = path.join(COMPETITORS_DIR, 'alerts.json')

    // Load previous snapshot
    let prevMap: Record<string, CompetitorSnapshot> = {}
    if (fs.existsSync(latestPath)) {
      const prev: CompetitorSnapshot[] = JSON.parse(fs.readFileSync(latestPath, 'utf-8'))
      for (const item of prev) prevMap[item.asin] = item
    }

    // Load existing alerts
    let existingAlerts: CompetitorAlert[] = []
    if (fs.existsSync(alertsPath)) {
      existingAlerts = JSON.parse(fs.readFileSync(alertsPath, 'utf-8'))
    }

    const timestamp = new Date().toISOString()
    const snapshot: CompetitorSnapshot[] = []
    const allAlerts: CompetitorAlert[] = []

    for (const config of COMPETITOR_ASINS) {
      const [pricingData, listingData] = await Promise.all([
        fetchPricing(config.asin),
        fetchListing(config.asin),
      ])

      const curr: CompetitorSnapshot = {
        asin: config.asin,
        name: config.name,
        brand: config.brand,
        category: config.category,
        price: pricingData.price,
        currency: pricingData.currency,
        bsr: listingData.bsr,
        rating: listingData.rating,
        reviewCount: listingData.reviewCount,
        imageUrl: listingData.imageUrl,
        hasDeal: pricingData.hasDeal,
        couponText: pricingData.couponText,
        timestamp,
      }

      const alerts = generateAlerts(prevMap[config.asin], curr)
      allAlerts.push(...alerts)
      snapshot.push(curr)
    }

    // Write latest
    fs.writeFileSync(latestPath, JSON.stringify(snapshot, null, 2))

    // Append to history
    let history: (CompetitorSnapshot & { snapshotTime: string })[] = []
    if (fs.existsSync(historyPath)) {
      history = JSON.parse(fs.readFileSync(historyPath, 'utf-8'))
    }
    const historyEntries = snapshot.map(s => ({ ...s, snapshotTime: timestamp }))
    history.push(...historyEntries)
    fs.writeFileSync(historyPath, JSON.stringify(history, null, 2))

    // Write alerts (keep latest 100)
    const updatedAlerts = [...existingAlerts, ...allAlerts].slice(-100)
    fs.writeFileSync(alertsPath, JSON.stringify(updatedAlerts, null, 2))

    return NextResponse.json({ snapshot, alerts: allAlerts, timestamp })
  } catch (err) {
    console.error('Competitors snapshot error:', err)
    return NextResponse.json({ error: true, message: String(err) }, { status: 500 })
  }
}
