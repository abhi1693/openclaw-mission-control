import { NextResponse } from 'next/server'
import { spawn } from 'child_process'
import { join } from 'path'
import { readFileSync, writeFileSync, existsSync, statSync } from 'fs'

const SP_API_PATH = join(process.env.HOME || '', '.openclaw', 'skills', 'amazon-sp-api', 'index.js')
const CACHE_DIR   = join(process.env.HOME || '', '.openclaw', 'workspace', 'zoviro-mission-control')
const CACHE_TTL_MS = 10 * 60 * 1000 // 10 minutes

function cacheFile(days: number) {
  return join(CACHE_DIR, `.top-products-${days}d.json`)
}

function getCached(days: number): any | null {
  try {
    const f = cacheFile(days)
    if (!existsSync(f)) return null
    if (Date.now() - statSync(f).mtimeMs > CACHE_TTL_MS) return null
    return JSON.parse(readFileSync(f, 'utf-8'))
  } catch { return null }
}

function setCached(days: number, data: any) {
  try { writeFileSync(cacheFile(days), JSON.stringify(data)) } catch { /* ignore */ }
}

async function runSpApi(args: string[]): Promise<any> {
  return new Promise((resolve, reject) => {
    const home = process.env.HOME || require('os').homedir()
    const child = spawn('node', [SP_API_PATH, ...args], {
      env: { ...process.env, HOME: home, PATH: `/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${process.env.PATH || ''}` },
      cwd: join(home, '.openclaw', 'skills', 'amazon-sp-api'),
    })
    let stdout = ''
    let stderr = ''

    child.stdout?.on('data', (d: Buffer) => { stdout += d })
    child.stderr?.on('data', (d: Buffer) => { stderr += d })

    const timer = setTimeout(() => {
      child.kill('SIGTERM')
      reject(new Error('SP-API timeout (3 min)'))
    }, 180_000)

    child.on('close', (code) => {
      clearTimeout(timer)
      if (code !== 0 && !stdout) {
        reject(new Error(`SP-API error (code ${code}): ${stderr.slice(0, 500)}`))
        return
      }
      try {
        const parsed = JSON.parse(stdout)
        resolve(parsed)
      } catch {
        reject(new Error(`JSON parse failed. stdout=${stdout.slice(0, 300)} stderr=${stderr.slice(0, 300)}`))
      }
    })
  })
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const days  = parseInt(searchParams.get('days') || '14')
  const force = searchParams.get('refresh') === 'true'

  // Cache check
  if (!force) {
    const cached = getCached(days)
    if (cached) {
      return NextResponse.json({ ...cached, cached: true })
    }
  }

  try {
    const data = await runSpApi(['top-products', '--days', String(days)])

    if (data.error) {
      return NextResponse.json({ error: data.error }, { status: 500 })
    }

    const result = {
      period:          data.period,
      totalLineItems:  data.totalLineItems,
      uniqueProducts:  data.uniqueProducts,
      totalRevenue:    data.totalRevenue,
      totalQuantity:   data.totalQuantity,
      products:        (data.products || []).slice(0, 10),
      fetchedAt:       new Date().toISOString(),
    }

    setCached(days, result)
    return NextResponse.json(result)
  } catch (err) {
    // Return stale cache if available
    const stale = getCached(days)
    if (stale) {
      return NextResponse.json({ ...stale, cached: true, stale: true })
    }
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
