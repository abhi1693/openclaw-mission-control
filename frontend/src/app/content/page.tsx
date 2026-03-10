'use client'

import { useEffect, useState, useRef, useCallback } from 'react'
import {
  Sparkles, Upload, Copy, Star, Trash2, ChevronDown, ChevronUp,
  Image as ImageIcon, X, Check, Wand2, Clapperboard,
} from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { DashboardPageLayout } from '@/components/templates/DashboardPageLayout'

// ─── Types ────────────────────────────────────────────────────────────────────

interface Product {
  asin: string
  name: string
  category: string
  images: string[]
}

interface PromptEntry {
  id: string
  asin: string
  productName: string
  type: string
  style: string
  tone: string
  platform: string
  extras: string
  geminiPrompt: string
  midjourneyPrompt: string
  starred: boolean
  createdAt: string
}

// ─── Scene Types ──────────────────────────────────────────────────────────────

const SCENE_TYPES = [
  { id: 'main',       label: 'Main Image',         emoji: '⬜', desc: 'on pure white background, centered, studio lighting, product photography' },
  { id: 'lifestyle',  label: 'Lifestyle',          emoji: '🛁', desc: 'in a cozy bathroom setting, natural morning light, lifestyle photography' },
  { id: 'closeup',    label: 'Ingredient Close-up', emoji: '🔬', desc: 'macro shot of key ingredients, artistic arrangement, soft focus background' },
  { id: 'comparison', label: 'Comparison',         emoji: '⚖️', desc: 'split-screen before and after comparison, clean layout' },
  { id: 'packaging',  label: 'Packaging',          emoji: '📦', desc: 'elegant product packaging, 45-degree angle, premium feel' },
  { id: 'custom',     label: 'Custom',             emoji: '✏️', desc: '' },
] as const
type SceneId = typeof SCENE_TYPES[number]['id']

const STYLES = ['Photography', '3D Render', 'Illustration', 'Minimal'] as const
type StyleType = typeof STYLES[number]

const TONES = ['Brand (Gold+Black)', 'Warm', 'Cool', 'Natural'] as const
type ToneType = typeof TONES[number]

const PLATFORMS = ['Amazon', 'Instagram', 'TikTok'] as const
type PlatformType = typeof PLATFORMS[number]

const PLATFORM_SPECS: Record<PlatformType, { spec: string; ar: string }> = {
  Amazon:    { spec: 'white background, high resolution, product-focused, 1:1 ratio', ar: '1:1' },
  Instagram: { spec: 'lifestyle aesthetic, vibrant colors, 4:5 portrait or 1:1 square', ar: '4:5' },
  TikTok:    { spec: 'vertical format, bold visuals, 9:16 aspect ratio', ar: '9:16' },
}

// ─── Prompt Generator ─────────────────────────────────────────────────────────

function generateGeminiPrompt(
  product: Product,
  scene: SceneId,
  style: StyleType,
  tone: ToneType,
  platform: PlatformType,
  extras: string,
  customDesc: string,
) {
  const sceneType = SCENE_TYPES.find(s => s.id === scene)!
  const sceneDesc = scene === 'custom' ? customDesc : sceneType.desc
  const { spec } = PLATFORM_SPECS[platform]
  const shortName = product.name.split(',')[0].trim()

  return `Create a ${style.toLowerCase()} ${sceneType.label.toLowerCase()} image of ${shortName}.

Scene: ${sceneDesc}

Color palette: ${tone} tones${tone === 'Brand (Gold+Black)' ? ' — gold accents on deep black background' : ''}.

Platform optimization: ${platform} (${spec}).
${extras ? `\nAdditional details: ${extras}` : ''}
Product description: ${product.name}
ASIN: ${product.asin} | Category: ${product.category}`
}

function generateMidjourneyPrompt(
  product: Product,
  scene: SceneId,
  style: StyleType,
  tone: ToneType,
  platform: PlatformType,
  extras: string,
  customDesc: string,
) {
  const sceneType = SCENE_TYPES.find(s => s.id === scene)!
  const sceneDesc = scene === 'custom' ? customDesc : sceneType.desc
  const { ar } = PLATFORM_SPECS[platform]
  const shortName = product.name.split(',')[0].trim()
  const toneStr = tone === 'Brand (Gold+Black)' ? 'gold and black luxury tones' : `${tone.toLowerCase()} tones`

  return `/imagine ${sceneType.label.toLowerCase()} of ${shortName}, ${style.toLowerCase()} style, ${toneStr}, ${sceneDesc}${extras ? `, ${extras}` : ''}, professional product photography, high quality, detailed --ar ${ar} --style raw --v 6.1`
}

// ─── Copy Button ──────────────────────────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [text])
  return (
    <button
      onClick={handleCopy}
      className="flex items-center gap-1 text-[11px] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--primary))] transition-colors"
    >
      {copied ? <Check className="w-3 h-3 text-[hsl(var(--primary))]" /> : <Copy className="w-3 h-3" />}
      {copied ? 'Copied!' : 'Copy'}
    </button>
  )
}

// ─── Image Upload Modal ───────────────────────────────────────────────────────

function UploadModal({
  asin,
  images,
  onClose,
  onUploaded,
}: {
  asin: string
  images: { name: string; url: string }[]
  onClose: () => void
  onUploaded: () => void
}) {
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [localImages, setLocalImages] = useState(images)
  const fileRef = useRef<HTMLInputElement>(null)

  const doUpload = useCallback(async (file: File) => {
    if (uploading) return
    setUploading(true)
    const fd = new FormData()
    fd.append('asin', asin)
    fd.append('file', file)
    try {
      const res = await fetch('/api/content/images', { method: 'POST', body: fd })
      const data = await res.json()
      if (data.url) {
        setLocalImages(prev => [...prev, { name: data.name, url: data.url }])
        onUploaded()
      }
    } finally {
      setUploading(false)
    }
  }, [asin, uploading, onUploaded])

  const handleFiles = useCallback((files: FileList | null) => {
    if (!files || files.length === 0) return
    doUpload(files[0])
  }, [doUpload])

  const handleDelete = useCallback(async (fileName: string) => {
    await fetch(`/api/content/images?asin=${asin}&file=${encodeURIComponent(fileName)}`, { method: 'DELETE' })
    setLocalImages(prev => prev.filter(i => i.name !== fileName))
    onUploaded()
  }, [asin, onUploaded])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm" onClick={onClose}>
      <Card
        className="w-full max-w-lg bg-[hsl(var(--card))] border-[hsl(var(--border))] p-6 space-y-5"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-slate-900 flex items-center gap-2">
            <ImageIcon className="w-4 h-4 text-[hsl(var(--primary))]" />
            Reference Images — {asin}
          </h3>
          <button onClick={onClose} className="p-1 hover:bg-[hsl(var(--secondary))] rounded">
            <X className="w-4 h-4 text-[hsl(var(--muted-foreground))]" />
          </button>
        </div>

        {/* Drop Zone */}
        <div
          className={`border-2 border-dashed rounded-xl p-8 text-center transition-colors cursor-pointer ${
            dragging
              ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.08)]'
              : 'border-[hsl(var(--border))] hover:border-[hsl(var(--primary)/0.4)]'
          }`}
          onDragOver={e => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={e => { e.preventDefault(); setDragging(false); handleFiles(e.dataTransfer.files) }}
          onClick={() => fileRef.current?.click()}
        >
          <Upload className="w-8 h-8 mx-auto mb-2 text-[hsl(var(--muted-foreground))]" />
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            {uploading ? 'Uploading…' : 'Drop or click to upload'}
          </p>
          <p className="text-[11px] text-[hsl(var(--muted-foreground)/0.5)] mt-1">JPG, PNG, WebP · max 5 MB</p>
          <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={e => handleFiles(e.target.files)} />
        </div>

        {/* Existing Images */}
        {localImages.length > 0 && (
          <div>
            <p className="text-[11px] text-[hsl(var(--muted-foreground))] uppercase tracking-wider mb-3">Uploaded ({localImages.length})</p>
            <div className="grid grid-cols-3 gap-2">
              {localImages.map(img => (
                <div key={img.name} className="relative group aspect-square rounded-lg overflow-hidden bg-[hsl(var(--secondary))]">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={img.url} alt={img.name} className="w-full h-full object-cover" />
                  <button
                    onClick={() => handleDelete(img.name)}
                    className="absolute top-1 right-1 p-0.5 rounded bg-black/70 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-600"
                  >
                    <Trash2 className="w-3 h-3 text-slate-900" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </Card>
    </div>
  )
}

// ─── History Entry ────────────────────────────────────────────────────────────

function HistoryEntry({
  entry,
  onToggleStar,
  onDelete,
}: {
  entry: PromptEntry
  onToggleStar: (id: string, starred: boolean) => void
  onDelete: (id: string) => void
}) {
  const [expanded, setExpanded] = useState(false)

  return (
    <Card className="p-4 bg-[hsl(var(--card))] border-[hsl(var(--border))] space-y-2.5 hover:border-[hsl(var(--primary)/0.3)] transition-colors">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-1 flex-wrap">
            <Badge variant="outline" className="text-[9px] border-[hsl(var(--primary)/0.3)] text-[hsl(var(--primary))]">
              {entry.type}
            </Badge>
            <Badge variant="accent" className="text-[9px]">
              {entry.platform}
            </Badge>
            {entry.starred && <Star className="w-3 h-3 text-yellow-600 fill-yellow-400" />}
          </div>
          <p className="text-xs font-medium text-slate-900 truncate">{entry.productName.split(',')[0]}</p>
          <p className="text-[10px] text-[hsl(var(--muted-foreground))] mt-0.5">
            {new Date(entry.createdAt).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
          </p>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          <button
            onClick={() => onToggleStar(entry.id, !entry.starred)}
            className="p-1 hover:bg-[hsl(var(--secondary))] rounded transition-colors"
          >
            <Star className={`w-3.5 h-3.5 ${entry.starred ? 'text-yellow-600 fill-yellow-400' : 'text-[hsl(var(--muted-foreground))]'}`} />
          </button>
          <button
            onClick={() => onDelete(entry.id)}
            className="p-1 hover:bg-[hsl(var(--secondary))] rounded text-[hsl(var(--muted-foreground))] hover:text-red-600 transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => setExpanded(e => !e)}
            className="p-1 hover:bg-[hsl(var(--secondary))] rounded text-[hsl(var(--muted-foreground))]"
          >
            {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      {/* Preview */}
      {!expanded && (
        <p className="text-[11px] text-[hsl(var(--muted-foreground))] line-clamp-2 leading-relaxed">
          {entry.geminiPrompt}
        </p>
      )}

      {/* Expanded */}
      {expanded && (
        <div className="space-y-3 pt-2 border-t border-[hsl(var(--border))]">
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] font-semibold text-[hsl(var(--primary))] uppercase tracking-wider">Gemini</span>
              <CopyButton text={entry.geminiPrompt} />
            </div>
            <pre className="text-[11px] text-[hsl(var(--muted-foreground))] whitespace-pre-wrap leading-relaxed bg-[hsl(var(--secondary)/0.5)] rounded p-2 font-sans">
              {entry.geminiPrompt}
            </pre>
          </div>
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] font-semibold text-blue-600 uppercase tracking-wider">Midjourney</span>
              <CopyButton text={entry.midjourneyPrompt} />
            </div>
            <pre className="text-[11px] text-[hsl(var(--muted-foreground))] whitespace-pre-wrap leading-relaxed bg-[hsl(var(--secondary)/0.5)] rounded p-2 font-sans">
              {entry.midjourneyPrompt}
            </pre>
          </div>
        </div>
      )}
    </Card>
  )
}

// ─── A+ Content Tab ───────────────────────────────────────────────────────────

function AplusTab() {
  const [products, setProducts] = useState<Product[]>([])
  const [loadingProducts, setLoadingProducts] = useState(true)
  const [selectedAsin, setSelectedAsin] = useState('')
  const [images, setImages] = useState<{ name: string; url: string }[]>([])
  const [loadingImages, setLoadingImages] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [strategy, setStrategy] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  // Load products
  useEffect(() => {
    fetch('/api/content/products')
      .then(r => r.json())
      .then(d => {
        setProducts(d.products || [])
        setLoadingProducts(false)
      })
      .catch(() => setLoadingProducts(false))
  }, [])

  // Load images when ASIN changes
  useEffect(() => {
    if (!selectedAsin) {
      setImages([])
      return
    }
    setLoadingImages(true)
    fetch(`/api/content/images?asin=${selectedAsin}`)
      .then(r => r.json())
      .then(d => {
        setImages(d.images || [])
        setLoadingImages(false)
      })
      .catch(() => setLoadingImages(false))
  }, [selectedAsin])

  const handleGenerate = useCallback(async () => {
    if (!selectedAsin) return
    setGenerating(true)
    setStrategy(null)
    setSaved(false)
    try {
      const res = await fetch('/api/content/strategy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'aplus', asin: selectedAsin }),
      })
      const data = await res.json()
      setStrategy(data.content ?? data.strategy ?? data.result ?? JSON.stringify(data))
    } finally {
      setGenerating(false)
    }
  }, [selectedAsin])

  const handleSave = useCallback(async () => {
    if (!strategy) return
    setSaving(true)
    try {
      await fetch('/api/content/strategy/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'aplus', asin: selectedAsin, content: strategy }),
      })
      setSaved(true)
    } finally {
      setSaving(false)
    }
  }, [strategy, selectedAsin])

  return (
    <div className="flex gap-6">
      {/* Left Column */}
      <div className="w-[320px] flex-shrink-0 space-y-4">
        <Card className="p-5 bg-[hsl(var(--card))] border-[hsl(var(--border))] space-y-4">
          <h3 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
            <span className="text-base">📄</span>
            A+ Content 生成
          </h3>

          {/* ASIN Selector */}
          <div className="space-y-1.5">
            <label className="text-[11px] text-[hsl(var(--muted-foreground))] uppercase tracking-wider block">选择产品</label>
            {loadingProducts ? (
              <Skeleton className="h-9 w-full" />
            ) : (
              <div className="relative">
                <select
                  value={selectedAsin}
                  onChange={e => { setSelectedAsin(e.target.value); setStrategy(null); setSaved(false) }}
                  className="w-full h-9 rounded-lg bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] text-slate-900 text-sm px-3 pr-8 appearance-none focus:outline-none focus:border-[hsl(var(--primary)/0.5)] transition-colors"
                >
                  <option value="">— 选择 ASIN —</option>
                  {products.map(p => (
                    <option key={p.asin} value={p.asin}>
                      {p.name.split(',')[0].trim()} ({p.asin})
                    </option>
                  ))}
                </select>
                <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[hsl(var(--muted-foreground))] pointer-events-none" />
              </div>
            )}
          </div>

          {/* Reference Image Thumbnails */}
          {selectedAsin && (
            <div className="space-y-1.5">
              <label className="text-[11px] text-[hsl(var(--muted-foreground))] uppercase tracking-wider block">参考图</label>
              {loadingImages ? (
                <div className="flex gap-2">
                  {[1, 2, 3].map(i => <Skeleton key={i} className="w-14 h-14 rounded-lg" />)}
                </div>
              ) : images.length > 0 ? (
                <div className="flex gap-2 flex-wrap">
                  {images.slice(0, 4).map(img => (
                    <div key={img.name} className="w-14 h-14 rounded-lg overflow-hidden bg-[hsl(var(--secondary))] border border-[hsl(var(--border))]">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={img.url} alt={img.name} className="w-full h-full object-cover" />
                    </div>
                  ))}
                  {images.length > 4 && (
                    <div className="w-14 h-14 rounded-lg bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] flex items-center justify-center text-xs text-[hsl(var(--muted-foreground))]">
                      +{images.length - 4}
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-[11px] text-[hsl(var(--muted-foreground)/0.5)] italic">暂无参考图</p>
              )}
            </div>
          )}

          {/* Generate Button */}
          <Button
            onClick={handleGenerate}
            disabled={!selectedAsin || generating}
            className="w-full bg-green-600 hover:bg-green-500 text-slate-900 border-0 flex items-center justify-center gap-2"
            size="sm"
          >
            <Wand2 className="w-3.5 h-3.5" />
            {generating ? '生成中…' : '生成 A+ 方案'}
          </Button>
        </Card>
      </div>

      {/* Right Column */}
      <div className="flex-1 min-w-0 space-y-4">
        {/* Save Button */}
        {strategy && (
          <div className="flex justify-end">
            <Button
              variant="outline"
              size="sm"
              onClick={handleSave}
              disabled={saving || saved}
              className="flex items-center gap-1.5 text-xs"
            >
              {saved ? <Check className="w-3.5 h-3.5 text-[hsl(var(--primary))]" /> : null}
              {saved ? '已保存' : saving ? '保存中…' : '保存方案'}
            </Button>
          </div>
        )}

        {/* Content Area */}
        <Card className="p-6 bg-[hsl(var(--card))] border-[hsl(var(--border))] min-h-[400px]">
          {generating ? (
            <div className="space-y-3">
              <Skeleton className="h-6 w-48" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-5/6" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          ) : strategy ? (
            <article className="prose prose-invert prose-sm max-w-none
              prose-headings:text-[hsl(var(--foreground))]
              prose-h1:text-2xl prose-h1:font-bold prose-h1:mb-4
              prose-h2:text-lg prose-h2:font-semibold prose-h2:mt-6 prose-h2:mb-3
              prose-h3:text-base prose-h3:font-semibold prose-h3:mt-4 prose-h3:mb-2
              prose-p:text-[hsl(var(--muted-foreground))] prose-p:leading-relaxed
              prose-li:text-[hsl(var(--muted-foreground))]
              prose-strong:text-[hsl(var(--foreground))]
              prose-code:text-[hsl(var(--primary))] prose-code:bg-[hsl(var(--secondary))] prose-code:px-1 prose-code:rounded
              prose-pre:bg-[hsl(var(--secondary))] prose-pre:border prose-pre:border-[hsl(var(--border))]
              prose-table:text-base
              prose-th:text-[hsl(var(--foreground))] prose-th:bg-[hsl(var(--secondary))]
              prose-td:text-[hsl(var(--muted-foreground))]
              prose-hr:border-[hsl(var(--border))]
              prose-blockquote:border-[hsl(var(--primary))] prose-blockquote:text-[hsl(var(--muted-foreground))]
            ">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{strategy}</ReactMarkdown>
            </article>
          ) : (
            <div className="flex items-center justify-center h-full min-h-[360px]">
              <p className="text-[hsl(var(--muted-foreground)/0.5)] text-sm italic">
                选择产品并生成 A+ Content 方案
              </p>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}

// ─── Shared prose class ──────────────────────────────────────────────────────

const PROSE_CLASS = `prose prose-invert prose-sm max-w-none
  prose-headings:text-[hsl(var(--foreground))]
  prose-h1:text-2xl prose-h1:font-bold prose-h1:mb-4
  prose-h2:text-lg prose-h2:font-semibold prose-h2:mt-6 prose-h2:mb-3
  prose-h3:text-base prose-h3:font-semibold prose-h3:mt-4 prose-h3:mb-2
  prose-p:text-[hsl(var(--muted-foreground))] prose-p:leading-relaxed
  prose-li:text-[hsl(var(--muted-foreground))]
  prose-strong:text-[hsl(var(--foreground))]
  prose-code:text-[hsl(var(--primary))] prose-code:bg-[hsl(var(--secondary))] prose-code:px-1 prose-code:rounded
  prose-pre:bg-[hsl(var(--secondary))] prose-pre:border prose-pre:border-[hsl(var(--border))]
  prose-table:text-base
  prose-th:text-[hsl(var(--foreground))] prose-th:bg-[hsl(var(--secondary))]
  prose-td:text-[hsl(var(--muted-foreground))]
  prose-hr:border-[hsl(var(--border))]
  prose-blockquote:border-[hsl(var(--primary))] prose-blockquote:text-[hsl(var(--muted-foreground))]`

// ─── Store Tab ────────────────────────────────────────────────────────────────

const STORE_CATEGORIES = ['All Products', 'Body Care', 'Hand Sanitizer'] as const
const STORE_SEASONS = [
  { id: 'spring',      label: 'Spring 🌸' },
  { id: 'summer',      label: 'Summer ☀️' },
  { id: 'holiday',     label: 'Holiday 🎄' },
  { id: 'new-launch',  label: 'New Launch 🚀' },
] as const

function StoreTab() {
  const [selectedCategory, setSelectedCategory] = useState<string>('All Products')
  const [selectedSeason, setSelectedSeason] = useState<string>('spring')
  const [extras, setExtras] = useState('')
  const [generating, setGenerating] = useState(false)
  const [strategy, setStrategy] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const handleGenerate = useCallback(async () => {
    setGenerating(true)
    setStrategy(null)
    setSaved(false)
    try {
      const res = await fetch('/api/content/strategy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'store', category: selectedCategory, season: selectedSeason, extras }),
      })
      const data = await res.json()
      setStrategy(data.content ?? data.strategy ?? data.result ?? JSON.stringify(data))
    } finally {
      setGenerating(false)
    }
  }, [selectedCategory, selectedSeason, extras])

  const handleSave = useCallback(async () => {
    if (!strategy) return
    setSaving(true)
    try {
      await fetch('/api/content/strategy/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'store', asin: selectedCategory, markdown: strategy }),
      })
      setSaved(true)
    } finally {
      setSaving(false)
    }
  }, [strategy, selectedCategory])

  return (
    <div className="flex gap-6">
      {/* Left Column */}
      <div className="w-[320px] flex-shrink-0 space-y-4">
        <Card className="p-5 bg-[hsl(var(--card))] border-[hsl(var(--border))] space-y-5">
          <h3 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
            <span className="text-base">🏪</span>
            Brand Store 方案
          </h3>

          {/* Category */}
          <div className="space-y-2">
            <label className="text-[11px] text-[hsl(var(--muted-foreground))] uppercase tracking-wider block">品类</label>
            <div className="grid grid-cols-1 gap-2">
              {STORE_CATEGORIES.map(cat => (
                <button
                  key={cat}
                  onClick={() => setSelectedCategory(cat)}
                  className={`rounded-lg border px-3 py-2 cursor-pointer transition-all text-left text-sm ${
                    selectedCategory === cat
                      ? 'border-[hsl(var(--primary)/0.6)] bg-[hsl(var(--primary)/0.08)] text-slate-900'
                      : 'border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:border-[hsl(var(--primary)/0.3)]'
                  }`}
                >
                  {cat}
                </button>
              ))}
            </div>
          </div>

          {/* Season */}
          <div className="space-y-2">
            <label className="text-[11px] text-[hsl(var(--muted-foreground))] uppercase tracking-wider block">季节 / 主题</label>
            <div className="grid grid-cols-2 gap-2">
              {STORE_SEASONS.map(s => (
                <button
                  key={s.id}
                  onClick={() => setSelectedSeason(s.id)}
                  className={`rounded-lg border px-3 py-2 cursor-pointer transition-all text-sm ${
                    selectedSeason === s.id
                      ? 'border-[hsl(var(--primary)/0.6)] bg-[hsl(var(--primary)/0.08)] text-slate-900'
                      : 'border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:border-[hsl(var(--primary)/0.3)]'
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>

          {/* Extras */}
          <div className="space-y-1.5">
            <label className="text-[11px] text-[hsl(var(--muted-foreground))] uppercase tracking-wider block">附加描述（可选）</label>
            <textarea
              value={extras}
              onChange={e => setExtras(e.target.value)}
              placeholder="品牌故事、特别要求…"
              rows={3}
              className="w-full rounded-lg bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] text-slate-900 text-sm px-3 py-2 placeholder:text-[hsl(var(--muted-foreground)/0.5)] focus:outline-none focus:border-[hsl(var(--primary)/0.5)] transition-colors resize-none"
            />
          </div>

          {/* Generate */}
          <Button
            onClick={handleGenerate}
            disabled={generating}
            className="w-full bg-green-600 hover:bg-green-500 text-slate-900 border-0 flex items-center justify-center gap-2"
            size="sm"
          >
            <Wand2 className="w-3.5 h-3.5" />
            {generating ? '生成中…' : '生成 Store 方案'}
          </Button>
        </Card>
      </div>

      {/* Right Column */}
      <div className="flex-1 min-w-0 space-y-4">
        {strategy && (
          <div className="flex justify-end">
            <Button
              variant="outline"
              size="sm"
              onClick={handleSave}
              disabled={saving || saved}
              className="flex items-center gap-1.5 text-xs"
            >
              {saved ? <Check className="w-3.5 h-3.5 text-[hsl(var(--primary))]" /> : null}
              {saved ? '已保存' : saving ? '保存中…' : '保存方案'}
            </Button>
          </div>
        )}

        <Card className="p-6 bg-[hsl(var(--card))] border-[hsl(var(--border))] min-h-[400px]">
          {generating ? (
            <div className="space-y-3">
              <Skeleton className="h-6 w-48" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-5/6" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          ) : strategy ? (
            <article className={PROSE_CLASS}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{strategy}</ReactMarkdown>
            </article>
          ) : (
            <div className="flex items-center justify-center h-full min-h-[360px]">
              <p className="text-[hsl(var(--muted-foreground)/0.5)] text-sm italic">
                选择品类和季节，生成 Brand Store 方案
              </p>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}

// ─── Campaign Tab ─────────────────────────────────────────────────────────────

const CAMPAIGN_SCENARIOS = [
  { id: 'new-launch',       label: 'New Launch 🚀' },
  { id: 'holiday-promo',    label: 'Holiday Promo 🎄' },
  { id: 'seasonal',         label: 'Seasonal 🌿' },
  { id: 'flash-sale',       label: 'Flash Sale ⚡' },
  { id: 'brand-awareness',  label: 'Brand Awareness 📣' },
] as const

const CAMPAIGN_CHANNELS = ['Amazon', 'Instagram', 'TikTok', 'Email'] as const

function CampaignTab() {
  const [products, setProducts] = useState<Product[]>([])
  const [loadingProducts, setLoadingProducts] = useState(true)
  const [selectedAsins, setSelectedAsins] = useState<string[]>([])
  const [selectedScenario, setSelectedScenario] = useState<string>('new-launch')
  const [selectedChannels, setSelectedChannels] = useState<string[]>(['Amazon'])
  const [extras, setExtras] = useState('')
  const [generating, setGenerating] = useState(false)
  const [strategy, setStrategy] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    fetch('/api/content/products')
      .then(r => r.json())
      .then(d => {
        setProducts(d.products || [])
        setLoadingProducts(false)
      })
      .catch(() => setLoadingProducts(false))
  }, [])

  const toggleAsin = useCallback((asin: string) => {
    setSelectedAsins(prev => prev.includes(asin) ? prev.filter(a => a !== asin) : [...prev, asin])
  }, [])

  const toggleChannel = useCallback((ch: string) => {
    setSelectedChannels(prev => prev.includes(ch) ? prev.filter(c => c !== ch) : [...prev, ch])
  }, [])

  const handleGenerate = useCallback(async () => {
    setGenerating(true)
    setStrategy(null)
    setSaved(false)
    try {
      const res = await fetch('/api/content/strategy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: 'campaign',
          asins: selectedAsins,
          scenario: selectedScenario,
          channels: selectedChannels,
          extras,
        }),
      })
      const data = await res.json()
      setStrategy(data.content ?? data.strategy ?? data.result ?? JSON.stringify(data))
    } finally {
      setGenerating(false)
    }
  }, [selectedAsins, selectedScenario, selectedChannels, extras])

  const handleSave = useCallback(async () => {
    if (!strategy) return
    setSaving(true)
    try {
      await fetch('/api/content/strategy/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'campaign', asin: selectedAsins.join(','), markdown: strategy }),
      })
      setSaved(true)
    } finally {
      setSaving(false)
    }
  }, [strategy, selectedAsins])

  return (
    <div className="flex gap-6">
      {/* Left Column */}
      <div className="w-[320px] flex-shrink-0 space-y-4">
        <Card className="p-5 bg-[hsl(var(--card))] border-[hsl(var(--border))] space-y-5">
          <h3 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
            <span className="text-base">📢</span>
            营销方案
          </h3>

          {/* Products */}
          <div className="space-y-2">
            <label className="text-[11px] text-[hsl(var(--muted-foreground))] uppercase tracking-wider block">产品（多选）</label>
            {loadingProducts ? (
              <div className="space-y-2">
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-full" />
              </div>
            ) : (
              <div className="space-y-1.5 max-h-[160px] overflow-y-auto pr-1">
                {products.map(p => {
                  const checked = selectedAsins.includes(p.asin)
                  return (
                    <label
                      key={p.asin}
                      className={`flex items-start gap-2.5 rounded-lg border px-3 py-2 cursor-pointer transition-all ${
                        checked
                          ? 'border-[hsl(var(--primary)/0.6)] bg-[hsl(var(--primary)/0.08)]'
                          : 'border-[hsl(var(--border))] hover:border-[hsl(var(--primary)/0.3)]'
                      }`}
                    >
                      <span className={`mt-0.5 w-4 h-4 flex-shrink-0 rounded border flex items-center justify-center transition-colors ${
                        checked
                          ? 'bg-[hsl(var(--primary))] border-[hsl(var(--primary))]'
                          : 'border-[hsl(var(--border))] bg-transparent'
                      }`}>
                        {checked && <Check className="w-2.5 h-2.5 text-black" />}
                      </span>
                      <input
                        type="checkbox"
                        className="sr-only"
                        checked={checked}
                        onChange={() => toggleAsin(p.asin)}
                      />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs text-slate-900 truncate">{p.name.split(',')[0].trim()}</p>
                        <p className="text-[10px] text-[hsl(var(--muted-foreground)/0.7)]">{p.asin}</p>
                      </div>
                    </label>
                  )
                })}
              </div>
            )}
          </div>

          {/* Scenario */}
          <div className="space-y-2">
            <label className="text-[11px] text-[hsl(var(--muted-foreground))] uppercase tracking-wider block">场景</label>
            <div className="grid grid-cols-1 gap-1.5">
              {CAMPAIGN_SCENARIOS.map(s => (
                <button
                  key={s.id}
                  onClick={() => setSelectedScenario(s.id)}
                  className={`rounded-lg border px-3 py-2 cursor-pointer transition-all text-left text-sm ${
                    selectedScenario === s.id
                      ? 'border-[hsl(var(--primary)/0.6)] bg-[hsl(var(--primary)/0.08)] text-slate-900'
                      : 'border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:border-[hsl(var(--primary)/0.3)]'
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>

          {/* Channels */}
          <div className="space-y-2">
            <label className="text-[11px] text-[hsl(var(--muted-foreground))] uppercase tracking-wider block">渠道（多选）</label>
            <div className="grid grid-cols-2 gap-1.5">
              {CAMPAIGN_CHANNELS.map(ch => {
                const checked = selectedChannels.includes(ch)
                return (
                  <button
                    key={ch}
                    onClick={() => toggleChannel(ch)}
                    className={`rounded-lg border px-3 py-2 cursor-pointer transition-all text-sm ${
                      checked
                        ? 'border-[hsl(var(--primary)/0.6)] bg-[hsl(var(--primary)/0.08)] text-slate-900'
                        : 'border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:border-[hsl(var(--primary)/0.3)]'
                    }`}
                  >
                    {ch}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Extras */}
          <div className="space-y-1.5">
            <label className="text-[11px] text-[hsl(var(--muted-foreground))] uppercase tracking-wider block">附加描述</label>
            <textarea
              value={extras}
              onChange={e => setExtras(e.target.value)}
              placeholder="促销力度、预算、目标受众…"
              rows={3}
              className="w-full rounded-lg bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] text-slate-900 text-sm px-3 py-2 placeholder:text-[hsl(var(--muted-foreground)/0.5)] focus:outline-none focus:border-[hsl(var(--primary)/0.5)] transition-colors resize-none"
            />
          </div>

          {/* Generate */}
          <Button
            onClick={handleGenerate}
            disabled={generating}
            className="w-full bg-green-600 hover:bg-green-500 text-slate-900 border-0 flex items-center justify-center gap-2"
            size="sm"
          >
            <Wand2 className="w-3.5 h-3.5" />
            {generating ? '生成中…' : '生成营销方案'}
          </Button>
        </Card>
      </div>

      {/* Right Column */}
      <div className="flex-1 min-w-0 space-y-4">
        {strategy && (
          <div className="flex justify-end">
            <Button
              variant="outline"
              size="sm"
              onClick={handleSave}
              disabled={saving || saved}
              className="flex items-center gap-1.5 text-xs"
            >
              {saved ? <Check className="w-3.5 h-3.5 text-[hsl(var(--primary))]" /> : null}
              {saved ? '已保存' : saving ? '保存中…' : '保存方案'}
            </Button>
          </div>
        )}

        <Card className="p-6 bg-[hsl(var(--card))] border-[hsl(var(--border))] min-h-[400px]">
          {generating ? (
            <div className="space-y-3">
              <Skeleton className="h-6 w-48" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-5/6" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          ) : strategy ? (
            <article className={PROSE_CLASS}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{strategy}</ReactMarkdown>
            </article>
          ) : (
            <div className="flex items-center justify-center h-full min-h-[360px]">
              <p className="text-[hsl(var(--muted-foreground)/0.5)] text-sm italic">
                选择产品和场景，生成营销方案
              </p>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}

// ─── Tab Config ───────────────────────────────────────────────────────────────

const CONTENT_TABS = [
  { id: 'prompt-studio', label: 'Prompt Studio',      emoji: '✨' },
  { id: 'aplus',         label: 'A+ Content',         emoji: '📄' },
  { id: 'store',         label: 'Brand Store',        emoji: '🏪' },
  { id: 'campaign',      label: 'Marketing Campaign', emoji: '📢' },
] as const

// ─── Main Page ────────────────────────────────────────────────────────────────

function ContentPageContent() {
  // Tab state
  const [activeTab, setActiveTab] = useState<string>('prompt-studio')

  // Products
  const [products, setProducts] = useState<Product[]>([])
  const [loadingProducts, setLoadingProducts] = useState(true)

  // Selections
  const [selectedAsin, setSelectedAsin] = useState('')
  const [selectedScene, setSelectedScene] = useState<SceneId>('main')
  const [customDesc, setCustomDesc] = useState('')
  const [selectedStyle, setSelectedStyle] = useState<StyleType>('Photography')
  const [selectedTone, setSelectedTone] = useState<ToneType>('Brand (Gold+Black)')
  const [selectedPlatform, setSelectedPlatform] = useState<PlatformType>('Amazon')
  const [extras, setExtras] = useState('')

  // Output
  const [geminiPrompt, setGeminiPrompt] = useState('')
  const [midjourneyPrompt, setMidjourneyPrompt] = useState('')
  const [generated, setGenerated] = useState(false)
  const [saving, setSaving] = useState(false)
  const [savedId, setSavedId] = useState<string | null>(null)

  // Upload Modal
  const [showUpload, setShowUpload] = useState(false)
  const [uploadImages, setUploadImages] = useState<{ name: string; url: string }[]>([])

  // History
  const [prompts, setPrompts] = useState<PromptEntry[]>([])
  const [loadingPrompts, setLoadingPrompts] = useState(true)
  const [historyTab, setHistoryTab] = useState<'all' | 'starred'>('all')

  // ── Load products
  useEffect(() => {
    fetch('/api/content/products')
      .then(r => r.json())
      .then(d => {
        setProducts(d.products || [])
        setLoadingProducts(false)
      })
      .catch(() => setLoadingProducts(false))
  }, [])

  // ── Load prompts
  const loadPrompts = useCallback(() => {
    setLoadingPrompts(true)
    fetch('/api/content/prompts')
      .then(r => r.json())
      .then(d => {
        setPrompts(d.prompts || [])
        setLoadingPrompts(false)
      })
      .catch(() => setLoadingPrompts(false))
  }, [])

  useEffect(() => { loadPrompts() }, [loadPrompts])

  // ── Selected product
  const selectedProduct = products.find(p => p.asin === selectedAsin)

  // ── Load images for upload modal
  const openUploadModal = useCallback(async () => {
    if (!selectedAsin) return
    const res = await fetch(`/api/content/images?asin=${selectedAsin}`)
    const data = await res.json()
    setUploadImages(data.images || [])
    setShowUpload(true)
  }, [selectedAsin])

  // ── Reload product images after upload
  const handleUploaded = useCallback(async () => {
    if (!selectedAsin) return
    const res = await fetch(`/api/content/images?asin=${selectedAsin}`)
    const data = await res.json()
    setUploadImages(data.images || [])
    // Refresh product list to update thumbnails
    const res2 = await fetch('/api/content/products')
    const data2 = await res2.json()
    setProducts(data2.products || [])
  }, [selectedAsin])

  // ── Generate
  const handleGenerate = useCallback(() => {
    if (!selectedProduct) return
    const g = generateGeminiPrompt(selectedProduct, selectedScene, selectedStyle, selectedTone, selectedPlatform, extras, customDesc)
    const m = generateMidjourneyPrompt(selectedProduct, selectedScene, selectedStyle, selectedTone, selectedPlatform, extras, customDesc)
    setGeminiPrompt(g)
    setMidjourneyPrompt(m)
    setGenerated(true)
    setSavedId(null)
  }, [selectedProduct, selectedScene, selectedStyle, selectedTone, selectedPlatform, extras, customDesc])

  // ── Save
  const handleSave = useCallback(async (starred = false) => {
    if (!selectedProduct || !generated) return
    setSaving(true)
    const sceneLabel = SCENE_TYPES.find(s => s.id === selectedScene)?.label ?? selectedScene
    const body = {
      asin: selectedProduct.asin,
      productName: selectedProduct.name,
      type: sceneLabel,
      style: selectedStyle,
      tone: selectedTone,
      platform: selectedPlatform,
      extras,
      geminiPrompt,
      midjourneyPrompt,
      starred,
    }
    try {
      const res = await fetch('/api/content/prompts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json()
      setSavedId(data.prompt?.id ?? null)
      loadPrompts()
    } finally {
      setSaving(false)
    }
  }, [selectedProduct, generated, selectedScene, selectedStyle, selectedTone, selectedPlatform, extras, geminiPrompt, midjourneyPrompt, loadPrompts])

  // ── Toggle star in history
  const handleToggleStar = useCallback(async (id: string, starred: boolean) => {
    await fetch(`/api/content/prompts?id=${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ starred }),
    })
    loadPrompts()
  }, [loadPrompts])

  // ── Delete from history
  const handleDelete = useCallback(async (id: string) => {
    await fetch(`/api/content/prompts?id=${id}`, { method: 'DELETE' })
    loadPrompts()
  }, [loadPrompts])

  // Filtered prompts for tab
  const filteredPrompts = historyTab === 'starred' ? prompts.filter(p => p.starred) : prompts

  // ─────────────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6 pb-10">
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-slate-900 tracking-tight flex items-center gap-2">
          <Clapperboard className="w-5 h-5 text-[hsl(var(--primary))]" />
          Content Studio
        </h2>
        <p className="text-sm text-[hsl(var(--muted-foreground))] mt-1">
          Generate AI-ready image prompts for Gemini & Midjourney
        </p>
      </div>

      {/* Tab Bar */}
      <div className="flex items-center gap-1 border-b border-[hsl(var(--border))]">
        {CONTENT_TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
              activeTab === tab.id
                ? 'border-[hsl(var(--primary))] text-[hsl(var(--primary))]'
                : 'border-transparent text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:border-[hsl(var(--border))]'
            }`}
          >
            <span>{tab.emoji}</span>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}

      {activeTab === 'prompt-studio' && (
        <>
          {/* Main Layout */}
          <div className="grid grid-cols-1 xl:grid-cols-5 gap-6">

            {/* ── Left: Prompt Studio (60%) ─────────────────────────────────────── */}
            <div className="xl:col-span-3 space-y-5">

              {/* Step 1: Product */}
              <Card className="p-5 bg-[hsl(var(--card))] border-[hsl(var(--border))] space-y-4">
                <h3 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                  <span className="w-5 h-5 rounded-full bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))] text-[10px] font-bold flex items-center justify-center">1</span>
                  Select Product
                </h3>

                <div className="flex gap-2">
                  {loadingProducts ? (
                    <Skeleton className="h-9 flex-1" />
                  ) : (
                    <div className="relative flex-1">
                      <select
                        value={selectedAsin}
                        onChange={e => { setSelectedAsin(e.target.value); setGenerated(false) }}
                        className="w-full h-9 rounded-lg bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] text-slate-900 text-sm px-3 pr-8 appearance-none focus:outline-none focus:border-[hsl(var(--primary)/0.5)] transition-colors"
                      >
                        <option value="">— Choose a product —</option>
                        {products.map(p => (
                          <option key={p.asin} value={p.asin}>
                            {p.name.split(',')[0].trim()} ({p.asin})
                          </option>
                        ))}
                      </select>
                      <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[hsl(var(--muted-foreground))] pointer-events-none" />
                    </div>
                  )}

                  <Button
                    variant="outline"
                    size="sm"
                    disabled={!selectedAsin}
                    onClick={openUploadModal}
                    className="flex items-center gap-1.5 text-xs whitespace-nowrap"
                  >
                    <Upload className="w-3.5 h-3.5" />
                    Ref Images
                  </Button>
                </div>

                {/* Thumbnails */}
                {selectedProduct && selectedProduct.images.length > 0 && (
                  <div className="flex gap-2 flex-wrap">
                    {selectedProduct.images.slice(0, 4).map(url => (
                      <div key={url} className="w-14 h-14 rounded-lg overflow-hidden bg-[hsl(var(--secondary))] border border-[hsl(var(--border))]">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={url} alt="ref" className="w-full h-full object-cover" />
                      </div>
                    ))}
                    {selectedProduct.images.length > 4 && (
                      <div className="w-14 h-14 rounded-lg bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] flex items-center justify-center text-xs text-[hsl(var(--muted-foreground))]">
                        +{selectedProduct.images.length - 4}
                      </div>
                    )}
                  </div>
                )}
              </Card>

              {/* Step 2: Scene Type */}
              <Card className="p-5 bg-[hsl(var(--card))] border-[hsl(var(--border))] space-y-4">
                <h3 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                  <span className="w-5 h-5 rounded-full bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))] text-[10px] font-bold flex items-center justify-center">2</span>
                  Scene Type
                </h3>
                <div className="grid grid-cols-3 gap-2">
                  {SCENE_TYPES.map(scene => (
                    <button
                      key={scene.id}
                      onClick={() => { setSelectedScene(scene.id); setGenerated(false) }}
                      className={`rounded-xl p-3 text-left transition-all border ${
                        selectedScene === scene.id
                          ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.1)] text-slate-900'
                          : 'border-[hsl(var(--border))] bg-[hsl(var(--secondary)/0.3)] text-[hsl(var(--muted-foreground))] hover:border-[hsl(var(--primary)/0.3)] hover:text-slate-900'
                      }`}
                    >
                      <div className="text-lg mb-1">{scene.emoji}</div>
                      <div className="text-xs font-medium leading-tight">{scene.label}</div>
                    </button>
                  ))}
                </div>
                {selectedScene === 'custom' && (
                  <input
                    type="text"
                    value={customDesc}
                    onChange={e => { setCustomDesc(e.target.value); setGenerated(false) }}
                    placeholder="Describe the scene…"
                    className="w-full h-9 rounded-lg bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] text-slate-900 text-sm px-3 focus:outline-none focus:border-[hsl(var(--primary)/0.5)] placeholder:text-[hsl(var(--muted-foreground)/0.5)] transition-colors"
                  />
                )}
              </Card>

              {/* Step 3: Parameters */}
              <Card className="p-5 bg-[hsl(var(--card))] border-[hsl(var(--border))] space-y-4">
                <h3 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                  <span className="w-5 h-5 rounded-full bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))] text-[10px] font-bold flex items-center justify-center">3</span>
                  Parameters
                </h3>

                <div className="grid grid-cols-2 gap-3">
                  {/* Style */}
                  <div>
                    <label className="text-[11px] text-[hsl(var(--muted-foreground))] uppercase tracking-wider mb-1.5 block">Style</label>
                    <div className="relative">
                      <select
                        value={selectedStyle}
                        onChange={e => { setSelectedStyle(e.target.value as StyleType); setGenerated(false) }}
                        className="w-full h-8 rounded-lg bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] text-slate-900 text-xs px-2.5 pr-6 appearance-none focus:outline-none focus:border-[hsl(var(--primary)/0.5)] transition-colors"
                      >
                        {STYLES.map(s => <option key={s}>{s}</option>)}
                      </select>
                      <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 text-[hsl(var(--muted-foreground))] pointer-events-none" />
                    </div>
                  </div>

                  {/* Tone */}
                  <div>
                    <label className="text-[11px] text-[hsl(var(--muted-foreground))] uppercase tracking-wider mb-1.5 block">Color Tone</label>
                    <div className="relative">
                      <select
                        value={selectedTone}
                        onChange={e => { setSelectedTone(e.target.value as ToneType); setGenerated(false) }}
                        className="w-full h-8 rounded-lg bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] text-slate-900 text-xs px-2.5 pr-6 appearance-none focus:outline-none focus:border-[hsl(var(--primary)/0.5)] transition-colors"
                      >
                        {TONES.map(t => <option key={t}>{t}</option>)}
                      </select>
                      <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 text-[hsl(var(--muted-foreground))] pointer-events-none" />
                    </div>
                  </div>

                  {/* Platform */}
                  <div>
                    <label className="text-[11px] text-[hsl(var(--muted-foreground))] uppercase tracking-wider mb-1.5 block">Platform</label>
                    <div className="relative">
                      <select
                        value={selectedPlatform}
                        onChange={e => { setSelectedPlatform(e.target.value as PlatformType); setGenerated(false) }}
                        className="w-full h-8 rounded-lg bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] text-slate-900 text-xs px-2.5 pr-6 appearance-none focus:outline-none focus:border-[hsl(var(--primary)/0.5)] transition-colors"
                      >
                        {PLATFORMS.map(p => <option key={p}>{p}</option>)}
                      </select>
                      <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 text-[hsl(var(--muted-foreground))] pointer-events-none" />
                    </div>
                  </div>

                  {/* Extras */}
                  <div>
                    <label className="text-[11px] text-[hsl(var(--muted-foreground))] uppercase tracking-wider mb-1.5 block">Extra Details</label>
                    <input
                      type="text"
                      value={extras}
                      onChange={e => { setExtras(e.target.value); setGenerated(false) }}
                      placeholder="e.g. bokeh, golden hour…"
                      className="w-full h-8 rounded-lg bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] text-slate-900 text-xs px-2.5 focus:outline-none focus:border-[hsl(var(--primary)/0.5)] placeholder:text-[hsl(var(--muted-foreground)/0.4)] transition-colors"
                    />
                  </div>
                </div>
              </Card>

              {/* Step 4: Generate */}
              <Card className="p-5 bg-[hsl(var(--card))] border-[hsl(var(--border))] space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                    <span className="w-5 h-5 rounded-full bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))] text-[10px] font-bold flex items-center justify-center">4</span>
                    Generate
                  </h3>
                  <Button
                    onClick={handleGenerate}
                    disabled={!selectedAsin}
                    className="flex items-center gap-2"
                    size="sm"
                  >
                    <Wand2 className="w-3.5 h-3.5" />
                    Generate Prompts
                  </Button>
                </div>

                {generated && (
                  <div className="space-y-4 pt-2 border-t border-[hsl(var(--border))]">
                    {/* Gemini */}
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <Sparkles className="w-3.5 h-3.5 text-[hsl(var(--primary))]" />
                          <span className="text-[11px] font-semibold text-[hsl(var(--primary))] uppercase tracking-wider">Gemini Prompt</span>
                        </div>
                        <CopyButton text={geminiPrompt} />
                      </div>
                      <pre className="text-[12px] text-[hsl(var(--muted-foreground))] whitespace-pre-wrap leading-relaxed bg-[hsl(var(--secondary)/0.5)] rounded-lg p-3 font-sans border border-[hsl(var(--border))]">
                        {geminiPrompt}
                      </pre>
                    </div>

                    {/* Midjourney */}
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <Sparkles className="w-3.5 h-3.5 text-blue-600" />
                          <span className="text-[11px] font-semibold text-blue-600 uppercase tracking-wider">Midjourney Prompt</span>
                        </div>
                        <CopyButton text={midjourneyPrompt} />
                      </div>
                      <pre className="text-[12px] text-[hsl(var(--muted-foreground))] whitespace-pre-wrap leading-relaxed bg-[hsl(var(--secondary)/0.5)] rounded-lg p-3 font-sans border border-[hsl(var(--border))]">
                        {midjourneyPrompt}
                      </pre>
                    </div>

                    {/* Save actions */}
                    <div className="flex gap-2 pt-1">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={saving || !!savedId}
                        onClick={() => handleSave(false)}
                        className="flex items-center gap-1.5 text-xs"
                      >
                        {savedId ? <Check className="w-3.5 h-3.5 text-[hsl(var(--primary))]" /> : null}
                        {savedId ? 'Saved' : saving ? 'Saving…' : 'Save'}
                      </Button>
                      <Button
                        size="sm"
                        disabled={saving || !!savedId}
                        onClick={() => handleSave(true)}
                        className="flex items-center gap-1.5 text-xs"
                      >
                        <Star className="w-3.5 h-3.5" />
                        {savedId ? 'Saved to Favorites' : saving ? 'Saving…' : '⭐ Save to Favorites'}
                      </Button>
                    </div>
                  </div>
                )}

                {!generated && (
                  <p className="text-[12px] text-[hsl(var(--muted-foreground)/0.5)] italic">
                    {selectedAsin ? 'Click "Generate Prompts" to create prompts for the selected product.' : 'Select a product above to get started.'}
                  </p>
                )}
              </Card>
            </div>

            {/* ── Right: History & Favorites (40%) ──────────────────────────────── */}
            <div className="xl:col-span-2 space-y-4">
              <Card className="bg-[hsl(var(--card))] border-[hsl(var(--border))] overflow-hidden">
                {/* Tabs */}
                <div className="flex border-b border-[hsl(var(--border))]">
                  {(['all', 'starred'] as const).map(tab => (
                    <button
                      key={tab}
                      onClick={() => setHistoryTab(tab)}
                      className={`flex-1 py-3 text-xs font-semibold uppercase tracking-wider transition-colors ${
                        historyTab === tab
                          ? 'text-[hsl(var(--primary))] border-b-2 border-[hsl(var(--primary))] -mb-px'
                          : 'text-[hsl(var(--muted-foreground))] hover:text-slate-900'
                      }`}
                    >
                      {tab === 'all' ? 'All Prompts' : '⭐ Favorites'}
                      {tab === 'all' && prompts.length > 0 && (
                        <span className="ml-1.5 bg-[hsl(var(--secondary))] text-[hsl(var(--foreground))] text-[9px] rounded-full px-1.5 py-0.5">
                          {prompts.length}
                        </span>
                      )}
                      {tab === 'starred' && prompts.filter(p => p.starred).length > 0 && (
                        <span className="ml-1.5 bg-yellow-400/20 text-yellow-600 text-[9px] rounded-full px-1.5 py-0.5">
                          {prompts.filter(p => p.starred).length}
                        </span>
                      )}
                    </button>
                  ))}
                </div>

                {/* List */}
                <div className="p-4 space-y-3 max-h-[calc(100vh-280px)] overflow-y-auto">
                  {loadingPrompts ? (
                    Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-20 w-full" />)
                  ) : filteredPrompts.length === 0 ? (
                    <div className="py-12 text-center">
                      <Sparkles className="w-8 h-8 mx-auto mb-3 text-[hsl(var(--muted-foreground)/0.3)]" />
                      <p className="text-sm text-[hsl(var(--muted-foreground)/0.5)]">
                        {historyTab === 'starred' ? 'No favorites yet' : 'No prompts yet — generate one!'}
                      </p>
                    </div>
                  ) : (
                    filteredPrompts.map(entry => (
                      <HistoryEntry
                        key={entry.id}
                        entry={entry}
                        onToggleStar={handleToggleStar}
                        onDelete={handleDelete}
                      />
                    ))
                  )}
                </div>
              </Card>
            </div>
          </div>

          {/* Upload Modal */}
          {showUpload && selectedAsin && (
            <UploadModal
              asin={selectedAsin}
              images={uploadImages}
              onClose={() => setShowUpload(false)}
              onUploaded={handleUploaded}
            />
          )}
        </>
      )}

      {activeTab === 'aplus' && <AplusTab />}
      {activeTab === 'store' && <StoreTab />}
      {activeTab === 'campaign' && <CampaignTab />}
    </div>
  )
}
export default function ContentPage() {
  return (
    <DashboardPageLayout
      signedOut={{ message: 'Sign in to view content', forceRedirectUrl: '/content' }}
      title="Content"
      description="内容资产库"
    >
      <ContentPageContent />
    </DashboardPageLayout>
  )
}
