import { NextResponse } from 'next/server'
import fs from 'fs'
import path from 'path'

const COMPETITORS_DIR = path.resolve(process.env.HOME || '', '.openclaw/skills/amazon-sp-api/reports/competitors')

export async function GET() {
  try {
    const alertsPath = path.join(COMPETITORS_DIR, 'alerts.json')
    if (!fs.existsSync(alertsPath)) {
      return NextResponse.json({ alerts: [], noData: true })
    }
    const alerts = JSON.parse(fs.readFileSync(alertsPath, 'utf-8'))
    return NextResponse.json({ alerts, noData: alerts.length === 0 })
  } catch (err) {
    console.error('Competitors alerts error:', err)
    return NextResponse.json({ alerts: [], noData: true, error: true })
  }
}
