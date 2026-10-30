# 打包与发布前的检查清单

> 这份文档记录**实测得到的事实**和发布前必须处理的事项。
> 目前尚未发布任何编译产物；正式打包前请逐项核对。

---

## 一、实测数据（Linux，2026-10）

用 PyInstaller 6.22 实际打过一次包（已排除无用的 Qt 模块）：

| 指标 | 实测值 |
|---|---|
| `--onedir` 解压后 | **204 MB** |
| 压缩后（tar.xz） | **60 MB** ← 用户实际下载大小 |
| 其中 PySide6 | **119 MB**（占 58%） |
| 其他大头 | pillow.libs 11M、lxml 9.4M、libgtk 8M、libcrypto 6.3M |

> 之前估算「80–150 MB」是**低估**的。真实情况：解压 200MB+、下载 60MB。
> `--onefile` 能压到 60–90MB，但启动慢 2–5 秒，且**数据必丢**（见下）。

---

## 二、数据目录（已改造完成，2026-10）

打包后程序目录可能在 `Program Files`（只读）或升级时被整体替换，
所以「只读资源」和「可写数据」必须分开。

### 现在的行为

```
APP_DIR    只读资源：代码、config.example.json、THIRD_PARTY_NOTICES.md、LICENSES/
DATA_ROOT  可写数据：config.json、.env、data/（数据库+缩略图）、output/、my_engines/
```

`DATA_ROOT` 的选择顺序（`config._resolve_data_root()`）：

| 顺序 | 条件 | 结果 |
|---|---|---|
| 1 | 环境变量 `IMGSEARCH_DATA_DIR` | 用它（测试 / 临时指定 / 高级用户） |
| 2 | exe 旁边有 `portable.txt` | 数据就留在 exe 旁（便携版） |
| 3 | **打包运行** | Windows `%LOCALAPPDATA%\image-search`<br>macOS `~/Library/Application Support/image-search`<br>Linux `$XDG_DATA_HOME/image-search`（缺省 `~/.local/share/image-search`） |
| 4 | **源码运行** | 仓库目录（**与改造前完全一致**，不需要迁移） |

> Windows 用 `LOCALAPPDATA` 而不是 `APPDATA`：图库+缩略图可能上百 MB，
> 不该跟着漫游配置文件同步。

### 其它连带改动

- `secrets.py` 不再自己算路径，改为 `from imgsearch.config import ENV_FILE`
  （此前两处各算一遍，打包后会分裂成两个 `.env`）
- 自定义 Python 引擎目录改为 `PLUGIN_DIR`（打包后在数据根下），
  `registry` 导入前会把它的父目录补进 `sys.path`
- `.gitignore` 增加 `/build/` `/dist/` `*.spec` `portable.txt`

### 首次发布前仍需人工确认

- [ ] 在没有 Python 的机器上跑打包产物：数据是否落在用户目录
- [ ] 关闭再打开：图库还在
- [ ] 升级（覆盖安装）：数据不丢

## 三、打包步骤

### 前置

```bash
pip install pyinstaller
```

### 排除清单（务必照抄，不是可选项）

不排除的话，PySide6 会把整个 Qt 拖进来（~580 MB）。下面这组是实测过的：

| 类别 | 模块 |
|---|---|
| Web 引擎 | `QtWebEngineCore` `QtWebEngineWidgets` `QtWebEngineQuick` `QtWebChannel` |
| QML / Quick | `QtQml` `QtQuick` `QtQuickWidgets` |
| 3D | `Qt3DCore` `Qt3DRender` |
| 多媒体 | `QtMultimedia` `QtMultimediaWidgets` `QtSpatialAudio` |
| 图表 / 可视化 | `QtCharts` `QtDataVisualization` |
| PDF | `QtPdf` `QtPdfWidgets` |
| 设计器 / 工具 | `QtDesigner` `QtUiTools` `QtHelp` |
| 测试 / 设备 | `QtTest` `QtBluetooth` `QtNfc` `QtPositioning` `QtLocation` `QtSensors` `QtSerialPort` |
| 数据库 / 状态机 | `QtSql` `QtStateMachine` `QtScxml` `QtRemoteObjects` |
| 语音 | `QtTextToSpeech` |
| 无关 Python 库 | `tkinter` `numpy` `matplotlib` |

### Windows（完整命令，直接复制）

> `--add-data` 用**分号** `源;目标`；行尾用 PowerShell 的反引号续行。

```powershell
.\venv\Scripts\python.exe -m PyInstaller --noconfirm --onedir --windowed --name ImageSearch `
  --paths . `
  --collect-submodules imgsearch --collect-submodules imgsearch_gui `
  --hidden-import bs4 --hidden-import cloudscraper --hidden-import lxml `
  --add-data "config.example.json;." `
  --add-data "THIRD_PARTY_NOTICES.md;." `
  --add-data "LICENSES;LICENSES" `
  --add-data "assets;assets" `
  --icon assets/ImageSearch.ico `
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets `
  --exclude-module PySide6.QtWebEngineQuick --exclude-module PySide6.QtWebChannel `
  --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick `
  --exclude-module PySide6.QtQuickWidgets `
  --exclude-module PySide6.Qt3DCore --exclude-module PySide6.Qt3DRender `
  --exclude-module PySide6.QtMultimedia --exclude-module PySide6.QtMultimediaWidgets `
  --exclude-module PySide6.QtSpatialAudio `
  --exclude-module PySide6.QtCharts --exclude-module PySide6.QtDataVisualization `
  --exclude-module PySide6.QtPdf --exclude-module PySide6.QtPdfWidgets `
  --exclude-module PySide6.QtDesigner --exclude-module PySide6.QtUiTools `
  --exclude-module PySide6.QtHelp `
  --exclude-module PySide6.QtTest --exclude-module PySide6.QtBluetooth `
  --exclude-module PySide6.QtNfc --exclude-module PySide6.QtPositioning `
  --exclude-module PySide6.QtLocation --exclude-module PySide6.QtSensors `
  --exclude-module PySide6.QtSerialPort `
  --exclude-module PySide6.QtSql --exclude-module PySide6.QtStateMachine `
  --exclude-module PySide6.QtScxml --exclude-module PySide6.QtRemoteObjects `
  --exclude-module PySide6.QtTextToSpeech `
  --exclude-module tkinter --exclude-module numpy --exclude-module matplotlib `
  run_gui.py
```


### Linux（完整命令）

```bash
python -m PyInstaller --noconfirm --onedir --windowed --name ImageSearch \
  --paths . \
  --collect-submodules imgsearch --collect-submodules imgsearch_gui \
  --hidden-import bs4 --hidden-import cloudscraper --hidden-import lxml \
  --add-data "config.example.json:." \
  --add-data "THIRD_PARTY_NOTICES.md:." \
  --add-data "LICENSES:LICENSES" \
  --add-data "assets:assets" \
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets \
  --exclude-module PySide6.QtWebEngineQuick --exclude-module PySide6.QtWebChannel \
  --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick \
  --exclude-module PySide6.QtQuickWidgets \
  --exclude-module PySide6.Qt3DCore --exclude-module PySide6.Qt3DRender \
  --exclude-module PySide6.QtMultimedia --exclude-module PySide6.QtMultimediaWidgets \
  --exclude-module PySide6.QtSpatialAudio \
  --exclude-module PySide6.QtCharts --exclude-module PySide6.QtDataVisualization \
  --exclude-module PySide6.QtPdf --exclude-module PySide6.QtPdfWidgets \
  --exclude-module PySide6.QtDesigner --exclude-module PySide6.QtUiTools \
  --exclude-module PySide6.QtHelp \
  --exclude-module PySide6.QtTest --exclude-module PySide6.QtBluetooth \
  --exclude-module PySide6.QtNfc --exclude-module PySide6.QtPositioning \
  --exclude-module PySide6.QtLocation --exclude-module PySide6.QtSensors \
  --exclude-module PySide6.QtSerialPort \
  --exclude-module PySide6.QtSql --exclude-module PySide6.QtStateMachine \
  --exclude-module PySide6.QtScxml --exclude-module PySide6.QtRemoteObjects \
  --exclude-module PySide6.QtTextToSpeech \
  --exclude-module tkinter --exclude-module numpy --exclude-module matplotlib \
  run_gui.py

tar -czf image-search-linux-x86_64.tar.gz -C dist ImageSearch
```

### 图标

仓库根的 `assets/` 里有整套尺寸（16–512 PNG + 一个多尺寸 `ImageSearch.ico`）。

| 用途 | 用哪个 |
|---|---|
| **Windows exe 图标** | `--icon assets/ImageSearch.ico`（ico 里含 16/24/32/48/64/128/256） |
| **窗口图标（运行期）** | `assets/ImageSearch-256.png`，由 `imgsearch_gui/assets.py` 自动定位 |
| Linux 桌面项 / AppImage | `assets/ImageSearch-256.png`（或 512） |

`assets/` 必须通过 `--add-data` 打进产物，否则运行期找不到 —— 窗口会退回 Qt 默认图标，
而且**不会报错**，很容易漏。

> Windows 还额外做了一件事：启动时设置 AppUserModelID，否则任务栏会显示成
> `python.exe` 的图标、分组也会错乱（见 `app.py::_claim_taskbar_identity`）。

### 入口

| 入口 | 用途 |
|---|---|
| `run_gui.py` | GUI（`--windowed`） |
| `run_cli.py` | CLI（`--console`） |

GUI 与 CLI 是**两个不同的产物**，命令里的 `--windowed` / `--console` 别弄反：
GUI 用 console 模式会多弹一个黑框；CLI 用 windowed 模式会看不到输出。

### 为什么不能省 `--collect-submodules`

引擎适配器是 **registry 用 pkgutil 动态扫描** 出来的，静态分析看不全；
漏了就是「内置 5 个引擎一个都没有」。

### 打完之后先验这四件事

1. 运行 `dist/ImageSearch/ImageSearch`（Windows 是 `ImageSearch.exe`）
2. 数据落在**用户目录**：Windows `%LOCALAPPDATA%\image-search`，Linux `$XDG_DATA_HOME/image-search`
3. 那里出现了 `config.json` + `data/image_metadata.db` + `data/thumbs`
4. 程序目录里**没有**多出用户数据；界面上拖一张图能搜出结果

### 压缩与发布

| 平台 | 产物 | 参考体积 |
|---|---|---|
| Windows | `Compress-Archive dist/ImageSearch image-search-windows-x64.zip` | 200 MB → **60–80 MB** |
| Linux | `tar -czf ... -C dist ImageSearch` | 204 MB → **60 MB**（tar.xz） |

> 打包时**不要**把 `data/`、`config.json`、`.env`、`.venv` 放进去 —— 那是用户自己的数据。

---

## 四、合规检查（Qt 用 LGPL-3.0）

打包后**逐条核对**：

- [ ] 用的是 `--onedir`（Qt 的 `.so`/`.dll` 是独立文件，用户可替换）
- [ ] `THIRD_PARTY_NOTICES.md` 在产物目录里
- [ ] `LICENSES/LGPL-3.0.txt` 与 `LICENSES/GPL-3.0.txt` 在产物里
- [ ] 程序内「设置 → 第三方许可」能正常打开
- [ ] 没有对 Qt 库做加壳/加密/妨碍替换的处理
- [ ] 没有静态链接 Qt

> LGPL **不要求**本项目开源，只要求 Qt 部分保持可替换 + 告知。

---

## 五、代码签名（可选，建议先不签）

不签名的后果：Windows 会显示「未知发布者 / Windows 已保护你的电脑」，
用户要手动点「更多信息 → 仍要运行」。

| 方案 | 成本 |
|---|---|
| 商业 CA（DigiCert / Sectigo） | $200–500 / 年 |
| Azure Trusted Signing | ~$10 / 月 |
| SignPath（开源项目） | 免费（需项目公开） |
| **不签** | 0 —— 在 README 里给出 SHA256 供核对 |

**建议**：预发布阶段不签；等有人抱怨再说。

---

## 六、发布前清单

### 代码

- [ ] 数据目录改造完成（第二节）
- [ ] `config.json` 确认不入库（已是）
- [ ] `.env` / `data/` 确认不入库（已是）
- [ ] 全部测试通过

### 打包

- [ ] 应用图标（`.ico` / `.icns` / `.png`）
- [ ] 按第三节打包，体积记录在案
- [ ] 在一台**没有装 Python** 的机器上验证启动
- [ ] 验证数据落在用户目录、关掉再开数据还在（数据目录改造后才成立）
- [ ] 验证升级不会丢数据

### 合规

- [ ] 第四节全部勾选
- [ ] README 的预发布声明与实际状态一致

### 分发

- [ ] GitHub Release 附上：产物压缩包、SHA256、更新说明
- [ ] 说明「Windows 未测试」的实际状态
- [ ] 若已切 GPL-3.0：更新 `LICENSE` 与 README

---

## 七、暂不处理的事项

- **跨平台编译**：不可行。Windows 的 exe 必须在 Windows 上打，macOS 同理。
- **自动更新**：需要额外机制（检查版本 + 下载 + 替换），暂不需要。
- **单文件（onefile）**：与数据目录方案冲突，且启动慢；已决定用 onedir。
