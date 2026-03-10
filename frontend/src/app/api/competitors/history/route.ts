import { NextResponse } from 'next/server'
import fs from 'fs'
import path from 'path'

const COMPETITORS_DIR = path.resolve(process.env.HOME || '', '.openclaw/skills/amazon-sp-api/reports/competitors')

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const asin = searchParams.get('asin')
  const days = parseInt(searchParams.get('days') ?? '30', 10)

  try {
    const historyPath = path.join(COMPETITORS_DIR, 'history.json')
    if (!fs.existsSync(historyPath)) {
      return NextResponse.json({ data: [], noData: true })
    }

    type HistoryEntry = { asin: string; snapshotTime: string; [key: string]: unknown }
    let history: HistoryEntry[] = JSON.parse(fs.readFileSync(historyPath, 'utf-8'))

    // Filter by ASIN
    if (asin) {
      history = history.filter(h => h.asin === asin)
    }

    // Filter by days
    const cutoff = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString()
    history = history.filter(h => h.snapshotTime >= cutoff)

    return NextResponse.json({ data: history, noData: history.length === 0 })
  } catch (err) {
    console.error('Competitors history error:', err)
    return NextResponse.json({ data: [], noData: true, error: true })
  }
}
