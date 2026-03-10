import { NextResponse } from 'next/server'
import fs from 'fs'
import path from 'path'

const COMPETITORS_DIR = path.resolve(process.env.HOME || '', '.openclaw/skills/amazon-sp-api/reports/competitors')

export async function GET() {
  try {
    const latestPath = path.join(COMPETITORS_DIR, 'latest.json')
    if (!fs.existsSync(latestPath)) {
      return NextResponse.json({ data: [], noData: true })
    }
    const data = JSON.parse(fs.readFileSync(latestPath, 'utf-8'))
    return NextResponse.json({ data, noData: false })
  } catch (err) {
    console.error('Competitors GET error:', err)
    return NextResponse.json({ data: [], noData: true, error: true })
  }
}
