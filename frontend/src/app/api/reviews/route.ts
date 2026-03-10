import { NextRequest, NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import os from 'os';

const CACHE_DIR = path.join(os.homedir(), '.openclaw/workspace/cache/reviews');

interface ReviewItem {
  title: string;
  rating: number;
  date: string;
  text: string;
  verified: boolean;
}

interface ReviewCache {
  asin: string;
  productName: string;
  rating: number;
  totalReviews: number;
  ratingDistribution: Record<string, number>;
  recentReviews: ReviewItem[];
  lastCrawled: string;
}

const MOCK_ASINS = ['B08N5WRWNW', 'B09G9FPHY6', 'B07XJ8C8F7', 'B08L5NP6NG'];

const MOCK_PRODUCTS: Record<string, string> = {
  B08N5WRWNW: 'Wireless Earbuds Pro',
  B09G9FPHY6: 'USB-C Hub 7-in-1',
  B07XJ8C8F7: 'Portable Charger 20000mAh',
  B08L5NP6NG: 'Smart LED Desk Lamp',
};

function generateMockData(asin: string): ReviewCache {
  const productName = MOCK_PRODUCTS[asin] ?? `Product ${asin}`;
  const rating = parseFloat((3.8 + Math.random()).toFixed(1));
  const totalReviews = Math.floor(50 + Math.random() * 450);

  const dist5 = Math.floor(totalReviews * 0.45);
  const dist4 = Math.floor(totalReviews * 0.25);
  const dist3 = Math.floor(totalReviews * 0.15);
  const dist2 = Math.floor(totalReviews * 0.08);
  const dist1 = totalReviews - dist5 - dist4 - dist3 - dist2;

  return {
    asin,
    productName,
    rating,
    totalReviews,
    ratingDistribution: { '5': dist5, '4': dist4, '3': dist3, '2': dist2, '1': dist1 },
    recentReviews: [
      {
        title: 'Great product, highly recommend!',
        rating: 5,
        date: '2025-02-10',
        text: 'Works exactly as described. Quality is top-notch and shipping was fast.',
        verified: true,
      },
      {
        title: 'Good value for the price',
        rating: 4,
        date: '2025-02-08',
        text: 'Solid product overall. Minor setup issue but customer support resolved it quickly.',
        verified: true,
      },
      {
        title: 'Does the job',
        rating: 3,
        date: '2025-02-05',
        text: 'Average product. Works as expected but nothing special.',
        verified: false,
      },
      {
        title: 'Exceeded expectations',
        rating: 5,
        date: '2025-01-30',
        text: 'Surprised by the build quality. Would definitely buy again.',
        verified: true,
      },
      {
        title: 'Disappointed with quality',
        rating: 2,
        date: '2025-01-25',
        text: 'Stopped working after 2 weeks. Not what I expected for the price. Returning it.',
        verified: true,
      },
    ],
    lastCrawled: new Date().toISOString(),
  };
}

function readCacheFile(asin: string): ReviewCache | null {
  const filePath = path.join(CACHE_DIR, `${asin}-latest.json`);
  try {
    const raw = fs.readFileSync(filePath, 'utf-8');
    return JSON.parse(raw) as ReviewCache;
  } catch {
    return null;
  }
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const asin = searchParams.get('asin');

  if (asin) {
    const data = readCacheFile(asin) ?? generateMockData(asin);
    return NextResponse.json({ success: true, data });
  }

  // Return all products summary
  const results: ReviewCache[] = [];

  // Try to read all cached files
  let cachedAsins: string[] = [];
  try {
    const files = fs.readdirSync(CACHE_DIR);
    cachedAsins = files
      .filter((f) => f.endsWith('-latest.json'))
      .map((f) => f.replace('-latest.json', ''));
  } catch {
    // cache dir might not exist yet
  }

  const allAsins = Array.from(new Set([...cachedAsins, ...MOCK_ASINS]));

  for (const a of allAsins) {
    const data = readCacheFile(a) ?? generateMockData(a);
    results.push(data);
  }

  return NextResponse.json({ success: true, data: results, count: results.length });
}
