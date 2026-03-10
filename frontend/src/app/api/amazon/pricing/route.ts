import { NextResponse } from 'next/server'
import fs from 'fs'
import path from 'path'
import { exec } from 'child_process'
import { promisify } from 'util'

const execAsync = promisify(exec)
const REPORTS_PATH = path.resolve(process.env.HOME || '', '.openclaw/skills/amazon-sp-api/reports')
const SP_API_PATH = path.resolve(process.env.HOME || '', '.openclaw/skills/amazon-sp-api/index.js')

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const asin = searchParams.get('asin')

  try {
    // If specific ASIN requested, query SP-API directly
    if (asin) {
      const { stdout } = await execAsync(`node ${SP_API_PATH} pricing --asin ${asin}`)
      const json = stdout.split('\n').filter(l => !l.startsWith('[dotenv')).join('\n')
      return NextResponse.json(JSON.parse(json))
    }

    // Otherwise read latest pricing report
    const files = fs.readdirSync(REPORTS_PATH).filter(f => f.startsWith('pricing-') && f.endsWith('.json') && !f.includes('history'))
    if (files.length === 0) {
      return NextResponse.json({ summary: { priceDrops: 0, priceIncreases: 0, stable: 0 }, priceDrops: [], priceIncreases: [], noData: true })
    }

    const latest = files.sort().reverse()[0]
    const data = JSON.parse(fs.readFileSync(path.join(REPORTS_PATH, latest), 'utf-8'))
    return NextResponse.json(data)
  } catch (err) {
    console.error('Pricing API error:', err)
    return NextResponse.json({ summary: { priceDrops: 0, priceIncreases: 0, stable: 0 }, priceDrops: [], priceIncreases: [], error: true })
  }
}
