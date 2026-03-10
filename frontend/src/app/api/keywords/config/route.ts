import { NextRequest, NextResponse } from 'next/server'
import { readFileSync, writeFileSync, existsSync } from 'fs'
import { join } from 'path'
import { homedir } from 'os'

const CONFIG_FILE = join(homedir(), '.openclaw', 'workspace', 'config', 'keywords.json')

interface KeywordEntry {
  asin: string
  keyword: string
  addedAt: string
}

function readKeywords(): KeywordEntry[] {
  if (!existsSync(CONFIG_FILE)) return []
  try {
    const data = JSON.parse(readFileSync(CONFIG_FILE, 'utf-8'))
    return data.keywords || []
  } catch {
    return []
  }
}

function writeKeywords(keywords: KeywordEntry[]) {
  writeFileSync(CONFIG_FILE, JSON.stringify({ keywords }, null, 2), 'utf-8')
}

export async function GET() {
  return NextResponse.json({ keywords: readKeywords() })
}

export async function POST(req: NextRequest) {
  const { asin, keyword } = await req.json()
  if (!asin || !keyword) {
    return NextResponse.json({ error: 'asin and keyword required' }, { status: 400 })
  }
  const keywords = readKeywords()
  const exists = keywords.find(k => k.asin === asin && k.keyword === keyword)
  if (exists) {
    return NextResponse.json({ error: 'Already exists' }, { status: 409 })
  }
  keywords.push({ asin, keyword, addedAt: new Date().toISOString() })
  writeKeywords(keywords)
  return NextResponse.json({ success: true, keywords })
}

export async function DELETE(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const asin = searchParams.get('asin')
  const keyword = searchParams.get('keyword')
  if (!asin || !keyword) {
    return NextResponse.json({ error: 'asin and keyword required' }, { status: 400 })
  }
  const keywords = readKeywords().filter(k => !(k.asin === asin && k.keyword === keyword))
  writeKeywords(keywords)
  return NextResponse.json({ success: true, keywords })
}
