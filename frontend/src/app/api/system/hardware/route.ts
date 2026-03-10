import { NextResponse } from 'next/server'
import { exec } from 'child_process'
import { promisify } from 'util'

const execAsync = promisify(exec)

async function run(cmd: string): Promise<string> {
  try {
    // Ensure macOS system binaries are in PATH
    const { stdout } = await execAsync(cmd, {
      env: { ...process.env, PATH: `/usr/sbin:/usr/bin:/bin:/sbin:${process.env.PATH ?? ''}` }
    })
    return stdout.trim()
  } catch {
    return ''
  }
}

export async function GET() {
  try {
    const [cpuIntel, cpuApple, cores, memsize, vmStat, dfOut, uptime, osVer, model] = await Promise.all([
      run('sysctl -n machdep.cpu.brand_string'),
      run("system_profiler SPHardwareDataType | grep 'Chip:' | awk -F': ' '{print $2}'"),
      run('sysctl -n hw.logicalcpu'),
      run('sysctl -n hw.memsize'),
      run('vm_stat'),
      run('df -k /'),
      run('uptime'),
      run('sw_vers -productVersion'),
      run('sysctl -n hw.model'),
    ])
    const cpu = cpuIntel || cpuApple || 'Unknown'

    // RAM
    const ramTotal = Math.round(parseInt(memsize) / (1024 ** 3))
    const pageSize = 4096
    const pagesFree    = parseInt(vmStat.match(/Pages free:\s+(\d+)/)?.[1] ?? '0')
    const pagesInactive= parseInt(vmStat.match(/Pages inactive:\s+(\d+)/)?.[1] ?? '0')
    const ramFreeBytes = (pagesFree + pagesInactive) * pageSize
    const ramUsed = Math.max(0, ramTotal - Math.round(ramFreeBytes / (1024 ** 3)))
    const ramPct  = Math.round((ramUsed / ramTotal) * 100)

    // Disk
    const dfLines = dfOut.split('\n')
    const dfData  = dfLines[1]?.split(/\s+/) ?? []
    const diskTotal = dfData[1] ? Math.round(parseInt(dfData[1]) / (1024 ** 2)) : 0 // GB
    const diskUsed  = dfData[2] ? Math.round(parseInt(dfData[2]) / (1024 ** 2)) : 0
    const diskFree  = dfData[3] ? Math.round(parseInt(dfData[3]) / (1024 ** 2)) : 0
    const diskUsedPct = diskTotal > 0 ? Math.round((diskUsed / diskTotal) * 100) : 0

    // Uptime (parse "up X days, HH:MM" or "up HH:MM")
    const uptimeMatch = uptime.match(/up\s+(.*?),\s+\d+ user/)
    const uptimeStr   = uptimeMatch?.[1]?.trim() ?? uptime.split(',')[0]?.replace(/.*up\s+/, '') ?? '—'

    return NextResponse.json({
      cpu:        cpu  || 'Unknown',
      cores:      parseInt(cores) || 0,
      ramTotal,
      ramUsed,
      ramPct,
      diskTotal,
      diskUsed,
      diskFree,
      diskUsedPct,
      uptime:     uptimeStr,
      osVersion:  osVer  || 'Unknown',
      model:      model  || 'Unknown',
    })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
