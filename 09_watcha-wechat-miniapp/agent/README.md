# Agent 配置指南（云开发控制台）

> 适用范围：本目录是「观猹」小程序两个 AI tab（一页纸快读 / 日程断舍离）的 **Agent 系统提示词与工具声明规格**。
> 本机没有微信开发者工具与云开发环境，以下步骤需在 **有云开发权限的机器上人工执行**；执行前本项目全部通过离线静态校验即可运行（降级内核）。

---

## 一、文件清单

| 文件 | 作用 |
| --- | --- |
| `system-prompt-quickread.md` | 「一页纸快读」Agent 的 system prompt，严格 JSON 输出 |
| `system-prompt-triage.md` | 「日程断舍离」Agent 的 system prompt，严格 JSON 输出 |
| `tools.json` | AG-UI 工具声明：`side=client` 由小程序端执行（`TOOL_CALL_START/ARGS/END/RESULT`），`side=server` 绑定 `cloudfunctions/` 下同名云函数 |

## 二、在云开发控制台创建 Agent（≤15 步）

1. 微信公众平台 → 小程序后台 →「云开发」，开通/选择环境，记下环境 ID（形如 `watcha-xxxxxx`）。
2. 云开发控制台左侧「AI 与大数据」→「Agent（智能体）」→「创建 Agent」。
3. 创建第一个 Agent：名称填 `quickread`，描述填「长文一页纸快读」。
4. 在「系统提示词」输入框中**整篇粘贴** `agent/system-prompt-quickread.md` 正文（从「你是『AI 一页纸快读』…」开始）。
5. 模型选择 `deepseek-v4.1-flash`（云函数与 Agent 保持同一模型，便于行为一致）。
6. 工具绑定：添加前端工具 `extract_url_text`、`save_to_history`、`share_card`（参数与 `tools.json` 中对应条目一致）；添加后端工具 `doc_insight_extract` → 选择云函数 `doc-insight`。
7. 保存后复制该 Agent 的 **botId**（`agent-xxxxxxxx` 形式）。
8. （可选，分场景双 Agent）重复 2–7 创建第二个 Agent：名称 `triage`，粘贴 `agent/system-prompt-triage.md`，后端工具 `triage_plan` → 云函数 `triage-plan`，复制其 botId。当前 `src/config.js` 契约冻结 `AGENT_BOT_ID` 为**单值字符串**（两场景共用一个 bot）；需按场景区分时，接入方自行把该字段扩展为映射并同步 `core/ai-adapter.js` 的读取逻辑。
9. 先部署云函数（控制台「云函数」→「创建」逐个上传 `cloudfunctions/health|doc-insight|triage-plan/` 目录；或使用 CloudBase CLI，见第三节）。
10. 在云函数「健康检查」调用示例里调用 `health`，预期返回 `{ ok: true, ts, sdk: 'wx-server-sdk', version }`；失败先查环境与权限。
11. 回到 `src/config.js`，把环境 ID 与 botId 填入（单值字符串，空字符串 = 强制离线降级）：
    ```js
    const CLOUD_ENV = 'watcha-xxxxxx'      // 第 1 步记录的环境 ID
    const AGENT_BOT_ID = 'agent-xxxxxxxx'  // 第 7 步的 botId
    ```
12. 微信开发者工具打开 `src/`，「详情 → 本地设置」勾选对应云环境后，在两个 tab 各发一次真实请求验证 AG-UI SSE 流（`RUN_STARTED` → `TEXT_MESSAGE_CONTENT`… → `RUN_FINISHED`）。
13. 若第 11 步留空或第 12 步调用失败，`core/agent.js` 自动降级到 `src/core/local-engine.js` 确定性内核——卡片标注「离线分析」（`usage.mode:'local'`），功能仍可用。
14. 在本机复跑离线校验：`node tools/check-static.js`（由并行任务 `DocsTools` 产出；若该脚本缺失，仓库根的 `npm run check` 等价），预期退出码 `0`。
15. 把第 1、7 步得到的环境 ID 与 botId 写入 `doc/DEPLOY-NOTES.md`（人工补录），供评审复现。

## 三、用 CloudBase CLI 一键部署（替代第 9 步）

```bash
npm i -g @cloudbase/cli   # 需要联网，评审机器上执行
tcb login
tcb fn deploy --config cloudbaserc.json
```

`cloudbaserc.json` 已声明三个云函数的 `name/timeout/runtime:"Nodejs18.15"/envVariables` 与 `version:"2.0"`。

## 四、提示词修改约定

- 两个 prompt 都必须保持「恰好 4 个区块 + 严格 JSON + 不可编造」三约束；改动区块标题需同步更新 `src/` 渲染组件与单测断言。
- `tools.json` 的 `side=server` 工具必须显式写 `cloudFunction` 字段且与 `cloudfunctions/` 目录名逐一对应。
- 云函数侧任何异常都返回 `{ ok:false, mode:'cloud', error }`，**绝不 throw**——这是降级链路可靠的前提。