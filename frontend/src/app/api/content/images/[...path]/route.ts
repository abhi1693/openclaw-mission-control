import { NextRequest, NextResponse } from 'next/server'
import { existsSync, readFileSync } from 'fs'
import { join, extname } from 'path'
import { homedir } from 'os'

const IMAGES_BASE = join(homedir(), '.openclaw', 'workspace', 'content', 'product-images')

const MIME: Record<string, string> = {
  '.jpg':  'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png':  'image/png',
  '.webp': 'image/webp',
}

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params
  if (!path || path.length < 2) {
    return new NextResponse('Not found', { status: 404 })
  }

  // path[0] = asin, path[1] = filename
  const [asin, ...rest] = path
  const fileName = rest.join('/')

  // Prevent path traversal
  if (fileName.includes('..')) {
    return new NextResponse('Forbidden', { status: 403 })
  }

  const filePath = join(IMAGES_BASE, asin, fileName)
  if (!existsSync(filePath)) {
    return new NextResponse('Not found', { status: 404 })
  }

  const ext = extname(fileName).toLowerCase()
  const mimeType = MIME[ext] ?? 'application/octet-stream'
  const buffer = readFileSync(filePath)

  return new NextResponse(buffer, {
    headers: {
      'Content-Type': mimeType,
      'Cache-Control': 'public, max-age=3600',
    },
  })
}
