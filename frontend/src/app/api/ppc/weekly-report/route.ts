import { NextResponse } from 'next/server'
import fs from 'fs'
import path from 'path'
import os from 'os'

const CACHE_DIR = path.join(os.homedir(), '.openclaw/skills/amazon-advertising/cache')

function getLatestMatchingFile(prefix: string): string | null {
  try {
    const files = fs.readdirSync(CACHE_DIR)
      .filter(f => f.startsWith(prefix) && f.endsWith('.json'))
      .sort()
      .reverse()
    return files.length ? path.join(CACHE_DIR, files[0]) : null
  } catch {
    return null
  }
}

export async function GET() {
  const file = getLatestMatchingFile('weekly-report-')
  if (!file) {
    return NextResponse.json({
      empty: true,
      message: '暂无周报数据。请运行 node ppc-weekly-report.js',
      overview: { totalSpend: null, totalSales: null, totalOrders: null, acos: null, roas: null },
      moneyKeywords: [],
      burnKeywords: [],
      actionItems: [],
      riskAlerts: [],
      summary: { highPriorityActions: 0, mediumPriorityActions: 0, criticalAlerts: 0, warningAlerts: 0 },
    })
  }

  try {
    const raw = JSON.parse(fs.readFileSync(file, 'utf-8'))
    return NextResponse.json({ ...raw, empty: false, source: path.basename(file) })
  } catch {
    return NextResponse.json(
      { empty: true, error: true, message: '缓存文件读取失败' },
      { status: 500 }
    )
  }
}
