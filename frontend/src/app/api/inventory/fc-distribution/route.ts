import { NextResponse } from 'next/server'
import fs from 'fs'

// FC ID → city_state override mapping
const FC_CITY_OVERRIDES: Record<string, string> = {
  'HGR5': 'SHIPPENSBURG, PA',
}

export async function GET() {
  try {
    const fcPath = '/Users/zovirollc/.openclaw/skills/h10-browser/data/inventory/fc_distribution.json'
    const skuMapPath = '/Users/zovirollc/.openclaw/workspace/config/sku-asin-map.json'

    if (!fs.existsSync(fcPath)) {
      return NextResponse.json({ error: true, message: 'FC distribution data not found' }, { status: 404 })
    }

    const raw = JSON.parse(fs.readFileSync(fcPath, 'utf-8'))

    // Detect new format by checking for `summary` key (new) vs `account_summary` (old)
    const isNewFormat = raw.summary !== undefined && raw.account_summary === undefined

    // Optionally enrich with SKU map product names
    let skuMap: Record<string, string> = {}
    if (fs.existsSync(skuMapPath)) {
      const mapData = JSON.parse(fs.readFileSync(skuMapPath, 'utf-8'))
      if (mapData.by_sku) {
        for (const [sku, info] of Object.entries(mapData.by_sku as Record<string, any>)) {
          skuMap[sku] = (info as any).name
        }
      }
    }

    if (!isNewFormat) {
      // Old format — pass through with name enrichment
      if (raw.by_sku) {
        for (const [sku, info] of Object.entries(raw.by_sku as Record<string, any>)) {
          if (!(info as any).name && skuMap[sku]) {
            (info as any).name = skuMap[sku]
          }
        }
      }
      return NextResponse.json({ ...raw, sku_name_map: skuMap })
    }

    // ── New format → transform to legacy shape expected by the frontend ──────

    // Build balance_scores lookup: sku → { score, gap_regions }
    const balanceScores: Record<string, { score: number; gap_regions: string[] }> = {}
    if (Array.isArray(raw.balance_scores)) {
      for (const entry of raw.balance_scores as Array<{ sku: string; score: number; gap_regions: string[] }>) {
        balanceScores[entry.sku] = { score: entry.score, gap_regions: entry.gap_regions }
      }
    }

    // Count unique FCs across all SKUs (sum fc_count per SKU as proxy)
    let fcCount = 0
    if (raw.by_sku) {
      for (const info of Object.values(raw.by_sku as Record<string, any>)) {
        fcCount += (info as any).fc_count ?? 0
      }
    }

    // Transform account_summary
    const account_summary = {
      total_units: raw.summary.total_inventory ?? 0,
      total_sellable: raw.summary.total_sellable ?? 0,
      customer_damaged: raw.summary.total_customer_damaged ?? 0,
      defective: raw.summary.total_defective ?? 0,
      fc_count: fcCount,
      sku_count: raw.by_sku ? Object.keys(raw.by_sku).length : 0,
    }

    // Helper: compute pct of a region's units relative to SKU total sellable
    function regionPct(units: number, totalSellable: number): number {
      if (!totalSellable) return 0
      return Math.round((units / totalSellable) * 1000) / 10 // one decimal
    }

    // Transform by_sku
    const by_sku: Record<string, any> = {}
    if (raw.by_sku) {
      for (const [sku, info] of Object.entries(raw.by_sku as Record<string, any>)) {
        const rd = (info as any).region_distribution ?? {}
        const totalSellable = (info as any).total_sellable ?? 0
        const bs = balanceScores[sku] ?? { score: null, gap_regions: [] }

        by_sku[sku] = {
          asin: (info as any).asin,
          name: (info as any).name ?? skuMap[sku] ?? sku,
          total_sellable: totalSellable,
          total_damaged: (info as any).customer_damaged ?? 0,
          total_defective: (info as any).defective ?? 0,
          fc_count: (info as any).fc_count ?? 0,
          regions: {
            west:    { units: rd.West    ?? 0, fcs: [], pct: regionPct(rd.West    ?? 0, totalSellable) },
            south:   { units: rd.South   ?? 0, fcs: [], pct: regionPct(rd.South   ?? 0, totalSellable) },
            midwest: { units: rd.Midwest ?? 0, fcs: [], pct: regionPct(rd.Midwest ?? 0, totalSellable) },
            east:    { units: rd.East    ?? 0, fcs: [], pct: regionPct(rd.East    ?? 0, totalSellable) },
          },
          balance_score: bs.score,
          gap_regions: bs.gap_regions,
          ad_guidance: raw.ad_guidance?.[sku] ?? null,
        }
      }
    }

    // fc_details from raw_rows (per-FC row-level data) or fallback to region summaries
    const fc_details: any[] = []

    const stateToRegion: Record<string, string> = {
      WA:'west',OR:'west',CA:'west',NV:'west',AZ:'west',UT:'west',CO:'west',NM:'west',ID:'west',MT:'west',WY:'west',HI:'west',AK:'west',
      TX:'south',OK:'south',AR:'south',LA:'south',MS:'south',AL:'south',TN:'south',KY:'south',WV:'south',VA:'south',NC:'south',SC:'south',GA:'south',FL:'south',MD:'south',DE:'south',DC:'south',
      ND:'midwest',SD:'midwest',NE:'midwest',KS:'midwest',MN:'midwest',IA:'midwest',MO:'midwest',WI:'midwest',IL:'midwest',IN:'midwest',MI:'midwest',OH:'midwest',
      ME:'east',NH:'east',VT:'east',MA:'east',RI:'east',CT:'east',NY:'east',NJ:'east',PA:'east',
    }

    if (Array.isArray(raw.raw_rows) && raw.raw_rows.length > 0) {
      // Use actual per-FC row data
      const skuAsinMap = raw.sku_asin_mapping ?? {}
      for (const row of raw.raw_rows as Array<any>) {
        const cityState = row.city_state ?? ''
        const stateMatch = cityState.match(/,\s*([A-Z]{2})$/)
        const state = stateMatch ? stateMatch[1] : ''
        const city = cityState.replace(/,\s*[A-Z]{2}$/, '').trim()
        fc_details.push({
          fc_id: row.fc_id ?? '',
          city: city,
          state: state,
          region: stateToRegion[state] ?? 'unknown',
          sku: row.sku ?? '',
          asin: skuAsinMap[row.sku] ?? '',
          sellable: row.sellable ?? 0,
          customer_damaged: row.customer_damaged ?? 0,
          defective: row.defective ?? 0,
          total: row.total ?? 0,
        })
      }
    } else {
      // Fallback: generate region-level summary rows from by_sku
      const regionCities: Record<string, { city: string; state: string }> = {
        West: { city: 'Los Angeles', state: 'CA' },
        South: { city: 'Dallas', state: 'TX' },
        Midwest: { city: 'Chicago', state: 'IL' },
        East: { city: 'New York', state: 'NY' },
      }
      if (raw.by_sku) {
        for (const [sku, info] of Object.entries(raw.by_sku as Record<string, any>)) {
          const rd = (info as any).region_distribution ?? {}
          for (const [region, units] of Object.entries(rd as Record<string, number>)) {
            if (units > 0) {
              const loc = regionCities[region] ?? { city: 'Unknown', state: '??' }
              fc_details.push({
                fc_id: `${region.toUpperCase().substring(0, 4)}1`,
                city: loc.city, state: loc.state,
                region: region.toLowerCase(),
                sku, asin: (info as any).asin ?? '',
                sellable: units, customer_damaged: 0, defective: 0, total: units,
              })
            }
          }
        }
      }
    }

    // Apply FC city overrides for Unknown entries
    for (const fc of fc_details) {
      if (fc.city === 'Unknown' && FC_CITY_OVERRIDES[fc.fc_id]) {
        const override = FC_CITY_OVERRIDES[fc.fc_id]
        const match = override.match(/^([^,]+),\s*([A-Z]{2})$/)
        if (match) {
          fc.city = match[1].trim()
          fc.state = match[2]
          // Also recalculate region based on new state
          fc.region = stateToRegion[fc.state] ?? 'unknown'
        }
      }
    }

    // Recalculate by_sku region_distribution based on updated fc_details
    const newRegionDistribution: Record<string, Record<string, number>> = {}
    for (const fc of fc_details) {
      if (!fc.sku || fc.region === 'unknown') continue
      if (!newRegionDistribution[fc.sku]) {
        newRegionDistribution[fc.sku] = { West: 0, South: 0, Midwest: 0, East: 0 }
      }
      const regionKey = fc.region.charAt(0).toUpperCase() + fc.region.slice(1)
      if (regionKey in newRegionDistribution[fc.sku]) {
        newRegionDistribution[fc.sku][regionKey] += fc.sellable
      }
    }

    // Update by_sku with new region_distribution and recalc balance_score
    for (const [sku, info] of Object.entries(by_sku)) {
      const newRd = newRegionDistribution[sku]
      const totalSellable = info.total_sellable
      if (newRd) {
        info.regions = {
          west:    { units: newRd.West,    fcs: [], pct: regionPct(newRd.West,    totalSellable) },
          south:   { units: newRd.South,   fcs: [], pct: regionPct(newRd.South,   totalSellable) },
          midwest: { units: newRd.Midwest, fcs: [], pct: regionPct(newRd.Midwest, totalSellable) },
          east:    { units: newRd.East,    fcs: [], pct: regionPct(newRd.East,    totalSellable) },
        }
        // Recalculate balance_score based on new region_distribution
        const regions = [newRd.West, newRd.South, newRd.Midwest, newRd.East]
        const maxRegion = Math.max(...regions)
        const nonZeroRegions = regions.filter(r => r > 0)
        const minRegion = nonZeroRegions.length > 0 ? Math.min(...nonZeroRegions) : 0
        const score = totalSellable > 0 ? Math.round(((maxRegion - minRegion) / totalSellable) * 100) : 0
        info.balance_score = score
        // Gap regions are those with 0 units when other regions have units
        const hasAnyUnits = regions.some(r => r > 0)
        info.gap_regions = hasAnyUnits ? regions.map((r, i) => r === 0 ? ['west', 'south', 'midwest', 'east'][i] : null).filter(Boolean) : []
      }
    }

    const fcData = {
      updated: raw.extracted_at,
      source: raw.source ?? 'Helium 10 Inventory Heat Map',
      account_summary,
      by_sku,
      fc_details,
      sku_name_map: skuMap,
    }

    return NextResponse.json(fcData)
  } catch (err: any) {
    return NextResponse.json({ error: true, message: err.message }, { status: 500 })
  }
}
