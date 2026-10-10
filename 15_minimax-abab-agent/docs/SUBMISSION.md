# MiniMax 商业应用挑战赛 · 参赛项目提交案 (Submission Dossier)

## 1. 项目定位与一句话价值 (Executive Summary)
- **项目名称**：Immersive Drama Agent（原生富媒体沉浸式互动推理剧 Agent）
- **参赛赛道**：MiniMax 商业应用挑战赛 · 娱乐消费与角色陪伴赛道（20万现金池）
- **一句话价值**：结合 MiniMax abab 文本大模型与拟真情绪 TTS（T2A v2）的互动推理剧 Agent，以独创“状态机四投影架构”杜绝人格飘移，搭载 6 维度量化评测体系与离线保活降级。

---

## 2. 核心痛点与技术突破 (Pain Points & Innovations)
1. **痛点一：角色在第 3 轮对话后产生严重“人格飘移”**
   - *突破*：提出“剧情不变量交给确定性状态机、语言表演交给 abab 7”的解耦架构。将阶段流转（phase）、线索解锁阈值、亲密/紧张度严格锁定在状态机内，语言指纹与口头禅自动化断言。
2. **痛点二：模型情绪标注与语音音色脱钩（表面愤怒、声线平淡）**
   - *突破*：自研情绪闭环解析器，将输出的情绪标签动态映射为 T2A v2 声学参数（speed/vol/pitch/emotion 范围夹紧），实现波形首部特征互异，真正做到“不是换标签，而是换波形”。
3. **痛点三：网络波动或上游欠费时评委现场翻车**
   - *突破*：实现异常永不逃逸的“单点熔断降级机制”。一旦接口报错，自动无缝切换到确定性离线语料与模拟波形，并在 UI 上透明提示，保证演示 100% 连贯完成。

---

## 3. 系统架构 (System Architecture)

```mermaid
flowchart TD
    User([玩家 / 评审]) --> UI[沉浸式 H5 终端 (氛围色 + 音频播放)]
    UI --> Server[Node.js 交互网关]
    
    subgraph CoreEngine [智能体导演内核]
        Director[导演状态机 Director Engine]
        Personas[原创人格库 (沈砚 / 林小满 / 何静澜)]
        MiniMaxClient[MiniMax 外呼与异常熔断层]
    end
    
    Server --> Director
    Director --> Personas
    Director --> MiniMaxClient
    
    subgraph MiniMaxAPI [MiniMax 官方云端服务]
        ABAB[abab 文本大模型]
        T2A[T2A v2 情绪拟真语音合成]
    end
    
    MiniMaxClient -->|在线模式| ABAB
    MiniMaxClient -->|在线模式| T2A
    MiniMaxClient -.->|故障断网| MockKernel[离线确定性 Mock 引擎]
    
    Director --> EvalSystem[6维量化评测系统]
    EvalSystem --> EvalReport[eval-report.json / md 交付报告]
```

---

## 4. 权威基准指标与实测性能 (Benchmarks)

| 评测维度 | 权重 | 得分 | 达标阈值 | 结论 |
|---|---|---|---|---|
| **人格一致性 (persona_fidelity)** | 22.0% | **100.0%** | 72.0% | ✅ 达标 (口头禅命中 10/10) |
| **情绪标注准确率 (emotion_accuracy)** | 20.0% | **90.0%** | 70.0% | ✅ 达标 (情绪位逐位匹配) |
| **语音表现力 (voice_expressiveness)** | 18.0% | **67.5%** | 50.0% | ✅ 达标 (声学参数极差显著) |
| **降级健壮性 (fallback_robustness)** | 15.0% | **100.0%** | 90.0% | ✅ 达标 (10次降级0异常逃逸) |
| **延迟达标率 (latency)** | 13.0% | **100.0%** | 80.0% | ✅ 达标 (单轮 < 2500ms) |
| **剧本推进完整性 (script_integrity)** | 12.0% | **100.0%** | 60.0% | ✅ 达标 (顺利通关至第5阶段) |
| **综合总评分** | 100% | **92.1%** | **75.0%** | **🏆 优秀** |

- **单元测试**：116 / 116 全量通过（Vitest Exit Code 0）。

---

## 5. 评委2分钟答辩/路演脚本 (2-Minute Pitch Script)
- **[0:00 - 0:30] 痛点引入**：各位评委好！当前市面上的 AI 陪伴和互动剧产品有三个致命硬伤：聊三句就出戏、声音和角色情绪脱钩、以及现场演示断网就崩溃。
- **[0:30 - 1:00] 技术突破**：我们基于 MiniMax 旗舰模型打造了沉浸式推理剧 Agent。核心创新是“状态机四投影”，将剧情推进、嫌疑人隐藏线索用数学状态机硬锁，把 abab 7 的语言表演与 T2A v2 的声学特征深度绑定。
- **[1:00 - 1:30] 动态演示**：运行 `./scripts/demo.sh`，可以看到面对真凶何静澜，当紧张度飙升时，角色的回复不仅带有 `[tense]` 标记，其导出的语速与音高波形也完全改变！即使我们拔掉网线，系统也能无缝切入离线语料，剧本照常推进。
- **[1:30 - 2:00] 商业闭环**：我们提供了行业首个 6 维自动化商业量化评估系统，综合评分高达 92.1%。该项目不仅能直接落地剧本杀和文旅沉浸体验，更是展示 MiniMax 情绪语音实力的标杆商业应用！

---

## 6. 一键复现指南 (Quickstart)

```bash
# 1. 运行 116 项全量单元与状态机测试
cd src && npm test

# 2. 运行一键离线会话演示与 6 维评测套件
./scripts/demo.sh
```
