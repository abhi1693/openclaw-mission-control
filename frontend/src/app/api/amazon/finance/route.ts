import { NextResponse } from 'next/server'
import fs from 'fs'
import path from 'path'

const REPORTS_PATH = path.resolve(process.env.HOME || '', '.openclaw/skills/amazon-sp-api/reports')

export async function GET() {
  try {
    const files = fs.readdirSync(REPORTS_PATH).filter(f => f.startsWith('finance-') && f.endsWith('.json'))
    if (files.length === 0) {
      return NextResponse.json({ summary: { totalRevenue: 0, totalFees: 0, feeRatio: 0 }, alerts: { feeAlerts: [], highMargin: [] }, mock: true })
    }
    
    const latest = files.sort().reverse()[0]
    const data = JSON.parse(fs.readFileSync(path.join(REPORTS_PATH, latest), 'utf-8'))
    return NextResponse.json(data)
  } catch (err) {
    console.error('Finance API error:', err)
    return NextResponse.json({ summary: { totalRevenue: 0, totalFees: 0, feeRatio: 0 }, alerts: { feeAlerts: [], highMargin: [] }, error: true })
  }
}
