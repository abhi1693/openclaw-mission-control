import { NextRequest, NextResponse } from 'next/server'
import { existsSync, mkdirSync, writeFileSync, readdirSync, unlinkSync } from 'fs'
import { join, extname } from 'path'
import { homedir } from 'os'

const IMAGES_BASE = join(homedir(), '.openclaw', 'workspace', 'content', 'product-images')
const MAX_SIZE = 5 * 1024 * 1024 // 5 MB
const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/webp']

function asinDir(asin: string) {
  return join(IMAGES_BASE, asin)
}

// GET ?asin=XXX  →  list images
export async function GET(req: NextRequest) {
  const asin = req.nextUrl.searchParams.get('asin')
  if (!asin) return NextResponse.json({ error: 'asin required' }, { status: 400 })

  const dir = asinDir(asin)
  if (!existsSync(dir)) return NextResponse.json({ images: [] })

  const files = readdirSync(dir).filter(f => /\.(jpg|jpeg|png|webp)$/i.test(f))
  return NextResponse.json({
    images: files.map(f => ({ name: f, url: `/api/content/images/${asin}/${f}` })),
  })
}

// POST multipart/form-data  asin + file
export async function POST(req: NextRequest) {
  try {
    const formData = await req.formData()
    const asin = formData.get('asin') as string | null
    const file = formData.get('file') as File | null

    if (!asin || !file) {
      return NextResponse.json({ error: 'asin and file required' }, { status: 400 })
    }
    if (!ALLOWED_TYPES.includes(file.type)) {
      return NextResponse.json({ error: 'Only jpg, png, webp allowed' }, { status: 400 })
    }
    if (file.size > MAX_SIZE) {
      return NextResponse.json({ error: 'File too large (max 5 MB)' }, { status: 400 })
    }

    const dir = asinDir(asin)
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true })

    const ext = extname(file.name) || '.jpg'
    const safeName = file.name.replace(/[^a-zA-Z0-9._-]/g, '_')
    const fileName = `${Date.now()}-${safeName}`
    const filePath = join(dir, fileName)

    const buffer = Buffer.from(await file.arrayBuffer())
    writeFileSync(filePath, buffer)

    return NextResponse.json({
      name: fileName,
      url: `/api/content/images/${asin}/${fileName}`,
    })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}

// DELETE ?asin=XXX&file=YYY
export async function DELETE(req: NextRequest) {
  const asin = req.nextUrl.searchParams.get('asin')
  const file = req.nextUrl.searchParams.get('file')

  if (!asin || !file) return NextResponse.json({ error: 'asin and file required' }, { status: 400 })

  // Prevent path traversal
  if (file.includes('/') || file.includes('..')) {
    return NextResponse.json({ error: 'Invalid filename' }, { status: 400 })
  }

  const filePath = join(asinDir(asin), file)
  if (!existsSync(filePath)) return NextResponse.json({ error: 'Not found' }, { status: 404 })

  unlinkSync(filePath)
  return NextResponse.json({ ok: true })
}
