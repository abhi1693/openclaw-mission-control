// Mock data for UI development — replace with real API calls
// Real Amazon data is already flowing via SP-API (orders, sales, inventory)

export const mockSalesWeekly = [
  { date: 'Feb 13', revenue: 3324.50, units: 100, orders: 77 },
  { date: 'Feb 14', revenue: 1572.33, units: 67,  orders: 66 },
  { date: 'Feb 15', revenue: 1693.33, units: 67,  orders: 59 },
  { date: 'Feb 16', revenue: 3468.29, units: 121, orders: 108 },
  { date: 'Feb 17', revenue: 2726.14, units: 86,  orders: 74 },
  { date: 'Feb 18', revenue: 3480.41, units: 109, orders: 92 },
  { date: 'Feb 19', revenue: 2747.13, units: 87,  orders: 75 },
]

export const mockPrevWeekSales = [
  { date: 'Feb 06', revenue: 2833.61, units: 89,  orders: 69 },
  { date: 'Feb 07', revenue: 2714.02, units: 98,  orders: 83 },
  { date: 'Feb 08', revenue: 2104.21, units: 79,  orders: 71 },
  { date: 'Feb 09', revenue: 2842.11, units: 89,  orders: 80 },
  { date: 'Feb 10', revenue: 4701.66, units: 134, orders: 98 },
  { date: 'Feb 11', revenue: 3126.98, units: 102, orders: 85 },
  { date: 'Feb 12', revenue: 4043.21, units: 129, orders: 108 },
]

export const mockInventory = [
  {
    sku: 'ZV-SERUM-01',
    name: 'Vitamin C Serum 30ml',
    asin: 'B0EXAMPLE01',
    available: 312,
    inbound: 500,
    reserved: 18,
    bsr: 1842,
    bsrCategory: 'Beauty & Personal Care',
    status: 'healthy' as const,
  },
  {
    sku: 'ZV-MOISTURIZER-02',
    name: 'Daily Moisturizer 50ml',
    asin: 'B0EXAMPLE02',
    available: 47,
    inbound: 0,
    reserved: 5,
    bsr: 4231,
    bsrCategory: 'Beauty & Personal Care',
    status: 'low' as const,
  },
  {
    sku: 'ZV-EYECREAM-03',
    name: 'Eye Cream 15ml',
    asin: 'B0EXAMPLE03',
    available: 189,
    inbound: 200,
    reserved: 12,
    bsr: 2987,
    bsrCategory: 'Beauty & Personal Care',
    status: 'healthy' as const,
  },
]


export const mockApprovals = [
  {
    id: 'a1',
    type: 'ppc',
    title: 'PPC 关键词竞价调整建议',
    description: '基于过去 14 天 ACoS 数据，建议对 12 个关键词调整出价',
    priority: 'high' as const,
    createdAt: '2026-02-19T09:00:00Z',
    preview: '+ "vitamin c serum for face" $1.20 → $1.45\n- "face serum anti aging" $0.90 → $0.72',
  },
  {
    id: 'a2',
    type: 'listing',
    title: 'Listing 标题优化草稿',
    description: 'ZV-MOISTURIZER-02 产品标题基于关键词研究重写',
    priority: 'medium' as const,
    createdAt: '2026-02-18T14:00:00Z',
    preview: 'ZOVIRO Daily Face Moisturizer with Hyaluronic Acid...',
  },
]

export const mockContent = {
  assets: [
    { id: 'v1', name: 'Vitamin C Serum Hero Shot', type: 'image', url: '/file.svg', status: 'ready', tags: ['Amazon', 'Main Image'] },
    { id: 'v2', name: 'Moisturizer Texture Reel', type: 'video', url: '/window.svg', status: 'editing', tags: ['Instagram', 'TikTok'] },
    { id: 'v3', name: 'Eye Cream Lifestyle Shot', type: 'image', url: '/globe.svg', status: 'ready', tags: ['Shopify', 'Social'] },
  ],
  social: [
    { id: 's1', platform: 'Instagram', date: '2026-02-20T18:00:00Z', title: 'The Science of Glow', status: 'scheduled', preview: 'Discover the active ingredients in our Vitamin C serum...' },
    { id: 's2', platform: 'TikTok', date: '2026-02-21T10:00:00Z', title: 'Morning Routine ASMR', status: 'draft', preview: 'Focus on texture and sound of the new moisturizer glass jar.' },
  ],
  blogs: [
    { id: 'b1', title: '5 Skincare Habits for 2026', status: 'published', author: 'Jarvis (AI)', views: 1240 },
    { id: 'b2', title: 'Why Hyaluronic Acid is Your Best Friend', status: 'generating', author: 'Jarvis (AI)', progress: 45 },
  ]
}

export const mockAlerts = [
  {
    id: 'alert-1',
    level: 'warning' as const,
    message: 'ZV-MOISTURIZER-02 库存仅剩 47 件，建议立即备货',
    timestamp: '2026-02-19T11:00:00Z',
  },
  {
    id: 'alert-2',
    level: 'info' as const,
    message: '竞品 B08XYZ123 今日降价 15%，当前售价 $21.99',
    timestamp: '2026-02-19T09:30:00Z',
  },
]

