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

## 搜索引擎

```bash
./run.sh engines list                  # 查看引擎与权重（权重小的先用）
./run.sh engines toggle ascii2d        # 启用/禁用
./run.sh engines move sauceNAO --up    # 调整顺序
./run.sh engines config sauceNAO       # 查看某引擎的详细配置
./run.sh engines reset                 # 恢复默认列表
```

内置引擎：

| 引擎 | 类型 | 说明 |
|---|---|---|
| `sauceNAO` | 官方 API | Pixiv 覆盖最好，需要 API Key；有速率限制（4 次 / 30 秒）|
| `ascii2d` | HTML 解析 | 无需 Key；可选 Cloudflare 绕过 |
| `danbooru` | 官方 API | 可用于补标签信息 |

搜索时会按权重顺序依次尝试，第一个有结果的引擎即返回。

---

## 项目结构

```
image-search/
├── imgsearch/                 ← 核心层（无 UI 依赖）
│   ├── config.py              ← 非敏感配置（config.json）+ 敏感键转发
│   ├── secrets.py             ← 凭据读写（.env / 环境变量，原子写 + 0600）
│   ├── cli.py                 ← 命令行入口
│   ├── engines/               ← 搜索引擎（base / registry / 各引擎实现）
│   ├── links/pixiv.py         ← Pixiv 图片直链模板管理
│   ├── processor/             ← 图片识别、dHash 感知哈希
│   └── utils/network.py       ← 请求封装（重试 / 代理 / cloudscraper）
├── tests/                     ← pytest
├── data/  output/             ← 运行时产物（已 gitignore）
├── run.sh / run.bat           ← 启动器（自动建 venv）
├── run_cli.py                 ← 单文件入口（供打包用）
├── gui.py                     ← 旧 tkinter GUI（待迁移到 PySide6）
└── requirements*.txt          ← 依赖（唯一的依赖声明来源）
```

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

- ✅ 适配 Linux：venv 启动脚本、PEP 668 兼容、路径全部 `pathlib`
- ✅ 项目拆为独立 git 仓库，工作区父仓不再跟踪本目录
- ✅ 凭据迁移到 `.env`，`config.json` 不再含任何密钥
- ✅ 重构为 `imgsearch/` 核心包（核心层与 UI 解耦）
- ✅ 修复 `PROJECT_DIR` 路径错位、`config.json` 非原子写等缺陷

待办：

- ⏳ 引擎层重写：单一数据源、Schema 驱动配置、新增 TraceMoe / IQDB 等
- ⏳ SQLite 本地图库（去重 + 缓存命中）
- ⏳ 多格式导出（urls.txt / CSV / JSON / HTML 缩略图墙 / 剪贴板）
- ⏳ GUI 迁移到 PySide6（Qt6）：原生拖拽、Schema 配置表单
