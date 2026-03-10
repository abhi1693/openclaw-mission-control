'use client'

import { useState, useCallback, useMemo, useEffect } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip,
  Legend, ResponsiveContainer, PieChart, Pie, Cell,
} from 'recharts'
import { KpiCard } from '@/components/shared/KpiCard'
import {
  Package, TrendingUp, AlertTriangle, RefreshCw,
  Search, X, ChevronUp, ChevronDown, ArrowUpDown,
  Archive, Truck, BoxIcon, Activity, MapPin,
} from 'lucide-react'
import { cn } from '@/lib/utils'
// @ts-ignore
import { ComposableMap, Geographies, Geography, Marker } from 'react-simple-maps'

// ─── Types ────────────────────────────────────────────────────────────────────

interface InventoryItem {
  sku: string
  fnsku: string
  asin: string
  productName: string
  condition: string
  yourPrice: number
  afnListingExists: string
  afnWarehouseQuantity: number
  afnFulfillableQuantity: number
  afnUnsellableQuantity: number
  afnReservedQuantity: number
  afnTotalQuantity: number
  afnInboundWorkingQuantity: number
  afnInboundShippedQuantity: number
  afnInboundReceivingQuantity: number
  afnResearchingQuantity: number
  afnReservedFutureSupply: number
  afnFutureSupplyBuyable: number
  perUnitVolume: number
}

interface InventorySummary {
  totalFulfillable: number
  totalReserved: number
  totalUnsellable: number
  totalWarehouse: number
  totalInboundWorking: number
  totalInboundShipped: number
  totalInboundReceiving: number
  totalResearching: number
}

interface InventoryStatusData {
  reportType: string
  totalSkus: number
  summary: InventorySummary
  items: InventoryItem[]
  error?: boolean
  errorMessage?: string
  cachedAt?: string
  fromCache?: boolean
}

// ─── FC Distribution Types ────────────────────────────────────────────────────

interface FCAccountSummary {
  total_sellable: number
  customer_damaged: number
  defective: number
  total_units: number
  fc_count: number
  sku_count: number
}

interface FCSkuRegions {
  units: number
  fcs: string[]
  pct: number
}

interface FCSku {
  asin: string
  name: string
  total_sellable: number
  total_damaged: number
  total_defective: number
  fc_count: number
  regions: {
    west: FCSkuRegions
    south: FCSkuRegions
    midwest: FCSkuRegions
    east: FCSkuRegions
  }
  balance_score?: number
  gap_regions?: string[]
  ad_guidance?: Record<string, string[]>
}

interface FCDetail {
  fc_id: string
  city: string
  state: string
  region: string
  sku: string
  asin: string
  sellable: number
  customer_damaged: number
  defective: number
  total: number
}

interface FCDistributionData {
  updated: string
  source: string
  account_summary: FCAccountSummary
  by_sku: Record<string, FCSku>
  fc_details: FCDetail[]
  sku_name_map: Record<string, string>
  error?: boolean
  message?: string
}

// ─── Color tokens ─────────────────────────────────────────────────────────────

const COLORS = {
  fulfillable: 'hsl(142 71% 45%)',
  reserved:    'hsl(217 91% 60%)',
  unsellable:  'hsl(0 72% 51%)',
  inbound:     'hsl(45 93% 58%)',
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

// ─── Custom Tooltip for Stacked Bar ──────────────────────────────────────────

function BarTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ name: string; value: number; fill: string }>; label?: string }) {
  if (!active || !payload?.length) return null
  const total = payload.reduce((s, p) => s + p.value, 0)
  return (
    <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3 shadow-xl text-sm min-w-[160px]">
      <p className="font-semibold text-[hsl(var(--foreground))] mb-2 truncate max-w-[200px]">{label}</p>
      {payload.map(p => (
        <div key={p.name} className="flex justify-between gap-4 text-xs">
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-2 h-2 rounded-full" style={{ background: p.fill }} />
            <span className="text-[hsl(var(--muted-foreground))]">{p.name}</span>
          </span>
          <span className="font-medium text-[hsl(var(--foreground))]">{fmtNum(p.value)}</span>
        </div>
      ))}
      <div className="border-t border-[hsl(var(--border))] mt-2 pt-1.5 flex justify-between text-xs font-semibold">
        <span className="text-[hsl(var(--muted-foreground))]">Total</span>
        <span className="text-[hsl(var(--foreground))]">{fmtNum(total)}</span>
      </div>
    </div>
  )
}

// ─── Custom Tooltip for Pie ───────────────────────────────────────────────────

function PieTooltip({ active, payload }: { active?: boolean; payload?: Array<{ name: string; value: number; payload: { fill: string } }> }) {
  if (!active || !payload?.length) return null
  const item = payload[0]
  return (
    <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3 shadow-xl text-sm">
      <div className="flex items-center gap-2">
        <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: item.payload.fill }} />
        <span className="font-medium text-[hsl(var(--foreground))]">{item.name}</span>
      </div>
      <p className="text-xl font-bold text-[hsl(var(--foreground))] mt-1">{fmtNum(item.value)}</p>
    </div>
  )
}

// ─── Inbound Pipeline ─────────────────────────────────────────────────────────

function InboundPipeline({ summary }: { summary: InventorySummary }) {
  const stages = [
    {
      label: 'Working',
      sub: '已下单待发货',
      value: summary.totalInboundWorking,
      icon: <BoxIcon className="w-5 h-5" />,
      color: 'hsl(217 91% 60%)',
    },
    {
      label: 'Shipped',
      sub: '在途运输中',
      value: summary.totalInboundShipped,
      icon: <Truck className="w-5 h-5" />,
      color: 'hsl(45 93% 58%)',
    },
    {
      label: 'Receiving',
      sub: '仓库收货中',
      value: summary.totalInboundReceiving,
      icon: <Archive className="w-5 h-5" />,
      color: COLORS.fulfillable,
    },
  ]
  const total = stages.reduce((s, st) => s + st.value, 0)

  return (
    <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
      <div className="px-4 py-3 border-b border-[hsl(var(--border))]">
        <h3 className="text-sm font-semibold text-[hsl(var(--foreground))]">Inbound Pipeline</h3>
        <p className="text-xs text-[hsl(var(--muted-foreground))] mt-0.5">入库进度 — Working → Shipped → Receiving</p>
      </div>
      <div className="p-4">
        <div className="flex items-stretch gap-0">
          {stages.map((stage, i) => (
            <div key={stage.label} className="flex items-stretch gap-0 flex-1">
              {/* Stage card */}
              <div className="flex-1 rounded-xl p-4 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] text-center">
                <div
                  className="w-10 h-10 rounded-xl mx-auto mb-3 flex items-center justify-center"
                  style={{ background: `${stage.color}20`, color: stage.color }}
                >
                  {stage.icon}
                </div>
                <p className="text-2xl font-bold text-[hsl(var(--foreground))]">{fmtNum(stage.value)}</p>
                <p className="text-sm font-medium text-[hsl(var(--foreground))] mt-0.5">{stage.label}</p>
                <p className="text-[10px] text-[hsl(var(--muted-foreground))] mt-0.5">{stage.sub}</p>
                {total > 0 && (
                  <div className="mt-2 text-xs" style={{ color: stage.color }}>
                    {((stage.value / total) * 100).toFixed(0)}%
                  </div>
                )}
              </div>
              {/* Arrow connector */}
              {i < stages.length - 1 && (
                <div className="flex items-center px-2 text-[hsl(var(--muted-foreground))] text-xl font-thin">
                  →
                </div>
              )}
            </div>
          ))}
        </div>
        {/* Progress bar */}
        {total > 0 && (
          <div className="mt-4 h-2 rounded-full overflow-hidden bg-[hsl(var(--secondary))] flex">
            {stages.map(stage => (
              <div
                key={stage.label}
                className="h-full transition-all"
                style={{
                  width: `${(stage.value / total) * 100}%`,
                  background: stage.color,
                }}
              />
            ))}
          </div>
        )}
        {total === 0 && (
          <p className="text-center text-xs text-[hsl(var(--muted-foreground))] mt-3">No inbound shipments</p>
        )}
      </div>
    </div>
  )
}

// ─── SKU Detail Table ─────────────────────────────────────────────────────────

type SortKey = keyof InventoryItem
type SortDir = 'asc' | 'desc'

function SkuDetailTable({ items }: { items: InventoryItem[] }) {
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('afnFulfillableQuantity')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [expanded, setExpanded] = useState(false)

  const filtered = useMemo(() => {
    const q = search.toLowerCase()
    return items.filter(
      i =>
        !q ||
        i.sku.toLowerCase().includes(q) ||
        i.asin.toLowerCase().includes(q) ||
        i.productName.toLowerCase().includes(q)
    )
  }, [items, search])

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      const av = a[sortKey]
      const bv = b[sortKey]
      if (typeof av === 'number' && typeof bv === 'number') {
        return sortDir === 'asc' ? av - bv : bv - av
      }
      return sortDir === 'asc'
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av))
    })
  }, [filtered, sortKey, sortDir])

  const rows = expanded ? sorted : sorted.slice(0, 10)

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const SortIcon = ({ col }: { col: SortKey }) => {
    if (sortKey !== col) return <ArrowUpDown className="w-3 h-3 opacity-40" />
    return sortDir === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />
  }

  const Th = ({ col, label, right }: { col: SortKey; label: string; right?: boolean }) => (
    <th
      className={cn(
        'px-3 py-2 font-medium cursor-pointer hover:text-[hsl(var(--foreground))] transition-colors select-none',
        right ? 'text-right' : 'text-left'
      )}
      onClick={() => handleSort(col)}
    >
      <span className={cn('flex items-center gap-1', right && 'justify-end')}>
        {label} <SortIcon col={col} />
      </span>
    </th>
  )

  return (
    <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
      <div className="px-4 py-3 border-b border-[hsl(var(--border))] flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-sm font-semibold text-[hsl(var(--foreground))]">SKU 明细表</h3>
          <p className="text-xs text-[hsl(var(--muted-foreground))] mt-0.5">
            {filtered.length} / {items.length} SKUs
          </p>
        </div>
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[hsl(var(--muted-foreground))]" />
          <input
            type="text"
            placeholder="Search SKU / ASIN / name…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="pl-8 pr-8 py-1.5 text-sm bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg w-56 focus:outline-none focus:ring-1 focus:ring-[hsl(var(--primary)/0.5)] text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))]"
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
            >
              <X className="w-3 h-3" />
            </button>
          )}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] text-xs uppercase tracking-wide">
              <th className="px-3 py-2 text-left font-medium">#</th>
              <Th col="sku" label="SKU / ASIN" />
              <Th col="productName" label="Product" />
              <Th col="yourPrice" label="Price" right />
              <Th col="afnFulfillableQuantity" label="Fulfillable" right />
              <Th col="afnReservedQuantity" label="Reserved" right />
              <Th col="afnUnsellableQuantity" label="Unsellable" right />
              <Th col="afnTotalQuantity" label="Total" right />
              <Th col="afnInboundWorkingQuantity" label="Working" right />
              <Th col="afnInboundShippedQuantity" label="Shipped" right />
              <Th col="afnInboundReceivingQuantity" label="Receiving" right />
              <Th col="afnResearchingQuantity" label="Research" right />
            </tr>
          </thead>
          <tbody>
            {rows.map((item, i) => (
              <tr
                key={item.sku || item.asin}
                className="border-b border-[hsl(var(--border)/0.5)] hover:bg-[hsl(var(--secondary))] transition-colors"
              >
                <td className="px-3 py-2.5 text-xs text-[hsl(var(--muted-foreground))]">{i + 1}</td>
                <td className="px-3 py-2.5">
                  <p className="font-mono text-xs font-semibold text-[hsl(var(--foreground))] leading-tight">{item.sku || '—'}</p>
                  {item.asin && (
                    <p className="text-[10px] text-[hsl(var(--muted-foreground))] mt-0.5">{item.asin}</p>
                  )}
                  {item.condition && item.condition !== 'NewItem' && (
                    <span className="text-[9px] px-1 rounded bg-[hsl(var(--secondary))] text-[hsl(var(--muted-foreground))]">
                      {item.condition}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2.5 text-xs text-[hsl(var(--muted-foreground))] max-w-[160px]">
                  <p className="truncate" title={item.productName}>{item.productName || '—'}</p>
                </td>
                <td className="px-3 py-2.5 text-right text-xs text-[hsl(var(--foreground))]">
                  {item.yourPrice > 0 ? `$${item.yourPrice.toFixed(2)}` : '—'}
                </td>
                <NumCell value={item.afnFulfillableQuantity} color={COLORS.fulfillable} />
                <NumCell value={item.afnReservedQuantity}    color={COLORS.reserved} />
                <NumCell value={item.afnUnsellableQuantity}  color={COLORS.unsellable} />
                <NumCell value={item.afnTotalQuantity} bold />
                <NumCell value={item.afnInboundWorkingQuantity}   color={COLORS.inbound} dim />
                <NumCell value={item.afnInboundShippedQuantity}   color={COLORS.inbound} dim />
                <NumCell value={item.afnInboundReceivingQuantity} color={COLORS.inbound} dim />
                <NumCell value={item.afnResearchingQuantity} dim />
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={12} className="px-4 py-8 text-center text-sm text-[hsl(var(--muted-foreground))]">
                  No matching SKUs
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {sorted.length > 10 && (
        <button
          onClick={() => setExpanded(e => !e)}
          className="w-full flex items-center justify-center gap-1.5 py-2.5 text-xs text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:bg-[hsl(var(--secondary))] transition-all"
        >
          {expanded
            ? <><ChevronUp className="w-3.5 h-3.5" /> Show less</>
            : <><ChevronDown className="w-3.5 h-3.5" /> Show all {sorted.length} SKUs</>}
        </button>
      )}
    </div>
  )
}

function NumCell({
  value, color, bold, dim,
}: {
  value: number
  color?: string
  bold?: boolean
  dim?: boolean
}) {
  if (value === 0) {
    return (
      <td className="px-3 py-2.5 text-right text-xs text-[hsl(var(--muted-foreground))] opacity-30">—</td>
    )
  }
  return (
    <td
      className={cn(
        'px-3 py-2.5 text-right text-xs tabular-nums',
        bold && 'font-semibold',
        dim && 'opacity-70'
      )}
      style={{ color: color || 'hsl(var(--foreground))' }}
    >
      {fmtNum(value)}
    </td>
  )
}

// ─── Filter Bar ───────────────────────────────────────────────────────────────

function FilterBar({
  skuFilter, asinFilter, onSkuChange, onAsinChange, onApply, onClear, loading,
}: {
  skuFilter: string; asinFilter: string
  onSkuChange: (v: string) => void
  onAsinChange: (v: string) => void
  onApply: () => void
  onClear: () => void
  loading: boolean
}) {
  const hasFilter = skuFilter.trim() || asinFilter.trim()
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[hsl(var(--muted-foreground))]" />
        <input
          type="text"
          placeholder="Filter by SKU…"
          value={skuFilter}
          onChange={e => onSkuChange(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && onApply()}
          className="pl-8 pr-3 py-1.5 text-sm bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg w-40 focus:outline-none focus:ring-1 focus:ring-[hsl(var(--primary)/0.5)] text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))]"
        />
      </div>
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[hsl(var(--muted-foreground))]" />
        <input
          type="text"
          placeholder="Filter by ASIN…"
          value={asinFilter}
          onChange={e => onAsinChange(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && onApply()}
          className="pl-8 pr-3 py-1.5 text-sm bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg w-40 focus:outline-none focus:ring-1 focus:ring-[hsl(var(--primary)/0.5)] text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))]"
        />
      </div>
      <button
        onClick={onApply}
        disabled={loading}
        className="px-3 py-1.5 text-sm font-medium bg-[hsl(var(--primary))] text-black rounded-lg hover:opacity-90 disabled:opacity-50 transition-all"
      >
        {loading ? 'Loading…' : 'Apply'}
      </button>
      {hasFilter && (
        <button
          onClick={onClear}
          className="flex items-center gap-1 px-2.5 py-1.5 text-sm text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] rounded-lg hover:bg-[hsl(var(--secondary))] transition-all"
        >
          <X className="w-3 h-3" /> Clear
        </button>
      )}
    </div>
  )
}

// ─── Cache time helper ────────────────────────────────────────────────────────

function formatCacheAge(cachedAt: string): string {
  const diffMs = Date.now() - new Date(cachedAt).getTime()
  const mins = Math.floor(diffMs / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  const hrs = Math.floor(mins / 60)
  return `${hrs} 小时前`
}

// ─── FC Region Colors ─────────────────────────────────────────────────────────
const FC_REGION_COLORS = {
  west:    '#3B82F6',
  south:   '#F97316',
  midwest: '#22C55E',
  east:    '#A855F7',
} as const

// ─── Amazon FC City → Coordinates lookup ─────────────────────────────────────
const CITY_COORDS: Record<string, [number, number]> = {
  // West
  'Las Vegas':        [-115.1398, 36.1699],
  'Phoenix':          [-112.0740, 33.4484],
  'Tucson':           [-110.9747, 32.2226],
  'Reno':             [-119.8138, 39.5296],
  'Sacramento':       [-121.4944, 38.5816],
  'Los Angeles':      [-118.2437, 34.0522],
  'Long Beach':       [-118.1937, 33.7701],
  'San Bernardino':   [-117.2898, 34.1083],
  'Ontario':          [-117.6509, 34.0633],
  'Riverside':        [-117.3961, 33.9806],
  'San Diego':        [-117.1611, 32.7157],
  'Fresno':           [-119.7871, 36.7378],
  'Stockton':         [-121.2908, 37.9577],
  'Tracy':            [-121.4397, 37.7397],
  'Oakland':          [-122.2712, 37.8044],
  'San Jose':         [-121.8863, 37.3382],
  'Seattle':          [-122.3321, 47.6062],
  'Tacoma':           [-122.4443, 47.2529],
  'Spokane':          [-117.4260, 47.6588],
  'Portland':         [-122.6765, 45.5231],
  'Salt Lake City':   [-111.8910, 40.7608],
  'Denver':           [-104.9903, 39.7392],
  'Colorado Springs': [-104.8214, 38.8339],
  'Boise':            [-116.2023, 43.6150],
  'Albuquerque':      [-106.6504, 35.0844],
  'El Paso':          [-106.4850, 31.7619],
  'Palm Springs':     [-116.5453, 33.8303],
  // South
  'Dallas':           [-96.7970, 32.7767],
  'Fort Worth':       [-97.3308, 32.7555],
  'Houston':          [-95.3698, 29.7604],
  'San Antonio':      [-98.4936, 29.4241],
  'Austin':           [-97.7431, 30.2672],
  'Oklahoma City':    [-97.5164, 35.4676],
  'Tulsa':            [-95.9928, 36.1540],
  'New Orleans':      [-90.0715, 29.9511],
  'Memphis':          [-90.0490, 35.1495],
  'Nashville':        [-86.7816, 36.1627],
  'Atlanta':          [-84.3880, 33.7490],
  'Charlotte':        [-80.8431, 35.2271],
  'Raleigh':          [-78.6382, 35.7796],
  'Richmond':         [-77.4360, 37.5407],
  'Jacksonville':     [-81.6557, 30.3322],
  'Tampa':            [-82.4572, 27.9506],
  'Miami':            [-80.1918, 25.7617],
  'Orlando':          [-81.3792, 28.5383],
  'Savannah':         [-81.0998, 32.0835],
  'Columbia':         [-81.0348, 34.0007],
  'Lexington':        [-84.5037, 38.0406],
  'Louisville':       [-85.7585, 38.2527],
  'Birmingham':       [-86.8025, 33.5186],
  'Jackson':          [-90.1848, 32.2988],
  'Little Rock':      [-92.2896, 34.7465],
  'Knoxville':        [-83.9207, 35.9606],
  'Rockford':         [-89.0940, 42.2711],
  'Montgomery':       [-86.2999, 32.3617],
  'Murfreesboro':     [-86.3900, 35.8456],
  'Dca':              [-77.0377, 38.8512],
  'Philadelphia':     [-75.1652, 39.9526],
  // Midwest
  'Chicago':          [-87.6298, 41.8781],
  'Indianapolis':     [-86.1581, 39.7684],
  'Columbus':         [-82.9988, 39.9612],
  'Cleveland':        [-81.6944, 41.4993],
  'Cincinnati':       [-84.5120, 39.1031],
  'Detroit':          [-83.0458, 42.3314],
  'St. Louis':        [-90.1994, 38.6270],
  'Kansas City':      [-94.5786, 39.0997],
  'Minneapolis':      [-93.2650, 44.9778],
  'Milwaukee':        [-87.9065, 43.0389],
  'Omaha':            [-95.9345, 41.2565],
  'Des Moines':       [-93.6091, 41.5868],
  'Dayton':           [-84.1916, 39.7589],
  'Joliet':           [-88.0817, 41.5250],
  'Waukegan':         [-87.8448, 42.3636],
  'Kenosha':          [-87.8212, 42.5847],
  'Edwardsville':     [-89.9534, 38.8114],
  'Jeffersonville':   [-85.7369, 38.2778],
  'Portage':          [-87.1764, 41.5800],
  'Whitestown':       [-86.3453, 40.0823],
  'Etna':             [-82.6854, 40.0062],
  'Twinsburg':        [-81.4412, 41.3123],
  'North Randall':    [-81.5270, 41.4373],
  'Euclid':           [-81.5262, 41.5931],
  'Rossford':         [-83.5652, 41.6076],
  'Romulus':          [-83.3960, 42.2223],
  'Hazelwood':        [-90.3676, 38.7714],
  // East
  'New York':         [-74.0060, 40.7128],
  'Newark':           [-74.1724, 40.7357],
  'Jersey City':      [-74.0776, 40.7178],
  'Baltimore':        [-76.6122, 39.2904],
  'Boston':           [-71.0589, 42.3601],
  'Providence':       [-71.4128, 41.8240],
  'Hartford':         [-72.6851, 41.7637],
  'Albany':           [-73.7562, 42.6526],
  'Buffalo':          [-78.8784, 42.8864],
  'Pittsburgh':       [-79.9959, 40.4406],
  'Allentown':        [-75.4902, 40.6023],
  'Robbinsville':     [-74.6171, 40.2207],
  'Staten Island':    [-74.1502, 40.5795],
  'Shippensburg':     [-77.5236, 40.0510],
  'Avenel':           [-74.2771, 40.5762],
  'Carteret':         [-74.2282, 40.5776],
  'Linden':           [-74.2446, 40.6220],
  'Woodbridge':       [-74.2843, 40.5573],
  'Breinigsville':    [-75.6096, 40.5451],
  'Carlisle':         [-77.1886, 40.2015],
  'Hazleton':         [-75.9746, 40.9584],
  'Bethlehem':        [-75.3705, 40.6259],
  'Eddystone':        [-75.3407, 39.8590],
  'Windsor':          [-72.6437, 41.8526],
  'Cromwell':         [-72.6454, 41.5973],
  'Middletown':       [-72.6506, 41.5623],
  'Fall River':       [-71.1550, 41.7015],
  'North Haven':      [-72.8590, 41.3912],
}

function normCity(city: string): string {
  return city.trim()
    .split(' ')
    .map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(' ')
}

function getFCCoords(city: string): [number, number] | null {
  const norm = normCity(city)
  return CITY_COORDS[norm] ?? null
}

function logScale(value: number, minVal: number, maxVal: number, minSize: number, maxSize: number): number {
  if (value <= 0) return minSize
  const logMin = Math.log1p(minVal)
  const logMax = Math.log1p(maxVal)
  const logVal = Math.log1p(value)
  if (logMax === logMin) return (minSize + maxSize) / 2
  return minSize + ((logVal - logMin) / (logMax - logMin)) * (maxSize - minSize)
}

interface TooltipState {
  x: number
  y: number
  fc: FCDetail
  productName: string
}

function USFCMap({ fcDetails, bySkuMap, skuFilter }: {
  fcDetails: FCDetail[]
  bySkuMap: Record<string, FCSku>
  skuFilter: string
}) {
  const [tooltip, setTooltip] = useState<TooltipState | null>(null)

  const filteredDetails = useMemo(() => {
    if (skuFilter === 'all') return fcDetails
    return fcDetails.filter(fc => fc.sku === skuFilter)
  }, [fcDetails, skuFilter])

  const mapPoints = useMemo(() => {
    return filteredDetails
      .map(fc => {
        const coords = getFCCoords(fc.city)
        if (!coords) return null
        return { fc, coords }
      })
      .filter(Boolean) as Array<{ fc: FCDetail; coords: [number, number] }>
  }, [filteredDetails])

  const sellableValues = mapPoints.map(p => p.fc.sellable)
  const minSellable = Math.min(...sellableValues, 0)
  const maxSellable = Math.max(...sellableValues, 1)
  const unknownCount = filteredDetails.length - mapPoints.length

  return (
    <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
      <div className="px-4 py-3 border-b border-[hsl(var(--border))] flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-[hsl(var(--foreground))]">🗺️ FC Geographic Distribution</h3>
          <p className="text-xs text-[hsl(var(--muted-foreground))] mt-0.5">
            {mapPoints.length} FCs mapped · {unknownCount > 0 ? `${unknownCount} unknown locations (see table)` : 'all locations resolved'}
          </p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          {(Object.entries(FC_REGION_COLORS) as [string, string][]).map(([region, color]) => (
            <div key={region} className="flex items-center gap-1.5 text-xs text-[hsl(var(--muted-foreground))]">
              <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: color }} />
              {region.charAt(0).toUpperCase() + region.slice(1)}
            </div>
          ))}
        </div>
      </div>
      <div className="relative" style={{ height: 420 }}>
        <ComposableMap
          projection="geoAlbersUsa"
          style={{ width: '100%', height: '100%' }}
        >
          <Geographies geography={"https://cdn.jsdelivr.net/npm/us-atlas@3/states-10m.json" as string}>
            {({ geographies }: { geographies: any[] }) =>
              geographies.map((geo: any) => (
                <Geography
                  key={geo.rsmKey}
                  geography={geo}
                  fill="#1e2535"
                  stroke="#2d3748"
                  strokeWidth={0.5}
                  style={{
                    default: { outline: 'none' },
                    hover: { outline: 'none', fill: '#252d40' },
                    pressed: { outline: 'none' },
                  }}
                />
              ))
            }
          </Geographies>
          {mapPoints.map(({ fc, coords }, idx) => {
            const r = logScale(fc.sellable, minSellable, maxSellable, 4, 22)
            const color = FC_REGION_COLORS[fc.region as keyof typeof FC_REGION_COLORS] ?? '#94a3b8'
            return (
              <Marker key={`${fc.fc_id}-${idx}`} coordinates={coords}>
                <circle
                  r={r}
                  fill={color}
                  fillOpacity={0.75}
                  stroke={color}
                  strokeWidth={1}
                  strokeOpacity={0.9}
                  style={{ cursor: 'pointer' }}
                  onMouseEnter={(e: React.MouseEvent<SVGCircleElement>) => {
                    const svgEl = (e.target as Element).closest('svg')
                    const svgRect = svgEl?.getBoundingClientRect()
                    const rect = (e.target as Element).getBoundingClientRect()
                    setTooltip({
                      x: rect.left - (svgRect?.left ?? 0) + rect.width / 2,
                      y: rect.top - (svgRect?.top ?? 0),
                      fc,
                      productName: bySkuMap[fc.sku]?.name ?? fc.sku,
                    })
                  }}
                  onMouseLeave={() => setTooltip(null)}
                />
              </Marker>
            )
          })}
        </ComposableMap>
        {tooltip && (
          <div
            className="absolute z-10 pointer-events-none rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] shadow-xl p-3 text-xs min-w-[180px]"
            style={{ left: tooltip.x + 8, top: tooltip.y - 8, transform: 'translateY(-100%)' }}
          >
            <p className="font-semibold text-[hsl(var(--foreground))] mb-1">{tooltip.fc.fc_id}</p>
            <p className="text-[hsl(var(--muted-foreground))]">{tooltip.fc.city}, {tooltip.fc.state}</p>
            <p className="text-[hsl(var(--muted-foreground))] capitalize">{tooltip.fc.region} region</p>
            <div className="border-t border-[hsl(var(--border))] mt-2 pt-1.5 space-y-0.5">
              <div className="flex justify-between gap-4">
                <span className="text-[hsl(var(--muted-foreground))]">Sellable</span>
                <span className="font-medium text-[hsl(var(--foreground))]">{tooltip.fc.sellable}</span>
              </div>
              {tooltip.fc.customer_damaged > 0 && (
                <div className="flex justify-between gap-4">
                  <span className="text-[hsl(var(--muted-foreground))]">Damaged</span>
                  <span className="font-medium text-orange-400">{tooltip.fc.customer_damaged}</span>
                </div>
              )}
              <div className="flex justify-between gap-4">
                <span className="text-[hsl(var(--muted-foreground))]">SKU</span>
                <span className="font-mono text-[hsl(var(--foreground))] text-[10px]">{tooltip.fc.sku}</span>
              </div>
            </div>
            <p className="text-[10px] text-[hsl(var(--muted-foreground))] mt-1.5 max-w-[200px] truncate" title={tooltip.productName}>
              {tooltip.productName}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── FCRegionDashboard ────────────────────────────────────────────────────────

type RegionKey = 'west' | 'south' | 'midwest' | 'east'

const REGION_LABELS: Record<RegionKey, string> = {
  west: 'West', south: 'South', midwest: 'Midwest', east: 'East',
}

const AD_GUIDANCE_ICONS: Record<string, string> = {
  increase: '🟢',
  maintain: '🟡',
  reduce:   '🔴',
}

function FCRegionDashboard({ bySku, fcDetails, skuFilter }: {
  bySku: Record<string, FCSku>
  fcDetails: FCDetail[]
  skuFilter: string
}) {
  const [tableSearch, setTableSearch] = useState('')
  const [tableSortKey, setTableSortKey] = useState<keyof FCDetail>('sellable')
  const [tableSortDir, setTableSortDir] = useState<'asc' | 'desc'>('desc')
  const [regionFilter, setRegionFilter] = useState<string>('all')

  const regionChartData = useMemo((): Array<{ region: string; units: number; pct: number; color: string }> => {
    const regions: RegionKey[] = ['west', 'south', 'midwest', 'east']
    if (skuFilter !== 'all' && bySku[skuFilter]) {
      const skuData = bySku[skuFilter]
      return regions.map(r => ({
        region: REGION_LABELS[r],
        units: skuData.regions[r]?.units ?? 0,
        pct: skuData.regions[r]?.pct ?? 0,
        color: FC_REGION_COLORS[r],
      }))
    }
    const totals: Record<RegionKey, number> = { west: 0, south: 0, midwest: 0, east: 0 }
    Object.values(bySku).forEach(sku => {
      regions.forEach(r => { totals[r] += sku.regions[r]?.units ?? 0 })
    })
    const total = Object.values(totals).reduce((s, v) => s + v, 0)
    return regions.map(r => ({
      region: REGION_LABELS[r],
      units: totals[r],
      pct: total > 0 ? Math.round((totals[r] / total) * 1000) / 10 : 0,
      color: FC_REGION_COLORS[r],
    }))
  }, [bySku, skuFilter])

  const skuMeta = skuFilter !== 'all' ? bySku[skuFilter] : null

  const filteredFcDetails = useMemo(() => {
    let rows = skuFilter !== 'all'
      ? fcDetails.filter(fc => fc.sku === skuFilter)
      : fcDetails
    if (regionFilter !== 'all') rows = rows.filter(fc => fc.region === regionFilter)
    const q = tableSearch.toLowerCase()
    if (q) {
      rows = rows.filter(fc =>
        fc.fc_id.toLowerCase().includes(q) ||
        fc.city.toLowerCase().includes(q) ||
        fc.sku.toLowerCase().includes(q)
      )
    }
    return [...rows].sort((a, b) => {
      const av = a[tableSortKey]
      const bv = b[tableSortKey]
      if (typeof av === 'number' && typeof bv === 'number') {
        return tableSortDir === 'asc' ? av - bv : bv - av
      }
      return tableSortDir === 'asc'
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av))
    })
  }, [fcDetails, skuFilter, regionFilter, tableSearch, tableSortKey, tableSortDir])

  const handleTableSort = (key: keyof FCDetail) => {
    if (tableSortKey === key) setTableSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setTableSortKey(key); setTableSortDir('desc') }
  }

  const totalForDonut = regionChartData.reduce((s, d) => s + d.units, 0)

  return (
    <div className="space-y-6">
      {/* ── Region Balance Dashboard ── */}
      <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
        <div className="px-4 py-3 border-b border-[hsl(var(--border))] flex items-center justify-between flex-wrap gap-2">
          <div>
            <h3 className="text-sm font-semibold text-[hsl(var(--foreground))]">📊 Region Balance Dashboard</h3>
            <p className="text-xs text-[hsl(var(--muted-foreground))] mt-0.5">
              {skuFilter === 'all' ? '所有 SKU 区域分布' : `SKU: ${skuFilter}`}
            </p>
          </div>
          {skuMeta && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-[hsl(var(--muted-foreground))]">Balance Score:</span>
              <span className={cn(
                'text-sm font-bold px-2 py-0.5 rounded-lg',
                (skuMeta.balance_score ?? 0) >= 80 ? 'bg-green-500/20 text-green-400' :
                (skuMeta.balance_score ?? 0) >= 60 ? 'bg-yellow-500/20 text-yellow-400' :
                'bg-red-500/20 text-red-400'
              )}>
                {skuMeta.balance_score ?? '—'}
              </span>
            </div>
          )}
        </div>
        <div className="p-4 grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Donut chart */}
          <div className="flex flex-col items-center">
            <p className="text-xs text-[hsl(var(--muted-foreground))] mb-2">区域占比</p>
            <div className="relative" style={{ height: 220 }}>
              <ResponsiveContainer width={220} height={220}>
                <PieChart>
                  <Pie
                    data={regionChartData}
                    cx="50%"
                    cy="50%"
                    innerRadius={65}
                    outerRadius={95}
                    paddingAngle={2}
                    dataKey="units"
                    nameKey="region"
                  >
                    {regionChartData.map((entry, i) => (
                      <Cell key={i} fill={entry.color} stroke="transparent" />
                    ))}
                  </Pie>
                  <RechartsTooltip
                    contentStyle={{
                      background: 'hsl(var(--card))',
                      border: '1px solid hsl(var(--border))',
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
              {skuMeta?.balance_score != null && (
                <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                  <span className="text-2xl font-bold text-[hsl(var(--foreground))]">{skuMeta.balance_score}</span>
                  <span className="text-[10px] text-[hsl(var(--muted-foreground))]">balance</span>
                </div>
              )}
            </div>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 mt-2">
              {regionChartData.map(d => (
                <div key={d.region} className="flex items-center gap-1.5 text-xs">
                  <span className="inline-block w-2 h-2 rounded-full flex-shrink-0" style={{ background: d.color }} />
                  <span className="text-[hsl(var(--muted-foreground))]">{d.region}</span>
                  <span className="font-medium text-[hsl(var(--foreground))]">{d.pct}%</span>
                </div>
              ))}
            </div>
          </div>

          {/* Bar chart + guidance */}
          <div>
            <p className="text-xs text-[hsl(var(--muted-foreground))] mb-2">各区域库存对比（理想线 25%）</p>
            <div style={{ height: 180 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={regionChartData} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                  <XAxis dataKey="region" tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} />
                  <YAxis tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} width={36} />
                  <RechartsTooltip
                    contentStyle={{
                      background: 'hsl(var(--card))',
                      border: '1px solid hsl(var(--border))',
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                  />
                  <Bar dataKey="units" radius={[4, 4, 0, 0]}>
                    {regionChartData.map((entry, i) => (
                      <Cell key={i} fill={entry.color} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            {skuMeta && (
              <div className="mt-3 space-y-2">
                {skuMeta.gap_regions && skuMeta.gap_regions.length > 0 && (
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs text-[hsl(var(--muted-foreground))]">Gap regions:</span>
                    {skuMeta.gap_regions.map(r => (
                      <span key={r} className="px-2 py-0.5 rounded-full text-xs font-medium bg-red-500/15 text-red-400 border border-red-500/30">
                        {r}
                      </span>
                    ))}
                  </div>
                )}
                {skuMeta.ad_guidance && (
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className="text-xs text-[hsl(var(--muted-foreground))]">Ad guidance:</span>
                    {Object.entries(skuMeta.ad_guidance).map(([action, regions]) => {
                      if (!Array.isArray(regions) || regions.length === 0) return null
                      return (
                        <span key={action} className="text-xs text-[hsl(var(--muted-foreground))]">
                          {AD_GUIDANCE_ICONS[action] ?? '⬜'} <strong className="text-[hsl(var(--foreground))]">{action}</strong>: {(regions as string[]).join(', ')}
                        </span>
                      )
                    })}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── FC Detail Table ── */}
      <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
        <div className="px-4 py-3 border-b border-[hsl(var(--border))] flex items-center justify-between gap-3 flex-wrap">
          <div>
            <h3 className="text-sm font-semibold text-[hsl(var(--foreground))]">FC 明细表</h3>
            <p className="text-xs text-[hsl(var(--muted-foreground))] mt-0.5">{filteredFcDetails.length} records</p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[hsl(var(--muted-foreground))]" />
              <input
                type="text"
                placeholder="FC ID / City / SKU…"
                value={tableSearch}
                onChange={e => setTableSearch(e.target.value)}
                className="pl-8 pr-8 py-1.5 text-sm bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg w-44 focus:outline-none focus:ring-1 focus:ring-[hsl(var(--primary)/0.5)] text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))]"
              />
              {tableSearch && (
                <button onClick={() => setTableSearch('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]">
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>
            <select
              value={regionFilter}
              onChange={e => setRegionFilter(e.target.value)}
              className="px-3 py-1.5 text-sm bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-[hsl(var(--foreground))] focus:outline-none"
            >
              <option value="all">All Regions</option>
              <option value="west">West</option>
              <option value="south">South</option>
              <option value="midwest">Midwest</option>
              <option value="east">East</option>
            </select>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] text-xs uppercase tracking-wide">
                {([
                  ['fc_id', 'FC ID'],
                  ['city', 'City, State'],
                  ['region', 'Region'],
                  ['sku', 'SKU'],
                  ['sellable', 'Sellable'],
                  ['customer_damaged', 'Damaged'],
                  ['defective', 'Defective'],
                  ['total', 'Total'],
                ] as [keyof FCDetail, string][]).map(([key, label]) => (
                  <th
                    key={key}
                    className="px-3 py-2 text-left font-medium cursor-pointer hover:text-[hsl(var(--foreground))] transition-colors select-none"
                    onClick={() => handleTableSort(key)}
                  >
                    <span className="flex items-center gap-1">
                      {label}
                      {tableSortKey === key
                        ? tableSortDir === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />
                        : <ArrowUpDown className="w-3 h-3 opacity-40" />
                      }
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredFcDetails.slice(0, 50).map((fc, i) => {
                const regionColor = FC_REGION_COLORS[fc.region as RegionKey] ?? '#94a3b8'
                const productName = bySku[fc.sku]?.name ?? fc.sku
                return (
                  <tr key={`${fc.fc_id}-${fc.sku}-${i}`} className="border-b border-[hsl(var(--border)/0.5)] hover:bg-[hsl(var(--secondary))] transition-colors">
                    <td className="px-3 py-2.5 font-mono text-xs font-semibold text-[hsl(var(--foreground))]">{fc.fc_id}</td>
                    <td className="px-3 py-2.5 text-xs text-[hsl(var(--muted-foreground))]">{fc.city}, {fc.state}</td>
                    <td className="px-3 py-2.5">
                      <span className="flex items-center gap-1.5 text-xs text-[hsl(var(--foreground))]">
                        <span className="inline-block w-2 h-2 rounded-full flex-shrink-0" style={{ background: regionColor }} />
                        {fc.region.charAt(0).toUpperCase() + fc.region.slice(1)}
                      </span>
                    </td>
                    <td className="px-3 py-2.5">
                      <p className="font-mono text-[10px] text-[hsl(var(--foreground))]">{fc.sku}</p>
                      <p className="text-[10px] text-[hsl(var(--muted-foreground))] truncate max-w-[120px]" title={productName}>{productName}</p>
                    </td>
                    <td className="px-3 py-2.5 text-right text-xs font-medium" style={{ color: '#22C55E' }}>{fc.sellable || '—'}</td>
                    <td className="px-3 py-2.5 text-right text-xs">{fc.customer_damaged > 0 ? <span className="text-orange-400">{fc.customer_damaged}</span> : <span className="opacity-30 text-[hsl(var(--muted-foreground))]">—</span>}</td>
                    <td className="px-3 py-2.5 text-right text-xs">{fc.defective > 0 ? <span className="text-red-400">{fc.defective}</span> : <span className="opacity-30 text-[hsl(var(--muted-foreground))]">—</span>}</td>
                    <td className="px-3 py-2.5 text-right text-xs font-semibold text-[hsl(var(--foreground))]">{fc.total}</td>
                  </tr>
                )
              })}
              {filteredFcDetails.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-sm text-[hsl(var(--muted-foreground))]">No matching records</td>
                </tr>
              )}
            </tbody>
          </table>
          {filteredFcDetails.length > 50 && (
            <p className="text-center text-xs text-[hsl(var(--muted-foreground))] py-2.5 border-t border-[hsl(var(--border))]">
              Showing 50 of {filteredFcDetails.length} records — use search or filters to narrow down
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function InventoryStatusPage() {
  const [data, setData] = useState<InventoryStatusData | null>(null)
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [skuFilter, setSkuFilter]   = useState('')
  const [asinFilter, setAsinFilter] = useState('')
  const [activeFilter, setActiveFilter] = useState({ sku: '', asin: '' })

  // ── FC Distribution state ──
  const [activeTab, setActiveTab] = useState<'inventory' | 'fc-distribution'>('inventory')
  const [fcData, setFcData] = useState<FCDistributionData | null>(null)
  const [fcLoading, setFcLoading] = useState(false)
  const [fcError, setFcError] = useState<string | null>(null)
  const [fcSkuFilter, setFcSkuFilter] = useState<string>('all')

  const fetchData = useCallback(async (sku: string, asin: string) => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (sku.trim())  params.set('sku',  sku.trim())
      if (asin.trim()) params.set('asin', asin.trim().toUpperCase())
      const res = await fetch(`/api/amazon/inventory-status?${params}`)
      const json: InventoryStatusData = await res.json()
      setData(json)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Fetch failed')
    } finally {
      setLoading(false)
    }
  }, [])

  const forceRefresh = useCallback(async () => {
    setRefreshing(true)
    setError(null)
    try {
      const res = await fetch('/api/amazon/inventory-status', { method: 'POST' })
      const json: InventoryStatusData = await res.json()
      setData(json)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Refresh failed')
    } finally {
      setRefreshing(false)
    }
  }, [])

  const fetchFcData = useCallback(async () => {
    setFcLoading(true)
    setFcError(null)
    try {
      const res = await fetch('/api/inventory/fc-distribution')
      const json: FCDistributionData = await res.json()
      if (json.error) throw new Error(json.message || 'FC data error')
      setFcData(json)
    } catch (e) {
      setFcError(e instanceof Error ? e.message : 'Failed to load FC data')
    } finally {
      setFcLoading(false)
    }
  }, [])

  // Auto-fetch on mount (will hit cache if available)
  useEffect(() => {
    fetchData('', '')
    fetchFcData()
  }, [fetchData, fetchFcData])

  const handleApply = () => {
    setActiveFilter({ sku: skuFilter, asin: asinFilter })
    fetchData(skuFilter, asinFilter)
  }
  const handleClear = () => {
    setSkuFilter('')
    setAsinFilter('')
    setActiveFilter({ sku: '', asin: '' })
    fetchData('', '')
  }

  // Chart data: top 20 SKUs by total quantity for the bar chart
  const barData = useMemo(() => {
    if (!data?.items) return []
    return [...data.items]
      .sort((a, b) => b.afnTotalQuantity - a.afnTotalQuantity)
      .slice(0, 20)
      .map(item => ({
        name: item.sku || item.asin,
        Fulfillable: item.afnFulfillableQuantity,
        Reserved:    item.afnReservedQuantity,
        Unsellable:  item.afnUnsellableQuantity,
      }))
  }, [data])

  // Pie chart data
  const pieData = useMemo(() => {
    if (!data?.summary) return []
    const s = data.summary
    const totalInbound = s.totalInboundWorking + s.totalInboundShipped + s.totalInboundReceiving
    return [
      { name: 'Fulfillable', value: s.totalFulfillable, fill: COLORS.fulfillable },
      { name: 'Reserved',    value: s.totalReserved,    fill: COLORS.reserved },
      { name: 'Unsellable',  value: s.totalUnsellable,  fill: COLORS.unsellable },
      { name: 'Inbound',     value: totalInbound,        fill: COLORS.inbound },
    ].filter(d => d.value > 0)
  }, [data])

  const totalInbound = data
    ? data.summary.totalInboundWorking + data.summary.totalInboundShipped + data.summary.totalInboundReceiving
    : 0

  return (
    <div className="flex flex-col">
      {/* ── Header ── */}
      <div className="border-b border-[hsl(var(--border))] py-4 flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-[hsl(var(--primary)/0.15)]">
            <Activity className="w-5 h-5 text-[hsl(var(--primary))]" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-[hsl(var(--foreground))]">Inventory</h1>
            <p className="text-xs text-[hsl(var(--muted-foreground))]">库存 · GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA</p>
          </div>
        </div>

        {/* Tab switcher - shown in header area */}
        <div className="flex items-center gap-1 p-1 rounded-xl bg-[hsl(var(--secondary))] border border-[hsl(var(--border))]">
          <button
            onClick={() => setActiveTab('inventory')}
            className={cn(
              'px-4 py-1.5 text-sm font-medium rounded-lg transition-all',
              activeTab === 'inventory'
                ? 'bg-[hsl(var(--card))] text-[hsl(var(--foreground))] shadow-sm'
                : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'
            )}
          >
            📦 Inventory
          </button>
          <button
            onClick={() => setActiveTab('fc-distribution')}
            className={cn(
              'px-4 py-1.5 text-sm font-medium rounded-lg transition-all',
              activeTab === 'fc-distribution'
                ? 'bg-[hsl(var(--card))] text-[hsl(var(--foreground))] shadow-sm'
                : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'
            )}
          >
            🗺️ FC Distribution
          </button>
        </div>

        {/* The existing filter bar and refresh button - only show on inventory tab */}
        {activeTab === 'inventory' && (
          <div className="flex items-center gap-3 flex-wrap">
            {data?.cachedAt && (
              <span className="text-xs text-[hsl(var(--muted-foreground))]">
                {data.fromCache ? '🗂 缓存' : '🔄 实时'} · 数据更新于 {formatCacheAge(data.cachedAt)}
              </span>
            )}
            <FilterBar
              skuFilter={skuFilter}
              asinFilter={asinFilter}
              onSkuChange={setSkuFilter}
              onAsinChange={setAsinFilter}
              onApply={handleApply}
              onClear={handleClear}
              loading={loading}
            />
            <button
              onClick={forceRefresh}
              disabled={loading || refreshing}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg bg-[hsl(var(--secondary))] text-[hsl(var(--foreground))] hover:bg-[hsl(var(--border))] disabled:opacity-40 transition-all"
              title="强制刷新（忽略缓存）"
            >
              <RefreshCw className={cn('w-3.5 h-3.5', refreshing && 'animate-spin')} />
              {refreshing ? '刷新中…' : '刷新数据'}
            </button>
          </div>
        )}
      </div>

      {/* ── TAB 1: Inventory Status (existing content) ── */}
      {activeTab === 'inventory' && (
        <>
          {/* ── Loading state ── */}
          {loading && !data && (
            <div className="flex-1 flex flex-col items-center justify-center gap-3 p-12">
              <div className="w-10 h-10 rounded-full border-2 border-[hsl(var(--primary)/0.3)] border-t-[hsl(var(--primary))] animate-spin" />
              <p className="text-sm text-[hsl(var(--muted-foreground))]">
                加载库存数据中… 缓存命中将秒开，否则可能需 1-3 分钟
              </p>
            </div>
          )}

          {/* ── Refreshing overlay notice ── */}
          {refreshing && data && (
            <div className="mx-6 mt-4 flex items-center gap-2 p-2.5 rounded-lg bg-[hsl(var(--primary)/0.08)] border border-[hsl(var(--primary)/0.2)] text-xs text-[hsl(var(--primary))]">
              <RefreshCw className="w-3.5 h-3.5 animate-spin flex-shrink-0" />
              正在从 SP-API 拉取最新数据，约需 1-3 分钟…
            </div>
          )}

          {/* ── Error ── */}
          {error && (
            <div className="m-6 flex items-center gap-2 p-3 rounded-lg bg-[hsl(var(--destructive)/0.1)] border border-[hsl(var(--destructive)/0.3)] text-sm text-[hsl(var(--destructive))]">
              <AlertTriangle className="w-4 h-4 flex-shrink-0" />
              {error}
            </div>
          )}

          {/* ── Main content ── */}
          {data && !loading && (
            <div className="space-y-6 pt-6">
              {/* API error notice */}
              {data.error && (
                <div className="flex items-start gap-2 p-3 rounded-lg bg-[hsl(var(--destructive)/0.1)] border border-[hsl(var(--destructive)/0.3)] text-sm text-[hsl(var(--destructive))]">
                  <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                  <div>
                    <strong>SP-API error:</strong> {data.errorMessage || 'Unknown error'}
                  </div>
                </div>
              )}

              {/* ── KPI cards ── */}
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                <KpiCard
                  label="Fulfillable"
                  value={fmtNum(data.summary.totalFulfillable)}
                  sub="可售库存"
                  icon={<Package />}
                  highlight
                />
                <KpiCard
                  label="Reserved"
                  value={fmtNum(data.summary.totalReserved)}
                  sub="预留库存"
                  icon={<Archive />}
                />
                <KpiCard
                  label="Unsellable"
                  value={fmtNum(data.summary.totalUnsellable)}
                  sub="不可售库存"
                  icon={<AlertTriangle />}
                />
                <KpiCard
                  label="Total Inbound"
                  value={fmtNum(totalInbound)}
                  sub={`Working ${fmtNum(data.summary.totalInboundWorking)} · Shipped ${fmtNum(data.summary.totalInboundShipped)} · Receiving ${fmtNum(data.summary.totalInboundReceiving)}`}
                  icon={<TrendingUp />}
                />
              </div>

              {/* ── Charts row: Bar + Pie ── */}
              {(barData.length > 0 || pieData.length > 0) && (
                <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
                  {/* Stacked bar chart */}
                  <div className="xl:col-span-2 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
                    <div className="px-4 py-3 border-b border-[hsl(var(--border))]">
                      <h3 className="text-sm font-semibold text-[hsl(var(--foreground))]">库存构成 (Top 20 SKUs)</h3>
                      <p className="text-xs text-[hsl(var(--muted-foreground))] mt-0.5">
                        Fulfillable / Reserved / Unsellable per SKU
                      </p>
                    </div>
                    <div className="p-4" style={{ height: 320 }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={barData} margin={{ top: 4, right: 8, left: 0, bottom: 60 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                          <XAxis
                            dataKey="name"
                            tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
                            angle={-45}
                            textAnchor="end"
                            interval={0}
                            height={70}
                          />
                          <YAxis
                            tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
                            tickFormatter={fmtNum}
                            width={40}
                          />
                          <RechartsTooltip content={<BarTooltip />} />
                          <Legend
                            wrapperStyle={{ fontSize: 11, paddingTop: 8, color: 'hsl(var(--muted-foreground))' }}
                          />
                          <Bar dataKey="Fulfillable" stackId="a" fill={COLORS.fulfillable} radius={[0, 0, 0, 0]} />
                          <Bar dataKey="Reserved"    stackId="a" fill={COLORS.reserved} />
                          <Bar dataKey="Unsellable"  stackId="a" fill={COLORS.unsellable} radius={[3, 3, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </div>

                  {/* Pie chart */}
                  <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
                    <div className="px-4 py-3 border-b border-[hsl(var(--border))]">
                      <h3 className="text-sm font-semibold text-[hsl(var(--foreground))]">库存状态占比</h3>
                      <p className="text-xs text-[hsl(var(--muted-foreground))] mt-0.5">
                        Fulfillable / Reserved / Unsellable / Inbound
                      </p>
                    </div>
                    <div className="p-4 flex flex-col items-center" style={{ height: 320 }}>
                      <ResponsiveContainer width="100%" height={220}>
                        <PieChart>
                          <Pie
                            data={pieData}
                            cx="50%"
                            cy="50%"
                            innerRadius={55}
                            outerRadius={90}
                            paddingAngle={2}
                            dataKey="value"
                          >
                            {pieData.map((entry, i) => (
                              <Cell key={i} fill={entry.fill} stroke="transparent" />
                            ))}
                          </Pie>
                          <RechartsTooltip content={<PieTooltip />} />
                        </PieChart>
                      </ResponsiveContainer>
                      {/* Legend */}
                      <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 mt-2">
                        {pieData.map(entry => {
                          const total = pieData.reduce((s, d) => s + d.value, 0)
                          return (
                            <div key={entry.name} className="flex items-center gap-1.5 text-xs">
                              <span
                                className="inline-block w-2 h-2 rounded-full flex-shrink-0"
                                style={{ background: entry.fill }}
                              />
                              <span className="text-[hsl(var(--muted-foreground))]">{entry.name}</span>
                              <span className="font-medium text-[hsl(var(--foreground))]">
                                {total > 0 ? `${((entry.value / total) * 100).toFixed(1)}%` : '0%'}
                              </span>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* ── Inbound Pipeline ── */}
              <InboundPipeline summary={data.summary} />

              {/* ── SKU Detail Table ── */}
              {data.items.length > 0 && <SkuDetailTable items={data.items} />}

              {/* Empty data */}
              {data.items.length === 0 && !data.error && (
                <div className="flex flex-col items-center justify-center py-16 text-center">
                  <Package className="w-10 h-10 text-[hsl(var(--muted-foreground))] mb-3 opacity-50" />
                  <p className="text-sm text-[hsl(var(--muted-foreground))]">
                    No inventory data returned.{' '}
                    {activeFilter.sku || activeFilter.asin
                      ? 'Try clearing the filter.'
                      : 'Check SP-API permissions.'}
                  </p>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* ── TAB 2: FC Distribution ── */}
      {activeTab === 'fc-distribution' && (
        <div className="space-y-6 pt-6">
          {fcLoading && (
            <div className="flex flex-col items-center justify-center py-16 gap-3">
              <div className="w-10 h-10 rounded-full border-2 border-[hsl(var(--primary)/0.3)] border-t-[hsl(var(--primary))] animate-spin" />
              <p className="text-sm text-[hsl(var(--muted-foreground))]">加载 FC 分布数据…</p>
            </div>
          )}
          {fcError && (
            <div className="flex items-center gap-2 p-3 rounded-lg bg-[hsl(var(--destructive)/0.1)] border border-[hsl(var(--destructive)/0.3)] text-sm text-[hsl(var(--destructive))]">
              <AlertTriangle className="w-4 h-4 flex-shrink-0" />
              {fcError}
            </div>
          )}
          {fcData && !fcLoading && (
            <>
              {/* Summary KPI cards */}
              <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
                <KpiCard label="Total Units" value={fmtNum(fcData.account_summary.total_units)} sub="所有 FC 合计" icon={<Package />} highlight />
                <KpiCard label="Sellable" value={fmtNum(fcData.account_summary.total_sellable)} sub="可售库存" icon={<TrendingUp />} />
                <KpiCard label="Damaged" value={fmtNum(fcData.account_summary.customer_damaged)} sub="顾客损坏" icon={<AlertTriangle />} />
                <KpiCard label="FC Count" value={String(fcData.account_summary.fc_count)} sub="配送中心数" icon={<BoxIcon />} />
                <KpiCard label="SKU Count" value={String(fcData.account_summary.sku_count)} sub="SKU 数" icon={<Archive />} />
                <KpiCard label="Updated" value={fcData.updated} sub={`来源: ${fcData.source}`} icon={<Activity />} />
              </div>

              {/* SKU filter dropdown */}
              <div className="flex items-center gap-3">
                <label className="text-sm font-medium text-[hsl(var(--muted-foreground))]">产品筛选:</label>
                <select
                  value={fcSkuFilter}
                  onChange={e => setFcSkuFilter(e.target.value)}
                  className="px-3 py-1.5 text-sm bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-[hsl(var(--foreground))] focus:outline-none focus:ring-1 focus:ring-[hsl(var(--primary)/0.5)]"
                >
                  <option value="all">All Products</option>
                  {Object.entries(fcData.by_sku).map(([sku, info]) => (
                    <option key={sku} value={sku}>{info.name || sku}</option>
                  ))}
                </select>
              </div>

              <USFCMap
                fcDetails={fcData.fc_details}
                bySkuMap={fcData.by_sku}
                skuFilter={fcSkuFilter}
              />

              <FCRegionDashboard
                bySku={fcData.by_sku}
                fcDetails={fcData.fc_details}
                skuFilter={fcSkuFilter}
              />
            </>
          )}
        </div>
      )}
    </div>
  )
}
