import { NextRequest, NextResponse } from 'next/server'
import { existsSync, readFileSync, writeFileSync } from 'fs'
import { join } from 'path'
import { homedir } from 'os'

const PROMPTS_FILE = join(homedir(), '.openclaw', 'workspace', 'content', 'prompts.json')

interface PromptEntry {
  id: string
  asin: string
  productName: string
  type: string
  style: string
  tone: string
  platform: string
  extras: string
  geminiPrompt: string
  midjourneyPrompt: string
  starred: boolean
  createdAt: string
}

function readPrompts(): PromptEntry[] {
  if (!existsSync(PROMPTS_FILE)) return []
  try {
    return JSON.parse(readFileSync(PROMPTS_FILE, 'utf-8')) as PromptEntry[]
  } catch {
    return []
  }
}

function writePrompts(data: PromptEntry[]) {
  writeFileSync(PROMPTS_FILE, JSON.stringify(data, null, 2), 'utf-8')
}

// GET  → list all, supports ?starred=true
export async function GET(req: NextRequest) {
  const starredOnly = req.nextUrl.searchParams.get('starred') === 'true'
  let prompts = readPrompts()
  if (starredOnly) prompts = prompts.filter(p => p.starred)

  // Starred first
  prompts.sort((a, b) => {
    if (a.starred && !b.starred) return -1
    if (!a.starred && b.starred) return 1
    return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
  })

  return NextResponse.json({ prompts })
}

// POST  → create
export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    const prompts = readPrompts()
    const entry: PromptEntry = {
      id: `p_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
      starred: false,
      createdAt: new Date().toISOString(),
      ...body,
    }
    prompts.unshift(entry)
    writePrompts(prompts)
    return NextResponse.json({ prompt: entry })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}

// PATCH ?id=XXX  → update (toggle star etc.)
export async function PATCH(req: NextRequest) {
  const id = req.nextUrl.searchParams.get('id')
  if (!id) return NextResponse.json({ error: 'id required' }, { status: 400 })

  try {
    const updates = await req.json()
    const prompts = readPrompts()
    const idx = prompts.findIndex(p => p.id === id)
    if (idx === -1) return NextResponse.json({ error: 'Not found' }, { status: 404 })
    prompts[idx] = { ...prompts[idx], ...updates }
    writePrompts(prompts)
    return NextResponse.json({ prompt: prompts[idx] })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}

// DELETE ?id=XXX
export async function DELETE(req: NextRequest) {
  const id = req.nextUrl.searchParams.get('id')
  if (!id) return NextResponse.json({ error: 'id required' }, { status: 400 })

  const prompts = readPrompts()
  const filtered = prompts.filter(p => p.id !== id)
  if (filtered.length === prompts.length) {
    return NextResponse.json({ error: 'Not found' }, { status: 404 })
  }
  writePrompts(filtered)
  return NextResponse.json({ ok: true })
}
