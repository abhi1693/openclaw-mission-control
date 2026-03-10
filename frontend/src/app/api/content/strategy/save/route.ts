import { NextResponse } from 'next/server'
import { writeFileSync, mkdirSync, readdirSync, statSync } from 'fs'
import path from 'path'

const STRATEGIES_DIR = path.join(process.env.HOME || '', '.openclaw/workspace/content/strategies')

export async function POST(req: Request) {
  try {
    const { type, asin, markdown } = await req.json()
    if (!type || !markdown) {
      return NextResponse.json({ error: 'type and markdown are required' }, { status: 400 })
    }
    mkdirSync(STRATEGIES_DIR, { recursive: true })
    const date = new Date().toISOString().split('T')[0]
    const filename = `${type}-${asin || 'all'}-${date}.md`
    writeFileSync(path.join(STRATEGIES_DIR, filename), markdown, 'utf-8')
    return NextResponse.json({ ok: true, filename })
  } catch (err) {
    console.error('[strategy/save] POST error:', err)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}

export async function GET() {
  try {
    mkdirSync(STRATEGIES_DIR, { recursive: true })
    const files = readdirSync(STRATEGIES_DIR)
      .filter(f => f.endsWith('.md'))
      .map(f => {
        const st = statSync(path.join(STRATEGIES_DIR, f))
        const parts = f.replace('.md', '').split('-')
        return {
          filename: f,
          type: parts[0],
          date: parts.slice(-3).join('-'),
          sizeKb: Math.round(st.size / 1024),
        }
      })
    return NextResponse.json({ files })
  } catch (err) {
    console.error('[strategy/save] GET error:', err)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
