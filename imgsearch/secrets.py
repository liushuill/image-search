"""
凭据管理 — 与 config.json 严格分离

约定（与工作区 HANDOVER §C 一致）：
  - 密钥只放 `.env`（权限 600）或真实环境变量，**绝不写进 config.json，绝不入库**
  - 真实环境变量优先于 `.env`，便于临时覆盖与 CI
  - 写入一律「原子写 + 0600」，避免出现「内容已写、权限未收」的窗口

用法::

    from imgsearch import secrets

    key = secrets.get("SAUCENAO_KEY")
    secrets.set("SAUCENAO_KEY", "...")   # 写入 .env
    secrets.ensure_env_file()            # 首次使用：生成模板并收紧权限
"""

import os
import stat
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 仓库根目录（本文件在 imgsearch/ 下）
PROJECT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_DIR / ".env"

# 已知凭据 → 用途说明（供 CLI 展示与校验）
# 已知凭据的**兜底说明**。真正权威的来源是各引擎 schema 里的 secret 字段
# （它有展示名、说明、是否必填），这里只保证「引擎不可用时仍能在界面上列出来」。
#
# ⚠️ 只放**真正的密钥**。用户名之类的非密钥不要在列在这里 ——
# 它不是 secret，引擎页已有专属字段；两处都能改又不互通，正是之前那个 bug。
KNOWN_SECRETS: Dict[str, str] = {
    "SAUCENAO_KEY": "SauceNAO API Key（https://saucenao.com/user.php?page=account）",
    "DANBOORU_API_KEY": "Danbooru API Key（/profile → Generate API key）",
}

# 运行时缓存：None 表示尚未加载
_cache: Optional[Dict[str, str]] = None

IS_WINDOWS = os.name == "nt"


def permission_status(is_windows: Optional[bool] = None) -> Tuple[str, bool]:
    """
    描述凭据文件的保护状态。

    Returns:
        ``(给人看的说明, 是否需要提醒)``

    ⚠️ **Windows 上没有 POSIX 权限位**：``chmod`` 只能表达只读位，
    普通文件的 ``st_mode`` 恒为 0666/0444 之类。所以不能拿 0o600 去比对 ——
    否则会显示一个在 Windows 上毫无意义的告警（而且用户无法「修好」它）。

    做成可传参是为了能在 Linux 上验证 Windows 分支。
    """
    win = IS_WINDOWS if is_windows is None else is_windows

    if not ENV_FILE.exists():
        return ("尚未创建（保存凭据时会自动生成）", False)

    if win:
        return ("Windows 下无 POSIX 权限位；保护依赖账户与磁盘权限", False)

    try:
        mode = stat.S_IMODE(ENV_FILE.stat().st_mode)
    except OSError:
        return ("无法读取文件权限", True)

    if mode == 0o600:
        return ("权限 600（仅本人可读写）", False)
    return (f"权限是 {oct(mode)}，建议收紧为 600", True)


def init_hint(is_windows: Optional[bool] = None) -> str:
    """
    首次创建 .env 的命令（随平台变化）。

    与 :func:`permission_status` 一样接受 ``is_windows`` 覆盖：
    否则「Windows 分支长什么样」这件事只能在 Windows 上测，
    POSIX 上跑测试就会失败（本项目的测试要在两边都能过）。
    """
    win = IS_WINDOWS if is_windows is None else is_windows
    if win:
        return "copy .env.example .env"
    return "cp .env.example .env && chmod 600 .env"


# ──────────────────────────────────────────────
#  解析
# ──────────────────────────────────────────────


def _read_lines() -> List[str]:
    """读取 .env 原始行；不存在返回空列表"""
    if not ENV_FILE.exists():
        return []
    try:
        return ENV_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def _split_kv(line: str) -> Optional[Tuple[str, str]]:
    """
    把一行拆成 (key, raw_value)。

    支持 `KEY=v`、`export KEY=v`、注释与空行（返回 None）。
    """
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    if s.lower().startswith("export "):
        s = s[len("export "):].lstrip()
    if "=" not in s:
        return None
    k, v = s.split("=", 1)
    k = k.strip()
    if not k:
        return None
    return k, v.strip()


def _unquote(v: str) -> str:
    """去掉成对的引号"""
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def _quote_if_needed(v: str) -> str:
    """值里有空格或 # 时加双引号，避免被解析截断"""
    if v == "" :
        return ""
    if any(c in v for c in " #\t\"'"):
        return '"' + v.replace('"', '\\"') + '"'
    return v


# ──────────────────────────────────────────────
#  读
# ──────────────────────────────────────────────


def load(force: bool = False) -> Dict[str, str]:
    """加载 .env 中的键值对（带缓存）"""
    global _cache
    if _cache is not None and not force:
        return _cache

    result: Dict[str, str] = {}
    for line in _read_lines():
        kv = _split_kv(line)
        if kv:
            result[kv[0]] = _unquote(kv[1])
    _cache = result
    return _cache


def invalidate_cache() -> None:
    """丢弃缓存（.env 被外部修改后调用）"""
    global _cache
    _cache = None


def get(name: str, default: Optional[str] = None) -> Optional[str]:
    """
    取凭据。

    优先级：真实环境变量 > .env > default。
    空字符串视为「未设置」，以便回退到默认值。
    """
    v = os.environ.get(name)
    if v:
        return v
    v = load().get(name)
    return v if v else default


def is_set(name: str) -> bool:
    """凭据是否已配置"""
    return bool(get(name))


# ──────────────────────────────────────────────
#  写
# ──────────────────────────────────────────────


def _write_atomic(lines: List[str]) -> None:
    """
    原子写入 .env 并确保权限 0600。

    先以 0600 创建临时文件再 os.replace，避免「先写后 chmod」的权限窗口。
    """
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = ENV_FILE.parent / (ENV_FILE.name + ".tmp")

    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines).rstrip("\n") + "\n")
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    os.replace(tmp, ENV_FILE)
    # Windows 上 chmod 只能表达只读位，无害；POSIX 上确保 600
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass


def set(name: str, value: str) -> Path:
    """
    写入/更新一条凭据到 .env（保留文件中的注释与其他键）。

    Returns:
        被写入的文件路径
    """
    key = name.strip()
    if not key:
        raise ValueError("凭据名不能为空")

    lines = _read_lines()
    new_line = f"{key}={_quote_if_needed(value)}"

    for i, line in enumerate(lines):
        kv = _split_kv(line)
        if kv and kv[0] == key:
            lines[i] = new_line
            break
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(new_line)

    _write_atomic(lines)
    invalidate_cache()
    return ENV_FILE


def unset(name: str) -> bool:
    """删除一条凭据（保留注释）。返回是否真的删掉了"""
    key = name.strip()
    lines = _read_lines()
    kept = [ln for ln in lines if not (lambda kv: kv and kv[0] == key)(_split_kv(ln))]
    if len(kept) == len(lines):
        return False
    _write_atomic(kept)
    invalidate_cache()
    return True


def ensure_env_file() -> bool:
    """
    确保 .env 存在且权限为 600。

    Returns:
        是否新建了文件
    """
    if ENV_FILE.exists():
        try:
            os.chmod(ENV_FILE, 0o600)
        except OSError:
            pass
        return False

    _write_atomic([
        "# image-search 凭据文件",
        "#",
        "# 权限必须为 600，且已在 .gitignore 中（绝不入库）",
        "# 真实环境变量优先于本文件，便于临时覆盖",
        "#",
    ])
    return True


def describe() -> List[Tuple[str, bool, str]]:
    """
    列出已知凭据的配置状态，供 CLI 展示。

    Returns:
        [(名称, 是否已配置, 用途说明), ...]
    """
    return [(name, is_set(name), desc) for name, desc in KNOWN_SECRETS.items()]


# 短于这个长度的凭据一律完全隐藏。
# 旧实现对短值返回 v[:2] + "****"，等于把 8 位密码的前 2 位直接印出来 ——
# 脱敏的意义是「能认出是哪一个」，不是「透露一部分」。
_MASK_MIN_LEN = 12


def masked(name: str) -> str:
    """
    脱敏显示：``c2e8****1db5``。

    只有足够长的值才露出首尾各 4 位（便于认出是哪一个 key）；
    短值一律返回 ``****``，避免泄露其中大部分内容。
    """
    v = get(name)
    if not v:
        return "(未设置)"
    if len(v) < _MASK_MIN_LEN:
        return "****"
    return f"{v[:4]}****{v[-4:]}"
