# File 1: research/anker-hardware.md

## Anker SOLIX Hardware Spec Sheet

*Compiled 2026-10-10 for hackathon prototype: AI energy-management agent scheduling Anker home battery by TOU price + solar forecast.*

---

### Family A: Portable Power Stations

| Spec | C1000 Gen 2 | C2000 Gen 2 | S2000 | F2600 | F3800 | F3800 Plus |
|------|-------------|-------------|-------|-------|-------|------------|
| Capacity | 1,024 Wh | 2,048 Wh | 2,010 Wh | 2,560 Wh | 3,840 Wh | 3,840 Wh |
| AC Continuous | 2,000 W | 2,400 W | 1,500 W | 2,400 W | 6,000 W | 6,000 W |
| AC Surge/Peak | 3,000 W | 4,000 W | N/A | 2,800 W | 9,000 W | 9,000 W |
| Solar Input Max | 600 W | 800 W | 400 W | 1,000 W | 2,400 W | 3,200 W |
| AC Charge Rate | 1,600 W | 1,800 W | ~600 W | 1,440 W | 1,800 W | 6,000 W |
| Expandable | +1,056 Wh | +2,048 Wh (BP2000) | No | +2,048 Wh (BP2600) | Up to 53.8 kWh (6×BP3800) | Up to 53.8 kWh |
| Grid-Tie / TOU | TOU in app | TOU in app | No (UPS only) | TOU in app | TOU + Peak Shaving in app | TOU + Peak Shaving + AC-couple |
| Comms | WiFi + BT | WiFi + BT | WiFi + BT | WiFi + BT | WiFi + BT | WiFi + BT |
| Matter / API / Modbus | None | None | None | None | None | None |
| Price (USD) | $529.99 | $899.99–$1,499.99 | $679.99 | $999.99–$1,499.99 | ~$2,999–$3,999 | ~$3,699 |
| Sources | [ankersolix.com/products/c1000-gen2](https://www.ankersolix.com/products/c1000-gen2) | [ankersolix.com/products/c2000-gen2](https://www.ankersolix.com/products/c2000-gen2) | [ankersolix.com/products/s2000-portable-power-station](https://www.ankersolix.com/products/s2000-portable-power-station) | [ankersolix.com/products/f2600](https://www.ankersolix.com/products/f2600) | [ankersolix.com/products/f3800](https://www.ankersolix.com/products/f3800) | [ankersolix.com/collections/f3800-plus](https://www.ankersolix.com/collections/f3800-plus) |

**Notes:**
- F3800 240V output cannot be used while charging via 120V AC. Source: [f3800 product page](https://www.ankersolix.com/products/f3800)
- S2000 has 1800W bypass + ≤10ms UPS; 6W idle. Source: [ankersolix.com/blogs/s2000-specs-faq](https://www.ankersolix.com/blogs/home-power-backup/anker-solix-s2000-official-specs-rumors-faq)
- F3800 Plus: 3200W solar, 6000W AC input, generator bypass. Source: [f3800 product page spec table](https://www.ankersolix.com/products/f3800)
- S5000 announced Oct 2026: 5,024 Wh, 4,500 W rated output. Source: [ess-news.com 2026-10-09](https://www.ess-news.com/2026/10/09/anker-solix-announces-s5000-power-station-with-4-5-kw-output/)

---

### Family B: Whole-Home Backup (Off-Grid / Hybrid)

| Spec | E10 (A17E1) | E10 + Power Dock |
|------|-------------|------------------|
| Per-module capacity | 6,144 Wh (B6000) | 6,144 Wh × 5 max per unit |
| System capacity | 6–90 kWh (3× E10 stacked) | 6–90 kWh |
| Rated output | 7.6 kW (1 batt) / 10 kW (2+ batt, ≤90 min) | 7.6–22.8 kW (up to 3× E10) |
| Turbo output | 10–30 kW, 90 min | 10–30 kW |
| Surge | Up to 37.2 kW (155 LRA) per unit | Up to 66 kW (275 LRA) dual |
| Solar input | 9 kW (2×4,500W, 30–450V) | 9–27 kW |
| AC charge | Grid via Power Dock / Inlet Box | ≤20ms auto switchover |
| Grid-tie / feed-in | **NO** (confirmed in FAQ) | **NO** |
| TOU / Peak Shaving | Yes (Self-Consumption + TOU via app) | Yes + Local Feed-in + TOU |
| Comms | WiFi + BT + Anker App | WiFi + BT + Anker App + 12-circuit load mgmt |
| Matter / API / Modbus | No published local API | No published local API |
| Protection | NEMA 4 (IP66) outdoor | Power Dock NEMA 3R |
| Certifications | UL 9540 / 9540A | UL 9540 / 9540A |
| Price (USD) | $3,999 (1 module) / $5,999 (2 module) | $7,799 (2 batt + Dock) |
| Sources | [ankersolix.com/products/e10](https://www.ankersolix.com/products/e10), [verge.com/news/860392](https://www.theverge.com/news/860392/anker-goes-big-with-new-whole-home-backup-system) | Same |

---

### Family C: Grid-Tied Home Energy Storage (Hybrid ESS)

| Spec | X1 (Hybrid/Acoupled) | XE | Solarbank Max AC | Solarbank 4 E5000 Pro |
|------|---------------------|-----|-----------------|---------------------|
| Battery per module | 5 kWh (B5) | 7 kWh | 7 kWh | 5,024 Wh |
| System capacity | 5–180 kWh (6 modules × 3 stacks) | up to 42 kWh (6 modules) | 7 kWh (expandable [ESTIMATE] up to 126 kWh) | 5–30 kWh (expansion) |
| Power output | 3–36 kW (6kW per power module, 1.1× rated) | 5 kW bidirectional | 5 kW | Up to 5,000 W PV input |
| Solar/PV input | MPPT, up to 100A | 15 kW PV | 5 kW PV | 5,000 W (4× MPPT) |
| TOU / Peak Shaving | **Yes** (Self-Consumption, TOU, Peak Shaving, Grid Charging modes) | **Yes** (dynamic tariff optimized) | **Yes** | **Yes** (AI-driven) |
| Grid feed-in | Yes (hybrid inverter, export-capable) | Yes | Yes | Yes (up to 2,000 W in DE [ESTIMATE]) |
| Comms | WiFi + Installer App + O&M Platform + Modbus TCP | WiFi + BT + **Modbus TCP** | WiFi + BT + **Modbus TCP** | WiFi + BT + **Modbus TCP** |
| Matter | No | No | No | No |
| Home Assistant | Modbus reference doc only; NOT in official HA integration | **Official** HA integration (anker-charging/ha-anker-solix-official) | **Official** HA integration | **Official** HA integration |
| Price | Installer quote; not DTC | UK/Ireland via installers | EU | £1,699 (UK) / ~€1,399 (DE) |
| Sources | [ankersolix.com/x1-hes](https://www.ankersolix.com/x1-energy-storage-system-hes), [service.ankersolix.com X1 Modes](https://service.ankersolix.com/article-description/Anker-SOLIX-X1-Modes-Explained---Australia), [osw.energy X1 datasheet](https://downloads.osw.energy/au/downloads/2720/docs/Datasheet%20-%20Anker%20Hybrid%20Three%20phase.pdf) | [ankersolix.com/eu/xe](https://www.ankersolix.com/eu/xe), [pv-magazine.com 2026-09-14](https://www.pv-magazine.com/2026/09/14/anker-solix-launches-xe-the-next-generation-all-in-one-home-energy-storage), [ess-news.com 2026-04-30](https://www.ess-news.com/2026/04/09/anker-solix-launches-new-solarbank-max-ac-targets-rooftop-solar-retrofits-with-7-kwh-plug-in-system) | [pv-magazine.com 2026-04-30](https://www.pv-magazine.com/2026/04/30/anker-solix-launches-7-kwh-modular-battery-with-5-kwh-bidirectional-inverter), [github HA integration](https://github.com/anker-charging/ha-anker-solix-official) | [ankersolix.com/uk/products/ae103](https://www.ankersolix.com/uk/products/ae103), [pv-magazine 2026-05-13](https://www.pv-magazine.com/2026/05/13/anker-solix-launches-modular-5-kwh-battery-for-residential-pv), [datasheet PDF](https://cdn2.balkonkraftwerk.de/downloads/AS-SB4-01/Anker%20SOLIX%20Solarbank%204%20Pro%20-%20Datenblatt.pdf) |

---

### Family D: Balcony / Plug-and-Play Storage (Legacy)

| Spec | Solarbank 2 E1600 Pro | Solarbank 2 E1600 AC |
|------|----------------------|---------------------|
| Capacity | 1,600 Wh | 1,600 Wh |
| Max PV input | 2,400 W (4× MPPT) | 2,400 W (4× MPPT) |
| Feed-in output | 800 W | 800 W |
| Off-grid AC | N/A | 1,200 W |
| Expansion | Up to 9,600 Wh (BP1600 × 5) | Up to 4,300 Wh |
| Comms | WiFi + BT + Anker App | WiFi + BT + Anker App |
| Modbus / HA | No (not in official integration) | No |
| Price | €555 (DE base) | €839 |
| Sources | [datasheet PDF](https://cdn.shopify.com/s/files/1/0690/2313/8087/files/Anker_solix_solarbank_2_E1600_Pro_A17C1_datasheet_1.pdf), [stekkerkompas.nl](https://www.stekkerkompas.nl/en/thuisbatterij/anker-solix-solarbank-2-e1600-pro) | [ankersolix.com/eu](https://www.ankersolix.com/eu/solar-panel-kit-with-battery/solarbank2ac-a17c2) |

---

### Control Surface / Third-Party Automation Matrix

| Product / Family | Anker App (WiFi+BT) | TOU Scheduling | Modbus TCP (LAN) | Official HA Integration | Matter | Cloud API | MQTT | Verdict |
|---|---|---|---|---|---|---|---|---|
| C1000 Gen 2 | ✅ CONFIRMED | ✅ TOU mode in app | ❌ UNKNOWN | ❌ Not supported | ❌ No | ❌ No public API | ❌ No | **App-only; no third-party write control** |
| C2000 Gen 2 | ✅ CONFIRMED | ✅ TOU mode in app | ❌ UNKNOWN | ❌ Not supported | ❌ No | ❌ No public API | ❌ No | **App-only** |
| S2000 | ✅ CONFIRMED | ❌ No TOU (UPS/bypass only) | ❌ UNKNOWN | ❌ | ❌ No | ❌ | ❌ | **App-only, no scheduling** |
| F2600 | ✅ CONFIRMED | ✅ TOU mode in app | ❌ UNKNOWN | ❌ | ❌ No | ❌ No public API | ❌ No | **App-only** |
| F3800 / F3800 Plus | ✅ CONFIRMED | ✅ TOU + Peak Shaving in app | ❌ UNKNOWN | ❌ | ❌ No | ❌ No public API | ❌ No | **App-only** |
| E10 | ✅ CONFIRMED | ✅ TOU + Self-Consumption (app) | ❌ UNKNOWN | ❌ | ❌ No | ❌ No public API | ❌ No | **App-only; no grid feed-in** |
| X1 (Hybrid/Acoupled) | ✅ Installer App + O&M Platform | ✅ TOU + Peak Shaving + Grid Charging modes | ⚠️ Protocol doc exists: [support article](https://support.ankersolix.com/s/article/Anker-SOLIX-X1-Series-Modbus-Protocol) | ❌ Excluded from official HA | ❌ No | ❌ No public cloud API | ❌ No | **Modbus TCP possible (CONFIRMED protocol doc, RUMORED for local read); not in active HA scope** |
| XE / XE AC | ✅ CONFIRMED | ✅ Dynamic tariff / TOU | ✅ **CONFIRMED** (port 502, toggle in app) | ✅ **Official** ([github](https://github.com/anker-charging/ha-anker-solix-official)) | ❌ No | ❌ | ❌ | **FULL local control via Modbus TCP; CONFIRMED** |
| Solarbank Max AC / Max | ✅ CONFIRMED | ✅ TOU / dynamic tariff | ✅ **CONFIRMED** | ✅ **Official** | ❌ No | ❌ | ❌ | **FULL local control; CONFIRMED** |
| Solarbank 4 E5000 Pro | ✅ CONFIRMED | ✅ AI-driven / dynamic tariff | ✅ **CONFIRMED** | ✅ **Official** | ❌ No | ❌ | ❌ | **FULL local control; CONFIRMED** |
| Smart Plug Gen 2 | ✅ CONFIRMED | ✅ | ✅ **CONFIRMED** | ✅ **Official** | ❌ | ❌ | ❌ | **CONFIRMED** |
| Smart Meter Gen 2 | ✅ CONFIRMED | N/A | ✅ **CONFIRMED** | ✅ **Official** | ❌ | ❌ | ❌ | **CONFIRMED; reports grid power via Modbus TCP** |

### Integration Limits (Known Constraints)

1. **F-series / E10 / S2000**: No local API, no Modbus TCP, no Matter. Control is exclusively through the Anker App (WiFi/BT) with cloud relay for remote access. Third-party automation is **impossible without reverse-engineering** (no published protocol for these models).
2. **X1**: Modbus protocol document published at [support.ankersolix.com/s/article/Anker-SOLIX-X1-Series-Modbus-Protocol](https://support.ankersolix.com/s/article/Anker-SOLIX-X1-Series-Modbus-Protocol) (RUMORED practical support), but Anker explicitly excludes X1 from the active official HA integration scope. Requires installer app/O&M platform for configuration. Source: [github HA README](https://github.com/anker-charging/ha-anker-solix-official) — "Due to current product roadmap prioritization… the following products are not part of the active integration scope… Anker provides official Modbus documentation."
3. **Solarbank 2 E1600 Pro/AC**: No Modbus TCP; community Home Assistant integration (mZ738/ha-anker-solix) uses an unofficial cloud API library. Source: [community HA feature request](https://community.home-assistant.io/t/feature-request-integration-or-addon-for-anker-solix-e1600-solarbank/641086) — "Unfortunately Anker does not provide any API capability yet."
4. **Modbus TCP enablement**: Must be toggled ON in Anker App → Device → Settings → "Three-Party Control Settings" → Modbus TCP toggle. IP + port 502 shown. Source: [HA README](https://github.com/anker-charging/ha-anker-solix-official)
5. **E10 no grid feed-in**: Confirmed FAQ: "No, neither supports feeding electricity back to the grid." Source: [E10 product page FAQ #2](https://www.ankersolix.com/products/e10)
6. **F3800 AC-couple limitation**: 240V output disabled during 120V AC charging. Source: [f3800 product page](https://www.ankersolix.com/products/f3800)

### Chinese Market Availability

- Anker SOLIX products are sold primarily in US/EU/UK/AU/CA. The Chinese domestic market (安克创新) has limited SOLIX availability; the brand's half-year 2026 report mentions expanding domestic home storage. Source: [chongdiantou.com](https://www.chongdiantou.com/archives/1788430968725.html), [anker.com.cn](https://www.anker.com.cn/)
- CNY pricing is not publicly listed on Chinese retail platforms for SOLIX line products. [ESTIMATE]: F3800 would be ¥20,000–28,000 based on USD $2,999–3,999 + ~30% import/markup.

---

---

# File 2: research/tou-tariff-cn.md

## China Time-of-Use (TOU) Tariff Policy Brief

*For AI energy-management agent: day-ahead scheduling of Anker home battery against TOU price spreads and solar forecast.*

---

### 1. National Framework

**Policy:** 发改价格〔2021〕1093号 — "Notice on Further Improving the Time-of-Use Electricity Pricing Mechanism"  
**Issued:** 2021-07-26, NDRC  
**Source:** [gov.cn/zhengce/zhengceku/2021-07/29/content_5628297.htm](https://www.gov.cn/zhengce/zhengceku/2021-07/29/content_5628297.htm)

Key rules:
- Peak-valley price ratio: ≥ **4:1** where annual max peak-valley load difference exceeds 40%; ≥ **3:1** otherwise
- Sharp peak (尖峰): surcharge ≥ **20%** above peak rate; activated when load ≥ 95% of historical max
- Deep valley (深谷): encouraged in areas with high renewable + CHP overlap
- Scope: all C&I users (excl. electrified rail); residents MAY opt in
- Dynamic adjustment: provinces must review periods/ratios against spot market signals
- Battery storage explicitly mentioned: "鼓励工商业用户通过配置储能…降低高峰时段用电负荷、增加低谷用电量" [1093号 §三(一)]

---

### 2. Provincial Examples

#### 2.1 Zhejiang (浙江) — 浙发改价格〔2026〕112号

**Effective:** 2026-07-01 (replaces 2024-21号)  
**Source:** [zj.gov.cn](https://www.zj.gov.cn/col/col1229203589/art/2026/art_db07d88b6c68f1412561a0e8640cc135.html), [gdshe.org summary](https://www.gdshe.org/article/27696.html)

| Tier | Ratio to flat | Note |
|------|-------------|------|
| 尖峰 (Sharp Peak) | **2.05** | Summer/winter afternoons |
| 高峰 (Peak) | **1.85** | Evening |
| 平段 (Flat) | **1.00** | Base |
| 低谷 (Valley) | **0.40** | Night |
| 深谷 (Deep Valley) | **0.20** | Midday PV surplus period (3h window) |

**Base:** Grid connection price + line loss + system operation fees (transmission + surcharges excluded from floating).

**Key insight for scheduling:** Sharp-peak-to-deep-valley spread = **2.05 − 0.20 = 1.85× flat base** — maximum arbitrage opportunity. Midday deep valley (11:00–14:00) aligns with PV surplus, meaning the agent can charge battery from solar during deep valley and discharge to sharp peak.

EV charging: midday valley window shifted +30 min (10:30–14:00); V2G discharge at sharp-peak/peak price in summer/winter.

#### 2.2 Guangdong (广东) — 粤发改价格〔2021〕331号

**Effective:** 2021-10-01  
**Source:** [ndrc.gov.cn coverage](https://www.ndrc.gov.cn/xwdt/gdzt/jgjzgg/nyjggg/202110/t20211027_1301148.html), [dgdp.dg.gov.cn full text](https://dgdp.dg.gov.cn/gkmlpt/content/4/4385/post_4385587.html), [cspplaza](https://cspplaza.com/article-20680-1.html)

| Tier | Ratio | Period |
|------|-------|--------|
| 尖峰 (Sharp Peak) | 2.04 (= peak×1.2) | Jul/Sep only, 10-12h & 14-19h |
| 高峰 (Peak) | **1.70** | 10-12h, 14-19h |
| 平段 (Flat) | **1.00** | 08-10h, 12-14h, 19-00h |
| 低谷 (Valley) | **0.38** | 00-08h |

Peak-valley ratio: **1.7:1:0.38** (≈4.5:1 peak-to-valley spread).  
Max spread example (2026): 广东 peak ~0.98, valley ~0.34, spread ~1.17 元/kWh (large industrial). Source: [cspplaza](https://cspplaza.com/article-20680-1.html)

#### 2.3 Shanghai (上海) — Residential

**Source:** [hi.online.sh.cn](https://hi.online.sh.cn/content/2024-05/14/content_10202981.htm), [shanghai.gov.cn pricing table xlsx](https://www.shanghai.gov.cn/cmsres/bd/bdef6cb5da0745ac901a1a3a89194719/d3975ef3b153d6c151802eb2066dc1b8.xlsx)

| Tier | Flat (no TOU) | Peak (06-22h) | Valley (22-06h) |
|------|--------------|---------------|----------------|
| 1 (≤170 kWh/mo) | 0.617 元/kWh | 0.617 元/kWh | 0.307 元/kWh |
| 2 (171-260) | +0.05 surcharge | 0.667 | 0.357 |
| 3 (>260) | +0.30 surcharge | 0.917 | 0.607 |

Residential peak-valley ratio: **2:1** (0.617 vs 0.307). Much smaller than C&I.  
TOU is voluntary for residents; adds ~1.5h evening peak window.

#### 2.4 Henan (河南) — 2025 Update

**Source:** [cnesa.org](https://www.cnesa.org/information/detail?column_id=3&id=234)
- Peak: 10:00-14:00, 17:00-21:00  
- Valley: 23:00-07:00  
- Ratio follows national ≥3:1 guidance

#### 2.5 Liaoning (辽宁) — 辽发改价格〔2023〕441号

**Source:** [fgw.ln.gov.cn PDF](https://fgw.ln.gov.cn/fgw/attachDir/2024/06/2024061209102740686.pdf)
- Full implementation of 1093号 framework
- Sharp peak surcharge ≥20% above peak

---

### 3. 2025–2026 Deregulation Trend: Fixed TOU Removal

**Critical for prototype:** Multiple provinces have announced removing *fixed catalog TOU periods* in favor of market-linked dynamic pricing.

Source: [xinhuanet/People's Daily Overseas 2026-05-26](https://app.xinhuanet.com/news/article.html?articleId=20260526b565e2a82a024f3ba91c4ccaa790bf46), [nea.gov.cn 2025-12-05](https://www.nea.gov.cn/20251205/75d2da536b874479a07f0e1a2e11a781/c.html)

Provinces removing fixed TOU (as of mid-2026):  
**贵州、湖北、陕西、河南、重庆、吉林、云南、辽宁、浙江**

Implications for the agent:
- Day-ahead price curve will come from **spot market / grid company announcements** rather than fixed catalog schedules
- Zhejiang 112号 (effective Jul 2026) retains structured ratios but shifts to **market-indexed base price** — agent needs day-ahead feed from provincial trading center
- NEA article notes: "工商业分时电价浮动比例调整为尖峰…元/千瓦时，峰谷套利空间被明显压缩" — storage arbitrage margins are tightening

---

### 4. 发改价格〔2025〕136号 — Renewable Feed-in Market Reform

**Issued:** 2025-01-27  
**Source:** [gov.cn/lianbo/bumen/202502/content_7002957.htm](https://www.gov.cn/lianbo/bumen/202502/content_7002957.htm)

- All new wind/solar projects fully enter market trading (no more fixed feed-in tariff)
- Existing projects grandfathered but face "mechanism price" auction
- Impact on household PV: surplus self-consumption becomes MORE valuable (grid export price drops); increases ROI for battery storage scheduling

---

### 5. Data Sources for the Agent

| Data Need | Source | Format | Access |
|-----------|--------|--------|--------|
| Day-ahead TOU price curve | Provincial grid company (国网/南网) monthly announcements; spot market clearing | PDF/Excel on gov portals | Free, public |
| 代理购电价格 (grid proxy purchase price) | Monthly by each provincial grid co. (e.g. Guangdong [hengqin PDF example](https://www.hengqin.gov.cn/attachment/0/432/432110/3896921.pdf)) | PDF table | Free |
| Solar irradiance forecast | 中国气象局 / Open-Meteo / NASA POWER API | JSON | Free |
| Real-time demand response signals | Provincial electricity exchange centers | varies | May require registration |

---

### 6. Arbitrage Sizing Example (Zhejiang 2026)

Assume flat base (grid proxy C&I purchase price) ≈ **0.55 元/kWh** (from Jan 2026 Guangdong proxy purchase data). Source: [zrtea.cn](https://www.zrtea.cn/policy_details.html?id=42)

- Charge at deep valley: 0.55 × 0.20 = **0.11 元/kWh**
- Discharge at sharp peak: 0.55 × 2.05 = **1.13 元/kWh**
- Spread: **1.02 元/kWh** (≈$0.14/kWh)
- For a 5 kWh battery (Solarbank 4): per-cycle revenue ≈ **5.1 元** (pre-efficiency losses)
- Two cycles/day (per XE spec): ≈ **10.2 元/day** = ~¥3,700/year

---

### 7. Glossary

| Chinese | Pinyin | English |
|---------|--------|----------|
| 分时电价 | fēnshí diànjià | Time-of-Use (TOU) pricing |
| 峰谷电价 | fēnggǔ diànjià | Peak-valley pricing |
| 尖峰电价 | jiānfēng diànjià | Sharp-peak / critical peak pricing |
| 深谷电价 | shēnggǔ diànjià | Deep-valley pricing |
| 削峰填谷 | xuēfēng tiángǔ | Peak shaving / valley filling |
| 现货市场 | xiànhuò shìchǎng | Spot market |
| 代理购电 | dàilǐ gòudiàn | Grid proxy purchase (for non-market users) |
| 输配电价 | shūpèidiàn jià | Transmission & distribution tariff |
| 政府性基金及附加 | zhèngfǔxìng jījīn jí fùjiā | Government surcharges (excluded from TOU floating) |