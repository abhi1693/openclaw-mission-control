import { NextRequest, NextResponse } from 'next/server';
import fs from 'fs/promises';
import path from 'path';
import os from 'os';

export interface RestockConfigItem {
  asin: string;
  leadTimeDays: number;
  fbaPrepDays: number;
  safetyStockDays: number;
}

const CONFIG_PATH = path.join(os.homedir(), '.openclaw', 'workspace', 'config', 'restock-config.json');

const DEFAULT_CONFIG: RestockConfigItem[] = [
  { asin: 'B001TEST01', leadTimeDays: 30, fbaPrepDays: 7, safetyStockDays: 14 },
  { asin: 'B001TEST02', leadTimeDays: 30, fbaPrepDays: 7, safetyStockDays: 14 },
  { asin: 'B001TEST03', leadTimeDays: 30, fbaPrepDays: 7, safetyStockDays: 14 },
  { asin: 'B001TEST04', leadTimeDays: 30, fbaPrepDays: 7, safetyStockDays: 14 },
];

async function readConfig(): Promise<RestockConfigItem[]> {
  try {
    const raw = await fs.readFile(CONFIG_PATH, 'utf-8');
    return JSON.parse(raw) as RestockConfigItem[];
  } catch {
    return DEFAULT_CONFIG;
  }
}

export async function GET() {
  const config = await readConfig();
  return NextResponse.json(config);
}

export async function PUT(req: NextRequest) {
  const body = await req.json() as RestockConfigItem[];
  await fs.mkdir(path.dirname(CONFIG_PATH), { recursive: true });
  await fs.writeFile(CONFIG_PATH, JSON.stringify(body, null, 2), 'utf-8');
  return NextResponse.json(body);
}
