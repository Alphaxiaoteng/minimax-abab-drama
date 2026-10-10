const cloud = require('wx-server-sdk')

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

const PROVIDER = 'cloudbase'
const MODEL = 'deepseek-v4.1-flash'
const MAX_TEXT_CHARS = 8000
const MAX_SENTENCES_DEFAULT = 3
const MAX_SENTENCES_LIMIT = 10
const VERSION = '1.0.0'

const SYSTEM_PROMPT = [
  '你是「AI 一页纸快读」的结构化抽取器。',
  '只依据用户提供的原文抽取信息，不可编造：原文没有的内容必须写「原文未提及」。',
  '只输出一个严格 JSON 对象（无注释、无尾逗号），不要输出寒暄、解释或 Markdown 代码围栏。',
  '字段定义：{"conclusion": string, "keyFigures": string[], "risks": string[], "quotes": string[]}。',
  'keyFigures/risks/quotes 数组长度均不得超过 maxSentences；quotes 必须是原文连续片段，数字与人名逐字照抄。'
].join('\n')

function fail (message, code) {
  return {
    ok: false,
    mode: 'cloud',
    error: { code: code || 'DOC_INSIGHT_ERROR', message: String(message) }
  }
}

function clampMaxSentences (value) {
  if (value === undefined || value === null || value === '') return MAX_SENTENCES_DEFAULT
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0) return MAX_SENTENCES_DEFAULT
  return Math.min(Math.floor(n), MAX_SENTENCES_LIMIT)
}

// 段落优先截断：在上限前半部分内寻找换行边界，避免截在句子中间。
function truncateText (text) {
  if (text.length <= MAX_TEXT_CHARS) return { text, truncated: false }
  const head = text.slice(0, MAX_TEXT_CHARS)
  const cut = head.lastIndexOf('\n')
  const clipped = cut > MAX_TEXT_CHARS / 2 ? head.slice(0, cut) : head
  return { text: clipped, truncated: true }
}

function extractJsonObject (raw) {
  let s = String(raw || '').trim()
  if (s.startsWith('```')) {
    s = s.replace(/^```[a-zA-Z]*\s*/, '').replace(/```\s*$/, '')
  }
  const start = s.indexOf('{')
  const end = s.lastIndexOf('}')
  if (start === -1 || end <= start) throw new Error('model output is not a JSON object')
  return JSON.parse(s.slice(start, end + 1))
}

function toList (value, maxSentences) {
  if (!Array.isArray(value)) return []
  return value
    .slice(0, maxSentences)
    .map((item) => String(item).trim())
    .filter(Boolean)
}

function normalizeStructured (parsed, maxSentences) {
  const conclusion = parsed.conclusion ? String(parsed.conclusion).trim() : '原文未提及'
  return {
    conclusion,
    keyFigures: toList(parsed.keyFigures, maxSentences),
    risks: toList(parsed.risks, maxSentences),
    quotes: toList(parsed.quotes, maxSentences)
  }
}

exports.main = async (event) => {
  try {
    const input = event || {}

    if (typeof input.text !== 'string' || input.text.trim() === '') {
      return fail('text must be a non-empty string', 'INVALID_INPUT')
    }
    if (input.url !== undefined && typeof input.url !== 'string') {
      return fail('url must be a string when provided', 'INVALID_INPUT')
    }
    if (input.scene !== undefined && input.scene !== 'quickread') {
      return fail('scene only supports "quickread"', 'INVALID_INPUT')
    }

    const maxSentences = clampMaxSentences(input.maxSentences)
    const truncatedInfo = truncateText(input.text.trim())

    const model = cloud.ai.createModel(PROVIDER)
    const result = await model.generateText({
      model: MODEL,
      messages: [
        { role: 'system', content: SYSTEM_PROMPT },
        {
          role: 'user',
          content: JSON.stringify({
            scene: 'quickread',
            url: input.url || '',
            maxSentences,
            text: truncatedInfo.text
          })
        }
      ]
    })

    const rawText = typeof result === 'string'
      ? result
      : (result && (result.text || result.content)) || ''

    return {
      ok: true,
      mode: 'cloud',
      version: VERSION,
      structured: normalizeStructured(extractJsonObject(rawText), maxSentences),
      truncated: truncatedInfo.truncated,
      usage: (result && result.usage) || null
    }
  } catch (err) {
    return fail((err && err.message) || String(err))
  }
}