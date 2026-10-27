# image-search — 二次元图片溯源工具

拖一张图进来，查出它的原始出处（Pixiv / Danbooru / Twitter 等），并把能批量下载的链接整理出来。

**不下载任何图片**，只输出链接与元数据。

> ⚠️ **预发布（pre-release）** —— 尚未正式发布，处于测试阶段。
> - Linux 已长期日常使用；Windows 已实机验证，**暂未进行完整测试**
> - 接口、配置格式、数据表结构仍可能变动；升级前请备份 `data/`
> - 许可为[预发布许可](LICENSE)：**禁止商业使用**；修改后分发必须同样开源。正式版将改为 **GPL-3.0**
> - 第三方组件许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)（Qt 为 LGPL-3.0）

---

## 目录

| 想做什么 | 去哪看 |
|---|---|
| 装上并搜第一张图 | 本页往下看 |
| 界面 / 命令行 / 配置 / 批量 / 导出 | [docs/usage.md](docs/usage.md) |
| **新增一个站点**（不写代码） | [docs/engines.md](docs/engines.md) |
| 图库：换位置还认得出、清理、判重 | [docs/library.md](docs/library.md) |
| 出问题了（尤其 Windows） | [docs/troubleshooting.md](docs/troubleshooting.md) |
| 想读 / 改代码 | [docs/architecture.md](docs/architecture.md) |
| 打包编译产物 | [docs/packaging-notes.md](docs/packaging-notes.md) |
| 某个设计为什么这么定 | [docs/history.md](docs/history.md) |

---

## 声明：关于 AI 参与

声明：本项目由作者使用AI完成。由于作者缺乏编程能力，作者实际的工作是：

1. 讨论并明确项目的用途，架构。并以行为逻辑链条进行检查。
2. 选择项目技术栈。为AI搜集资料以及提供相关文档，尽量避免其产生边界歪的偏差
3. 测试并提出修改意见，交由AI修改。

尽管作者尽可能地想了一些可能遇到的bug情况，并进行了针对性意见让AI修复。但仍可能遇到各种问题。请您谅解

---

## 界面

![搜索](docs/images/search.png)

单窗口 + 侧栏，七个页面：搜索 / 图库 / 浏览 / 清理 / 引擎 / 凭据 / 设置。
界面用 PySide6（Qt6），在 KDE Wayland 下走原生 wayland，不做 XWayland 转译。

---

## 能做什么

- **拖图即搜**：按内容指纹（dHash）识别，同一张图换个位置再搜直接命中缓存，**不消耗配额**
- **五个内置引擎**，各自校准阈值；按权重依次尝试，达标即停
- **图库**：记录搜过的图与结果，可批量识别整个目录（缓存优先、逐张节流、额度用尽可停）
- **加站点不写代码**：填一张字段映射表就行（JSON / HTML 两类模板），内置向导带「测试」按钮
- **导出**：urls.txt / CSV / JSON / JSONL / HTML 缩略图墙 / 复制到剪贴板
- **凭据只在界面填**：写进 `.env`（0600），不落 `config.json`、不入库

---

## 快速开始

需要 **Python 3.10+**，其余依赖首次运行时自动装进 `.venv`，不污染系统 Python。

### Linux

```bash
./run-gui.sh            # 图形界面
./run.sh search 图.jpg   # 命令行
```

### Windows

```bat
run-gui.bat             :: 图形界面
run.bat search 图.jpg    :: 命令行
```

> **PowerShell 要写 `.\run-gui.bat`** —— 当前目录不在 PATH 里，直接敲会 `CommandNotFoundException`。

装了多个 Python 也不用手动挑：`bootstrap.py` 会检查版本，太旧时自动换到更新的解释器重跑。
找不到 Python 会给出可照抄的处理办法，不会让你卡在「装依赖失败」上。

---

## 数据放在哪里

| 类别 | 内容 | 位置 |
|---|---|---|
| 只读资源 | 代码、`config.example.json`、`LICENSES/` | 程序所在目录 |
| **可写数据** | `config.json`、`.env`、`data/`（图库 + 缩略图）、`output/` | 见下 |

可写数据按以下顺序决定：

1. 环境变量 `IMGSEARCH_DATA_DIR`
2. exe 旁边放一个 `portable.txt` → 数据留在 exe 旁（**便携版**）
3. **打包运行** → Windows `%LOCALAPPDATA%\image-search`、macOS `~/Library/Application Support/image-search`、Linux `$XDG_DATA_HOME/image-search`（缺省 `~/.local/share/image-search`）
4. **源码运行** → 仓库目录（就是你现在看到的样子）

> 从源码跑的**不需要迁移任何东西** —— 第 4 条与改造前完全一致。

---

## 目前状态

- **尚未发布编译产物**。打包前的准备与实测数据见 [docs/packaging-notes.md](docs/packaging-notes.md)
- 测试：949 项（pytest），Linux 与 Windows 均可运行
- 已知限制：`PySide6` 限制在 `<6.12`（6.12.0 有可复现的退出崩溃），细节见 [troubleshooting](docs/troubleshooting.md)

---

## 许可

- **本项目**：[预发布许可](LICENSE) —— 允许非商业使用与修改；修改后分发须以同等许可开源；**禁止商业使用**。正式版将改为 **GPL-3.0**
- **第三方组件**：见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。Qt / PySide6 使用 **LGPL-3.0**，本项目以动态链接方式使用、未修改其源码
- 商业使用请先联系作者取得书面许可
