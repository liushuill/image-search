# image-search — 二次元图片溯源工具

以图搜图，查出图片的原始出处（Pixiv / Danbooru / Twitter 等），并导出可批量下载的链接。

- **核心层零 UI 依赖** —— `imgsearch/` 是纯 Python 包，CLI 与（未来的）GUI 共用同一套引擎
- **凭据与配置分离** —— API Key 只放 `.env`（0600），绝不进 `config.json`、绝不入库
- **Linux / Windows 同一份代码**，各自一个启动脚本

---

## 快速开始

### Linux / macOS

```bash
./run.sh config secrets            # 查看凭据状态
./run.sh search 图片.jpg            # 搜索出处
./run.sh search 图片.jpg --url      # 顺便生成 Pixiv 图片直链
./run.sh batch ./待查目录            # 批量搜索，产出 JSON + CSV
```

首次运行会自动创建 `.venv` 并安装依赖（不会污染系统 Python）。

### Windows

```bat
run.bat search 图片.jpg
run.bat batch 待查目录
```

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

### 非敏感配置 → `config.json`

```bash
./run.sh config show                       # 查看（凭据自动脱敏）
./run.sh config set proxy http://127.0.0.1:7897
./run.sh config set saucenao_key YOUR_KEY  # 敏感键会自动写入 .env
```

> ⚠️ 本机代理是 Clash Verge / mihomo，默认端口 **7897**，且**不是常开**。
> 程序在代理不可用时会自动降级为直连并打印提示。

---

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

内置引擎（权重小的先用）：

| 引擎 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `sauceNAO` | 官方 API | ✅ 启用 | Pixiv 覆盖最好，需要 API Key |
| `iqdb` | HTML 解析 | ✅ 启用 | IQDB 聚合：Danbooru / Konachan / yande.re / Gelbooru / Sankaku / e-shuushuu / Zerochan / Anime-Pictures。无需凭据 |
| `ascii2d` | HTML 解析 | ⏸ 禁用 | **已确认不可用**：上传端点被 Cloudflare WAF 挡（403，cloudscraper 无效），备用图床 catbox.moe 拒收（412）。仅保留实现供日后站点恢复 |
| `traceMoe` | 官方 API | ⏸ 禁用 | 动画截图溯源（回答"第几集第几秒"）。**对插画会高分误报**，需要时用 `-e traceMoe` |
| `danbooru` | 官方 API | ⏸ 禁用 | 需要账号（用户名 + API Key）|

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
│   ├── engines/               ← 搜索引擎
│   │   ├── schema.py          ←   CONFIG_SCHEMA 协议（字段声明/类型/校验）
│   │   ├── base.py            ←   SearchEngine / SearchResult
│   │   ├── registry.py        ←   引擎类注册与解析（自动发现内置引擎）
│   │   ├── store.py           ←   EngineStore：配置的唯一数据源
│   │   ├── quota.py           ←   滑动窗口限流（跨进程有效）
│   │   └── saucenao / iqdb / ascii2d / tracemoe / danbooru
│   ├── library/               ← 本地图库（以 dHash 内容为身份）
│   │   ├── db.py              ←   SQLite schema 与迁移
│   │   ├── paths.py           ←   根路径登记（拒绝嵌套 / 失效检测 / 重新指定）
│   │   ├── store.py           ←   按内容查找与写入、缓存结果复用
│   │   ├── thumbs.py          ←   按内容存放的缩略图缓存
│   │   └── cleanup.py         ←   占用统计与清理（含 VACUUM 回收）
│   ├── links/pixiv.py         ← Pixiv 图片直链模板管理
│   ├── processor/             ← 图片识别、dHash 感知哈希
│   └── utils/network.py       ← 请求封装（重试 / 代理 / cloudscraper）
├── my_engines/                ← 自定义引擎（engines new 生成，可动态加载）
├── tests/                     ← pytest（265 项）
├── data/  output/             ← 运行时产物（已 gitignore）
├── run.sh / run.bat           ← 启动器（自动建 venv）
├── run_cli.py                 ← 单文件入口（供打包用）
├── gui.py                     ← 旧 tkinter GUI（待迁移到 PySide6）
└── requirements*.txt          ← 依赖（唯一的依赖声明来源）
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
- ✅ 测试 202 → **265 项**（含「移动后仍命中」与「空间真的回收」两条关键回归）

**顺带修掉的一个真 bug**：引擎里写的是
``create_session(proxies=self.proxies or get_proxies())`` ——
上层判定「代理不可用，本次直连」并传入 `None` 后，引擎会 `or` 回退去读配置，
把那个坏代理又捡回来，**自动降级被彻底架空**。已改为代理只由调用方决定。

待办：

- ⏳ 多格式导出（urls.txt / CSV / JSON / HTML 缩略图墙 / 剪贴板）
- ⏳ GUI 迁移到 PySide6（Qt6）：原生拖拽、Schema 配置表单、
  **凭据录入页（用户无需手编 .env）**、图库路径管理页、清理页

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
