# 架构与实现说明 · 沉浸式互动推理剧 Agent

> 赛事：MiniMax · 2026 开放平台 abab 7 与智能体商业应用大赛
> 工程标识：`immersive-drama-agent`
> 状态：可运行、可离线复现、含端到端评测验证系统

---

## 1. 痛点与解法

**痛点**：市面上的「AI 陪伴 / AI 剧本杀」普遍是三件事的拼接体——文本模型聊天框 + 一次性 TTS 音色 + 硬编码剧情分支。结果是：人格飘移（第 3 轮就不像同一个人）、语音与情绪脱钩（角色在暴怒，声音依旧平静）、演示依赖网络与密钥（评审现场断网即翻车）、效果无法量化（"感觉不错"不是证据）。

**解法**：把「人格」「情绪」「语音」「剧情状态」四者做成**同一台状态机的四个投影**，并为它配套一套**离线确定性的评测验证系统**。

```
                     ┌──────────────────────────────────────────┐
   玩家输入  ────────▶│  DramaEngine（导演状态机）                │
                     │  信任度 / 紧张度 / 线索 / 阶段 四元状态     │
                     └───────┬──────────────────┬───────────────┘
                             │ 系统提示词(含状态)  │ 情绪参数
                             ▼                  ▼
                     ┌───────────────┐   ┌───────────────┐
                     │ MiniMax abab7 │   │ MiniMax T2A v2│
                     │ 文本续写+情绪   │   │ 情绪化语音合成  │
                     └───────┬───────┘   └───────┬───────┘
                             │                  │
                  TransportError/UpstreamError  │
                             ▼                  ▼
                     ┌─────────────────────────────────┐
                     │ MiniMaxClient 降级层（唯一决策点）│
                     │  重试 → 确定性语料 + 合成 WAV     │
                     └──────────────┬──────────────────┘
                                    ▼
                     ┌─────────────────────────────────┐
                     │  EvalSuite 评测系统               │
                     │  6 维加权评分 / A-B 盲评 / 音频锚定 │
                     └─────────────────────────────────┘
```

---

## 2. 模块依赖（单向，禁止反向）

```
core/  ──▶  personas/  ──▶  minimax/  ──▶  engine/  ──▶  eval/  ──▶  server/ ui/ cli/
```

| 目录 | 职责 | 关键契约 |
|---|---|---|
| `core/` | 冻结契约：类型、错误层级、配置、确定性 PRNG | `core/types.ts`、`core/contracts.ts` |
| `personas/` | 3 个原创人格 + 情绪化声线方案 | `loadAllPersonas()`、`personaRegistry` |
| `engine/` | 推理剧剧本 + 导演状态机 | `defaultScreenplay`、`DramaEngine` |
| `minimax/` | 外呼边界（HTTP/伪传输）、降级层、离线语料与 WAV 合成 | `MiniMaxTransport`、`MiniMaxClient` |
| `eval/` | 6 维评分、人格一致性、A-B 盲评、端到端音频锚定、报告 | `runEvalSuite()`、`EvalReport` |
| `server/ ui/ cli/` | H5 沉浸界面、HTTP 服务、演示与评测入口 | `startServer()` |

`core/contracts.ts` 是一份**编译期接口拓扑**（不导出任何运行时代码），用于在多人并行开发时把函数签名焊死。

---

## 3. 核心算法与技术选型理由

### 3.1 导演状态机：把「剧情」变成可计算的四元状态

`DramaState = { phase, trust, tension, revealedClueIds }`

- **信任度 trust**：由玩家语用决定（敌意关键词 −、信任/共情关键词 +），夹紧 `[0,100]`。
- **紧张度 tension**：追证强度累积。
- **线索揭示**：`clue.requiredTrust ≤ trust` 即揭示，线索强度**严格递增**（0→30→55→70→85→95），保证"越深入越接近真相"的单调体验。
- **阶段推进**：`phaseGates = {intro:0, exploration:20, cross-examination:50, confrontation:80, resolution:95}`，阶段沿 `SCENE_PHASE_ORDER` **只进不退**；抵达 `resolution` 置 `ended`，后续 `send()` 抛 `ValidationError`。

*为什么不用 LLM 直接管剧情*：LLM 无法保证不变量（会倒退、会提前揭底、会遗忘已揭示线索）。把剧情交给确定性状态机，把语言表演交给模型，是唯一能在现场演示中稳定复现的分工。

**状态不可变**：每次转移返回新 `DramaState`，旧快照永不被改写——这是评测系统能对"阶段轨迹"做断言的前提。

### 3.2 情绪闭环：文本 → 情绪标注 → 声学参数

模型被要求在**回复末尾**输出 `（语气：X）` 标记，8 类情绪 `calm/joyful/tense/sorrowful/furious/fearful/suspicious/tender`。

`resolveVoiceSettings(profile, emotion)` = 人格基准参数 ⊗ 情绪覆盖项，再夹紧到 T2A v2 合法区间（`speed 0.5–2.0`、`vol 0.1–10.0`、`pitch −12–12`）。

例如：沈砚（冷面法医）基准 `speed 0.92 / pitch −3`，进入 `furious` 时覆盖为 `speed 1.16 / pitch +5`；何静澜（阴郁画廊主）基准 `speed 0.85 / pitch −2`，`sorrowful` 覆盖为 `speed 0.68 / pitch −6`。**不同的不是标签，是波形**——评测系统用「不同情绪产出的音频首 200 字节必须互异」来锚定这一点。

*选型理由*：MiniMax 的 T2A v2 支持 `emotion` 字段与 `pitch/speed/vol` 细粒度控制，这是官方王牌能力；把情绪做成"可测量参数"而非提示词祈祷，才有复现性。

### 3.3 降级层：唯一决策点，绝不向上抛异常

```
恒等不变量：任何网络形态失败，玩家侧感知只有「音色换成了离线合成」，
           对话永不中断，异常永不逃逸到 UI。
```

- `MiniMaxTransport` 只负责"把请求变成字节"，允许抛 `TransportError`（可降级）/ `UpstreamError`（不可降级）。
- `MiniMaxClient` 是**唯一**做重试与降级决策的地方；一旦降级，`mode` **永久**切为 `'mock'`，后续调用不再触碰网络（避免反复超时拖垮现场体验）。
- 降级原因被归一为 5 类：`no_credential` / `forced_offline` / `transport_failure` / `upstream_error`，直接写进评测报告。

### 3.4 离线确定性：同输入 → 逐字节同输出

评测系统的地基。全部随机性来自 `DeterministicRandom`（mulberry32 + FNV-1a 哈希），**禁止** `Math.random()` 与未注入的 `Date.now()`。

- 文本派生键：`hash(全部 messages 指纹) ⊗ hash(userText) ⊗ turnIndex ⊗ hash(personaId) ⊗ MOCK_SEED`
- 语音派生键：`hash(text) ⊗ hash(voiceId) ⊗ hash(emotion)` → 确定性合成 **真实可播放的 16-bit PCM WAV**（44 字节标准头 + 基频/谐波/包络由情绪映射表决定）

*选型理由*：离线语料若用随机字符串，评测就无从断言；用确定性 WAV 而非空字节，评测才能对"时长 vs 文本长度""情绪 vs 波形差异"做真实锚定。

### 3.5 评测验证系统：6 维加权 + A-B 盲评 + 音频锚定

| 维度 | 权重 | 观测来源 |
|---|---|---|
| 人格一致性 `persona_fidelity` | 0.22 | 口头禅命中率、禁忌词违规、句长分布、第一人称使用率 |
| 情绪标注准确率 `emotion_accuracy` | 0.20 | 12 轮固定剧本的 `expected` vs `actual` 逐位比对 |
| 语音表现力 `voice_expressiveness` | 0.18 | 同一文本在 8 类情绪下的声学参数离散度 + 波形首部差异 |
| 降级健壮性 `fallback_robustness` | 0.15 | 注入故障后异常逃逸次数（必须为 0）、降级后调用是否停止触网 |
| 延迟达标率 `latency` | 0.13 | P95 端到端耗时 vs `EVAL_THRESHOLDS.latencyP95Ms` |
| 剧本推进完整性 `script_integrity` | 0.12 | 阶段单调性、线索揭示与信任度闸值一致性、终局唯一性 |

通过条件：`overall ≥ 0.75` **且**每个维度各自达标（防止用高权重维度掩盖短板）。

**A-B 盲评**用确定性启发式裁判（口头禅密度、情绪标记存在性、句长合规、禁忌词），同分按 id 字典序裁决——"并列不判负"，保证同一批候选任意次运行排名一致。

---

## 4. 快速开始

```bash
cd 15_minimax-abab-agent/src
npm install

npm run typecheck     # tsc --noEmit
npm test              # 全量单元 + 端到端测试
npm run demo          # 终端跑完整对话（默认沈砚）
npm run demo -- he-jinglan
npm run eval          # 跑评测套件并写出 artifacts/ 报告
npm run serve         # 启动 H5 界面 → http://127.0.0.1:8787
```

### 接入真实 MiniMax 凭证

```bash
export MINIMAX_API_KEY=sk-xxx          # 不设置则自动进入离线确定性模式
export AGENT_FORCE_OFFLINE=1           # 强制离线，用于演示降级路径
```

未设置密钥时 `loadConfig()` 直接返回 `mode: 'mock'`，**不会**发起任何网络请求，也**不会**把密钥写入日志或报告（`publicConfigSummary()` 只暴露 `credentialPresent: boolean`）。

---

## 5. 交付物对照

| 官方要求 | 本工程产物 |
|---|---|
| 源码仓库（含 Dockerfile / requirements.txt / package.json） | `src/package.json`、`src/Dockerfile`、`src/requirements.txt`、`src/.dockerignore` |
| 架构与说明文档（流程图 + 算法 + 选型理由） | 本文件 |
| 在线体验 / 一键运行脚本 | `npm run serve`（H5 响应式）/ `npm run demo`（终端）/ `Dockerfile` |
| 演示视频脚本 | `docs/DEMO_SCRIPT.md` |
| 自动化验证（Exit Code 0） | `npm test` → vitest 全绿；`npm run eval` → 评分报告 |
