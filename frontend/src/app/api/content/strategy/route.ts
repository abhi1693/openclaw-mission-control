import { NextResponse } from 'next/server'
import { readFileSync } from 'fs'
import path from 'path'

function parseProducts() {
  try {
    const file = readFileSync(
      path.join(process.env.HOME || '', '.openclaw/workspace/config/zoviro-products.md'),
      'utf-8'
    )
    const products: { asin: string; name: string; category: string }[] = []
    const lines = file.split('\n')
    let currentCategory = ''
    for (const line of lines) {
      if (line.startsWith('## ')) currentCategory = line.replace('## ', '').trim()
      const m = line.match(/\*\*(.+?)\*\*.*\(([A-Z0-9]{10})\)/)
      if (m) products.push({ asin: m[2], name: m[1], category: currentCategory })
    }
    return products
  } catch {
    return []
  }
}

function generateAplus(asin: string, extras?: string): { markdown: string; prompts: { label: string; prompt: string }[] } {
  const products = parseProducts()
  const product = products.find(p => p.asin === asin)
  const productName = product?.name || `Product (${asin})`
  const category = product?.category || 'Health & Beauty'

  const markdown = `# A+ Content Strategy — ${productName}
**ASIN:** ${asin}
**Category:** ${category}
${extras ? `**Notes:** ${extras}` : ''}

---

## Module 1: Brand Story Header
**Type:** Brand Story Header (Full Width)
**Copy Suggestion:**
> Rooted in nature, refined by science. ZOVIRO was founded on the belief that your skin deserves the purest ingredients — no compromise, no shortcuts.

**Image Description:** Wide lifestyle banner featuring clean, minimalist lab-to-nature aesthetic. Show botanicals alongside precision dropper bottles. Warm natural light, earth tones.

**Gemini Prompt:** "Create a wide panoramic banner for a premium skincare brand. Left side: lush botanical garden with key herbs. Right side: elegant glass bottles in a clean white lab setting. Seamless gradient transition. Warm golden hour lighting. Ultra-HD photorealistic."

---

## Module 2: Product Overview
**Type:** Product Feature (4-image grid)
**Copy Suggestion:**
> **${productName}** — designed for results you can see and feel. Formulated with clinically-tested actives and zero unnecessary additives.

**Image Description:** Product hero shot from multiple angles — front, back label close-up, texture swatch, and lifestyle in-use shot.

**Gemini Prompt:** "Professional product photography of a skincare serum bottle. Four-panel layout: (1) Hero front view on white marble, (2) Back label macro with ingredient list, (3) Serum texture drop on fingertip, (4) Person applying product to glowing skin. Clean, clinical aesthetic."

---

## Module 3: Ingredient Spotlight
**Type:** Ingredients Highlight (3-column)
**Copy Suggestion:**
> **What's inside matters.** Every ingredient is chosen for a reason — sourced responsibly, tested rigorously, and included at effective concentrations.

**Image Description:** Three hero ingredients shown as macro botanical shots with name overlays. Clean white background with subtle shadow.

**Gemini Prompt:** "Macro photography of three hero skincare ingredients: (1) Fresh aloe vera cross-section showing gel, (2) Vitamin C crystal cluster with citrus half, (3) Hyaluronic acid molecule visualization with water droplets. Consistent minimalist white background, studio lighting, ultra-sharp detail."

---

## Module 4: Comparison Chart
**Type:** Comparison Table
**Copy Suggestion:**
> See the ZOVIRO difference. We don't cut corners — compare us side by side.

**Image Description:** Clean infographic-style comparison table. ZOVIRO column highlighted in brand green. Competitor column in neutral gray. Check marks and X marks in flat icon style.

**Gemini Prompt:** "Clean minimal infographic comparison chart design. Two columns: left labeled 'ZOVIRO' with green accent color (#2D7D5A), right labeled 'Others' in gray. Rows: Key Actives, Concentration %, Paraben-Free, Dermatologist Tested, Cruelty-Free. Green checkmarks vs gray X marks. White background, sans-serif typography."

---

## Module 5: How to Use
**Type:** Step-by-Step (numbered)
**Copy Suggestion:**
> Simple. Consistent. Effective. Three steps to better skin — morning and night.

**Image Description:** Three-panel horizontal sequence showing application steps. Model with clean skin, no heavy makeup. Soft daylight bathroom setting.

**Gemini Prompt:** "Three-step skincare routine photography. Panel 1: Cleansed face, hands cupping water. Panel 2: Applying serum with fingertips to cheek, gentle press. Panel 3: Final glowing skin close-up, dewy texture. Consistent soft natural light, neutral bathroom backdrop, diverse skin tone model."

---

## Module 6: Customer Benefits
**Type:** Benefits Bar (icon + text)
**Copy Suggestion:**
> Real results. Real people. Over 10,000 five-star reviews and counting.
> - ✦ Visible results in 14 days
> - ✦ Suitable for sensitive skin
> - ✦ Dermatologist tested
> - ✦ Free from parabens, sulfates & artificial fragrance

**Image Description:** Flat icon set with benefit labels. Consistent line-art style, brand color palette. Arranged horizontally with dividers.

**Gemini Prompt:** "Flat vector icon set for skincare brand benefits. Four icons in consistent line-art style, brand green color: (1) Calendar with checkmark for '14-Day Results', (2) Leaf for 'Clean Ingredients', (3) Shield with cross for 'Dermatologist Tested', (4) Heart for 'Sensitive Skin Safe'. White background, modern minimal design."

---

## Module 7: Cross-sell
**Type:** Cross-sell / Related Products
**Copy Suggestion:**
> Complete your ZOVIRO routine. Our products are designed to work together — better results, fewer steps.

**Image Description:** Flat lay of 3–4 complementary products arranged together. Matching aesthetic — white/marble surface, consistent lighting. Subtle "Complete the Set" text overlay.

**Gemini Prompt:** "Elegant flat lay product photography of 4 complementary skincare products from the same brand. White marble surface, soft natural side lighting. Products arranged in a slight arc. Brand color tags visible. '${productName} Collection' text overlay in minimalist sans-serif. Ultra-HD commercial quality."
`

  const prompts = [
    { label: 'Module 1 – Brand Story Header', prompt: 'Create a wide panoramic banner for a premium skincare brand. Left side: lush botanical garden with key herbs. Right side: elegant glass bottles in a clean white lab setting. Seamless gradient transition. Warm golden hour lighting. Ultra-HD photorealistic.' },
    { label: 'Module 2 – Product Overview', prompt: `Professional product photography of a skincare serum bottle. Four-panel layout: (1) Hero front view on white marble, (2) Back label macro with ingredient list, (3) Serum texture drop on fingertip, (4) Person applying product to glowing skin. Clean, clinical aesthetic.` },
    { label: 'Module 3 – Ingredient Spotlight', prompt: 'Macro photography of three hero skincare ingredients: (1) Fresh aloe vera cross-section showing gel, (2) Vitamin C crystal cluster with citrus half, (3) Hyaluronic acid molecule visualization with water droplets. Consistent minimalist white background, studio lighting, ultra-sharp detail.' },
    { label: 'Module 4 – Comparison Chart', prompt: "Clean minimal infographic comparison chart design. Two columns: 'ZOVIRO' with green accent and 'Others' in gray. Rows for Key Actives, Concentration, Paraben-Free, Dermatologist Tested, Cruelty-Free. Green checkmarks vs gray X marks. White background, sans-serif typography." },
    { label: 'Module 5 – How to Use', prompt: 'Three-step skincare routine photography. Panel 1: Cleansed face, hands cupping water. Panel 2: Applying serum with fingertips to cheek. Panel 3: Final glowing skin close-up, dewy texture. Consistent soft natural light, neutral bathroom backdrop.' },
    { label: 'Module 6 – Customer Benefits', prompt: 'Flat vector icon set for skincare brand benefits. Four icons in consistent line-art style, brand green color: Calendar for 14-Day Results, Leaf for Clean Ingredients, Shield for Dermatologist Tested, Heart for Sensitive Skin Safe. White background, modern minimal design.' },
    { label: 'Module 7 – Cross-sell', prompt: `Elegant flat lay product photography of 4 complementary skincare products from the same brand. White marble surface, soft natural side lighting. Products arranged in a slight arc. '${productName} Collection' text overlay in minimalist sans-serif. Ultra-HD commercial quality.` },
  ]

  return { markdown, prompts }
}

function generateStore(category: string, season: string, extras?: string): { markdown: string; prompts: { label: string; prompt: string }[] } {
  const markdown = `# Brand Store Strategy — ${category}
**Season:** ${season}
${extras ? `**Notes:** ${extras}` : ''}

---

## Section 1: Hero Banner
**Copy Suggestion:**
> **${season} Essentials** — Discover ZOVIRO's curated ${category.toLowerCase()} collection for the season ahead.
> *Shop now — free shipping on orders $50+*

**Image Description:** Full-width hero banner with seasonal color palette. Feature 2–3 hero products styled with seasonal props (e.g., spring florals, autumn leaves). Brand logo prominent top-left.

**Gemini Prompt:** "E-commerce hero banner for ${season} season, ${category} brand ZOVIRO. Seasonal color palette (${season === 'Spring' ? 'soft pastels, blush, sage green' : season === 'Summer' ? 'bright white, coral, aqua' : season === 'Fall' ? 'warm amber, terracotta, deep green' : 'icy blue, silver, deep navy'}). Three premium product bottles center-stage. Seasonal botanical props. Brand name 'ZOVIRO' in top-left. 3:1 wide format. Ultra-HD photorealistic."

---

## Section 2: Featured Products
**Copy Suggestion:**
> **Bestsellers this ${season}** — Our customers can't stop talking about these.

**Image Description:** Grid of 4–6 product images. Consistent clean white background, product name and brief descriptor below each.

**Gemini Prompt:** "Clean e-commerce product grid photography. ${season} themed styling. 6 skincare product bottles on white background, arranged in 2-row grid. Each with soft drop shadow. Consistent warm studio lighting. Minimalist, premium aesthetic."

---

## Section 3: Brand Story
**Copy Suggestion:**
> **Why ZOVIRO?**
> We started with one question: why do most skincare products have so many ingredients you can't pronounce?
> ZOVIRO was built differently — every formula starts with a purpose, not a trend.

**Image Description:** Split layout — left: founder/team lifestyle shot or lab imagery. Right: bold copy on brand color background.

**Gemini Prompt:** "Brand story section for premium skincare company. Split composition: left side shows hands working in a clean laboratory with botanical ingredients, right side is solid brand green (#2D7D5A) with space for white text. Warm, authentic, approachable. Natural light photography style."

---

## Section 4: Seasonal Promotion
**Copy Suggestion:**
> **${season} Sale — Up to 20% Off**
> Limited time. Stock up on your favorites or try something new.
> *Use code: ${season.toUpperCase()}ZOVIRO at checkout*

**Image Description:** Promotional banner with bold typography, countdown urgency element, and bright CTA button. Seasonal color accent.

**Gemini Prompt:** "Promotional sale banner for ${season} skincare sale. Bold typography '${season} Sale — 20% Off'. Bright accent color CTA button 'Shop Now'. Product arrangement with price tags. Festive but premium feel. Clean white and brand green color scheme."

---

## Section 5: Customer Reviews
**Copy Suggestion:**
> **What our customers say**
> ★★★★★ "This changed my skincare routine completely." — Sarah M., Verified Purchase
> ★★★★★ "I've tried everything. This is the one." — James K., Verified Purchase

**Image Description:** Social proof section with star ratings, circular customer avatars, short quote excerpts. Light neutral background, warm card design.

**Gemini Prompt:** "Social proof / testimonial section design for e-commerce. Three review cards side by side. Each with 5 gold stars, circular customer avatar photo, short quote text, verified badge. Light warm background (#F9F6F2), rounded cards with subtle shadow. Modern, trustworthy aesthetic."
`

  const prompts = [
    { label: 'Section 1 – Hero Banner', prompt: `E-commerce hero banner for ${season} season, ${category} brand ZOVIRO. Seasonal color palette. Three premium product bottles center-stage. Seasonal botanical props. 'ZOVIRO' in top-left. 3:1 wide format. Ultra-HD photorealistic.` },
    { label: 'Section 2 – Featured Products', prompt: `Clean e-commerce product grid photography. ${season} themed styling. 6 skincare product bottles on white background, 2-row grid. Consistent warm studio lighting. Minimalist, premium aesthetic.` },
    { label: 'Section 3 – Brand Story', prompt: 'Brand story section for premium skincare company. Split composition: left shows hands in a clean laboratory with botanicals, right is solid brand green with space for white text. Warm, authentic. Natural light photography style.' },
    { label: 'Section 4 – Seasonal Promotion', prompt: `Promotional sale banner for ${season} skincare sale. Bold typography. Bright CTA button. Product arrangement. Festive but premium. Clean white and brand green color scheme.` },
    { label: 'Section 5 – Customer Reviews', prompt: 'Social proof testimonial section design. Three review cards side by side. Each with 5 gold stars, circular customer avatar, short quote text, verified badge. Light warm background, rounded cards with subtle shadow. Modern, trustworthy.' },
  ]

  return { markdown, prompts }
}

function generateCampaign(
  asins: string[],
  scenario: string,
  channels: string[],
  extras?: string
): { markdown: string; prompts: { label: string; prompt: string }[] } {
  const products = parseProducts()
  const selectedProducts = asins.map(asin => {
    const p = products.find(x => x.asin === asin)
    return p ? p.name : `Product (${asin})`
  })
  const productList = selectedProducts.join(', ')

  const allChannels = channels.length > 0 ? channels : ['Amazon', 'Instagram', 'TikTok', 'Email']

  const channelSections: string[] = []
  const prompts: { label: string; prompt: string }[] = []

  for (const channel of allChannels) {
    if (channel.toLowerCase() === 'amazon') {
      channelSections.push(`## Channel: Amazon
**Scenario:** ${scenario}
**Products:** ${productList}

**Copy Suggestion (Sponsored Brand Ad):**
> Discover ZOVIRO — ${scenario}. Premium formulas, real results.

**Copy Suggestion (Product Description Update):**
> **Perfect for ${scenario}.** ${productList} — shop the collection.

**Image Prompt:**
> Clean product bundle flat lay on white marble. All ${asins.length} products arranged together. Subtle "${scenario}" text overlay. Amazon-optimized 1:1 format.

**Gemini Prompt:** "Amazon sponsored brand ad image. Product bundle of ${asins.length} premium skincare items on white marble surface. Golden hour side lighting. '${scenario}' text badge in top-right. Clean, conversion-optimized. 1:1 square format, 1000x1000px."

**Size:** 1000×1000px (main image), 1200×628px (headline banner)

---`)
      prompts.push({ label: 'Amazon – Sponsored Brand Ad', prompt: `Amazon sponsored brand ad image. Product bundle of ${asins.length} premium skincare items on white marble surface. Golden hour side lighting. '${scenario}' text badge in top-right. Clean, conversion-optimized. 1:1 square format.` })
    }

    if (channel.toLowerCase() === 'instagram') {
      channelSections.push(`## Channel: Instagram
**Scenario:** ${scenario}
**Products:** ${productList}

**Feed Post Copy:**
> Your skin called. It wants ${productList}. ✨
> This ${scenario} — give it what it deserves.
> Shop via link in bio 🔗
> #ZOVIRO #CleanBeauty #${scenario.replace(/\s+/g, '')} #SkincareRoutine

**Story Copy:**
> Swipe up → ${scenario} deals are LIVE 🎉
> ${selectedProducts[0] || 'Shop now'} + more in the collection.

**Reel Hook (first 3 seconds):**
> "POV: your skincare glow-up starts TODAY 💚"

**Image Prompt:**
> Aesthetic Instagram flat lay. ${productList} products surrounded by seasonal props. Warm golden light. Slight film grain for organic feel.

**Gemini Prompt:** "Instagram-worthy flat lay product photography. ${productList} skincare products surrounded by fresh botanicals and seasonal props. Warm golden side light. Slight film grain texture for organic social feel. 4:5 portrait format, 1080×1350px."

**Size:** Feed: 1080×1080px or 1080×1350px | Story/Reels: 1080×1920px

---`)
      prompts.push({ label: 'Instagram – Feed Post', prompt: `Instagram-worthy flat lay product photography. ${productList} skincare products surrounded by fresh botanicals and seasonal props. Warm golden side light. Slight film grain texture. 4:5 portrait format, 1080×1350px.` })
    }

    if (channel.toLowerCase() === 'tiktok') {
      channelSections.push(`## Channel: TikTok
**Scenario:** ${scenario}
**Products:** ${productList}

**Hook Script (0–3s):**
> "Wait — you're NOT using this for ${scenario}?? 😱"

**Body Script (3–15s):**
> "Okay so I've been obsessed with ${selectedProducts[0] || 'this'} lately. It's literally perfect for ${scenario}. Let me show you why..."

**CTA (15–20s):**
> "Link in bio — they ship fast and the bundle deal is actually insane right now."

**Trending Format:** Before/After skin transformation | GRWM (Get Ready With Me) | "Things I bought that actually work"

**Thumbnail Prompt:**
> Bold eye-catching TikTok thumbnail. Split before/after or bold product close-up. Text overlay "${scenario}" in large font. High saturation, attention-grabbing.

**Gemini Prompt:** "TikTok video thumbnail for skincare brand. Bold split-screen: left side dull skin / right side glowing skin. Product bottle ${selectedProducts[0] || 'ZOVIRO'} prominent center. Large bold text '${scenario}' at top. High contrast, vibrant colors. 9:16 vertical format, 1080×1920px."

**Size:** 1080×1920px (9:16 vertical)

---`)
      prompts.push({ label: 'TikTok – Video Thumbnail', prompt: `TikTok video thumbnail for skincare brand. Bold split-screen: left dull skin / right glowing skin. Product bottle prominent center. Large bold text '${scenario}' at top. High contrast, vibrant colors. 9:16 vertical format, 1080×1920px.` })
    }

    if (channel.toLowerCase() === 'email') {
      channelSections.push(`## Channel: Email
**Scenario:** ${scenario}
**Products:** ${productList}

**Subject Line Options:**
- 🌿 Your ${scenario} skincare haul starts here
- Limited time: ${scenario} collection is LIVE
- Wei, your skin deserves this (${scenario} picks inside)
- Save 20% — ${scenario} sale ends Sunday

**Preheader Text:**
> Premium formulas, real results. Shop ${productList} →

**Email Body Copy:**
> **Hi [First Name],**
> 
> ${scenario} is the perfect time to refresh your routine.
> 
> We've put together our best-performing products — tried, tested, and trusted by thousands of customers:
> 
> ${selectedProducts.map((name, i) => `**${i + 1}. ${name}** — [Shop now →]`).join('\n> ')}
> 
> **[Shop the ${scenario} Collection →]**
> 
> Free shipping on all orders. Returns are easy.
> 
> — The ZOVIRO Team

**Hero Image Prompt:**
> Email header banner. ${productList} products in clean flat lay. "${scenario}" headline text overlay. Brand green accent. 600px wide (email-optimized).

**Gemini Prompt:** "Email marketing hero banner, 600px width email format. ZOVIRO skincare products ${productList} arranged elegantly on clean white surface. Bold serif headline '${scenario} Collection' in dark text. Brand green (#2D7D5A) accent border. Professional, conversion-focused design."

**Size:** 600×300px (email header banner)

---`)
      prompts.push({ label: 'Email – Hero Banner', prompt: `Email marketing hero banner, 600px width. ZOVIRO skincare products arranged elegantly on clean white surface. Bold serif headline '${scenario} Collection'. Brand green (#2D7D5A) accent. Professional, conversion-focused design.` })
    }
  }

  const markdown = `# Campaign Strategy — ${scenario}
**Products:** ${productList}
**Channels:** ${allChannels.join(', ')}
${extras ? `**Notes:** ${extras}` : ''}

---

${channelSections.join('\n')}
`

  return { markdown, prompts }
}

export async function POST(req: Request) {
  try {
    const body = await req.json()
    const { type, asin, asins, category, season, scenario, channels, extras } = body

    if (!type) {
      return NextResponse.json({ error: 'type is required (aplus | store | campaign)' }, { status: 400 })
    }

    if (type === 'aplus') {
      if (!asin) return NextResponse.json({ error: 'asin is required for type=aplus' }, { status: 400 })
      const result = generateAplus(asin, extras)
      return NextResponse.json(result)
    }

    if (type === 'store') {
      if (!category) return NextResponse.json({ error: 'category is required for type=store' }, { status: 400 })
      const result = generateStore(category, season || 'All Season', extras)
      return NextResponse.json(result)
    }

    if (type === 'campaign') {
      if (!asins || !Array.isArray(asins) || asins.length === 0) {
        return NextResponse.json({ error: 'asins (array) is required for type=campaign' }, { status: 400 })
      }
      if (!scenario) return NextResponse.json({ error: 'scenario is required for type=campaign' }, { status: 400 })
      const result = generateCampaign(asins, scenario, channels || [], extras)
      return NextResponse.json(result)
    }

    return NextResponse.json({ error: `Unknown type: ${type}. Use aplus | store | campaign` }, { status: 400 })
  } catch (err) {
    console.error('[strategy/route] error:', err)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
