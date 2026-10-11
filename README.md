# 💰 2026 高奖金蓝海赛事攻坚矩阵 (Cash-Only Bisai Workspace)

> **根目录映射**：`/Users/albert/Documents/project/bisai` -> `apps/bisai`  
> **过滤原则**：**严格剔除无现金/仅算力券/仅证书赛事，仅保留真金白银现金奖池且竞争烈度低、高胜率的项目**。  
> **当前精选**：共 **10 项高奖金实战赛事**，全量配置独立分支与专属开发工程。

---

## 📅 现金奖池与紧急度时间线

| 梯队 | 目录 | 赛事名称 | 报名截止 | 现金奖金标准 | 核心技术栈 |
| :---: | :--- | :--- | :---: | :--- | :--- |
| **P0 紧急** | [`07_na-zhou-aidc`](file:///Users/albert/Documents/project/apps/bisai/07_na-zhou-aidc/RULES.md) | 初焰·钠宙｜钠电 × AIDC 线上黑客松 | **10-13 (剩3天)** | **特等10万 / 冠军1万 / 亚军3千 现金** | Python 线性规划 / 储能调度仿真 |
| **P1 黄金** | [`08_anker-hackathon`](file:///Users/albert/Documents/project/apps/bisai/08_anker-hackathon-2026/RULES.md) | Anker 首届黑客松挑战赛 (AI 软硬件) | **10-17 (剩7天)** | **18万+ 现金池 (一等5万) + 包机票住宿** | 边缘算力用电管家 / 智能体 |
| **P1 黄金** | [`09_watcha-wechat`](file:///Users/albert/Documents/project/apps/bisai/09_watcha-wechat-miniapp/RULES.md) | 观猹 × 2026 微信小程序开发大赛 | **10-17 (剩7天)** | **49 万元 现金奖金池** | 微信 AI 小程序 |
| **P1 黄金** | [`11_genai-open-agent`](file:///Users/albert/Documents/project/apps/bisai/11_genai-open-agent/RULES.md) | Open Agent Hackathon 2026 全球智能体 | **10-22 (剩12天)** | **$20,000 美元现金 (约 14.5 万人民币)** | Multi-Agent / 自主反思协作 |
| **P1 黄金** | [`12_suks-suzhou`](file:///Users/albert/Documents/project/apps/bisai/12_suks-suzhou-ai-hackathon/RULES.md) | 苏客松 2026 苏州 AI 黑客松 | **10-26 (剩16天)** | **50 万元总奖池 (冠军 5 万现金)** | 工业视觉质检 / AIxEverything |
| **P2 充裕** | [`01_coze-skills`](file:///Users/albert/Documents/project/apps/bisai/01_coze-skills-agent/RULES.md) | 扣子 (Coze) AI 智能体与技能共创 | **10-31** | **21万+ 现金池 + 苹果全家桶 + 长期分成** | 扣子 Plugin / 垂类小工具 |
| **P2 充裕** | [`15_minimax-abab`](file:///Users/albert/Documents/project/apps/bisai/15_minimax-abab-agent/RULES.md) | MiniMax · 2026 abab 7 与智能体商业应用 | **11-22** | **20 万元现金 + 创投意向书** | MiniMax 高保真语音 TTS / 全模态 |
| **P2 充裕** | [`16_zhipu-autoglm`](file:///Users/albert/Documents/project/apps/bisai/16_zhipu-autoglm-agent/RULES.md) | 智谱 AI · 2026 AutoGLM 端侧智能体共创 | **11-28** | **30 万元现金 (一等奖 10 万直款)** | AutoGLM SDK / Phone & PC 自动化脚本 |
| **P2 充裕** | [`17_dorahacks-anna`](file:///Users/albert/Documents/project/apps/bisai/17_dorahacks-anna-ai-mcp/RULES.md) | DoraHacks · Anna AI App Builder (MCP 专项) | **11-30** | **月 $80,000 美金资助 (单应用 $6,000 现金)** | Model Context Protocol Server |
| **P3 远期** | [`18_wakeathon-cq`](file:///Users/albert/Documents/project/apps/bisai/18_wakeathon-chongqing-2027/RULES.md) | 雾客松 2027 重庆跨年 AI 黑客松 | **2027-01-10** | **20 万元总奖池 (冠军 8 万现金)** | 工业级综合 AI 原型交付 |

---

## 🛠️ 交付铁律与统一控制台

本项目遵循客观真实交付原则：以真实计算、真实物理模型与真实终端 **Exit Code 0** 为唯一依据，杜绝静态 Mock 与占位符。

### 统一控制台常用命令

```bash
# 执行全部 10 个赛事的单元与回归测试套件 (当前 752 项测试 100% 通过)
make test-all

# 执行全部 10 个赛事的完整端到端独立演示 (Exit Code 0)
make demo-all

# 全量双重交付验证 (test-all + demo-all)
make verify-all
```

---

## 📊 全量交付验收矩阵 (10/10 绿灯通过)

| 编号 | 赛事目录 | 交付核心功能 | 自动化测试数 | 演示入口 | 验收状态 |
| :---: | :--- | :--- | :---: | :--- | :---: |
| **01** | [`01_coze-skills-agent`](file:///Users/albert/Documents/project/apps/bisai/01_coze-skills-agent) | 扣子插件网关 · OpenAPI 3.0 规范自检 (0 error/0 warn) · 容灾沙箱 · 意图路由 | **140 pass** | `./01_coze-skills-agent/scripts/demo.sh` | ✅ 绿灯 |
| **07** | [`07_na-zhou-aidc`](file:///Users/albert/Documents/project/apps/bisai/07_na-zhou-aidc) | 钠电 × AIDC 削峰填谷 LP 调度 · 32 机柜热力数字孪生 · ECharts 离线纯局域网渲染 | **125 pass** | `./07_na-zhou-aidc/scripts/demo.sh` | ✅ 绿灯 |
| **08** | [`08_anker-hackathon-2026`](file:///Users/albert/Documents/project/apps/bisai/08_anker-hackathon-2026) | Anker Solix 24h 闭环 MPC 滚动时域调度 · NILM 负荷分解 · SOH 电池衰减与 ROI 报表 | **143 pass** | `./08_anker-hackathon-2026/scripts/demo.sh` | ✅ 绿灯 |
| **09** | [`09_watcha-wechat-miniapp`](file:///Users/albert/Documents/project/apps/bisai/09_watcha-wechat-miniapp) | 观猹微信小程序 · TF-IDF+正则确定性本地抽取 · iPhone 16 Pro H5 离线免编译模拟器 | **41 pass + 13 rules** | `./09_watcha-wechat-miniapp/scripts/demo.sh` | ✅ 绿灯 |
| **11** | [`11_genai-open-agent`](file:///Users/albert/Documents/project/apps/bisai/11_genai-open-agent) | 企业级多智能体协同 · 4 角色 DAG 拓扑看板 · 黑板事件流 · 人工审核闸门 | **66 pass** | `./11_genai-open-agent/scripts/demo.sh` | ✅ 绿灯 |
| **12** | [`12_suks-suzhou-ai-hackathon`](file:///Users/albert/Documents/project/apps/bisai/12_suks-suzhou-ai-hackathon) | InspectAI 表面缺陷 CPU 亚秒质检 · 800% 傅里叶频域放大镜 · 缺陷卡尺 · ISO 报告 | **56 pass (8/8 吻合)** | `./12_suks-suzhou-ai-hackathon/scripts/demo.sh` | ✅ 绿灯 |
| **15** | [`15_minimax-abab-agent`](file:///Users/albert/Documents/project/apps/bisai/15_minimax-abab-agent) | 镜厅推理剧会话状态机 · 动态 SVG 线索红绳墙 · 心理压力计 · 商业化得分 92.1 | **116 pass** | `./15_minimax-abab-agent/scripts/demo.sh` | ✅ 绿灯 |
| **16** | [`16_zhipu-autoglm-agent`](file:///Users/albert/Documents/project/apps/bisai/16_zhipu-autoglm-agent) | AutoGLM 端侧跨平台自动化 · 手机触控水波纹 · 无障碍节点树检查器 · 漂移自愈 | **30 pass** | `./16_zhipu-autoglm-agent/scripts/demo.sh` | ✅ 绿灯 |
| **17** | [`17_dorahacks-anna-ai-mcp`](file:///Users/albert/Documents/project/apps/bisai/17_dorahacks-anna-ai-mcp) | 零依赖手写 JSON-RPC 2.0 MCP 服务 · RRF 混合重排 · 安全准入防御 · Web 检查器 | **35 pass + 17 smoke** | `./17_dorahacks-anna-ai-mcp/scripts/demo.sh` | ✅ 绿灯 |
| **18** | [`18_wakeathon-chongqing-2027`](file:///Users/albert/Documents/project/apps/bisai/18_wakeathon-chongqing-2027) | 雾醒山城 3D 空间计算 · Three.js/CSS 双引擎 · 5 电影级导播机位 · 24 场景评测 (81.5分) | **24/24 eval pass** | `./18_wakeathon-chongqing-2027/scripts/demo.sh` | ✅ 绿灯 |
| **合计** | **10 大纯现金赛事全家桶** | **全真机/全真算法/零假数据/零外部侵入** | **752 项测试全绿** | `make demo-all` | **100% 交付达标** |

