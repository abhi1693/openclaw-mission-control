import { NextResponse } from 'next/server'

export async function GET() {
  try {
    const { mockContent } = await import('@/lib/mock/data')
    return NextResponse.json({ ...mockContent, demo: true })
  } catch (err) {
    return NextResponse.json({ error: 'Failed to fetch content' }, { status: 500 })
  }
}
