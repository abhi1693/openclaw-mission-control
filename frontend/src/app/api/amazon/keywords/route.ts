import { NextResponse } from 'next/server'
import fs from 'fs'
import path from 'path'

const REPORTS_PATH = path.resolve(process.env.HOME || '', '.openclaw/skills/amazon-sp-api/reports')

export async function GET() {
  try {
    // Check for imported search terms report
    const searchTermsFile = path.join(REPORTS_PATH, 'search-terms.json')
    if (fs.existsSync(searchTermsFile)) {
      const data = JSON.parse(fs.readFileSync(searchTermsFile, 'utf-8'))
      return NextResponse.json(data)
    }

    // Check for keyword analysis reports
    const files = fs.readdirSync(REPORTS_PATH).filter(f => f.startsWith('keywords-') && f.endsWith('.json'))
    if (files.length > 0) {
      const latest = files.sort().reverse()[0]
      const data = JSON.parse(fs.readFileSync(path.join(REPORTS_PATH, latest), 'utf-8'))
      return NextResponse.json(data)
    }

    // No data available
    return NextResponse.json({
      noData: true,
      message: '请从 Amazon Brand Analytics 或 Advertising Console 导出搜索词报告，保存为 reports/search-terms.json',
      period: 'N/A',
      summary: { addKeywords: 0, negativeKeywords: 0, bidUpSuggestions: 0, bidDownSuggestions: 0, watchList: 0 },
      topAdd: [],
      topNegative: [],
      topBidUp: [],
      topBidDown: [],
    })
  } catch (err) {
    console.error('Keywords API error:', err)
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
