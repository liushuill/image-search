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
        "label": "图形界面",
    },
}


def log(message: str) -> None:
    print(f"[image-search] {message}", file=sys.stderr, flush=True)


def venv_python() -> Path:
    """venv 里解释器的路径（Windows 与 POSIX 布局不同）"""
    if IS_WINDOWS:
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def ensure_venv() -> Path:
    """
    确保 venv 存在。**不往系统 Python 里装任何东西** ——
    Debian/Ubuntu 有 PEP 668 保护，系统级 pip install 本来也会被拒绝。
    """
    python = venv_python()
    if python.exists():
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


def ensure_dependencies(python: Path, spec: dict) -> None:
    if has_module(python, spec["sentinel"]):
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
