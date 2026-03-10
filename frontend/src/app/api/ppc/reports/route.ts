/**
 * GET    /api/ppc/reports              — list all .md files
 * GET    /api/ppc/reports?file=<name>  — return content of a specific file
 * DELETE /api/ppc/reports?file=<name>  — delete a specific .md file
 *
 * Reads from: ~/.openclaw/workspace/reports/ppc/
 * Only .md files. JSON ai-insights live in skills/amazon-advertising/cache/
 * and are served by /api/ppc/ai-insights for the PPC page tab.
 */
import { NextResponse } from 'next/server'
import fs from 'fs'
import path from 'path'
import os from 'os'

const PPC_DIR = path.resolve(
  os.homedir(),
  '.openclaw/workspace/reports/ppc'
)

function ensureDir() {
  if (!fs.existsSync(PPC_DIR)) fs.mkdirSync(PPC_DIR, { recursive: true })
}

function parseFilename(filename: string) {
  const base = filename.replace('.md', '')
  const dateMatch = base.match(/(\d{4}-\d{2}-\d{2})$/)
  const date = dateMatch ? dateMatch[1] : ''
  const prefix = date ? base.slice(0, base.length - date.length - 1) : base
  return { prefix, date }
}

export async function GET(request: Request) {
  try {
    ensureDir()

    const { searchParams } = new URL(request.url)
    const file = searchParams.get('file')

    if (file) {
      const safeName = path.basename(file)
      if (!safeName.endsWith('.md')) {
        return NextResponse.json({ error: 'Only .md files allowed' }, { status: 400 })
      }
      const filePath = path.join(PPC_DIR, safeName)
      if (!fs.existsSync(filePath)) {
        return NextResponse.json({ error: 'File not found' }, { status: 404 })
      }
      const content = fs.readFileSync(filePath, 'utf-8')
      return NextResponse.json({ file: safeName, content })
    }

    const files = fs.readdirSync(PPC_DIR)
      .filter(f => f.endsWith('.md'))
      .map(f => {
        const stat = fs.statSync(path.join(PPC_DIR, f))
        const { prefix, date } = parseFilename(f)
        return {
          filename: f,
          prefix,
          date,
          sizeKb: Math.ceil(stat.size / 1024),
          modifiedAt: stat.mtime.toISOString(),
        }
      })
      .sort((a, b) => b.date.localeCompare(a.date) || b.modifiedAt.localeCompare(a.modifiedAt))

    return NextResponse.json({ reportsDir: PPC_DIR, count: files.length, files })
  } catch (e) {
    console.error('[ppc/reports]', e)
    return NextResponse.json({ error: 'Failed to read reports directory' }, { status: 500 })
  }
}

export async function DELETE(request: Request) {
  try {
    const { searchParams } = new URL(request.url)
    const file = searchParams.get('file')

    if (!file) {
      return NextResponse.json({ error: 'Missing file parameter' }, { status: 400 })
    }

    if (file.includes('..') || file.includes('/') || file.includes('\\')) {
      return NextResponse.json({ error: 'Invalid file path' }, { status: 400 })
    }
    const safeName = path.basename(file)
    if (!safeName.endsWith('.md')) {
      return NextResponse.json({ error: 'Only .md files allowed' }, { status: 400 })
    }

    const filePath = path.join(PPC_DIR, safeName)
    if (!fs.existsSync(filePath)) {
      return NextResponse.json({ error: 'File not found' }, { status: 404 })
    }

    fs.unlinkSync(filePath)
    return NextResponse.json({ deleted: safeName })
  } catch (e) {
    console.error('[ppc/reports DELETE]', e)
    return NextResponse.json({ error: 'Failed to delete file' }, { status: 500 })
  }
}
