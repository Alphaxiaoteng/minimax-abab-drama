# 微信开发者工具导入与真机调试指引 (WeChat DevTools Guide)

> 面向大赛评委与开发者。按本指引可在 5 分钟内完成导入、编译、离线降级演示与真机预览。
> 前置软件：[微信开发者工具](https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html) 稳定版（Stable Build）即可。

---

## 1. 导入目录（第一步，最容易错）

1. 打开微信开发者工具 → 「小程序」→ **导入**。
2. **目录选择本项目的根目录 `09_watcha-wechat-miniapp/`**（即包含 `project.config.json` 的那一层），**不要**直接选 `src/`。
3. 工具会读取根目录 `project.config.json`，自动识别：
   - `miniprogramRoot: "src/"` —— 小程序代码根（主包 + 分包都在其中）
   - `cloudfunctionRoot: "cloudfunctions/"` —— 云函数目录（health / doc-insight / triage-plan）

目录结构速览：

```text
09_watcha-wechat-miniapp/
├── project.config.json      # 开发者工具工程配置（导入时选这一层）
├── cloudbaserc.json         # 云函数部署声明（可选）
├── cloudfunctions/          # 云函数源码（可选）
├── src/                     # 小程序代码根
│   ├── app.json             # pages 主包 3 个 tab；subPackages 2 个分包
│   ├── config.js            # CLOUD_ENV / AGENT_BOT_ID / IS_OFFLINE_DEMO
│   ├── pages/home|quickread|triage/   # 主包：首页 + 两个 tab 场景页
│   ├── packages/quickread/  # 分包：详情页 detail、历史页 history
│   ├── packages/triage/     # 分包：今日安排页 today
│   ├── components/          # 四个自定义组件（均已 usingComponents 声明）
│   └── core/                # agent / ai-adapter / local-engine（离线内核）
└── docs/WECHAT_DEVTOOLS_GUIDE.md   # 本文档
```

> 合规说明：微信官方规范要求 **tabBar 页面必须在主包 `pages` 中定义**（`pagePath` “必须在 pages 中先定义”）。
> 本项目三个 tab（首页 / 一页纸 / 断舍离）全部位于主包，仅详情、历史、今日安排进入分包按需加载，`preloadRule` 在首页预下载 quickread 分包。`npm run check` 的规则 (j) 会持续把关此约束。

## 2. AppID 与测试号选择

| 场景 | 做法 |
|---|---|
| **评委快速体验（推荐）** | 导入时 AppID 一栏点「**使用测试号**」（或留空选游客模式）。测试号可编译、可模拟器运行、可预览；**不可**使用云开发。产品自带离线确定性内核，无云环境也能完整演示双场景。 |
| **有自己的小程序 AppID** | 填入 `wx` 开头的真实 AppID，并同步替换 `project.config.json` 里的 `appid`（仓库占位值为 `wx0000000000000000`，直接编译会报 AppID 格式/校验错误）。 |
| **需要云开发 AI 流式链路** | 必须使用**已开通云开发的正式 AppID**，然后按第 5 节配置环境。 |

注意：项目 `appid` 占位符不影响 Node 侧的 `npm run verify` / `./scripts/demo.sh`，它们完全不经过微信工具。

## 3. 本地设置（编译配置）逐项说明

导入后在工具右上角「详情 → 本地设置」核对，仓库 `project.config.json` 已内置以下推荐值：

| 设置项 | 对应字段 | 推荐值 | 为什么 |
|---|---|---|---|
| ES6 转 ES5 | `setting.es6: true` | **开** | 源码含 `const`/箭头函数/解构；开启后由工具内置 babel 转译，兼容全部真机基础库。 |
| 增强编译 | `setting.enhance: true` | **开** | 补齐 async/await 等语法运行时（`core/agent.js` 使用 Promise 链）。 |
| 上传时压缩样式 | `setting.postcss: true` | **开** | wxss 自动补全 flex 兼容前缀。 |
| 上传代码时自动压缩混淆 | `setting.minified: true` | **开** | 上传体验版/提审包时进一步压缩体积；主包当前未压缩仅 109.6 KB（占 2MB 硬限 5.35%）。 |
| 不校验合法域名 | `setting.urlCheck: false` | **开**（即不校验） | 云开发 AI 域名由平台托管；本地联调无需在后台配域名。正式提审前在小程序后台配置合法域名。 |
| 按需注入 | `app.json: lazyCodeLoading` | `requiredComponents` | 只注入页面实际用到的自定义组件代码，是「秒开」的关键开关。 |

其余无需勾选「用 npm 模块」「代码保护」等选项：本工程**零第三方运行时依赖**。

## 4. 编译与入口调试

1. 编译（Ctrl/Cmd+B）。首帧即出内容：首页 `onLoad` 全同步读本地缓存，**不发起任何网络请求**，模拟器应无白屏。
2. 右上角「普通编译」下拉 → **添加编译模式**，可直接指定启动页调试（`project.config.json` 已内置 3 条 condition）：
   - `pages/home/index`（首页秒开）
   - `pages/quickread/index`（一页纸快读 tab）
   - `pages/triage/index`（日程断舍离 tab）
3. tab 切换走 `wx.switchTab`；详情/历史/今日安排在分包内，首次进入时工具控制台会打印分包下载日志，属正常现象。

## 5. 云开发 AI 链路（可选进阶）

不配云环境**不影响演示**（见第 6 节）。要跑通在线流式：

1. 「云开发」控制台创建环境，得到环境 ID（如 `watcha-xxx`）。
2. 编辑 `src/config.js`：`CLOUD_ENV = '<环境ID>'`；按 `agent/README.md` 创建云开发 Agent 并填 `AGENT_BOT_ID`。
3. 右键 `cloudfunctions/health` → 上传并部署（云端安装依赖），调用应返回 `{ ok: true }`；同样部署 `doc-insight`、`triage-plan`。
4. 流式链路为 SSE/AG-UI：控制台 Network 面板应看到 `RUN_STARTED → TEXT_MESSAGE_CONTENT → RUN_FINISHED` 事件序列。
5. 超时/失败无需手动处理：`TIMEOUT_MS`（60s）后 `core/ai-adapter.js` 判定不可用，**自动**降级离线内核。

## 6. 本地离线降级演示（评委零风险路径）

设计目标就是「现场演示零翻车」，两种方式任选：

**方式 A（默认即离线）**：不配置 `CLOUD_ENV` 直接编译。任意长文点「生成一页纸」，输出卡片标注「离线分析」（`usage.mode: 'local'`），结论/关键数据/风险点/原文引用四区块齐全——由 `src/core/local-engine.js` 正则提数 + TF-IDF 摘要真实计算，非假数据；日程 tab 同理产出 Top3/延后/删除建议。

**方式 B（演示“在线→断网无缝降级”）**：配好云环境后，在调试面板「Network」切到**无网络**（或拔网线/关 Wi-Fi），再点生成——请求失败即静默切到离线内核，页面不白屏、不弹错误，卡片照常产出。这正对应 `npm run verify` 中「抛错降级 mode=local 且 structured 非空」的自检。

**方式 C（录屏专用）**：`src/config.js` 将 `IS_OFFLINE_DEMO` 置 `true`，强制全离线，产出完全确定、可复现。

## 7. 真机预览步骤

1. 工具栏点「**预览**」→ 生成二维码。
2. 用**微信**扫码：
   - 测试号：扫码账号需为该测试号管理员（登录 mp 平台查看）；预览包在手机上以「测试号小程序」运行。
   - 游客模式：仅能在工具的「真机调试」里连模拟器桥，不能外发扫码——评委建议用测试号。
3. 首次扫码若提示下载分包，属正常（quickread 14.1 KB / triage 8.9 KB，秒下）。
4. 需要边操作边看日志时用「**真机调试**」按钮（2.0 模式），可远程查看真机 console 与网络面板。
5. 真机验证清单：三 tab 可切换、离线卡片四区块完整、断网后生成不白屏、首页如实显示「首屏 X ms」。

## 8. 交付前合规自检（无需开发者工具）

在仓库根目录执行：

```bash
npm run verify      # 13 条静态规则（含 tabBar 主包约束、未声明组件、页面死链检查）+ 41 项单元测试
./scripts/demo.sh   # 体积分析 + 双链路「秒开→流式→结构化→抛错降级」离线自检，全部 Exit Code 0
```

`npm run check` 与真机编译前的预检一一对应：规则 (a) 页面四件套、(b) 组件引用可解析、(j) tabBar 主包约束、(k) 无未声明组件、(m) 导航/分享路径无死链。静态审计全绿后再导入开发者工具，可避免绝大多数「导入即报错」。

## 9. 常见问题 (FAQ)

| 现象 | 原因与解法 |
|---|---|
| 导入后提示 AppID 不合法 | 仓库占位 `wx0000000000000000`；改选「测试号」或填真实 AppID（第 2 节）。 |
| 报「tabBar 第 N 个页面未找到」 | 检查是否误把 `src/` 当导入根、或改动过 `app.json`；`npm run check` 规则 (j) 会拦截此类违规。 |
| 模拟器白屏 | 正常不应出现；若出现，检查是否删除了 `app.js` 的缓存预热逻辑。t0 秒开路径零网络依赖。 |
| 分包页面跳转失败 | tab 页必须 `wx.switchTab`，分包页用 `wx.navigateTo`；本工程已按此实现，自定义改动时注意。 |
| 预览二维码手机打不开 | 测试号需管理员本人扫码；或改用「真机调试」。 |
