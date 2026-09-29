"""
「复制到剪贴板」不是一个文件格式，而是同一份 URL 文本的去向。

注册成虚拟格式，是为了让它出现在 CLI/GUI 的同一张格式清单里
（用户勾选的就是一组「输出方式」），而实际落盘时会被跳过。
"""

from imgsearch.exporters.base import Format, register
from imgsearch.exporters.urls import render as render_urls

register(Format(
    key="clipboard", label="复制到剪贴板", ext="txt", render=render_urls,
    virtual=True,
    help="不写文件；GUI 会直接放进剪贴板，CLI 会打印出来供管道使用",
))


def copy_to_clipboard(text: str) -> bool:
    """
    把文本放进系统剪贴板。

    CLI 场景下没有 Qt，因此尝试常见的命令行工具；
    都不可用时返回 False，由调用方决定退回「打印出来」。

    Returns:
        是否成功写入剪贴板
    """
    import os
    import shutil
    import subprocess

    candidates = []
    if os.name == "nt":
        candidates.append(["clip"])
    elif sys_platform_is_mac():
        candidates.append(["pbcopy"])
    else:
        if os.environ.get("WAYLAND_DISPLAY"):
            candidates.append(["wl-copy"])
        candidates.append(["xclip", "-selection", "clipboard"])
        candidates.append(["xsel", "--clipboard", "--input"])

    for cmd in candidates:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            proc = subprocess.run(cmd, input=text.encode("utf-8"),
                                  timeout=10)
            if proc.returncode == 0:
                return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


def sys_platform_is_mac() -> bool:
    import sys
    return sys.platform == "darwin"
