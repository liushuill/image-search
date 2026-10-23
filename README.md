# image-search — 二次元图片溯源工具

> ⚠️ **预发布（pre-release）** —— 本项目尚未正式发布，目前处于测试阶段。
>
> - **暂未进行 Windows 相关测试**（Linux 下已长期日常使用）
> - 接口、配置格式、数据表结构仍可能变动；升级前请先备份 `data/`
> - 许可为 [预发布许可](LICENSE)：**禁止商业使用**；修改后分发必须同样开源。
>   正式版将改为 **GPL-3.0**
> - 第三方组件许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)（Qt 为 LGPL-3.0）

以图搜图，查出图片的原始出处（Pixiv / Danbooru / Twitter 等），并导出可批量下载的链接。

- **核心层零 UI 依赖** —— `imgsearch/` 是纯 Python 包，CLI 与 GUI 共用同一套引擎
- **凭据与配置分离** —— API Key 只放 `.env`（0600），绝不进 `config.json`、绝不入库
- **Windows 理论上可用**（同一份代码 + 独立启动脚本），但**尚未实测**

---

## 声明：关于 AI 参与

声明：本项目由作者使用AI完成。由于作者缺乏编程能力，作者实际的工作是：

1. 讨论并明确项目的用途，架构。并以行为逻辑链条进行检查。
2. 选择项目技术栈。为AI搜集资料以及提供相关文档，尽量避免其产生边界歪的偏差
3. 测试并提出修改意见，交由AI修改。

尽管作者尽可能地想了一些可能遇到的bug情况，并进行了针对性意见让AI修复。但仍可能遇到各种问题。请您谅解

---

## 快速开始

### 图形界面（推荐）

```bash
./run-gui.sh          # Linux（首次自动装 PySide6）
run-gui.bat           # Windows
```

单窗口 + 侧栏，已实现三个页面：

| 页面 | 作用 |
|---|---|
| **搜索** | 拖入图片即搜；结果表可复制/打开链接；缓存命中会明确标注「未消耗配额」 |
| **引擎** | 按各引擎自己的 Schema 自动生成配置表单；「测试」按钮只做配置自检与端点连通性检查，**不消耗搜索配额** |
| **凭据** | **凭据只在这里填**；程序写进 `.env` 并设为 600 —— 你不需要打开那个文件 |
| **设置** | 代理地址与探活地址（含「测试代理」）、是否使用本地图库、是否缓存缩略图 |

> 已实测在 KDE Wayland 下使用**原生 wayland 平台插件**（`platformName() == "wayland"`），
> 不走 XWayland 转译，因此拖拽与 HiDPI 都是原生行为。

### 命令行

```bash
./run.sh config secrets            # 查看凭据状态
./run.sh search 图片.jpg            # 搜索出处
./run.sh search 图片.jpg --url      # 顺便生成 Pixiv 图片直链
./run.sh batch ./待查目录            # 批量搜索，产出 JSON + CSV
```

首次运行会自动创建 `.venv` 并安装依赖（不会污染系统 Python）。

### Windows

**只要设备上有 Python 3.10+ 即可**，不需要额外装任何东西：

```bat
run-gui.bat                        :: 图形界面（首次自动装 PySide6）
run.bat search 图片.jpg            :: 命令行
run.bat engines list
```

首次运行会自动创建 `.venv` 并安装依赖。若提示找不到 Python：

- 到 <https://www.python.org/downloads/> 安装，**安装时勾选 "Add python.exe to PATH"**
- 装完**关掉再重开**命令行窗口（PATH 才会刷新）
- 启动脚本会优先用 `py -3`（Python 官方启动器），没有才退回 `python`

> 批处理文件刻意**只含 ASCII**：cmd.exe 是按当前代码页逐行解析 `.bat` 的，
> 中文写在 `if` 块里很容易出问题。所有面向用户的提示都由 Python 打印。

#### ⚠️ Windows 的验证状态（请如实看待）

**开发与测试都在 Linux 上完成，本项目尚未在 Windows 实机上运行过。**
已排除的障碍与尚未覆盖的风险分开列，避免"应该没问题"这种含糊说法：

**已排除（可在 Linux 上验证的部分）**

- 代码里没有平台特有 API（无 `os.startfile` / `winreg` / 硬编码盘符）
- GUI **没有硬编码字体**（Qt6 版跟随系统字体；旧 tkinter 版写死了 `Microsoft YaHei UI`）
- 路径比较已按平台归一大小写（Windows 不敏感，否则重复/嵌套检测会失效）
- venv 布局差异（`Scripts\python.exe`）由 `bootstrap.py` 统一处理
- `.bat` 纯 ASCII、无 BOM、支持 `py -3`
- 「解压后自动建环境」这条路径已实测（在 Linux 上跑的全新解压 → venv → 可用）
- GUI 的 offscreen 测试会构造每个页面并走真实数据库路径

**尚未覆盖（需要 Windows 实机才能确认）**

- 🔎 从未在 Windows 上启动过 PySide6 窗口
- 🔎 从未执行过任何一个 `.bat`
- 🔎 从资源管理器**拖拽**进窗口（`toLocalFile()` 在 Windows 返回 `C:/...`，理论上没问题）
- 🔎 高 DPI 缩放下控件的实际观感（尺寸已做屏幕自适应，但字体/间距观感未经目视）
- 🔎 中文路径、超长路径（Windows 仍限 260 字符，未做 `\\?\` 前缀处理 ——
  注意这与**分隔符**无关，前者已处理并有测试守着）
- 🔎 杀毒软件/受控文件夹访问对 `.venv` 创建与 `.env` 写入的干扰

如果 Windows 上出问题，最可能是上面这几条之一。把报错原文或截图给我即可。

### 直接调用（等价方式）

```bash
python -m imgsearch search 图片.jpg
python run_cli.py search 图片.jpg      # 无需设置 PYTHONPATH
imgsearch search 图片.jpg              # 若已 pip install -e .
```

---

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

## 本地图库

### 为什么要以「内容」而不是「路径」为身份

实际工作流是：**搜完一批图 → 下载原图 → 把图统一移到「搜集过的」目录**。
文件路径会不断变化，所以：

- 图片身份 = **dHash 感知哈希**，路径只是**可变的「最后已知位置」**
- 文件移到任何目录，都能凭 dHash 认出「这张搜过了」，**直接复用缓存结果**
- 这意味着**不重复消耗搜索配额**（SauceNAO 免费版只有 100 次/天）

```bash
./run.sh search 某张图.jpg          # 首次：正常搜索，并自动记入图库
./run.sh search 这张图的新位置.jpg   # 之后：图库命中，零配额消耗
./run.sh search 某张图.jpg --refresh # 想重新搜：加 --refresh
```

```
📚 图库命中：这张图搜过了 —— 同一张
   记录 id=1 · dHash=d6b2ced6b2b39184
   —— 以下结果来自本地缓存，未消耗任何搜索配额 ——
```

### 路径管理

```bash
./run.sh library add /path/to/图库 --label 图片库   # 手动登记（可多个，支持尚未挂载的外接盘）
./run.sh library list                               # 路径列表 + 状态 + 每路径统计
./run.sh library relocate 1 /新位置                  # 目录被改名/搬走：重新指定，记录路径一起改写
./run.sh library refresh                            # 重新检查文件是否还在原位（不会删记录）
./run.sh library find 某张图.jpg                     # 这张搜过了吗（与文件名、路径无关）
```

- **拒绝嵌套**：`图片库/` 与 `图片库/待查/` 不能同时登记 —— 否则同一张图会被记两次。
  添加时就会明确告知与哪条路径冲突。
- **失效路径只标记、不清数据**：外接盘未挂载或目录改名时标出来，用 `relocate` 指定新位置即可。

### 清理持久化数据

```bash
./run.sh library stats                              # 按路径 + 按类别的占用明细
./run.sh library clean --results                    # 清空搜索结果（保留图片记录与 dHash 索引）
./run.sh library clean --thumbs                     # 清空缓存缩略图
./run.sh library clean --path 3 --images --thumbs    # 清空某条路径的全部数据
./run.sh library clean --orphans                    # 清理孤立缩略图
./run.sh library remove 3 --purge all               # 移除路径时顺带清空其数据
```

- 清理前会先**预演**（显示将删除多少条、约多少体积），再要求确认；`--yes` 跳过确认。
- ⚠️ 每次清理后都会 **`checkpoint → VACUUM → checkpoint`**。
  SQLite 的 `DELETE` 只把页标记为可复用、文件不会缩小；而 WAL 模式下
  `VACUUM` 的产物又先落在 `-wal` 里 —— 不 checkpoint 的话磁盘占用**看起来不降反升**。
  这就是「清了半天发现文件没变小」的根因。实测 20000 条记录：**15.4 MB → 56 KB**。

### 直接查数据库

底库就是**一个 SQLite 文件**（`data/image_metadata.db`，WAL 模式）。
不需要装任何东西 —— Python 自带 SQLite：

```bash
./run.sh library sql --tables              # 列出表与行数（不用会 SQL）
./run.sh library sql --schema              # 列出字段定义
./run.sh library sql --schema images       # 只看某张表
./run.sh library sql                        # 打印速查表 + 可直接照抄的示例查询
./run.sh library sql "SELECT dhash, abs_path FROM images LIMIT 5"
./run.sh library sql --write "UPDATE ..."  # 默认只读，要改得显式加 --write
```

默认**只读**（两道护栏：语句筛查 + `PRAGMA query_only`），目的是防手滑而非安全边界。
输出是列对齐的表格，中文按全角宽度计算，不会错位。

> 不用系统装的 `sqlite3`（Debian 上要 apt）。若想用那个交互 shell：
> `sudo apt install sqlite3`，然后 `sqlite3 data/image_metadata.db .tables`。

表结构：

```
roots   (id, path, label, added_at, enabled)          你手动登记的根路径
images  (id, dhash, width, height, size, mtime,       dhash = 身份；路径只是
         root_id→roots, abs_path, rel_path,              「最后已知位置」
         first_seen, last_seen, missing)
results (id, image_id→images, engine, similarity,      一条命中；删图会级联删结果
         pixiv_id, pixiv_page, artist, artist_id,
         title, material, ext_urls, highres_url,
         thumbnail, danbooru_id, gelbooru_id,
         twitter_id, extra_ids, detail, fetched_at)
meta    (key, value)                                   内部元信息
```

规模参考：约 **790 字节/图**（含多条结果），4000 张 ≈ 5 MB，10 万张 ≈ 120 MB。

### 判重档位

匹配结果会如实告知，不把「相似」当成「同一张」：

| 判定 | 含义 |
|---|---|
| `exact` | dHash 相同且尺寸相同 —— 基本就是同一张（可能被重新编码过） |
| `scaled` | dHash 距离很小但尺寸不同 —— 同一张画的缩放版 |
| `similar` | dHash 距离在阈值内且尺寸相同 —— 视觉接近，需人工确认 |

实测：一张 400×300 的原图与它「缩到一半 + 质量 30」的版本，dHash 距离仅 **1**，
判定为 `scaled` —— 正是「质量被压缩、想找原图」要解决的场景。

---

## 仓库里入库什么、不入库什么

`git archive`（也就是推上去的整包）只含**源码 + 模板 + 占位符**：

| 入库 | 不入库（`.gitignore`） |
|---|---|
| `imgsearch/` `imgsearch_gui/` `tests/` | **`config.json`**（你本机的设置：代理、阈值、启停） |
| `config.example.json`（默认值模板） | `.env`（含真实凭据） |
| `.env.example` `requirements*.txt` 启动脚本 | `data/` 下所有真实数据：SQLite 库、`thumbs/`、`cache/`、额度账本、备份 |
| `data/.gitkeep` `output/.gitkeep`（空目录占位） | `output/` 下导出的结果 |
| `docs/`（文档、配图、历史设计） | `docs/reference/`（从网页保存的参考素材，可重新获取） |
| | `.venv/` `__pycache__/` `.pytest_cache/` |

> `config.json` 曾经是入库的（想让 `git diff` 暴露默认值改动）。
> 发布前改成不跟踪：它含个人设置，公开仓库里带着没有意义。
> 现在由 `config.example.json` 承担「默认值长什么样」这个职责。

> 早期那两份 Danbooru 参考网页直接躺在 `docs/` 里，**只是碰巧**被
> `*Danbooru.html` 通配规则忽略。现在统一挪到 `docs/reference/` 并加了
> **目录级**规则——`docs/` 从此可以放心放真文档，它会正常入库、能被 diff。

## 界面预览

![搜索](docs/images/search.png)

![引擎配置](docs/images/engines.png)

**新建引擎向导**（选类型 → 填映射 → 测试 → 创建，不写代码）：

![新建引擎](docs/images/wizard.png)

![清理](docs/images/cleanup.png)

三处「看图」的地方：

| 位置 | 能做什么 |
|---|---|
| **搜索结果表** | 首列「预览」显示该条命中的图源缩略图，一眼看出哪个匹配是对的 |
| **侧栏「浏览」页** | 缩略图墙：按路径/文件名筛选，双击打开，右键复制路径。<br>**每次切到本页都会自动刷新**（刚搜完图/刚批量识别过都能立刻看到） |
| **图库页 →「识别未搜索的图…」** | 开跑前列出**具体哪些图**，可取消勾选排除、按名字筛选、全选/全不选/反选 |

缩略图都在后台线程生成，并落盘缓存（本地图复用按内容命名的
`thumbs/`，与其他功能同一份缓存），第二次打开几乎瞬时。

### 存储占用（实测，不是估算）

| 项目 | 单个 | 101 张 | 1 万张 |
|---|---|---|---|
| 原图 | ~1.5 MB | 148 MB | ~15 GB |
| **本地图缩略图**（256px / 质量 82） | **12.3 KB** | **1.8 MB** | ~120 MB |
| **图源缩略图**（每条命中一个） | 4–10 KB | 每个新图 ~55 KB | — |

缩略图只占原图的约 **1.2%**。

**图源缩略图缓存是整套缓存里唯一会无界增长的东西**（每看一次新图的结果
就多几条），因此：

- 有容量上限 `url_thumb_cache_mb`（默认 100 MB，**在「设置」页可调**，0 = 不限制）
- 超出后按 **最久未用** 自动淘汰（依据访问时间）
- **「清理」页能看见它、也能单独清空**（可只清某条路径名下的）

### 两个实测得来的细节

- **图源缩略图的链接会失效**：SauceNAO 的缩略图地址带 `?auth=…` 令牌，
  实测「当场取有效、过一会儿再取 403」。所以磁盘缓存键用**去掉查询串的
  URL** —— 重新搜索同一张图能命中缓存；历史记录里的旧链接取不到时，
  格子会明确显示「取不到（链接已过期）」，而不是留空白让人以为坏了。
- **不同图源的可达性相反**：iqdb.org 的缩略图直连 200、走代理失败；
  i.pximg.net 反之。所以下载是「先直连（短超时）→ 再走代理」。

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

## 所有引擎都是配置

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

## 项目结构

```
image-search/
├── imgsearch/                 ← 核心层（无 UI 依赖）
│   ├── config.py              ← 非敏感配置（config.json）+ 敏感键转发
│   ├── secrets.py             ← 凭据读写（.env / 环境变量，原子写 + 0600）
│   ├── cli.py                 ← 命令行入口
│   ├── engines/               ← 搜索引擎（**没有站点专属代码**）
│   │   ├── schema.py          ←   字段声明/类型/校验
│   │   ├── base.py            ←   SearchEngine / SearchResult
│   │   ├── registry.py        ←   适配器类注册与解析
│   │   ├── store.py           ←   EngineStore：配置的唯一数据源
│   │   ├── quota.py           ←   滑动窗口限流（跨进程有效）
│   │   └── adapters/          ←   两类通用适配器 + 内置引擎的预设
│   │       ├── declarative.py ←     公共骨架（请求/鉴权/量纲/两步/限流）
│   │       ├── paths.py       ←     JSON 路径（a.b[0].c、回退链 a|b）
│   │       ├── dom.py         ←     HTML 选择器（css@attr、:self）
│   │       ├── generic_json.py / generic_html.py  ← 两个适配器类
│   │       └── presets.py     ←     5 个内置引擎 = 5 张映射表
│   ├── library/               ← 本地图库（以 dHash 内容为身份）
│   │   ├── db.py              ←   SQLite schema 与迁移
│   │   ├── paths.py           ←   根路径登记（拒绝嵌套 / 失效检测 / 重新指定）
│   │   ├── store.py           ←   按内容查找与写入、缓存结果复用
│   │   ├── thumbs.py          ←   按内容存放的缩略图缓存
│   │   └── cleanup.py         ←   占用统计与清理（含 VACUUM 回收）
│   ├── batch.py               ← 批量识别（缓存优先 / 额度策略 / 逐张节流）
│   ├── exporters/             ← 导出（不下载，只出地址）
│   │   ├── base.py            ←   记录模型 / 文件名模板 / 格式注册表
│   │   ├── collect.py         ←   从 搜索结果 / 图库 / CSV 收集
│   │   └── urls / tabular / structured / html_report / clipboard_format
│   ├── links/pixiv.py         ← Pixiv 图片直链模板管理
│   ├── processor/             ← 图片识别、dHash 感知哈希
│   └── utils/network.py       ← 请求封装（重试 / 代理 / cloudscraper）
├── my_engines/                ← 自定义 Python 引擎（配置表达不了时才用）
├── tests/                     ← pytest（851 项）
│   └── legacy/                ←   迁移前的 5 个 Python 引擎，仅作双跑对比
├── LICENSE                    ← 预发布许可（禁止商用；正式版将改 GPL-3.0）
├── THIRD_PARTY_NOTICES.md     ← 第三方组件许可（Qt 为 LGPL-3.0）
├── LICENSES/                  ← LGPL-3.0 / GPL-3.0 全文
├── config.example.json        ← 默认配置模板（config.json 由首次运行生成，不入库）
├── data/  output/             ← 运行时产物（已 gitignore）
├── imgsearch_gui/             ← PySide6 界面（薄壳，业务逻辑都在 imgsearch/）
│   ├── main_window.py         ←   单窗口 + 侧栏
│   ├── workers.py             ←   后台搜索线程（含 stdout 桥接，拿到引擎实时进度）
│   ├── pages/                 ←   搜索 / 图库 / 浏览 / 清理 / 引擎 / 凭据 / 设置
│   ├── dialogs/               ←   批量识别 / 导出 / 新建引擎向导
│   └── widgets/               ←   拖拽区 / Schema 表单 / 结果表
├── run.sh / run.bat           ← CLI 启动器（自动建 venv）
├── run-gui.sh / run-gui.bat   ← GUI 启动器
├── run_cli.py                 ← CLI 单文件入口（供打包用）
├── run_gui.py                 ← GUI 单文件入口（供打包用）
└── requirements*.txt          ← 依赖（唯一的依赖声明来源）
```

### 启动引导（跨平台）

`run.sh` / `run-gui.sh` / `run.bat` / `run-gui.bat` 都只是**薄封装**，
真正的逻辑在 [`bootstrap.py`](bootstrap.py)：找/建 venv、按需装依赖、启动目标模块。

这么分层的原因：

1. **两个平台共用一套行为** —— 不会出现「Linux 那份改了、Windows 那份忘了」
2. **batch 只剩几行 ASCII** —— 规避 cmd 代码页的坑
3. **这段逻辑能被真实测试**（见 `tests/test_bootstrap.py`）——
   否则发出去的就是一段从未运行过的 Windows 脚本

依赖是否齐备靠「能不能 import 哨兵包」判断（`requests` / `PySide6`），
而不是靠标记文件 —— 标记文件会跟实际状态不一致。

### 声明式适配器：不写代码接新站点

内置两个通用适配器，**填一张映射表**就能接一个新站点：

| 适配器 | 适用 | 配置方式 |
|---|---|---|
| **JSON 适配器** `genericJson` | 站点返回 JSON | 点号路径：`data.creator`、`results[0].x` |
| **HTML 适配器** `genericHtml` | 站点返回 HTML 页面 | CSS 选择器：`td.image a@href`、`:self` |

两者共用同一套请求/鉴权/量纲逻辑，站点差异全部写在配置里。

> 一个类可以挂**多个实例**：接 A 站和 B 站只要加两条引擎配置，
> 不需要写两个文件。

```bash
# 加一个 JSON 站点
imgsearch engines add booruA --module imgsearch.engines.adapters.generic_json \
    --class GenericJson
imgsearch engines config booruA --set api_url=https://booru.example
imgsearch engines config booruA --set results_path=posts
imgsearch engines config booruA --set field_artist=tag_string_artist
```

#### 映射表的写法

| 配置项 | JSON 适配器 | HTML 适配器 |
|---|---|---|
| 结果在哪 | `results_path`（如 `results`；留空=顶层数组） | `container_selector` + `row_selector` |
| 相似度 | `field_similarity` = 路径 | `field_similarity` = 选择器 |
| 量纲 | `similarity_scale`：`0-100` / `0-1` / `percent-text` / `none` |
| 各字段 | `field_artist` / `field_title` / `field_urls` / `field_thumbnail` … |
| 回退链 | 用 `\|` 串起来取第一个非空的：`anilist.title.chinese\|anilist.title.romaji` |
| 行过滤 | — | `row_must_contain`：只保留文本含该词的行（排除「你的图片」这类块） |
| 协议相对地址 | `//host/x` 会自动补成 `https://host/x` |

#### 两个真实站点的验证（开发时做过，不是纸上设计）

**HTML 适配器重现 IQDB**（纯配置，零代码）：

```
container_selector  #pages
row_selector        table
row_must_contain    similarity
similarity_scale    percent-text
field_similarity    :self                     ← 整行文本里取 "42% similarity"
field_urls          td.image a@href
field_thumbnail     td.image img@src
```

结果与手写引擎一致：`42 / 41 / 40`，条数相同、链接相同（协议相对地址已补全）。

**JSON 适配器重现 TraceMoe**：

```
results_path       result
similarity_scale   0-1                        ← TraceMoe 是 0–1 小数
field_similarity   similarity
field_title        anilist.title.chinese|anilist.title.native|anilist.title.romaji
field_urls         anilist.siteUrl|video
params             {"anilistInfo": "", "cutBorders": ""}   ← 手写版也传这两个
```

结果条数相同、AniList 链接相同；差异只有「标题被格式化成了第几集」——
那属于**需要计算的字段**，声明式表达不了。

#### 覆盖不到的情况（请写一个普通引擎文件）

- **多步流程**：如 Ascii2D 的 `POST → 拿重定向 URL → GET 解析`
- **Cloudflare 反爬**：需要 cloudscraper
- **需要计算/拼接的字段**：如由 ID 推导原图地址、把时间秒数格式化成 `第 5 集 @ 15:48`

⚠️ HTML 适配器**最脆**：站点改版会让选择器静默失效。
所以它在「一个元素都找不到」时会报错并给出诊断（页面标题、整页 table 数），
而「有元素但全被过滤掉」视为**正常无匹配**、返回空列表——
这两件事必须分开，否则正常的"没搜到"会被误报成配置错误。

### 引擎的统一模板

**每个引擎都声明同一组类属性**（内置引擎与自定义引擎一致）：

```python
class MyEngine(SearchEngine):
    NAME = "mysite"                    # 配置里的稳定标识（改名=新引擎）
    DISPLAY_NAME = "MySite"            # 界面显示名
    DEFAULT_API_URL = "https://…"      # 站点地址（用户可覆盖）
    DEFAULT_ORDER = 60                 # 权重顺序
    ENABLED_BY_DEFAULT = False         # 新装环境是否默认启用
    AUTH_MODE = "required"             # 凭据需求，见下
    CONFIG_SCHEMA = COMMON_SCHEMA.extend(Schema(...))
```

#### `AUTH_MODE`：凭据需求三档

| 值 | 含义 | 本项目里 |
|---|---|---|
| `required` | 没有凭据完全不能用 | SauceNAO |
| `optional` | 没有凭据能用一部分 | Danbooru（只能搜公网 URL） |
| `none` | 本来就不需要凭据 | IQDB / Ascii2D / TraceMoe |

引擎页会显示「凭据：必须 / 可选 / 无需」。

#### 「使用 API Key」开关（`use_api_key`）

在 `COMMON_SCHEMA` 里，所以**所有引擎同一套模板都有它**。但：

- 只有声明了 `secret` 字段的引擎才在界面上显示这个开关
  （对 IQDB 这类显示一个永远用不上的开关是噪声）
- 关掉之后：
  - **该引擎的凭据从「凭据」页消失**（这正是这个开关的用途：我不打算给它填凭据）
  - 引擎按匿名处理（`uses_api_key` 为 False，不发送凭据）
  - `required` 引擎会**立刻明确报错**并说明是哪个开关关掉了 ——
    而不是构造成功、请求时才给一个莫名的 HTTP 错误

> ⚠️ 关掉 Danbooru 的开关**不能**让本地文件也能搜：匿名
> `POST /iqdb_queries.json` 实测返回 403 CSRF，只有匿名 `GET ?url=` 可用。

#### 凭据页按引擎分组

凭据页的条目从各引擎的 schema 自动推导（不是手写清单），
声明了 `secret` 字段的引擎会自动多出一个分组：

```
┌ SauceNAO（Pixiv 覆盖最好） ───── [必填] 打码
│  API Key        [____________]
├ Danbooru ────────────────────── [必填] 打码
│  API Key        [____________]
│  用户名          [liushuill___]   （明文，便于核对）
```

### 加一个搜索引擎

架构目标是**只写一个文件**：

1. `./run.sh engines new mysite` → 生成 `my_engines/mysite.py` 模板
2. 在模板里声明 `CONFIG_SCHEMA`（要暴露哪些配置）并实现 `search()`
3. `./run.sh engines add mysite --module my_engines.mysite --class Mysite`

配置表单、类型转换、校验、`.env` 回退、限流、CLI 的 `show`/`--set`
全部由 schema 自动派生，**不需要改动任何界面或 CLI 代码**。

---

## 开发

```bash
.venv/bin/python -m pytest          # 全量测试
```

依赖分为三份，均以 `requirements.txt` 为基准：

| 文件 | 用途 |
|---|---|
| `requirements.txt` | 运行时（requests / Pillow / bs4 / lxml / cloudscraper）|
| `requirements-dev.txt` | 加 pytest |
| `requirements-gui.txt` | 加 PySide6（Qt6）|

> `pyproject.toml` 刻意**不重复声明依赖**，避免同一事实写在多处。

---

## 平台差异

| 项 | 处理方式 |
|---|---|
| **路径大小写** | Windows 路径不区分大小写。所有根路径比较都按平台归一（`casefold`），否则 `C:\Images` 与 `c:\images` 会被当成两条路径 —— 重复登记与嵌套检测会双双失效 |
| **路径分隔符** | ✅ **已处理，且不手写**。所有路径都交给 `os.path` / `pathlib`：`normpath` 会把 `C:/a/b` 归一成 `C:\a\b`，`commonpath`/`relpath` 也吃混合分隔符。**代码里没有任何 `split("/")` / `replace("\\","/")` 式的路径拼接**（这类手写正是跨平台路径 bug 的经典根因）。已用 `ntpath` 在 Linux 上验证 Windows 语义，并有守卫测试禁止以后手写 |
| **跨盘符** | `os.path.relpath` 在 Windows 跨盘符会抛异常，已捕获并退化为空相对路径 |
| **长路径前缀** | ⚠️ 未处理。这是 **Windows 的 260 字符上限**，与分隔符无关；需要 `\\?\` 前缀才能突破。库路径过深时可能失败 |
| **venv 布局** | POSIX 是 `bin/python`，Windows 是 `Scripts/python.exe`，由 `bootstrap.py` 统一处理 |
| **控制台编码** | `.bat` 保持纯 ASCII；CLI 在需要时把 stdout 重新包装成 UTF-8（且会先确认对方有 `.buffer`） |
| **文件锁与 WAL** | Windows 上 `os.replace` 与 WAL 均可用；⚠️ 但**不要把 `data/` 放到网络盘**（NFS/SMB），WAL 依赖同目录共享内存，网络文件系统上会损坏数据 |
| **长路径** | Windows 仍有 260 字符上限；库路径过深时可能失败（未做 `\\?\` 前缀处理） |
| **emoji 输出** | CLI 输出含 emoji（✅🔍📚）。Windows 终端 `chcp 65001` 下可能显示为方框，但不影响功能 |

## 迁移状态（v0.2）

已完成：

**P1 — Linux 适配与拆仓**

- ✅ 适配 Linux：venv 启动脚本、PEP 668 兼容、路径全部 `pathlib`
- ✅ 项目拆为独立 git 仓库，工作区父仓不再跟踪本目录
- ✅ 凭据迁移到 `.env`，`config.json` 不再含任何密钥
- ✅ 重构为 `imgsearch/` 核心包（核心层与 UI 解耦）
- ✅ 修复 `PROJECT_DIR` 路径错位、`config.json` 非原子写等缺陷

**P2 — 引擎层重写**

- ✅ `EngineStore` 单一数据源（旧版多实例互相覆盖 → lost update）
- ✅ Schema 驱动配置：字段/类型/校验/`.env` 回退集中一处
- ✅ 修复 9 项引擎配置缺陷（改名丢模块绑定、缓存键错误、`0` 被当空值、
  大小写口径不一致、`load()` 短路漏补默认值、陈旧字段误伤校验 等），均有回归测试
- ✅ 新增 IQDB、TraceMoe 引擎；内置引擎自动发现
- ✅ `engines new` 自定义引擎脚手架（加引擎 = 写一个文件）
- ✅ auto 模式按权重降级 + **按引擎校准**的相似度阈值
- ✅ 按引擎的代理路由 `proxy_mode`；连接失败不再白等间隔
- ✅ 测试从 94 项扩到 **202 项**，且全部隔离到临时目录（不再碰真实配置）

**P3 — 本地图库（核心层）**

- ✅ SQLite 图库，**以 dHash 内容为身份**、路径只作「最后已知位置」，
  因此文件移动后仍能认出「这张搜过了」并复用结果（省搜索配额）
- ✅ 多根路径手动登记；拒绝嵌套；失效路径标记与重新指定
- ✅ 按路径 / 按类别的占用统计
- ✅ 清理：搜索结果 / 缩略图 / 单路径全部数据 / 孤立缩略图，
  每次清理后 checkpoint → VACUUM → checkpoint，空间真实回收
- ✅ 测试 202 → **851 项**（含「移动后仍命中」与「空间真的回收」两条关键回归）

**顺带修掉的一个真 bug**：引擎里写的是
``create_session(proxies=self.proxies or get_proxies())`` ——
上层判定「代理不可用，本次直连」并传入 `None` 后，引擎会 `or` 回退去读配置，
把那个坏代理又捡回来，**自动降级被彻底架空**。已改为代理只由调用方决定。

**P5（第一轮）— Qt6 GUI**

- ✅ 单窗口 + 侧栏；原生 Wayland；原生拖拽
- ✅ **搜索页**：拖入即搜、结果表、复制/打开链接、缓存命中标注
- ✅ **引擎页**：Schema 驱动表单（新增引擎不用改界面）+ 引擎「测试」按钮
- ✅ **凭据页**：填完即写入 `.env`（600），用户永不接触该文件
- ✅ 后台线程 + stdout 桥接：搜索不阻塞界面，且能拿到引擎的实时进度
- ✅ 测试 265 → **851 项**（新增 GUI 的 offscreen 测试，含后台线程端到端）

**顺带修掉一个真 bug**：`imgsearch/cli.py` 顶部会把非 UTF-8 的标准流
重新包装，直接访问 `sys.stdout.buffer`。而 GUI 会把 stdout 换成自定义对象
（stdout 桥接），那种对象没有 `buffer` —— 由于 `cli` 是惰性导入的，
症状表现为「搜索时报一个和编码毫无关系的 AttributeError」。
现在包装前会确认对方真的有 `.buffer`，桥接对象也声明自身 `encoding="utf-8"`。

待办：

- ⏳ 多格式导出（urls.txt / CSV / JSON / HTML 缩略图墙 / 剪贴板）
- ⏳ GUI 第二轮：**图库路径管理页**（添加/移除并询问是否清理持久化数据）
  与**独立清理页**（按路径/按类别、先预演后执行、显示真实回收量）

### 已在代理下复测（2026-09）

- ✅ **Ascii2D 确认不可用**（原判断保留但已升级为定论）：
  开后代理复测，`POST /search/color/` 在「直连 / 代理 / 换 Referer+Origin /
  全浏览器头 / cloudscraper」**五种组合下一律 403**（Cloudflare WAF），
  而首页 `GET /` 正常 200 —— 说明是该 POST 端点被规则拦，不是网络或请求头问题。
  备用路径 catbox.moe 也拒收（412 Invalid uploader）。
- ✅ 各引擎在代理下均正常：SauceNAO 95.2% 命中、IQDB 命中并抠出 post ID、
  TraceMoe 正常返回（含片源文件名）
- ✅ 按引擎代理路由验证通过：`proxy_mode=off` 的引擎确实走直连
- ✅ 阈值用真实图库校准（见下）；顺带修好 IQDB 的服务名显示
  （原先取单元格文本会拼成 `DanbooruGelbooru`，改为按链接主机判定）

### 阈值校准（2026-09，10 张真实待查图实测）

两个引擎的相似度都呈**明显双峰分布**，阈值就取在中间的空白带里：

| 引擎 | 噪声簇 | 空白带 | 真实命中簇 | 阈值 |
|---|---|---|---|---|
| SauceNAO | 42–48% | 48–85% | 85–96% | **60%** |
| IQDB | 34–44% | 50–87% | 87–97% | **65%** |

- SauceNAO 命中率 **8/10**（真实命中 85.4–95.8%）
- IQDB 命中率 **8/10**（真实命中 87–97%，全部对应 Danbooru/Gelbooru 帖子）
- ⚠️ IQDB 阈值最初凭感觉设成 45%，实测发现它会放进一个 44% 的噪声样本 ——
  已按数据改为 65%（落在空白带内）
- 低于阈值的结果不会丢失：仍会以「低置信度」形式在最终兜底时呈现

### 待办

- 🔎 Danbooru 经代理仍返回 403，需要账号凭据后再验证
  （目前尚未配置 `DANBOORU_LOGIN` / `DANBOORU_API_KEY`）
- 🔎 样本量仅 10 张，若长期使用建议再抽一批复核阈值

---

**P6 — 引擎全配置化（2026-10）**

目标：把「加一个引擎 = 写一个 Python 文件」变成「加一个引擎 = 填一张表」。

- ✅ 两个通用适配器：**JSON**（点号路径 `data.creator`）与 **HTML**
  （CSS 选择器 `td.image a@href`、整行 `:self`）
- ✅ 5 个内置引擎全部改成配置预设 —— `imgsearch/engines/` 里**不再有站点专属代码**，
  旧实现移到 `tests/legacy/` 只作双跑对比
- ✅ 为此补了 9 项通用能力：限流、Cloudflare 绕过、两步请求、按排名估算相似度、
  字段变换（`~strip_prefix` / `~regex` / `~tags_title`）、模板字段
  （`第 {episode} 集 @ {from:time}`）、数组筛选（`edges[?isMain=true]`）、
  链接主机白名单、按字段去重
- ✅ **新建引擎向导**：选类型 → 填映射 → 点「测试」看原始响应 → 创建
- ✅ 每一步都用**新旧双跑对比**验证（59 项，同一个响应两条路径逐字段比对）
- ✅ 界面修正：勾选框白底块、高级设置改为真折叠（原先是禁用）、
  设置页可滚动（原先会把输入框压到 14px）、批量日志显示配置名而不是类名

**迁移中确认的两处损失**（如实记录，都有测试盯着）：

- IQDB 的 `detail` 从「图库名 | 尺寸」变成只有图库名 —— 尺寸在相邻单元格，
  soupsieve 在这个表格结构上 `nth-child` / 兄弟选择器取不到
- SauceNAO 的高清直链少了「从 `ext_urls` 挑 `i.pximg.net`」那层回退 ——
  那是「在数组里按子串筛选」，路径语法只支持按字段值筛选（`[?k=v]`）

**回滚点**：`git tag v0.10-python-engines` 是最后一个「引擎=Python 文件」的版本。
回滚时 `config.json` 也要一起切，否则新格式的配置旧代码读不了。

测试数 754 → **851 项**。

---

## 许可

- **本项目**：[预发布许可](LICENSE) —— 允许非商业使用与修改；
  修改后分发须以同等许可开源；**禁止商业使用**。正式版将改为 **GPL-3.0**。
- **第三方组件**：见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
  Qt / PySide6 使用 **LGPL-3.0**：本项目以动态链接方式使用、未修改其源码，
  分发编译产物时会一并附带许可全文与组件告知（程序内「设置 → 第三方许可」
  也可查看）。
- **商业使用**：如需商用，请联系作者取得书面许可。
