import { NextResponse } from 'next/server'
import { exec } from 'child_process'
import { promisify } from 'util'
import path from 'path'

const execAsync = promisify(exec)
const SP_API_PATH = path.resolve(require('os').homedir(), '.openclaw/skills/amazon-sp-api/index.js')

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const days = searchParams.get('days') || '7'

  try {
    const { stdout } = await execAsync(`node ${SP_API_PATH} orders --days ${days}`)
    const json = stdout.split('\n').filter(l => !l.startsWith('[dotenv')).join('\n')
    const data = JSON.parse(json)
    return NextResponse.json(data)
  } catch (err: unknown) {
    console.error('SP-API orders error:', err)
    return NextResponse.json({ orders: [], mock: true })
  }
}
