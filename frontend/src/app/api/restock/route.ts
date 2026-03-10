import { NextResponse } from 'next/server';
import fs from 'fs/promises';
import path from 'path';
import os from 'os';
import type { RestockConfigItem } from './config/route';

const CONFIG_PATH = path.join(os.homedir(), '.openclaw', 'workspace', 'config', 'restock-config.json');
const INVENTORY_CACHE_DIR = path.join(os.homedir(), '.openclaw', 'workspace', 'cache', 'inventory');

const DEFAULT_CONFIG: RestockConfigItem[] = [
  { asin: 'B001TEST01', leadTimeDays: 30, fbaPrepDays: 7, safetyStockDays: 14 },
  { asin: 'B001TEST02', leadTimeDays: 30, fbaPrepDays: 7, safetyStockDays: 14 },
  { asin: 'B001TEST03', leadTimeDays: 30, fbaPrepDays: 7, safetyStockDays: 14 },
  { asin: 'B001TEST04', leadTimeDays: 30, fbaPrepDays: 7, safetyStockDays: 14 },
];

interface InventoryCacheItem {
  asin: string;
  productName?: string;
  currentStock: number;
  lastUpdated?: string;
}

function hashCode(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = (hash << 5) - hash + str.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

function getDailySales(asin: string): number {
  // Fixed daily sales per ASIN, range 5–20
  return (hashCode(asin) % 16) + 5;
}

async function readConfig(): Promise<RestockConfigItem[]> {
  try {
    const raw = await fs.readFile(CONFIG_PATH, 'utf-8');
    return JSON.parse(raw) as RestockConfigItem[];
  } catch {
    return DEFAULT_CONFIG;
  }
}

async function readInventoryCache(): Promise<InventoryCacheItem[] | null> {
  try {
    const files = await fs.readdir(INVENTORY_CACHE_DIR);
    const jsonFiles = files.filter((f) => f.endsWith('.json'));
    if (jsonFiles.length === 0) return null;

    const items: InventoryCacheItem[] = [];
    for (const file of jsonFiles) {
      const raw = await fs.readFile(path.join(INVENTORY_CACHE_DIR, file), 'utf-8');
      const data = JSON.parse(raw);
      if (Array.isArray(data)) {
        items.push(...(data as InventoryCacheItem[]));
      } else {
        items.push(data as InventoryCacheItem);
      }
    }
    return items.length > 0 ? items : null;
  } catch {
    return null;
  }
}

const MOCK_PRODUCT_NAMES: Record<string, string> = {
  B001TEST01: 'Test Product Alpha',
  B001TEST02: 'Test Product Beta',
  B001TEST03: 'Test Product Gamma',
  B001TEST04: 'Test Product Delta',
};

function getMockInventory(asin: string): number {
  // Fixed mock stock per ASIN, range 50–300
  return (hashCode(asin) % 251) + 50;
}

export async function GET() {
  const [config, cachedInventory] = await Promise.all([readConfig(), readInventoryCache()]);

  const now = new Date().toISOString();

  const items = config.map((cfg) => {
    const cached = cachedInventory?.find((c) => c.asin === cfg.asin);
    const currentStock = cached?.currentStock ?? getMockInventory(cfg.asin);
    const productName = cached?.productName ?? MOCK_PRODUCT_NAMES[cfg.asin] ?? cfg.asin;
    const lastUpdated = cached?.lastUpdated ?? now;

    const dailySales = getDailySales(cfg.asin);
    const daysUntilStockout = Math.round(currentStock / dailySales);
    const reorderQty = (cfg.leadTimeDays + cfg.fbaPrepDays + cfg.safetyStockDays) * dailySales;

    let urgency: 'critical' | 'warning' | 'ok';
    if (daysUntilStockout < 14) {
      urgency = 'critical';
    } else if (daysUntilStockout < 30) {
      urgency = 'warning';
    } else {
      urgency = 'ok';
    }

    return {
      asin: cfg.asin,
      productName,
      currentStock,
      dailySales,
      daysUntilStockout,
      reorderQty,
      urgency,
      lastUpdated,
    };
  });

  const summary = {
    critical: items.filter((i) => i.urgency === 'critical').length,
    warning: items.filter((i) => i.urgency === 'warning').length,
    ok: items.filter((i) => i.urgency === 'ok').length,
  };

  return NextResponse.json({ items, summary });
}
