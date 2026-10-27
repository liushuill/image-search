# 架构

> 想读代码 / 想改代码之前看这份。用户用法见 [usage.md](usage.md)。

## 两个包，一条硬边界

```
imgsearch/       核心层：引擎、图库、批量、导出。**零 Qt 依赖**
imgsearch_gui/   界面层：只负责显示与交互，业务逻辑一律调核心层
```

这条边界是硬约束：`imgsearch/` 里没有任何 `import PySide6`，也没有反向依赖界面。
因此 CLI 能在无图形环境下跑，测试也能只测逻辑不碰界面。

## 一次搜索的数据流

```
图片 → dHash → 查图库 ──命中──→ 直接复用结果（不消耗配额）
                      └─未命中─→ 按启用顺序问引擎（各自阈值）
                                  └→ 达标即采用；全部不达标则用最好的低置信结果
                                  └→ 结果写回图库（下次免费）
```

批量识别 = 上面这段循环 + 节流 + 额度策略；导出只输出链接，不下载文件。

---

## 目录结构

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
├── tests/                     ← pytest（当前 949 项）
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
真正的逻辑在 [`bootstrap.py`](../bootstrap.py)：找/建 venv、按需装依赖、启动目标模块。

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


## 打包

编译产物的做法、实测体积、Qt LGPL 合规要求都记在
[packaging-notes.md](packaging-notes.md) —— **这是给构建者看的，不放进 README**。

## 已知的一处架构欠债

`service.py`（GUI 用的服务层）在 `search_with_cache()` 里**延迟导入** `cli.search_image`
—— 引擎循环只有一份实现（在 `cli.py`），但方向是反的。功能上没问题，
将来若要把 CLI 拆出去，应该把这段循环移到 `service` 或 `engines/` 下。
