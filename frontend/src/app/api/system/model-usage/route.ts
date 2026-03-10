import { NextResponse } from 'next/server'
import { readFileSync, readdirSync } from 'fs'
import { join } from 'path'
import { homedir } from 'os'

interface SessionEntry {
  model?: string
  modelProvider?: string
  inputTokens?: number
  outputTokens?: number
  totalTokens?: number
  contextTokens?: number
  sessionId?: string
  updatedAt?: number
}

// All tracked models — shown even with zero usage
const ALL_MODELS: { id: string; name: string; provider: string }[] = [
  { id: 'anthropic/claude-opus-4-6',           name: 'Claude Opus 4.6',    provider: 'Anthropic' },
  { id: 'anthropic/claude-opus-4-5',           name: 'Claude Opus 4.5',    provider: 'Anthropic' },
  { id: 'anthropic/claude-sonnet-4-6',         name: 'Claude Sonnet 4.6',  provider: 'Anthropic' },
  { id: 'anthropic/claude-sonnet-4-5',         name: 'Claude Sonnet 4.5',  provider: 'Anthropic' },
  { id: 'google-gemini-cli/gemini-3-pro-preview',   name: 'Gemini 3 Pro',   provider: 'Google' },
  { id: 'google-gemini-cli/gemini-3-flash-preview', name: 'Gemini 3 Flash', provider: 'Google' },
  { id: 'openai-codex/gpt-5.2',               name: 'GPT-5.2',            provider: 'OpenAI' },
  { id: 'openai-codex/gpt-5.2-codex',         name: 'GPT-5.2 Codex',      provider: 'OpenAI' },
  { id: 'openai-codex/gpt-5.3-codex',         name: 'GPT-5.3 Codex',      provider: 'OpenAI' },
  { id: 'openai-codex/gpt-5.3-codex-spark',   name: 'GPT-5.3 Spark',      provider: 'OpenAI' },
]

// Cost per 1M tokens (input / output) in USD — best available estimates
const MODEL_COST: Record<string, { input: number; output: number }> = {
  'anthropic/claude-opus-4-6':           { input: 15.0,  output: 75.0  },
  'anthropic/claude-opus-4-5':           { input: 15.0,  output: 75.0  },
  'anthropic/claude-sonnet-4-6':         { input: 3.0,   output: 15.0  },
  'anthropic/claude-sonnet-4-5':         { input: 3.0,   output: 15.0  },
  'google-gemini-cli/gemini-3-pro-preview':   { input: 1.25,  output: 5.0   },
  'google-gemini-cli/gemini-3-flash-preview': { input: 0.075, output: 0.3   },
  'openai-codex/gpt-5.2':               { input: 2.5,   output: 10.0  },
  'openai-codex/gpt-5.2-codex':         { input: 2.5,   output: 10.0  },
  'openai-codex/gpt-5.3-codex':         { input: 2.5,   output: 10.0  },
  'openai-codex/gpt-5.3-codex-spark':   { input: 0.5,   output: 1.5   },
}

export async function GET() {
  const agentsDir = join(homedir(), '.openclaw', 'agents')

  // Seed aggregator with all known models at zero
  const agg: Record<string, {
    name: string; provider: string; inputTokens: number; outputTokens: number;
    totalTokens: number; cost: number; sessions: number
  }> = {}

  for (const m of ALL_MODELS) {
    agg[m.id] = { name: m.name, provider: m.provider, inputTokens: 0, outputTokens: 0, totalTokens: 0, cost: 0, sessions: 0 }
  }

  try {
    const agentIds = readdirSync(agentsDir)

    for (const agentId of agentIds) {
      const sessionsFile = join(agentsDir, agentId, 'sessions', 'sessions.json')
      try {
        const raw  = readFileSync(sessionsFile, 'utf-8')
        const data = JSON.parse(raw) as Record<string, SessionEntry>

        for (const session of Object.values(data)) {
          const modelId  = session.model
          const provider = session.modelProvider
          if (!modelId || !session.totalTokens) continue

          const fullId = provider ? `${provider}/${modelId}` : modelId

          // Init entry if it's an unknown model not in ALL_MODELS
          if (!agg[fullId]) {
            const knownModel = ALL_MODELS.find(m => m.id === fullId)
            agg[fullId] = {
              name:     knownModel?.name ?? modelId,
              provider: knownModel?.provider ?? provider ?? 'Unknown',
              inputTokens: 0, outputTokens: 0, totalTokens: 0, cost: 0, sessions: 0,
            }
          }

          const inp   = session.inputTokens  ?? 0
          const out   = session.outputTokens ?? 0
          const tot   = session.totalTokens  ?? (inp + out)
          const rates = MODEL_COST[fullId]
          const cost  = rates ? (inp / 1_000_000) * rates.input + (out / 1_000_000) * rates.output : 0

          agg[fullId].inputTokens  += inp
          agg[fullId].outputTokens += out
          agg[fullId].totalTokens  += tot
          agg[fullId].cost         += cost
          agg[fullId].sessions     += 1
        }
      } catch {
        // skip agents with no sessions file
      }
    }

    // Sort: used models first (by tokens desc), then unused alphabetically
    const models = Object.entries(agg)
      .map(([id, v]) => ({ id, ...v }))
      .sort((a, b) => {
        if (b.totalTokens !== a.totalTokens) return b.totalTokens - a.totalTokens
        return a.name.localeCompare(b.name)
      })

    const totalTokens = models.reduce((s, m) => s + m.totalTokens, 0)
    const totalCost   = models.reduce((s, m) => s + m.cost, 0)

    return NextResponse.json({ models, totalTokens, totalCost })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
