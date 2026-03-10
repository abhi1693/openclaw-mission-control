import { NextResponse } from 'next/server'
import fs from 'fs/promises'
import path from 'path'

const COGS_PATH = path.resolve(process.env.HOME || '', '.openclaw/workspace/config/cogs.json')

export interface CostItem {
  sku: string
  asin: string
  productName: string
  unitCost: number
  shippingToPort: number
  freight: number
  customs: number
  dutyRate: number
  lastMile: number
  prep: number
  otherCost: number
  totalLandedCost: number
  currency: string
  updatedAt: string
}

interface CogsFile {
  items: CostItem[]
}

async function readCogs(): Promise<CogsFile> {
  try {
    const raw = await fs.readFile(COGS_PATH, 'utf-8')
    return JSON.parse(raw) as CogsFile
  } catch {
    return { items: [] }
  }
}

export async function GET() {
  const data = await readCogs()
  return NextResponse.json(data)
}

export async function PUT(req: Request) {
  try {
    const body = await req.json() as CogsFile
    if (!Array.isArray(body.items)) {
      return NextResponse.json({ error: 'Invalid payload' }, { status: 400 })
    }
    await fs.mkdir(path.dirname(COGS_PATH), { recursive: true })
    await fs.writeFile(COGS_PATH, JSON.stringify(body, null, 2), 'utf-8')
    return NextResponse.json({ ok: true, count: body.items.length })
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json({ error: msg }, { status: 500 })
  }
}
