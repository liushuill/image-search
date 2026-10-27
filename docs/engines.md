# 引擎：加一个站点 = 填一张表

> 内置引擎全部由配置预设提供，`imgsearch/engines/` 里没有一行站点专属代码。
> 想接新站点，先看下面「新建引擎向导」。

---

## 内置引擎与适配器

> **本站点的引擎全部由「配置预设」提供，没有一行站点专属的 Python 代码。**
> `imgsearch/engines/` 里只剩基类、schema、注册表、存储，以及两个**通用适配器**。
> 旧的 Python 实现移到 `tests/legacy/`，仅用于「新旧双跑对比」测试。

内置引擎（权重小的先用）：

| 引擎 | 承载 | 默认 | 说明 |
|---|---|---|---|
| `sauceNAO` | JSON 适配器 | ✅ 启用 | Pixiv 覆盖最好，需要 API Key。限流 100/天 + 4/30 秒 |
| `iqdb` | HTML 适配器 | ✅ 启用 | 聚合 Danbooru / Konachan / yande.re / Gelbooru / Sankaku / e-shuushuu / Zerochan / Anime-Pictures。无需凭据 |
| `ascii2d` | HTML 适配器 | ⏸ 禁用 | 两步请求（POST→重定向→GET）+ Cloudflare 绕过。**站点目前仍拦截自动请求**，失败可忽略 |
| `traceMoe` | JSON 适配器 | ⏸ 禁用 | 动画截图溯源（回答"第几集第几秒"）。**对插画会高分误报**，需要时用 `-e traceMoe` |
| `danbooru` | JSON 适配器 | ⏸ 禁用 | 需要账号（用户名 + API Key）。它不返回相似度，`similarity_scale=rank` 按排名估算 |

两个适配器（`genericJson` / `genericHtml`）本身就是「模板」：
新站点 = 往配置里填一张映射表，见下面的「声明式适配器」。

### 新建引擎向导（界面上点几下就行）

引擎页 →「新建引擎…」：

```
名称 / 类型（JSON | HTML）/ 站点地址 / 接口路径
────────────────────────────────────
接口与字段映射（结果数组路径、相似度量纲、各字段路径/选择器…）
────────────────────────────────────
用这张图测试：[选择…]  [测试这个引擎]
  → 显示 请求地址 / 响应原文（前 800 字）/ 解析出几条 / 第一条各字段
```

**「测试这个引擎」会显示原始响应** —— 没有它，你分不清
「映射写错了」还是「站点根本没返回」。这一步是给非程序员用的关键。

向导只放「让新引擎跑起来」必需的 15 个字段；限流、代理、额外 ID 映射
等等，创建后在「引擎」页继续调（那里有全部 45 个字段）。

### 迁移时补的能力（都能用于新站点）

| 能力 | 配置项 | 原先是谁的需求 |
|---|---|---|
| 限流 | `long_limit/long_window/short_limit/short_window` | SauceNAO、TraceMoe |
| Cloudflare 绕过 | `cloudflare_bypass` | Ascii2D |
| 两步请求 | `follow_redirect` + `step2_delay` | Ascii2D |
| 按排名估算相似度 | `similarity_scale=rank` + `rank_scores` | Danbooru |
| 字段变换 | `path~strip_prefix:X` / `~regex:PATTERN` / `~tags_title:N` | 多个 |
| 模板字段 | `template:第 {episode} 集 @ {from:time}` | TraceMoe |
| 数组筛选 | `edges[?isMain=true]` | TraceMoe |
| 链接白名单 | `links_from_hosts` | Ascii2D（结果页混着导航链接） |
| 去重 | `dedupe_by` | Ascii2D（选择器并集匹配两次） |

### 迁移中确认的两处损失（如实记录）

- **IQDB** 的 `detail` 从「图库名 | 尺寸」变成只有图库名 ——
  尺寸在相邻单元格，而 soupsieve 在这个表格结构上
  `nth-child` / 兄弟选择器都取不到
- **SauceNAO** 的高清直链少了「从 `ext_urls` 里挑 `i.pximg.net`」那层回退 ——
  那是「在数组里按子串筛选」，现有路径语法只支持按字段值筛选（`[?k=v]`）

### auto 模式：按权重降级 + 阈值判定

`search` 不带 `-e` 时按权重顺序依次尝试已启用的引擎：

1. 某引擎的最高相似度 **≥ 它自己的阈值** → 立即采用
2. 未达阈值 → 记为候选，继续试下一个引擎
3. 全部试完仍无一达标 → 返回置信度相对最高的一组，并**明确标注低置信度**
4. 引擎报错（网络/配置/限额）→ 打印原因并跳过，不中断整轮

⚠️ **阈值按引擎校准，不是统一数字**。各引擎的相似度量纲不同——同一张图
IQDB 报 53%、SauceNAO 报 95%——用一刀切的阈值会把 IQDB 这类刻度偏保守的引擎永久误杀。
各引擎默认值见 `engines show <名称>`，可用 `--min-similarity` 临时覆盖（`0` = 不设阈值）。

### 网络与代理

代理**不是常开**，程序会自动处理：

- 全局 `proxy` 配置存在但探测不通 → **自动降级为直连**（只影响本次运行，不改配置）
- 每个引擎可单独设 `proxy_mode`：
  - `auto`（默认）跟随全局设置
  - `on` 强制走代理 —— 适合 Pixiv / catbox 这类境内不可达的服务
  - `off` 强制直连 —— 适合 saucenao / iqdb 这类直连即可的
  ```bash
  ./run.sh engines config iqdb --set proxy_mode=on
  ```
- 连接失败的引擎**不会**白等 `request_delay`（没发出去的请求不消耗配额）

⚠️ **`cloudscraper` 与代理不兼容**：它自带一套模仿浏览器指纹的 SSL 上下文，
经代理隧道时会在 TLS 握手阶段直接失败（实测 `SSLV3_ALERT_HANDSHAKE_FAILURE`，
且用 `session.proxies` 或每次请求显式传 `proxies=` 都一样）。
所以同时需要「代理 + CF 绕过」时，程序**优先保代理**并改用普通请求
（能连上比绕过重要；何况 cloudscraper 也打不过现代 Cloudflare WAF）。

实测连通性（本机 Clash，2026-09）：

| 目标 | 直连 | 经代理 |
|---|---|---|
| saucenao.com / iqdb.org / api.trace.moe | ✅ | ✅ |
| catbox.moe | ❌ | ✅ |
| pixiv.net / i.pximg.net | ❌ | ✅ |
| danbooru.donmai.us | ❌ 超时 | ✅ 403 |

---

