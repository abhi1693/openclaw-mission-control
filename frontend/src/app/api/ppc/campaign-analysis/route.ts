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
  const file = getLatestMatchingFile('campaign-analysis-')
  if (!file) {
    return NextResponse.json({
      empty: true,
      message: '暂无 Campaign 分析数据。请运行 node ppc-campaign-analyzer.js',
      summary: null,
      duplicates: [],
      asinCoverage: { whitelist: [], covered: [], uncovered: [] },
      typeDistribution: { sp: {}, sb: {}, totalDailyBudget: 0 },
      zombieCampaigns: [],
      naming: { issueCount: 0, issues: [] },
      recommendations: [],
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
