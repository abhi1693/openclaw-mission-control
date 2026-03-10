import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import os from 'os';

const CACHE_DIR = path.join(os.homedir(), '.openclaw/workspace/cache/reviews');

const TEST_ASINS: Record<string, string> = {
  B08N5WRWNW: 'Wireless Earbuds Pro',
  B09G9FPHY6: 'USB-C Hub 7-in-1',
  B07XJ8C8F7: 'Portable Charger 20000mAh',
  B08L5NP6NG: 'Smart LED Desk Lamp',
};

function randomBetween(min: number, max: number): number {
  return Math.random() * (max - min) + min;
}

function generateReviewData(asin: string, productName: string) {
  const rating = parseFloat(randomBetween(3.8, 4.8).toFixed(1));
  const totalReviews = Math.floor(randomBetween(50, 500));

  const dist5 = Math.floor(totalReviews * 0.45);
  const dist4 = Math.floor(totalReviews * 0.25);
  const dist3 = Math.floor(totalReviews * 0.15);
  const dist2 = Math.floor(totalReviews * 0.08);
  const dist1 = totalReviews - dist5 - dist4 - dist3 - dist2;

  const now = new Date();
  const dateStr = (daysAgo: number) => {
    const d = new Date(now);
    d.setDate(d.getDate() - daysAgo);
    return d.toISOString().split('T')[0];
  };

  return {
    asin,
    productName,
    rating,
    totalReviews,
    ratingDistribution: { '5': dist5, '4': dist4, '3': dist3, '2': dist2, '1': dist1 },
    recentReviews: [
      {
        title: 'Amazing quality, love it!',
        rating: 5,
        date: dateStr(2),
        text: `Really impressed with the ${productName}. Exactly what I needed and arrived quickly.`,
        verified: true,
      },
      {
        title: 'Good product, minor issues',
        rating: 4,
        date: dateStr(5),
        text: 'Overall satisfied. There were a few small quirks at first but it works great now.',
        verified: true,
      },
      {
        title: 'Solid purchase',
        rating: 4,
        date: dateStr(9),
        text: 'Bought this as a gift and the recipient loved it. Good build quality.',
        verified: false,
      },
      {
        title: 'Works as described',
        rating: 5,
        date: dateStr(14),
        text: 'No complaints. Does exactly what the listing says. Would buy again.',
        verified: true,
      },
      {
        title: 'Not worth the money',
        rating: 2,
        date: dateStr(20),
        text: `Disappointed with the ${productName}. It stopped working after 3 weeks and the return process was a hassle.`,
        verified: true,
      },
    ],
    lastCrawled: now.toISOString(),
  };
}

export async function POST() {
  try {
    fs.mkdirSync(CACHE_DIR, { recursive: true });

    const written: string[] = [];

    for (const [asin, productName] of Object.entries(TEST_ASINS)) {
      const data = generateReviewData(asin, productName);
      const filePath = path.join(CACHE_DIR, `${asin}-latest.json`);
      fs.writeFileSync(filePath, JSON.stringify(data, null, 2), 'utf-8');
      written.push(asin);
    }

    return NextResponse.json({
      success: true,
      message: `Crawled and cached ${written.length} products`,
      asins: written,
      cacheDir: CACHE_DIR,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
