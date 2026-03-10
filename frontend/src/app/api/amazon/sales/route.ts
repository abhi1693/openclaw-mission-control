import { NextResponse } from 'next/server'
import { exec } from 'child_process'
import { promisify } from 'util'
import path from 'path'

const execAsync = promisify(exec)
const SP_API_PATH = path.resolve(require('os').homedir(), '.openclaw/skills/amazon-sp-api/index.js')

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const days = searchParams.get('days') || '14'

  try {
    const { stdout } = await execAsync(`node ${SP_API_PATH} sales --days ${days}`, { timeout: 60000 })
    // Strip dotenv log lines (go to stderr but just in case)
    const json = stdout.split('\n').filter(l => !l.startsWith('[dotenv')).join('\n')
    const data = JSON.parse(json)
    return NextResponse.json({
      ...data,
      fetchedAt: data.fetchedAt ?? new Date().toISOString(),
    })
  } catch (err: unknown) {
    console.error('SP-API sales error:', err)
    return NextResponse.json({
      period: `Last ${days} days`,
      metrics: [],
      error: true,
      message: 'SP-API 连接失败，请检查凭证配置',
    }, { status: 503 })
  }
}
