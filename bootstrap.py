#!/usr/bin/env python3
"""
跨平台启动引导 —— 只用标准库，因此系统自带的 Python 就能跑

职责：确保 ``.venv`` 存在且依赖齐备，然后用 venv 里的解释器启动目标。

## 为什么把这段逻辑放在 Python 里

而不是分别写在 ``run.sh`` 与 ``run.bat`` 里：

1. **两个平台共用同一套行为** —— 不会出现「Linux 那份修了、Windows 那份忘了」
2. **batch 只剩几行 ASCII** —— cmd.exe 按当前代码页逐行解析批处理文件，
   中文更容易在 ``if`` 块里出问题；把消息都交给 Python 打印就没有这个风险
3. **这段逻辑可以在任意一台机器上被真实测试** —— 包括本机。
   否则我发出去的是一段从没运行过的 Windows 脚本。

用法::

    python bootstrap.py cli [参数...]
    python bootstrap.py gui [参数...]

也可以被 run.sh / run.bat 调用，见仓库根目录的那两个薄封装。
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
VENV_DIR = REPO_DIR / ".venv"
IS_WINDOWS = os.name == "nt"

# 最低解释器版本（与 pyproject.toml 的 requires-python 保持一致）
MIN_PYTHON = (3, 10)

# 重新执行自己时用的环境变量标记 —— 防止「换了个解释器还是太旧」时无限套娃
_REEXEC_FLAG = "IMAGE_SEARCH_BOOTSTRAP_REEXEC"

# 两种入口各自需要什么
TARGETS = {
    "cli": {
        "module": "imgsearch",
        "requirements": "requirements.txt",
        # 用「能不能 import 这个包」判断依赖是否齐备，而不是靠标记文件 ——
        # 标记文件会与实际状态不一致（比如用户手动删了包）
        "sentinel": "requests",
        "label": "命令行",
    },
    "gui": {
        "module": "imgsearch_gui",
        "requirements": "requirements-gui.txt",
        "sentinel": "PySide6",
        # 「能 import」不等于「版本对」：还要按 requirements 里的区间校验
        "pin": "PySide6",
        "label": "图形界面",
    },
}


def log(message: str) -> None:
    print(f"[image-search] {message}", file=sys.stderr, flush=True)


def _version_text(info=None) -> str:
    """把版本元组渲染成 “3.9.10” 这种可读形式"""
    v = sys.version_info if info is None else info
    return ".".join(str(part) for part in tuple(v)[:3])


def _too_old() -> bool:
    return tuple(sys.version_info[:2]) < MIN_PYTHON


def find_newer_python() -> "str | None":
    """
    Windows：让 ``py`` 启动器找出一个 >= MIN_PYTHON 的解释器，返回其路径。

    为什么需要这一步：``py -3`` 取的是**启动器配置的默认版本**，不一定是最新的。
    实机复现（2026-10）：机器上同时装了 3.9 与 3.14，``py -3`` 却解析到 3.9 ——
    于是 ``run.bat`` 拿 3.9 去建 venv，装依赖时退回源码编译（几分钟到十几分钟，
    看起来像卡死），而真正的需求只是「用新一点的那个」。

    只探测 ``3.15 … 3.10`` 这几档；**POSIX 上直接返回 None**（那边 python3
    就一个，没有启动器，也就不用猜）。
    """
    if not IS_WINDOWS:
        return None

    for minor in range(15, MIN_PYTHON[1] - 1, -1):
        try:
            result = subprocess.run(
                ["py", f"-3.{minor}", "-c", "import sys; print(sys.executable)"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode != 0 or not result.stdout.strip():
            continue

        candidate = result.stdout.strip().splitlines()[-1].strip()
        try:
            if Path(candidate).resolve() == Path(sys.executable).resolve():
                continue          # 就是当前这个（比如 py -3.9 指向自己）
        except OSError:
            pass
        return candidate
    return None


def ensure_python_version(argv: list) -> None:
    """
    太旧的解释器直接给出可执行的指示，而不是让它在建 venv / 装依赖时
    以一个和版本毫无关系的错误失败。

    能换就换：Windows 上如果 ``py`` 启动器装着更新的版本，就**换过去重跑自己**，
    用户什么都不用做。换不了才报错退出。

    ``argv`` 用调用方传进来的那一个（与 ``main`` 同源），
    而不是在这里读全局 ``sys.argv`` —— 否则这段逻辑没法被单独测试。
    """
    if not _too_old():
        return

    current = _version_text()
    wanted = "%d.%d" % MIN_PYTHON
    newer = None if os.environ.get(_REEXEC_FLAG) else find_newer_python()

    if newer:
        log(f"当前解释器是 Python {current}，低于所需的 {wanted}；改用 {newer}")
        env = dict(os.environ)
        env[_REEXEC_FLAG] = "1"
        proc = subprocess.run(
            [newer, str(REPO_DIR / "bootstrap.py"), *argv], env=env,
        )
        sys.exit(proc.returncode)

    log(f"需要 Python {wanted} 或更高版本，但当前解释器是 Python {current}：")
    log(f"  {sys.executable}")
    log("怎么办：")
    log("  · Windows：安装新版 Python（勾选 Add python.exe to PATH），"
        "或直接用启动器指定版本： py -3.14 bootstrap.py gui")
    log("  · Debian / Ubuntu：sudo apt install python3.11 python3.11-venv")
    log("  · macOS：brew install python@3.12")
    sys.exit(2)


def venv_python() -> Path:
    """venv 里解释器的路径（Windows 与 POSIX 布局不同）"""
    if IS_WINDOWS:
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def venv_version(venv_dir: Path = None) -> "tuple | None":
    """
    从 ``pyvenv.cfg`` 读出这个 venv 是用哪个版本建的。

    读文件而不是跑子进程：这段逻辑在**每次启动**都会走，没必要为它多起一个进程。
    取不到就返回 None（不当成错误 —— 那是别人的 venv 布局，不是我们的判断依据）。
    """
    cfg = (venv_dir or VENV_DIR) / "pyvenv.cfg"
    try:
        # utf-8-sig：容忍 BOM。Python 自己写的 pyvenv.cfg 没有 BOM，
        # 但有些工具/脚本（如 Windows PowerShell 5.1 的 Set-Content）会加，
        # 带着 BOM 时第一行的键会变成 "\ufeffversion"，匹配不上就成了「读不到」。
        text = cfg.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key.strip().lower() != "version":
            continue
        parts = value.strip().split(".")
        try:
            return (int(parts[0]), int(parts[1]))
        except (IndexError, ValueError):
            return None
    return None


def ensure_venv() -> Path:
    """
    确保 venv 存在。**不往系统 Python 里装任何东西** ——
    Debian/Ubuntu 有 PEP 668 保护，系统级 pip install 本来也会被拒绝。
    """
    python = venv_python()
    if python.exists():
        # 旧版本建出来的 venv 会一直被复用，而它里面的依赖是按旧解释器装的 ——
        # 症状是一堆「和版本毫无关系」的 ImportError / SyntaxError。
        # 这里提前说清楚，并给出删掉重建的指示（.venv 只是依赖，删了不丢数据）。
        built_by = venv_version()
        if built_by is not None and built_by < MIN_PYTHON:
            log(f"现有 {VENV_DIR.name} 是用 Python "
                f"{built_by[0]}.{built_by[1]} 创建的，低于所需的 "
                f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}，里面的依赖也不可用。")
            log(f"请删除 {VENV_DIR} 后重新运行（它只含依赖，删掉不会丢任何数据）。")
            sys.exit(2)
        return python

    log(f"首次运行：正在创建虚拟环境 {VENV_DIR.name} …")
    try:
        result = subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)])
    except OSError as e:
        log(f"无法创建虚拟环境：{e}")
        sys.exit(1)

    if result.returncode != 0 or not python.exists():
        log("创建虚拟环境失败。请确认系统 Python 带有 venv 模块：")
        log("  · Debian / Ubuntu：sudo apt install python3-venv")
        log("  · Windows：重新安装 Python 时勾选 “Add python.exe to PATH”")
        sys.exit(1)
    return python


def has_module(python: Path, module: str) -> bool:
    """venv 里能不能 import 这个模块"""
    try:
        return subprocess.run(
            [str(python), "-c", f"import {module}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
    except OSError:
        return False


def pip(python: Path, *args: str) -> int:
    return subprocess.run([str(python), "-m", "pip", *args]).returncode


def _requirement_bounds(requirements: Path, package: str) -> "tuple | None":
    """
    从 requirements 文件里读出某个包的版本区间 ``(最低, 最高不含)``。

    只支持 ``PySide6>=6.6.0,<6.12`` 这种简单写法 —— 够用且不用引入
    ``packaging`` 依赖。读不到就返回 None（不做判断，别拦着用户）。
    """
    try:
        text = requirements.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line.lower().startswith(package.lower()):
            continue
        low = high = None
        for part in line[len(package):].split(","):
            part = part.strip()
            if part.startswith(">="):
                low = _version_tuple(part[2:])
            elif part.startswith("<="):
                high = _version_tuple(part[2:], exclusive=False)
            elif part.startswith("<") and not part.startswith("<="):
                high = _version_tuple(part[1:])
        return (low, high)
    return None


def _version_tuple(text: str, exclusive: bool = True) -> "tuple":
    """
    把 "6.12" 变成 (6, 12)。

    每一段只取**开头**的数字：``6.12.0rc1`` → (6, 12, 0)（而不是 1 ——
    那是把所有数字拼起来的结果），``6.12.1`` → (6, 12, 1)。
    """
    parts = []
    for chunk in text.strip().split("."):
        digits = ""
        for ch in chunk:
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def installed_version(python: Path, module: str) -> "tuple | None":
    """问 venv：这个模块装的是哪个版本"""
    try:
        out = subprocess.run(
            [str(python), "-c", f"import {module}; print({module}.__version__)"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    return _version_tuple(out.stdout.strip().splitlines()[-1])


def check_version_pin(python: Path, spec: dict) -> None:
    """
    「能 import」不代表「版本对」。

    实测教训：Windows 上 venv 里装过 PySide6 6.12.0，而 6.12 会让进程在退出时
    崩溃（0xC0000409）。但 ``ensure_dependencies`` 只看 ``import PySide6``
    是否成功，于是这个不合适的版本会**一直被复用**，症状看起来像"程序自己的 bug"。

    这里按 requirements 里写的区间校验；不合规就明确提示怎么换回去。
    """
    name = spec.get("pin")
    if not name:
        return
    bounds = _requirement_bounds(REPO_DIR / spec["requirements"], name)
    if not bounds:
        return
    low, high = bounds
    current = installed_version(python, name)
    if current is None:
        return

    too_low = low is not None and current < low
    too_high = high is not None and current >= high
    if not (too_low or too_high):
        return

    want = f"（最低 {'.'.join(map(str, low))}）" if low else ""
    cap = f"（上限不含 {'.'.join(map(str, high))}）" if high else ""
    log(f"⚠️ {name} 版本是 {'.'.join(map(str, current))}，不在 "
        f"{spec['requirements']} 要求的范围内{want}{cap}。")
    if too_high and name == "PySide6":
        log("   注意：当初观察到 6.12.0 在这个项目上「用例全过、退出时 "
            "0xC0000409」。")
        log("   0xC0000409 是 Windows 上 abort() 的返回码，根因可能不在 6.12 "
            "本身，")
        log("   而是程序自己的线程收尾（已修）。限制暂保留，待复测。")
    log("   修复办法（二选一，都可以照抄）：")
    log(f"     · 让它自己修：删除 {VENV_DIR} 后重新运行本脚本（.venv 只含依赖，"
        "删掉不丢数据）")
    log(f"     · 手动改：{python} -m pip install "
        f"\"{name}{_bounds_text(low, high)}\"")
    sys.exit(2)


def _bounds_text(low, high) -> str:
    """把区间还原成 pip 能懂的写法"""
    chunks = []
    if low:
        chunks.append(">=" + ".".join(map(str, low)))
    if high:
        chunks.append("<" + ".".join(map(str, high)))
    return ",".join(chunks)


def warn_if_low_integrity() -> None:
    """
    Windows：当前进程若跑在**低完整性**（沙箱/受限会话）里，给出明确警告。

    为什么值得单列一条：实测遇到过一种极难查的情况 —— venv 是在低完整性会话
    里创建的，`Scripts\\python.exe` 于是带上 Low 标签，之后用这个 venv 启动的
    进程都跑在 Low 完整性下：

    - 打开文件夹一律 `ShellExecute ... failed (error 5)`（UIPI 拒绝）
    - `explorer` 子进程以 0xC0000142 起不来
    - 但**测试、渲染、CLI 全都正常** —— 症状看起来像"代码有 bug"

    这种 venv 无法靠改代码救回来，只能在普通终端里重建。
    """
    if not IS_WINDOWS:
        return
    try:
        out = subprocess.run(["whoami", "/groups"], capture_output=True,
                             text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return
    if "S-1-16-4096" not in out:
        return
    log("⚠️ 当前进程运行在低完整性（沙箱/受限会话）环境中。")
    log("   在这种环境里创建出来的 .venv 会带上 Low 标签，之后：")
    log("     · 打开文件夹一律失败（ShellExecute error 5）")
    log("     · explorer 子进程起不来（0xC0000142）")
    log("   而测试、渲染、CLI 都正常 —— 很难看出是这个原因。")
    log(f"   建议：在普通终端里删除 {VENV_DIR} 后重新运行本脚本。")


def ensure_dependencies(python: Path, spec: dict) -> None:
    if has_module(python, spec["sentinel"]):
        check_version_pin(python, spec)
        return

    log(f"正在安装{spec['label']}依赖（{spec['requirements']}）…首次约需 1–3 分钟")
    pip(python, "install", "--quiet", "--upgrade", "pip")

    if pip(python, "install", "-r", str(REPO_DIR / spec["requirements"])) != 0:
        log("依赖安装失败。常见原因：")
        log("  · 网络不通 —— 若本机代理不是常开，先开代理再试")
        log("  · 也可先设代理：export HTTPS_PROXY=http://127.0.0.1:7897")
        sys.exit(1)

    # 可选：把 imgsearch 注册成命令。失败不影响使用（下面会用 PYTHONPATH 兜底）
    pip(python, "install", "--quiet", "--no-deps", "-e", str(REPO_DIR))
    log("依赖安装完成。")


def build_env() -> dict:
    """
    用 PYTHONPATH 而非切换工作目录 —— 这样调用者传的相对路径仍然指向他所在的位置，
    而不是被悄悄改成仓库目录。
    """
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(REPO_DIR) + (os.pathsep + existing if existing else "")
    return env


def main(argv: list) -> int:
    # ⚠️ 必须在**建 venv 之前**判版本：
    # 否则一个 3.9 的解释器会一路走到「装依赖失败」，
    # 报出来的却是一个和版本毫无关系的错误（实机见过：源码编译卡死十分钟）。
    ensure_python_version(argv)
    warn_if_low_integrity()

    if not argv or argv[0] not in TARGETS:
        print(__doc__)
        return 2

    kind, extra = argv[0], argv[1:]
    spec = TARGETS[kind]

    # GUI 不解析命令行参数，收到 --help 会直接开窗、让人以为"卡住了"。
    # 这里给一句明确的话，并指到真正有 --help 的 CLI 上。
    if kind == "gui" and any(a in ("-h", "--help") for a in extra):
        print(
            "image-search 图形界面\n\n"
            "  ./run-gui.sh        Linux / macOS\n"
            "  run-gui.bat         Windows\n\n"
            "首次运行会自动创建 .venv 并安装 PySide6。\n"
            "命令行功能请用：./run.sh --help"
        )
        return 0

    python = ensure_venv()
    ensure_dependencies(python, spec)

    if not (REPO_DIR / ".env").exists():
        log("提示：尚未配置凭据（SAUCENAO_KEY 等）——")
        log("      GUI 在「凭据」页填写；CLI 可 cp .env.example .env 后编辑。")

    try:
        return subprocess.run(
            [str(python), "-m", spec["module"], *extra], env=build_env()
        ).returncode
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
