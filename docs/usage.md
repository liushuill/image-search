# 使用手册

> 这是 README 之外的详细用法：界面、命令行、配置、批量、导出。
> 想新增站点请先看 [engines.md](engines.md)；图库与清理见 [library.md](library.md)。

---

> 界面与常用命令已经写在 [README](../README.md#使用) 里了，这里只放细节。

## 配置

### 凭据 → `.env`（权限 600，已 gitignore）

```bash
cp .env.example .env
chmod 600 .env
# 编辑填入 SAUCENAO_KEY
```

密钥获取：<https://saucenao.com/user.php?page=account>

也可以临时用真实环境变量覆盖（优先级高于 `.env`）：

```bash
SAUCENAO_KEY=xxx ./run.sh search 图片.jpg
```

### 非敏感配置 → `config.json`（本地文件，不入库）

`config.json` 是**你自己机器上的**设置：代理地址、校准过的阈值、引擎启停。
它**不进 git** —— 公开仓库里带别人的本地设置没有意义。

首次运行会自动按默认值创建它。模板见 `config.example.json`。

```bash
./run.sh config show                       # 查看（凭据自动脱敏）
./run.sh config set proxy http://127.0.0.1:7897
./run.sh config set saucenao_key YOUR_KEY  # 敏感键会自动写入 .env
```

> 想恢复默认：删掉 `config.json` 再启动（或 `./run.sh engines reset` 只重置引擎列表）。

> ⚠️ 本机代理是 Clash Verge / mihomo，默认端口 **7897**，且**不是常开**。
> 程序在代理不可用时会自动降级为直连并打印提示。

---


## 凭据的唯一定义处

**凭据只在「凭据」页填写**，落点是 `.env`（权限 600）。引擎页的凭据字段是
**只读的**，只显示「有没有、值是什么（脱敏）」并给一个跳转按钮。

为什么不允许两处都能改：

- `config.json` 是**入库**文件。曾经引擎页也能改 api_key，值会写进那里 ——
  等于把密钥写回版本历史（正是 P1 刚清理掉的问题）
- 引擎级的值**优先于** `.env`，于是「凭据页显示的值」和「实际生效的值」
  可能不是同一个，表现为「明明改了 key 却还报未配置」

现在的保证：

- `EngineStore.update()` 遇到凭据字段会把值写进 `.env`，配置里只留空占位
- `EngineStore.save()` 落盘前再清一次凭据字段（兜底，防任何绕过路径）
- 已有配置里的遗留密钥会自动搬迁到 `.env`（按配置版本迁移，并明确报告覆盖情况）
- 「凭据」页的清单来自**引擎 schema ∪ 已知清单**，所以自定义引擎声明的
  凭据会自动出现，不必回来改界面

> ⚠️ 如果你曾在引擎页填过 API Key，`config.json` 的 git diff 会显示密钥字段被清空 ——
> 那是修复，请照常提交。密钥本身已搬到 `.env`（已 gitignore）。


## 批量识别

把一整本"待查"目录逐个识别出来，结果写入图库。

```bash
./run.sh batch 待查目录 --dry-run          # 先看要处理多少、还剩多少额度（零消耗）
./run.sh batch 待查目录 --limit 10         # 先跑 10 张试水
./run.sh batch 待查目录                   # 按配置（默认单次 20 张）
./run.sh batch 待查目录 --no-recursive     # 不含子目录
./run.sh batch 待查目录 --export urls,csv  # 识别完顺便导出本次新搜到的
```

GUI 在**图库页 → 「识别未搜索的图…」**：先给预览（零消耗），确认后开始，
有进度条、可随时取消，结束给出统计。

### 三条让它能"分几天安全跑完"的性质

| 性质 | 为什么重要 |
|---|---|
| **先查缓存再联网** | 已识别过的图命中缓存、**零配额**跳过 → 重跑 = 接着上次跑，随时中断都行 |
| **结果写入图库** | 否则跑完什么都没留下，第二天还得从头来 |
| **额度策略可配** | 额度用尽时是停下还是换引擎，由 `batch_quota_policy` 决定，不写死在代码里 |

### 逐张节流（避免被静默降级）

SauceNAO 免费额度是 **100 次/天**，但还有个服务端限制 **4 次/30 秒**。
连续猛打会在第 5 张就被 429 —— 而 auto 模式的引擎循环用
`except Exception` 兜底后继续下一个引擎，于是**静默降级**到覆盖差很多的引擎，
尽管当天额度还剩一大半。

所以批量会按引擎声明的速率**逐张节流**（30/4 = 7.5 秒），
让主引擎真的被每一张用到。预览里会写明"逐张节流 7.5 秒"，
免得你以为卡住了。

### 额度用尽时

`batch_quota_policy`（在**设置页**可改）：

- `stop`（默认）：停下来并说明还剩多少。不会不知情地拿弱引擎凑数。
  已识别的都已入库，明天再点一次自动接着跑。
- `fallback`：继续用其他引擎把剩下的跑完，报告里会注明降级来源与用量。

> 实测：389 张的目录，SauceNAO 100 次/天 → 约需 4 天。
> 第 1 次跑 10 张用了 4 次 SauceNAO（当时还没有节流，第 5 张起被限流降级到
> IQDB）；加上节流后再跑 6 张，**6 张全部走了 SauceNAO**（配额 4 → 10）。
> 重跑同样 10 张时全部命中缓存，**配额一条没动**。


## 导出

导出**不下载任何文件**，只输出地址。可一次勾选多种格式。

```bash
# 从本地图库导出（把已经搜过的批量导出）
./run.sh export --library --formats all -o ./out
./run.sh export --library 3 -f urls,html            # 限定某条根路径

# 从旧版 batch 产出的 CSV 导出
./run.sh export --csv search_results.csv -f urls,csv,json

# 搜完顺便导出
./run.sh search 图片.jpg --export urls,csv,html -o ./out
```

| 格式 | 扩展名 | 说明 |
|---|---|---|
| `urls` | `.txt` | 一行一个 URL —— 最通用，AriaNg / `aria2c -i` / IDM 批量导入都能吃 |
| `csv` | `.csv` | 表格；`similarity` 是**数值**（可直接排序），带 BOM 便于 Excel 认中文 |
| `json` | `.json` | 数组，字段完整、容器保持结构（`pixiv` 子对象 / `ids` 字典） |
| `jsonl` | `.jsonl` | 一行一条，便于流式处理 |
| `html` | `.html` | **缩略图墙报告**：单文件可离线打开，缩略图默认内嵌，带筛选框 |
| `clipboard` | — | 不写文件；GUI 直接进剪贴板，CLI 用 `wl-copy`/`xclip`/`xsel`/`clip`，都没有就打印出来 |

### 文件名模板

```bash
./run.sh export --library -f csv --name-template "{artist} - {title} ({pixiv_id})"
```

占位符：`{pixiv_id}` `{page}` `{artist}` `{title}` `{similarity}` `{engine}`
`{dhash}` `{file}` `{ext}`。未知占位符**原样保留**（静默丢字段比留个
`{unknown}` 更难排查）。非法字符会按 Windows+POSIX 的并集清理。

### 一个被修掉的数据缺口

SauceNAO 命中 Danbooru/Gelbooru 索引时，`data` 里**没有 `pixiv_id` 字段**，
但 `ext_urls` 里带着旧式的 `member_illust.php?...illust_id=NNN`。
旧实现只读字段，于是这个 ID 就丢了 —— 而它正是生成 `pixiv.re` / `pixiv.cat`
下载直链（AriaNg 批量下载）所必需的东西。

现在 `SearchResult` 会从来源链接里把 Pixiv ID 补出来（新旧两种 URL 写法都认），
并且**已有的值不会被覆盖**。这条修复对缓存记录同样生效 ——
导出走的是与「刚搜出来」完全相同的归一化路径。


## 搜索引擎

```bash
./run.sh engines list                    # 查看引擎、权重与「为什么不能用」的备注
./run.sh engines show sauceNAO           # 查看某引擎的全部配置字段与说明
./run.sh engines config sauceNAO --set api_url=https://...   # 改任意字段（--set 可重复）
./run.sh engines toggle ascii2d          # 启用 / 禁用
./run.sh engines move sauceNAO --up      # 调整搜索顺序
./run.sh engines rename my_engine newname  # 改名（顺序与模块绑定都会保留）
./run.sh engines new my_engine           # 生成自定义引擎模板到 my_engines/
./run.sh engines reset                   # 恢复默认列表
```


## 关于 Danbooru 引擎（默认停用）

**默认停用，代码保留** —— 门槛比别的引擎高，但有满足条件的账号时可用。

它的以图搜图端点 `POST /iqdb_queries.json` 会校验**这把 API Key 自身**的
两个列表（依据 [Danbooru 源码](https://github.com/danbooru/danbooru)）：

```
app/logical/session_loader.rb:238
    raise User::PrivilegeError if !api_key.has_permission?(...)

app/models/api_key.rb
    has_permission?(ip, controller, action) = ip_permitted? && action_permitted?
    ip_permitted?     -> true if permitted_ip_addresses.empty?   # 空 = 不限制
    action_permitted? -> true if permissions.empty?              # 空 = 不限制
```

即 Key 上那两个**可选**字段（**IP Addresses** / **Permissions**）一旦填过，
就必须匹配，否则**所有端点**都返回 403。走代理时出口 IP 随节点变化，
填死 IP 很容易失效。

**启用前请确认**：到 <https://danbooru.danmai.us/api_keys> 把你的 Key 的
**IP Addresses 与 Permissions 两个字段清空**。

要判断是不是这个问题，看错误码即可：

| 现象 | 含义 |
|---|---|
| `401 Invalid API key` | 凭据本身不对 |
| `403 PrivilegeError`（所有端点都 403） | 凭据正确，但 Key 被限制了 |
| `403` + CSRF 字样 | 请求未被认可为已认证（多为 User-Agent 伪装） |

> 顺带说明：**匿名 GET `/iqdb_queries.json?url=…` 是可用的**（实测返回 20 条匹配），
> 但本地文件走的是 POST 上传，仍然需要一把可用的 Key。所以**没有账号就直接用
> IQDB 引擎** —— 它同样会搜 Danbooru 的帖子。

引擎在 `engines list` 的备注列与 GUI 引擎页都会显示这条「使用须知」，
不必等搜索失败才知道前提条件。


## 图库

本地图库是「这张图搜过没有」的记录：以 **dHash 内容**为身份，所以文件移动/改名后仍能命中缓存、省掉搜索配额。

路径怎么登记、怎么清理、判重档位、直接查数据库 —— 见 [library.md](library.md)。
