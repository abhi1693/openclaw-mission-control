import { NextResponse } from 'next/server'
import { exec } from 'child_process'
import { promisify } from 'util'
import path from 'path'

const execAsync = promisify(exec)
const SP_API_PATH = path.resolve(process.env.HOME || '', '.openclaw/skills/amazon-sp-api/index.js')

export async function GET() {
  try {
    // Fetch directly from SP-API for full inventory
    const { stdout } = await execAsync(`node ${SP_API_PATH} inventory`)
    const json = stdout.split('\n').filter(l => !l.startsWith('[dotenv')).join('\n')
    const data = JSON.parse(json)
    
    // Filter to only FBA SKUs
    const items = (data.items || []).filter((item: { sku: string }) => item.sku.endsWith('-FBA'))
    
    // Categorize by stock level
    const critical = items.filter((i: { totalSupply: number }) => (i.totalSupply ?? 0) <= 10)
    const lowStock = items.filter((i: { totalSupply: number }) => (i.totalSupply ?? 0) > 10 && (i.totalSupply ?? 0) <= 50)
    const overstock = items.filter((i: { totalSupply: number }) => (i.totalSupply ?? 0) > 500)
    const healthy = items.filter((i: { totalSupply: number }) => (i.totalSupply ?? 0) > 50 && (i.totalSupply ?? 0) <= 500)
    
    const result = {
      items: items.map((item: { sku: string; asin?: string; productName?: string; totalSupply?: number }) => ({
        sku: item.sku,
        asin: item.asin,
        productName: item.productName || item.sku,
        available: item.totalSupply || 0,
        inbound: 0,
        reserved: 0,
        status: (item.totalSupply ?? 0) <= 10 ? 'critical' : (item.totalSupply ?? 0) <= 50 ? 'lowStock' : (item.totalSupply ?? 0) > 500 ? 'overstock' : 'healthy',
      })),
      summary: {
        total: items.length,
        critical: critical.length,
        lowStock: lowStock.length,
        overstock: overstock.length,
        restock: 0,
        healthy: healthy.length,
      },
      alerts: {
        critical: critical.slice(0, 10).map((i: any) => ({ ...i, priority: 'high', message: `${i.totalSupply} units left` })),
        lowStock: lowStock.slice(0, 15),
        overstock: overstock.slice(0, 10),
        restock: [],
      }
    }
    
    return NextResponse.json(result)
  } catch (err) {
    console.error('Inventory API error:', err)
    return NextResponse.json({ items: [], summary: { total: 0, critical: 0 }, alerts: { critical: [], lowStock: [] }, error: true, mock: true })
  }
}
