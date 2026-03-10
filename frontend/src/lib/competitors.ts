export interface CompetitorConfig {
  asin: string
  name: string
  brand: string
  category: string
  notes?: string
}

export const COMPETITOR_ASINS: CompetitorConfig[] = [
  {
    asin: 'B0PLACEHOLDER01',
    name: 'Competitor Product A',
    brand: 'Brand A',
    category: 'Main Category',
    notes: 'Primary competitor — replace with real ASIN',
  },
  {
    asin: 'B0PLACEHOLDER02',
    name: 'Competitor Product B',
    brand: 'Brand B',
    category: 'Main Category',
    notes: 'Secondary competitor — replace with real ASIN',
  },
  {
    asin: 'B0PLACEHOLDER03',
    name: 'Competitor Product C',
    brand: 'Brand C',
    category: 'Main Category',
    notes: 'Tertiary competitor — replace with real ASIN',
  },
]

export const ALERT_THRESHOLDS = {
  priceDropPercent: 5,
  priceRisePercent: 10,
  bsrDropPercent: 15,
  newReviewsPerDay: 3,
}
