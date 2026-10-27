# 故障排查

> 出问题时先看这里。Windows 相关的问题占了大部分 —— 它的环境差异最多。

---

## 装不上 / 找不到 Python

首次运行会自动建 `.venv` 并装依赖。若提示找不到 Python：

- 到 <https://www.python.org/downloads/> 安装，**安装时勾选 "Add python.exe to PATH"**
- 装完**关掉再重开**命令行窗口（PATH 才会刷新）
- 启动脚本会优先用 `py -3`（Python 官方启动器），没有才退回 `python`
- **装了多个 Python 也不用手动挑**：`bootstrap.py` 会检查版本，太旧时自动换到
  `py` 启动器里满足 3.10+ 的最新一个（例如 `py -3` 指向 3.9、而机器上还有 3.14 时，
  它会改用 3.14 重跑）；实在找不到才报错，并给出可照抄的处理办法

> 批处理文件刻意**只含 ASCII**：cmd.exe 是按当前代码页逐行解析 `.bat` 的，
> 中文写在 `if` 块里很容易出问题。所有面向用户的提示都由 Python 打印。

## 常见问题

### Windows：点「打开导出目录」没反应 / 报 error 5

**症状**（三种表现，根因相同）：

```
qt.qpa.services: ShellExecute 'file:///C:/.../output' failed (error 5)
```

- 弹窗说「无法打开」，原因里是 `PermissionError: [WinError 5] 拒绝访问`
- 或者干脆**点了没反应**（程序以为成功，其实什么都没打开）
- 有时伴随 `explorer 立即退出，code=0xc0000142`

**原因：进程跑在「低完整性（Low）」下，被 UIPI 挡住。**

打开**文件夹**不是程序自己能做到的事 —— 它必须请正在运行的 Explorer 代劳。
而 Low 完整性的进程不允许向 Medium 的 Explorer 发窗口消息，于是：

| 操作 | 低完整性下的结果 |
|---|---|
| 打开**文件夹** | ❌ WinError 5（需要 shell） |
| 打开**文件** | ✅ 正常（走文件关联，直接起子进程，不需要 shell） |

**怎么来的：** 如果**上级目录**带 Low 强制标签且有继承标记（`(OI)(CI)`），
在里面创建的 `.venv` 会继承这个标签，于是 venv 里的 python 跑在 Low 完整性。
常见于：项目放在某个被沙箱/受限进程创建过的目录里（CI 工作区、某些同步盘、
安全软件的重定向目录等）。

**自查（Windows PowerShell）：**

```powershell
# 1. venv 里的 python 处于什么完整性？Low 就是中招了
.\.venv\Scripts\python.exe -c "from imgsearch_gui.shell_open import process_integrity as p; print(p())"

# 2. 文件本身有没有 Low 标签
icacls .\.venv\Scripts\python.exe | Select-String "Mandatory"

# 3. 上级目录是不是元凶（有则说明会被继承）
icacls C:\path\to\你的\项目父目录 | Select-String "Mandatory"
```

程序自己也会提示：启动时若检测到 Low 会打印警告；「打不开」的弹窗里
带一行 `进程完整性=Low`。

**修复：把项目移出那个目录，再重建 venv。**

```powershell
mkdir C:\Users\你\image-search          # 普通目录
cd C:\Users\你\image-search
git clone https://github.com/liushuill/image-search.git
cd image-search
copy C:\旧位置\image-search\config.json .   # 个人配置
copy C:\旧位置\image-search\.env .          # 凭据
xcopy /E /I C:\旧位置\image-search\data data  # 图库（数据库 + 缩略图）
.\run-gui.bat                                  # 在这里重建 venv
```

> ⚠️ **只删 `.venv` 重建是没用的** —— 只要还在同一个父目录下，
> 新文件照样继承 Low 标签。必须换目录。
>
> ⚠️ 也**不要**直接给那个父目录改完整性标签：如果它同时是别的工具的工作区，
> 提权会让那些工具失去写权限。换目录最安全。

**验证修好了：**

```powershell
.\.venv\Scripts\python.exe -c "from imgsearch_gui.shell_open import process_integrity as p; print(p())"
# 期望输出 Medium，而不是 Low
```

### 拖进来了，但什么都没发生

拖拽失败时**不会静默**——右上角状态栏会说原因。四种情况：

| 你拖的东西 | 提示 | 该怎么办 |
|---|---|---|
| **多个图片** | 一次只处理第一张（你选了 N 张） | 单张搜索只取第一张 |
| **一个文件夹** | 这是文件夹 —— 请到「图库」页面添加文件夹，再批量识别 | 到图库页登记根路径，再用批量识别 |
| **网页上的图片链接** | 这是网页上的图片链接，不是本地文件 —— 请先把图片下载下来 | 本工具**不下载任何文件**，先自己存到本地 |
| **不是图片的文件** | 不是支持的图片格式（jpg / png / webp / bmp / gif / tiff） | 换一张 |

提示出现时，右上角那行背景会**先快速亮起、再缓缓淡到一个浅橙色**（约 0.75 秒），
停在能看清文字的程度——这样既不会漏看，也不会一直刺眼。

> ⚠️ 一个容易踩的坑：**从 Pixiv 之类站点拖"还没加载完"的图片**时，
> 浏览器交出去的可能是一个 **`.html` 文件**（右键另存也一样）。
> 那不是图片，提示会告诉你"不是支持的图片格式"。

### PySide6 6.12 退出时崩溃

`requirements-gui.txt` 限制 `PySide6<6.12`。这不是"保守起见"，是实测过的：

**现象**：整套用例全过、进度条走到 100%，进程在**退出时**以 `0xC0000409`
结束（Windows 上 `abort()` 的返回码，崩溃模块是 `ucrtbase.dll`），pytest 侧
没有任何 traceback。结果是退出码变成"假失败" —— 让人分不清"真回归"和"收尾崩"。

**复现条件（同一份代码，只换 Qt 版本）**

| 条件 | 6.12.0 | 6.11.2 |
|---|---|---|
| 正常目录 + Medium 完整性（`S-1-16-8192`）+ 完整桌面 | ❌ **3/3 崩** | ✅ 3/3 `exit=0` |
| 全量套件（907 收集） | 用例全过、退出崩 | ✅ `903 passed, 4 skipped` |

**已经缩到的范围**：`tests/test_gui_prefs.py::TestUnsavedChangesGuard`（9 个用例）。

- 按类拆开 `test_gui_prefs.py` 的 6 个类 → 只有这个类崩，其余 5 类 `exit=0`
- 该类 9 个用例**逐个单跑** → 全部 `exit=0`
- 该类 9 个用例**一起跑** → 3/3 崩
- 该类**不含任何线程**，只涉及引擎页表单、`QMessageBox` 的 monkeypatch 与页面切换
  → 与我们修过的「缩略图线程收尾」是**两个独立问题**
- 换图形平台（`offscreen` / `minimal`）都复现，只是概率不同

**特征**：**累积型** —— 单跑不炸，累积到一定量的控件/对话框之后才炸。

**根因未定位**：可能是我们的对象泄漏（对话框没设 parent、信号重复连接），
也可能是 Qt 自身。6.11.2 上一切正常，所以限制先留着，等 6.13 再评估。

> 曾一度怀疑「这只是低完整性会话的产物」，已在正常环境复测排除：
> Medium 完整性 + 干净目录下依然 3/3 崩。


## Windows 的验证状态

**开发原先在 Linux 上完成；2026-10 在一台 Windows 11（Python 3.14.5 / PySide6 6.11.2）
上跑过一轮。** 下面把「实测通过」与「没覆盖」分开列，避免"应该没问题"这种含糊说法。

> ⚠️ **「打开文件夹」失败的真实原因：venv 建在了沙箱里**
>
> 曾经出现过 `ShellExecute ... failed (error 5)`，排查过程走了两个弯路
> （先怀疑 `os.startfile` 不可靠，又怀疑 Python 3.14 改了实现）。最后实测定位到：
>
> ```
> venv 是在低完整性会话（沙箱）里创建的
>   → .venv\Scripts\python.exe 的 ACL 带 "Mandatory Label/Low"
>   → 用它启动的进程运行在 Low 完整性（S-1-16-4096）
>   → Low 进程不能向中完整性的 Explorer 发窗口消息（UIPI）
>   → ShellExecute 一律返回 5；连 explorer 子进程都以 0xC0000142 起不来
> ```
>
> 对照实验（同一个 3.14.5）：venv 里的 python 全失败，**base 解释器全成功**。
> 所以**不是代码问题、不是版本问题**。
>
> ⚠️ 注意：如果 **venv 所在的上级目录**带 Low 标签（继承），那么在里面重建 venv
> **没有用** —— 新文件照样继承 Low。正确做法是**把项目整个移到普通目录**
> （例如 `C:\Users\你\image-search`）再重建 `.venv`。
>
> 程序现在会在两处给出提示：启动时若检测到低完整性会话会警告；
> 「打不开」的弹窗里带 `进程完整性=Low` 这样的线索，一眼可辨。

**在「无 shell 会话」里也依然有效的结论**

- ✅ `run.bat` / `run-gui.bat` 都能启动；包括「机器上同时装着 3.9 与 3.14、`py -3` 却解析到 3.9」
  这条路径 —— `bootstrap.py` 会自己发现更新的解释器并换过去重跑
- ✅ PySide6 窗口能起，所有页面能构造与渲染（`QWidget.grab()` 渲染，不依赖 shell）
- ✅ 150% 缩放（2560×1600）下中文与控件布局正常；字体取系统默认（Microsoft YaHei UI）
- ✅ 测试套件在 6.11.2 上**全过、退出码 0**；原先 5 项「假设本机是 POSIX」的测试已改成平台无关
- ✅ CLI 在 `chcp 65001` 下中文与 emoji 正常
- ✅ 路径大小写归一、venv 布局（`Scripts\python.exe`）、`.env` 写入均有测试覆盖并在实机跑通
- ✅ `bootstrap.py` 的解释器版本处理与 PySide6 版本校验（3.9→3.14 自动切换、旧 venv 拦截）

**另外单独验证过的**

- ✅ **打开输出目录 / 打开文件夹**：在**干净目录**（Medium + Explorer 在跑）下实测通过，
  资源管理器正常弹出（详见「常见问题 → Windows 打不开文件夹」）
- ✅ **从资源管理器拖图进窗口**：作者在 Linux 与 Windows 上均已手动验证
- ✅ `bootstrap.py` 在「`py` 默认解析到 3.9.10、`python` 是应用商店占位符」的机器上，
  仍能正确换到 3.14 并跑起来

**仍然没覆盖**

- 🔎 「窗口真的显示在用户桌面上」—— 只验证了渲染与退出码
- 🔎 在文件管理器中**选中**某张图（`explorer /select`）
- 🔎 高 DPI 下字体/间距的**观感**（截图核对过布局，但没有逐项目视）
- 🔎 中文路径、超长路径（Windows 仍限 260 字符，未做 `\\?\` 前缀处理 ——
  注意这与**分隔符**无关，前者已处理并有测试守着）
- 🔎 杀毒软件/受控文件夹访问对 `.venv` 创建与 `.env` 写入的干扰

**已知问题**

- PySide6 限制在 `<6.12`：**6.12.0 上有一个可复现的退出崩溃**（Windows 11 +
  Python 3.14.5，同一份代码只换 Qt）。现象是用例全过、退出时 `0xC0000409`
  （`abort`，崩在 `ucrtbase.dll`），pytest 侧没有任何 traceback。
  **已在正常桌面（Medium 完整性、非沙箱目录）复现 3/3**，因此不是环境问题。
  完整证据、缩到的范围与复现条件见「常见问题 → PySide6 6.12 退出时崩溃」。
- 解释器版本：`pyproject.toml` 要求 **Python ≥ 3.10**。`bootstrap.py` 在建 venv 之前
  就会检查版本，太旧时要么自动换到更新的解释器（Windows 的 `py` 启动器），
  要么给出可照抄的处理办法 —— 而不是让人卡在「装依赖失败」上。

如果 Windows 上出问题，把报错原文或截图给我即可。

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

