// SSE 增量解析 + AG-UI 事件映射。
// 跨 chunk 缓冲：网络分片可能在 '\n\n' 帧中间、data: 前缀中间到达，必须缓存到完整帧才派发。

function createSSEParser({ onEvent } = {}) {
  let buf = '';
  const emit = typeof onEvent === 'function' ? onEvent : () => {};
  return {
    // 喂入一段文本（可能是半帧）
    feed(chunkText) {
      if (!chunkText) return;
      buf += String(chunkText);
      // 帧分隔符：空行。兼容 \n\n / \r\n\r\n
      let idx;
      while ((idx = indexOfFrame(buf)) !== -1) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + frameSepLength(buf, idx));
        dispatchFrame(frame, emit);
      }
    },
    // 收尾：把剩余无终止空行的 buffer 也派发（防止最后一条 data: 丢失）
    flush() {
      if (buf.trim()) {
        dispatchFrame(buf, emit);
        buf = '';
      } else {
        buf = '';
      }
    }
  };
}

function indexOfFrame(s) {
  const a = s.indexOf('\n\n');
  const b = s.indexOf('\r\n\r\n');
  if (a === -1) return b;
  if (b === -1) return a;
  return Math.min(a, b);
}

function frameSepLength(s, idx) {
  return s.slice(idx).startsWith('\r\n\r\n') ? 4 : 2;
}

// 一帧可能有多个字段行（event:/id:/retry:/data:），只取 data 负载；多行 data 以 \n 拼接。
function dispatchFrame(frame, emit) {
  const lines = frame.replace(/\r\n/g, '\n').split('\n');
  const dataLines = [];
  for (const line of lines) {
    if (line.startsWith(':')) continue; // 注释行（心跳）
    if (line === 'data') { dataLines.push(''); continue; }
    if (line.startsWith('data:')) {
      let payload = line.slice(5);
      if (payload.startsWith(' ')) payload = payload.slice(1); // 去掉可选单空格
      dataLines.push(payload);
    }
  }
  if (dataLines.length === 0) return;
  const joined = dataLines.join('\n');
  if (joined === '') return;
  emit(joined);
}

// AG-UI 事件：JSON 解析失败一律归为 UNKNOWN，绝不抛异常打断流。
function parseAGUIEvent(raw) {
  try {
    const obj = JSON.parse(raw);
    return {
      type: obj.type || 'UNKNOWN',
      delta: typeof obj.delta === 'string' ? obj.delta : '',
      toolCallName: obj.toolCallName || '',
      toolCallId: obj.toolCallId || '',
      message: obj.message || '',
      content: typeof obj.content === 'string' ? obj.content : (obj.content === undefined ? '' : JSON.stringify(obj.content)),
      data: obj
    };
  } catch (e) {
    return { type: 'UNKNOWN', delta: '', toolCallName: '', toolCallId: '', message: '', content: '', data: raw };
  }
}

// 把 AG-UI 事件映射为 UI 步骤 kind：think 工具过程 / text 正文 / tool 工具调用 / done 结束 / error 错误。
// artifact：STATE_SNAPSHOT 视为可视化产物快照。
function mapAGUIEventToStep(evt) {
  if (!evt || !evt.type) return { kind: 'text', text: '' };
  switch (evt.type) {
    case 'TEXT_MESSAGE_CONTENT':
      return { kind: 'text', text: evt.delta || '' };
    case 'TEXT_MESSAGE_START':
      return { kind: 'text', text: '' };
    case 'TEXT_MESSAGE_END':
      return { kind: 'text', text: '' };
    case 'TOOL_CALL_START':
      return { kind: 'tool', text: evt.toolCallName || 'tool' };
    case 'TOOL_CALL_ARGS':
      return { kind: 'think', text: evt.delta || '' };
    case 'TOOL_CALL_END':
      return { kind: 'tool', text: '' };
    case 'TOOL_CALL_RESULT':
      return { kind: 'artifact', text: evt.content || '' };
    case 'STATE_SNAPSHOT':
    case 'STATE_DELTA':
      return { kind: 'artifact', text: '' };
    case 'STEP_STARTED':
      return { kind: 'think', text: '' };
    case 'STEP_FINISHED':
      return { kind: 'think', text: '' };
    case 'RUN_STARTED':
      return { kind: 'think', text: '' };
    case 'RUN_FINISHED':
      return { kind: 'done', text: '' };
    case 'RUN_ERROR':
      return { kind: 'error', text: evt.message || '运行失败' };
    default:
      return { kind: 'text', text: '' };
  }
}

module.exports = { createSSEParser, parseAGUIEvent, mapAGUIEventToStep };