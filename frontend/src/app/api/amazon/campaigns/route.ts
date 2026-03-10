import { NextResponse } from 'next/server'
import { exec } from 'child_process'
import { promisify } from 'util'
import path from 'path'

const execAsync = promisify(exec)
const GUARD_PATH = path.resolve(require('os').homedir(), '.openclaw/skills/amazon-advertising/guard.js')

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const type = searchParams.get('type') || 'sp'

  try {
    const { stdout, stderr } = await execAsync(
      `node ${GUARD_PATH} campaigns --type ${type}`,
      { timeout: 60000 }
    )
    // Filter out auth/log lines
    const lines = stdout.split('\n').filter(l =>
      !l.startsWith('[Auth]') && !l.startsWith('[dotenv') && l.trim()
    )
    const jsonStr = lines.join('\n')
    const data = JSON.parse(jsonStr)
    return NextResponse.json(data)
  } catch (err: unknown) {
    console.error('Campaigns API error:', err)
    return NextResponse.json({
      campaigns: [],
      count: 0,
      error: true,
      message: 'Amazon Advertising API 连接失败',
    }, { status: 503 })
  }
}
