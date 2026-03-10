import { NextResponse } from 'next/server'
import { readFileSync, existsSync, readdirSync } from 'fs'
import { join } from 'path'
import { homedir } from 'os'

const PRODUCTS_FILE = join(homedir(), '.openclaw', 'workspace', 'config', 'zoviro-products.md')
const IMAGES_BASE   = join(homedir(), '.openclaw', 'workspace', 'content', 'product-images')

interface Product {
  asin: string
  name: string
  category: string
  images: string[]
}

function parseProducts(md: string): Product[] {
  const products: Product[] = []

  // Split by ### headings that contain an ASIN pattern
  const sections = md.split(/\n(?=### )/)

  for (const section of sections) {
    // Match "### B0XXXXXXXXX — Some Name" or "### B0XXXXXXXXX — Some Name (variant)"
    const headerMatch = section.match(/^### (B\w{9,})\s*[—–-]+\s*(.+)/)
    if (!headerMatch) continue

    const asin = headerMatch[1].trim()

    // Try to get the full product name from "**产品名：**" line
    const nameMatch = section.match(/产品名[：:]\s*\*?\*?\s*(.+)/)
    const name = nameMatch ? nameMatch[1].replace(/^\*+|\*+$/g, '').trim() : headerMatch[2].trim()

    // Determine category from section context (look for preceding ## heading)
    // We'll infer from ASIN patterns or keywords in the section
    let category = 'Other'
    if (/body oil|shimmer body|body lotion/i.test(section)) {
      category = 'Body Care'
    } else if (/foaming hand sanitizer/i.test(section)) {
      category = 'Hand Sanitizer'
    } else if (/hand sanitizer gel/i.test(section)) {
      category = 'Hand Sanitizer Gel'
    } else if (/wipes/i.test(section)) {
      category = 'Hand Sanitizing Wipes'
    }

    // Scan for uploaded images
    const imgDir = join(IMAGES_BASE, asin)
    let images: string[] = []
    if (existsSync(imgDir)) {
      images = readdirSync(imgDir)
        .filter(f => /\.(jpg|jpeg|png|webp)$/i.test(f))
        .map(f => `/api/content/images/${asin}/${f}`)
    }

    products.push({ asin, name, category, images })
  }

  // Deduplicate by ASIN (keep first occurrence)
  const seen = new Set<string>()
  return products.filter(p => {
    if (seen.has(p.asin)) return false
    seen.add(p.asin)
    return true
  })
}

// Also handle the table-based entries (ASINs in | ASIN | ... | format)
function parseTableProducts(md: string, existing: Set<string>): Product[] {
  const products: Product[] = []
  const tableRowRegex = /\|\s*(B\w{9,})\s*\|[^|]*\|[^|]*\|/g
  let m
  while ((m = tableRowRegex.exec(md)) !== null) {
    const asin = m[1].trim()
    if (existing.has(asin)) continue
    existing.add(asin)

    const imgDir = join(IMAGES_BASE, asin)
    let images: string[] = []
    if (existsSync(imgDir)) {
      images = readdirSync(imgDir)
        .filter(f => /\.(jpg|jpeg|png|webp)$/i.test(f))
        .map(f => `/api/content/images/${asin}/${f}`)
    }
    products.push({ asin, name: asin, category: 'Hand Sanitizing Wipes', images })
  }
  return products
}

export async function GET() {
  try {
    if (!existsSync(PRODUCTS_FILE)) {
      return NextResponse.json({ products: [] })
    }

    const md = readFileSync(PRODUCTS_FILE, 'utf-8')
    const products = parseProducts(md)
    const seen = new Set(products.map(p => p.asin))
    const tableProducts = parseTableProducts(md, seen)

    return NextResponse.json({ products: [...products, ...tableProducts] })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
