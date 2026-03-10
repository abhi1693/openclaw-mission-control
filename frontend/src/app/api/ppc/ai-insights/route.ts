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
  const file = getLatestMatchingFile('ai-insights-result-')

  if (!file) {
    return NextResponse.json({
      empty: true,
      message: '等待下次 AI 分析运行',
      hint: 'node ~/.openclaw/skills/amazon-advertising/ppc-ai-insights.js --format prompt',
    })
  }

  try {
    const raw = fs.readFileSync(file, 'utf8')
    const data = JSON.parse(raw)
    return NextResponse.json({ empty: false, ...data })
  } catch {
    return NextResponse.json({
      empty: true,
      message: 'AI 洞察文件解析失败，请重新运行分析',
    })
  }
}
