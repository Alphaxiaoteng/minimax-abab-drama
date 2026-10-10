const cloud = require('wx-server-sdk')

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

const PROVIDER = 'cloudbase'
const MODEL = 'deepseek-v4.1-flash'
const MAX_ITEMS = 50
const MAX_ITEM_CHARS = 200
const SYSTEM_PROMPT = [
  '你是「日程断舍离」的决策内核。输入是今日待办条目数组 items 与当前时间 now。',
  '只依据输入条目做分类，不可编造输入中不存在的事项。',
  '只输出一个严格 JSON 对象（无注释、无尾逗号），不要寒暄、解释或 Markdown 代码围栏。',
  '字段定义：{"top3":[{"text":string,"reason":string}], "later":[{"text":string,"reason":string}], "drop":[{"text":string,"reason":string}], "blocks":[{"start":string,"end":string,"text":string}]}。',
  'top3 恰好 3 条（不足 3 条时按实际数量）；drop 每条必须给出可核验的理由；blocks 按时间先后排列，时间使用 24 小时制 HH:mm。',
  '所有 text 必须是输入条目的原文或其忠实缩写，不得新增事实。'
].join('\n')

function fail (message, code) {
  return {
    ok: false,
    mode: 'cloud',
    error: { code: code || 'TRIAGE_ERROR', message: String(message) }
  }
}

function normalizeItems (rawItems) {
  if (!Array.isArray(rawItems) || rawItems.length === 0) {
    return { ok: false, message: 'items must be a non-empty array' }
  }
  const clipped = rawItems.slice(0, MAX_ITEMS)
  const texts = []
  for (const item of clipped) {
    if (item === null || item === undefined) continue
    const text = typeof item === 'string' ? item : (typeof item.text === 'string' ? item.text : '')
    const trimmed = text.trim()
    if (!trimmed) continue
    texts.push(trimmed.slice(0, MAX_ITEM_CHARS))
  }
  if (texts.length === 0) return { ok: false, message: 'items contain no usable text' }
  return { ok: true, texts }
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

function toTaskList (value, limit) {
  if (!Array.isArray(value)) return []
  return value.slice(0, limit).map((entry) => {
    if (typeof entry === 'string') {
      return { text: entry.trim(), reason: '原文未提及理由' }
    }
    const obj = entry || {}
    return {
      text: String(obj.text || '').trim(),
      reason: String(obj.reason || '').trim() || '原文未提及理由'
    }
  }).filter((entry) => entry.text)
}

function toBlocks (value) {
  if (!Array.isArray(value)) return []
  return value.map((block) => {
    const obj = block || {}
    return {
      start: String(obj.start || '').trim(),
      end: String(obj.end || '').trim(),
      text: String(obj.text || '').trim()
    }
  }).filter((block) => block.text)
}

exports.main = async (event) => {
  try {
    const input = event || {}
    const normalized = normalizeItems(input.items)
    if (!normalized.ok) return fail(normalized.message, 'INVALID_INPUT')

    const now = typeof input.now === 'string' && input.now.trim()
      ? input.now.trim()
      : new Date().toISOString()

    const model = cloud.ai.createModel(PROVIDER)
    const result = await model.generateText({
      model: MODEL,
      messages: [
        { role: 'system', content: SYSTEM_PROMPT },
        { role: 'user', content: JSON.stringify({ now, items: normalized.texts }) }
      ]
    })

    const rawText = typeof result === 'string'
      ? result
      : (result && (result.text || result.content)) || ''

    const parsed = extractJsonObject(rawText)

    return {
      ok: true,
      mode: 'cloud',
      structured: {
        top3: toTaskList(parsed.top3, 3),
        later: toTaskList(parsed.later, 10),
        drop: toTaskList(parsed.drop, 10),
        blocks: toBlocks(parsed.blocks)
      },
      meta: {
        itemCount: normalized.texts.length,
        droppedCount: Math.max((Array.isArray(input.items) ? input.items.length : 0) - MAX_ITEMS, 0),
        usage: (result && result.usage) || null
      }
    }
  } catch (err) {
    return fail((err && err.message) || String(err))
  }
}