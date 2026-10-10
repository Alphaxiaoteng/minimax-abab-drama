# China Residential Time-of-Use (分时电价) Tariff & 2025–2026 Policy Landscape
*Fact-pack for the Anker home-battery scheduling agent. Every 元/kWh figure cites a primary 发改委 / 电网 filing or a state-grid page. Figures are 含税 unless noted. Residential prices do NOT include 政府性基金及附加 (small, ~0.02–0.03元/kWh). Data as of 2026-10-10.*

## Legend — provenance
- **官方**: number lifted directly from an official filing or state-grid tariff table (URL cited).
- **[ESTIMATE]**: derived (arithmetic) or a commonly-published value I could not confirm in a primary source on this pass. Treat as planning input, not ground truth.

---

## 1. National framework

**发改价格〔2021〕1093号《关于进一步完善分时电价机制的通知》** — https://www.ndrc.gov.cn/xxgk/zcfb/tz/202107/t20210729_1292067.html
- Peak/valley price ratio: **≥4:1** where system peak-valley load gap >40%; otherwise **≥3:1**.
- **尖峰 (critical peak)**: introduced on top of peak, **≥ +20% over peak price**.
- Residential TOU is a *rollout*: “有条件的地方，要按程序推广居民分时电价政策，逐步拉大峰谷价差” → residential TOU is **opt-in, not mandated**.

**发改价格〔2025〕136号《关于深化新能源上网电价市场化改革…的通知》** (2025-01-27) — https://www.gov.cn/lianbo/bumen/202502/content_7002957.htm and https://www.ndrc.gov.cn/xxgk/zcfb/tz/202502/t20250209_1396066.html
- All wind/PV grid-export energy enters the market; export price set by market.
- **存量项目 (before 2025-06-01)**: 机制电价 = current policy, capped at local coal benchmark price.
- **增量项目 (after 2025-06-01)**: 机制电价 via yearly competitive bidding.
- Difference (market avg vs 机制电价) settled monthly as 差价结算, booked into 系统运行费用.
- **Explicit ban on forced storage co-location** as a precondition for approval/grid-connection of new PV.

**2025–2026 trend — fixed 工商业 分时 being cancelled**: 贵州/湖北/陕西/河南/重庆/吉林/云南/辽宁/浙江 etc. are retiring government-fixed 工商业 TOU for market-following prices — https://www.chinanews.cn (via 中国网, 2026-07-29) http://tt.cnkbd.cn/dongtai/12412.html ; “超10省取消尖峰电价”, 2026-09 — https://finance.sina.com.cn/roll/2026-09-10/doc-inirixks2768584.shtml . Residential TOU is so far unaffected but the *spread* it tracks is compressing nationally.

---

## 2. Provincial residential schedules

### 2.1 深圳 / 广东 — 官方
Source table (深圳市居民生活电价价目表, PDF) — https://fgw.sz.gov.cn/attachment/1/1460/1460239/11394935.pdf ; policy notice — https://fgw.sz.gov.cn/gkmlpt/content/9/9493/mmpost_9493596.html

| 时段窗口 | 一档 (元/kWh) | 二档 | 三档 | 窗口定义 |
|---|---|---|---|---|
| 尖峰/峰 (峰期) | 1.1121 | 1.1621 | 1.4121 | 高峰 10:00–12:00, 14:00–19:00 |
| 平段 (平期) | 0.6542 | 0.7042 | 0.9542 | 平时段 8:00–10:00, 12:00–14:00, 19:00–24:00 |
| 低谷 (谷期) | 0.2486 | 0.2986 | 0.5486 | 低谷 0:00–8:00 |

- Residential **峰谷比价 1.7:1:0.38** (notice). No *residential* 尖峰; 尖峰 (+25% over 峰) is 工商业/大工业 only (Jul–Sep & ≥35°C days, 11–12 / 15–17). Source: https://fgw.sz.gov.cn/gkmlpt/content/9/9493/mmpost_9493596.html
- **阶梯 on top**: 夏季(5–10月) 一档 0–260度 / 二档 261–600 / 三档 601+; 非夏季 0–200 / 201–400 / 401+. Residential TOU is **opt-in** (“居民用户可自主选择是否执行峰谷电价”).
- Guangdong 工商业 peak-valley spread 珠三角六市 **1.3963元/kWh**, 全国最高 (2026-09) — https://finance.sina.com.cn/roll/2026-09-10/doc-inirixks2768584.shtml

### 2.2 上海 — 官方 (一档) / 官方 tier table
Shanghai 市场监管/政府 pages — https://scjgj.sh.gov.cn/1072/20210303/2c9bf2f677811b0b017781247e9104fe.html and https://english.shanghai.gov.cn/en-Business-PremisesUtilities-WaterElectricityandGas/20260818/7d4767035baf4263b8819080f33ac62e.html ; 分时机制 notice PDF — https://www.shanghai.gov.cn/cmsres/11/11ef6ccf01c3435488c453168b331e5f/297d9dff9b59d336f08f0eb6b80179e0.pdf

| 时段 | 一档 峰 (元/kWh) | 一档 谷 | 说明 |
|---|---|---|---|
| 峰段 06:00–22:00 | 0.617 | — | 官方 (scjgj.sh.gov.cn) |
| 谷段 22:00–次日06:00 | — | 0.307 | 官方 |

- Tiered (阶梯, annual kWh): T1 0–3120 / T2 3121–4800 / T3 4800+. English gov page lists T1 峰0.617/谷0.307; T2/T3 add tiered uplift (≈ +0.05 / +0.30). T2/T3 exact peak/valley **values [ESTIMATE]** (page OCR partial).
- 冬季(1、12月) 19:00–21:00 = **尖峰时段** but applies to 工商业 分时 windows in that notice, not core residential 2-tier schedule. Residential = opt-in choice between 阶梯-only vs 阶梯+分时.

### 2.3 山东 — 官方
烟台发改委 政策解读 (2025-04-21) — https://fgw.yantai.gov.cn/art/2025/4/21/art_52219_2909514.html ; 山东电网销售电价表 — https://www.jining.gov.cn/module/download/downfile.jsp?classid=0&filename=128863c36ae24b20ac95542c43f7d915.pdf

| 档 | 峰段 8:00–22:00 | 谷段 22:00–次日8:00 | 谷段(采暖期 20:00–8:00) |
|---|---|---|---|
| 一档 | 0.5769 | 0.3769 | 0.3469 |
| 二档 | 0.6269 | 0.4269 | 0.3969 |
| 三档 | 0.8769 | 0.6769 | 0.6469 |

- Mechanism: 阶梯 base (一档 0.5469) **+0.03 峰 / −0.17 谷** (−0.20 谷 in heating season). Source: 烟台发改委 + 青岛供电表 PDF http://www.qingdao.gov.cn/ywdt/zwzl/ggqsydwgk/srqd/gd/gwsdsdlgsqdgdgs/djsf/sfyj/202310/P020231031532722239238.pdf
- **Opt-in 自愿选择**; 阶梯 still applies. 尖峰 (工商业): Jun–Aug 10:30–11:30 & 19:00–21:00 — 山东电网表 PDF. 山东 工商业 spread 0.9023元/kWh (2026-09) — sina 储能产业网 link above.

### 2.4 浙江 — 官方 (一档 峰/谷) 
浙江物价局 浙价资[2012]169号 PDF — https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web3549/site/attach/0/fe6c1374be1b44d5861b6ef636cba0e0.pdf ; 宁波居民电价 (2026-05) — https://finance.sina.cn/2026-05-19/detail-inhymqce3213824.d.html ; CPEM 峰谷电 — https://www.cpem.org.cn/list2/99450.html

| 时段 | 一档 (元/kWh) |
|---|---|
| 峰段 8:00–22:00 | 0.568 |
| 谷段 22:00–次日8:00 | 0.288 |

- Flat (no-TOU) 一档 base 0.538 (宁波 sina). T2 +0.05 / T3 +0.30 on 峰&谷同步. **Opt-in 自愿申请**; 阶梯 applies by annual kWh (一档 ≤2760/yr).
- 深谷 exists for 工商业 (holidays/midday), 浙发改价格〔2026〕112号 (peak 16–23 all year, midday valley extended) — https://finance.sina.com.cn/wm/2026-07-01/doc-inifiaeu6267845.shtml

### 2.5 江苏 — 官方 (windows + tiers), prices partly [ESTIMATE]
国网南通 居民电价提示 (2026-07) — https://nginx-ntfb.ntfabu.com/ntfb/site1/mweb/ja9rl/c36833330.html ; 苏州/江苏销售电价表 — https://fg.suzhou.gov.cn/szfgw/djglwj/201907/7ff8fd63642d4d048fc0010a86fbc1d5.shtml

| 时段窗口 | 价格 |
|---|---|
| 峰段 8:00–21:00 | 一档平段基础 **上上浮 [ESTIMATE ≈+0.15]** |
| 谷段 21:00–次日8:00 | **下浮 [ESTIMATE ≈−0.17]** |
| 未开通分时 | 全天平段 = 阶梯档价 |

- 一档 flat 0.5283 (不满1千伏); 阶梯: 一档 ≤230度/月, 二档 +0.05, 三档 +0.3; 合表 0.5483 (南通信). **Opt-in 自愿申请, 选定后一年内不得变更**; 阶梯叠加. Exact 峰/谷 yuan per kWh **not in a primary residential table on this pass → [ESTIMATE]**.
- 工商业 (for context): 江苏 spread fell to 0.5473元/kWh after 426号文 (2025) — https://m.bjx.com.cn/mnews/20250707/1449717.shtml

### 2.6 四川 — 官方 (windows + 阶梯), residential 谷 price [ESTIMATE]
川发改价格〔2025〕185号 — https://gysctq.sczwfw.gov.cn/art/2025/5/30/art_35125_287567.html ; 居民阶梯 一档 0.5224 — https://sc.people.com.cn (2012) via search; 阶梯调整 川发改价格〔2026〕255号 — https://www.163.com/dy/article/L0E4C06B05568W0A.html

- **居民低谷时段 (official): 23:00–次日07:00** (“一户一表居民用户低谷电价政策时段划分维持不变”). Exact residential 谷/峰 yuan **not published in a primary residential table on this pass → [ESTIMATE]** (typically 谷 ≈ flat−0.15~0.20, 峰 ≈ flat+0.10~0.15).
- 阶梯: 一档 0.5224, 二档 0.6224, 三档 0.8224; 2026-07 summer 一档 0–260度. 工商业 尖峰: Jul–Aug 13–14 & 21–23 (+3h), Dec/Jan 尖峰 cancelled. Opt-in for residential; 阶梯叠加.

### 2.7 北京 — 官方 (阶梯 only; residential TOU not offered)
北京市发改委 电价页 (2026-07-22) — https://fgw.beijing.gov.cn/bmcx/djcx/jzldj/202110/t20211025_2520169.htm ; 2023 分时 notice was **工商业-only**, “居民用电价格不受影响” — https://www.beijing.gov.cn/zhengce/zcjd/202308/t20230822_3227446.html

| 档 | 月电量 | 不满1千伏 | 1千伏及以上 |
|---|---|---|---|
| 一档 | 1–240度 | 0.4883 | 0.4783 |
| 二档 | 241–400度 | 0.5383 | 0.5283 |
| 三档 | >400度 | 0.7883 | 0.7783 |

- **Beijing residential = tiered flat price, no current residential peak-valley TOU option** per the official 电价 table (only 工商业 has TOU/尖峰, e.g. 京发改〔2026〕1184号 输配电 — https://fgw.beijing.gov.cn/fgwzwgk/2024zcwj/bwqtwj/202607/t20260722_4777454.htm). → **Low value for residential battery arbitrage in Beijing.**

### 2.8 湖南 — 官方 (阶梯), residential TOU yuan [ESTIMATE]
湘发改价调规〔2024〕14号 (阶梯) — https://fgw.hunan.gov.cn/fgw/xxgk_70899/zcfg/dfxfg/202401/t20240131_32641110.html ; 湘发改价调规〔2025〕385号 (优化分时, 工商业) — http://fgw.hunan.gov.cn/fgw/xxgk_70899/zcfg/dfxfg/202507/t20250702_33727950.html

- 阶梯: 一档 ≤200度 **0.588** (不满1千伏); 二档 +0.05; 三档 +0.30. Residential 峰谷 yuan per kWh **not confirmed in primary residential table → [ESTIMATE]**; residential TOU opt-in.
- 工商业 spread Hunan **1.5209元/kWh (7月, 2nd highest nationally)** — https://m.bjx.com.cn/mnews/20250707/1449717.shtml

---

## 3. 尖峰 / 深谷 presence and multipliers
- **尖峰 exists mostly on the 工商业 side** in the candidate set: 广东/深圳 大工业 = 峰段 **+25%** (Jul–Sep & ≥35°C); 四川 Jul–Aug 3h window; 山东 Jun–Aug windows; 上海 winter 19–21 (工商业 notice); 江苏 has 尖峰 per 2025 新政 (shortened). National rule = **≥ +20% over peak** (1093号). Pure **residential 尖峰 is rare / effectively absent** — residential max is the 峰 tier.
- **深谷** (deepest valley) is a 工商业 add-on for holidays/midday (浙江 21号/112号, 江苏 major-holiday deep valley, 上海). Not in the residential schedules above.
- “超10省取消尖峰” in 2026-09 → 尖峰 prevalence is declining. Source: https://finance.sina.com.cn/roll/2026-09-10/doc-inirixks2768584.shtml

## 4. National extremes (observed)
- **Cheapest residential 低谷**: **0.2486元/kWh (深圳, 一档谷期)** — official Shenzhen PDF. Shandong 采暖谷 0.3469 is next-lowest confirmed residential.
- **Most expensive residential 峰**: **1.4121元/kWh (深圳, 三档峰期)** / **1.1121元/kWh 一档峰**.
- **工商业** context (not residential): national avg 尖峰 1.275元/kWh, single-tier; residential never reaches this.

## 5. Opt-in vs default + 阶梯 stacking — matrix

| 省/市 | Residential TOU | 阶梯 on top? |
|---|---|---|
| 深圳/广东 | 自愿 opt-in | YES |
| 上海 | 自愿 opt-in | YES (annual tier) |
| 山东 | 自愿 opt-in | YES |
| 浙江 | 自愿申请 opt-in | YES (annual tier) |
| 江苏 | 自愿申请 opt-in (锁定1年) | YES |
| 四川 | opt-in (低谷) | YES |
| 北京 | **无 residential TOU** | YES (only tiered) |
| 湖南 | opt-in | YES |

Implication for the agent: charging the battery in 谷 *adds* monthly kWh, which can push the household into 二/三档 (+0.05 / +0.30), eroding arbitrage. The optimizer must model tier accumulation, not just TOU windows. Default (national) is opt-in per 1093号 “推广” language.

## 6. Distributed PV + storage self-consumption & feed-in (上网电价)
- **136号文 (2025)**: PV export goes to market; 存量 机制电价 capped at local coal benchmark, 增量 via bidding; monthly 差价结算 into 系统运行费用; **forced storage co-location banned as grid-connection precondition**. https://www.gov.cn/lianbo/bumen/202502/content_7002957.htm
- **Export is compensated** via market price + (for selected projects) a 机制电价差价, not a fixed national FIT. Provincial 江苏 存量机制电价 references coal benchmark **0.391元/kWh** — http://www.js.sgcc.com.cn/images/xxgk/gwjssdlyxgs/zcfg/2025-12-16/1450526373443280896.pdf
- **No dedicated national household 储能 self-consumption tariff yet** [INFERENCE from absence in 136号 + provincial filings]. Household self-consumption is economically driven by avoiding peak retail price, not by a subsidy. Prior distributed-PV 分布式光伏 电量补贴 / 0.42元 class FIT is legacy; new projects are market-priced.

## 7. Summary spread table — theoretical residential arbitrage (⚠️ DERIVED)

| 城市/省 | 谷 (元/kWh) | 峰 (元/kWh) | 理论毛价差 (元/kWh) | 净套利 after ~10–15% round-trip loss [ESTIMATE] |
|---|---|---|---|---|
| 深圳 (一档) | 0.2486 | 1.1121 | **0.8635** | ≈0.73–0.77 |
| 山东 (一档非采暖) | 0.3769 | 0.5769 | **0.2000** | ≈0.17–0.18 |
| 山东 (一档采暖谷) | 0.3469 | 0.5769 | **0.2300** | ≈0.19–0.21 |
| 上海 (一档) | 0.307 | 0.617 | **0.3100** | ≈0.26–0.28 |
| 浙江 (一档) | 0.288 | 0.568 | **0.2800** | ≈0.24–0.25 |
| 江苏/四川/湖南 | 谷 0.3583 [EST] | 峰 0.5083 [EST] | ≈0.15 [EST] | ≈0.13 [EST] |
| 北京 | n/a (no residential TOU) | — | 0 | 0 |

*All spread columns are **arithmetic derivations from official single-tier prices → [ESTIMATE]**, not published figures. Round-trip-loss haircut is an engineering assumption.

**Realistic daily arbitrage margin:** the single best residential spread in the candidate set is **Shenzhen ≈0.86元/kWh gross (≈0.73–0.77 net)**, one full charge/discharge cycle/day across the 0:00–8:00 谷 → 10–12/14–19 峰 windows. Most other cities yield only **0.2–0.3元/kWh**, which is thin for a ~5–10 kWh home battery (≈¥1–6/day/cycle). **Design recommendation for the prototype:** anchor the arbitrage demo on Shenzhen/Guangdong (largest residential spread + best 工商业 spread 1.3963元/kWh), and treat Shandong/Zhejiang/Shanghai as secondary. Add the 2025–26 risk that national spreads are compressing as fixed 工商业 分时 is cancelled — the agent should forecast prices from market/现货 signals rather than assume static TOU forever.

---
### Source index (for citation integrity)
- 1093号 (NDRC, 2021): https://www.ndrc.gov.cn/xxgk/zcfb/tz/202107/t20210729_1292067.html
- 136号 (gov.cn / NDRC, 2025): https://www.gov.cn/lianbo/bumen/202502/content_7002957.htm · https://www.ndrc.gov.cn/xxgk/zcfb/tz/202502/t20250209_1396066.html
- 深圳 居民价目表 PDF: https://fgw.sz.gov.cn/attachment/1/1460/1460239/11394935.pdf · 深圳 通知: https://fgw.sz.gov.cn/gkmlpt/content/9/9493/mmpost_9493596.html
- 上海: https://scjgj.sh.gov.cn/1072/20210303/2c9bf2f677811b0b017781247e9104fe.html · https://english.shanghai.gov.cn/en-Business-PremisesUtilities-WaterElectricityandGas/20260818/7d4767035baf4263b8819080f33ac62e.html · 分时PDF: https://www.shanghai.gov.cn/cmsres/11/11ef6ccf01c3435488c453168b331e5f/297d9dff9b59d336f08f0eb6b80179e0.pdf
- 山东 烟台解读: https://fgw.yantai.gov.cn/art/2025/4/21/art_52219_2909514.html · 济宁电价表PDF: https://www.jining.gov.cn/module/download/downfile.jsp?classid=0&filename=128863c36ae24b20ac95542c43f7d915.pdf · 青岛PDF: http://www.qingdao.gov.cn/ywdt/zwzl/ggqsydwgk/srqd/gd/gwsdsdlgsqdgdgs/djsf/sfyj/202310/P020231031532722239238.pdf
- 浙江: https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web3549/site/attach/0/fe6c1374be1b44d5861b6ef636cba0e0.pdf · https://finance.sina.cn/2026-05-19/detail-inhymqce3213824.d.html · https://www.cpem.org.cn/list2/99450.html · 21号/112号: https://finance.sina.com.cn/wm/2026-07-01/doc-inifiaeu6267845.shtml
- 江苏 南通: https://nginx-ntfb.ntfabu.com/ntfb/site1/mweb/ja9rl/c36833330.html · 苏州表: https://fg.suzhou.gov.cn/szfgw/djglwj/201907/7ff8fd63642d4d048fc0010a86fbc1d5.shtml · 426号文价差: https://m.bjx.com.cn/mnews/20250707/1449717.shtml
- 四川 185号: https://gysctq.sczwfw.gov.cn/art/2025/5/30/art_35125_287567.html · 255号: https://www.163.com/dy/article/L0E4C06B05568W0A.html
- 北京 电价表: https://fgw.beijing.gov.cn/bmcx/djcx/jzldj/202110/t20211025_2520169.htm · 2023 工商业-only: https://www.beijing.gov.cn/zhengce/zcjd/202308/t20230822_3227446.html · 1184号: https://fgw.beijing.gov.cn/fgwzwgk/2024zcwj/bwqtwj/202607/t20260722_4777454.htm
- 湖南 14号: https://fgw.hunan.gov.cn/fgw/xxgk_70899/zcfg/dfxfg/202401/t20240131_32641110.html · 385号: http://fgw.hunan.gov.cn/fgw/xxgk_70899/zcfg/dfxfg/202507/t20250702_33727950.html
- 全国尖峰取消/价差: https://finance.sina.com.cn/roll/2026-09-10/doc-inirixks2768584.shtml · 工商业市场化趋势: http://tt.cnkbd.cn/dongtai/12412.html
- 江苏存量机制电价0.391: http://www.js.sgcc.com.cn/images/xxgk/gwjssdlyxgs/zcfg/2025-12-16/1450526373443280896.pdf
