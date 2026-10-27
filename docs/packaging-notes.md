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
pip install pyinstaller        # 建议放进 requirements-dev.txt
```

### 排除无用的 Qt 模块（实测有效，省掉 400+ MB）

```
PySide6.QtWebEngine*  Qt3D*  QtMultimedia*  QtCharts  QtDataVisualization
QtPdf*  QtDesigner  QtUiTools  QtHelp  QtTest  QtBluetooth  QtNfc
QtPositioning  QtLocation  QtSensors  QtSerialPort  QtSql
QtSpatialAudio  QtTextToSpeech  QtRemoteObjects  QtScxml  QtStateMachine
tkinter  numpy  matplotlib
```

### 两条命令（Linux 实测可用）

```bash
# GUI（推荐 onedir，见合规要求）
python -m PyInstaller --noconfirm --onedir --windowed --name ImageSearch \
  --paths . $(printf -- "--exclude-module %s " \
      PySide6.QtWebEngineCore PySide6.QtWebEngineWidgets PySide6.QtQml \
      PySide6.QtQuick PySide6.Qt3DCore PySide6.Qt3DRender \
      PySide6.QtMultimedia PySide6.QtCharts PySide6.QtPdf \
      PySide6.QtDesigner PySide6.QtUiTools PySide6.QtHelp PySide6.QtTest \
      PySide6.QtSql PySide6.QtSensors PySide6.QtSerialPort \
      tkinter numpy matplotlib) \
  --add-data "config.example.json:." \
  --add-data "THIRD_PARTY_NOTICES.md:." \
  --add-data "LICENSES:LICENSES" \
  run_gui.py

# CLI
python -m PyInstaller --noconfirm --onedir --console --name ImageSearch-CLI \
  --paths . run_cli.py
```

> Windows 上 `--add-data` 的分隔符是 `;` 而不是 `:`（`源;目标`）。

### 可能需要的 `--hidden-import`

`bs4`、`cloudscraper`、`lxml`、`charset_normalizer` 有时探测不到；
打包后启动若报 `ModuleNotFoundError`，逐个补上。

### 入口

| 入口 | 用途 |
|---|---|
| `run_gui.py` | GUI（`--windowed`） |
| `run_cli.py` | CLI（`--console`） |

`build_exe.bat` 是 Windows 上的骨架脚本，已指向这两个入口。

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
