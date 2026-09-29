"""
后台任务

搜索可能耗时几十秒（多引擎依次降级，引擎之间还有 request_delay），
放在 UI 线程里界面会直接假死。所以统一丢到 QThread。

**为什么要桥接 stdout**：引擎内部是用 ``print()`` 汇报进度的，
这一层用 ``redirect_stdout`` 把那些行转成 Qt 信号，
从而**不改动引擎代码**就拿到实时进度。

代价：``sys.stdout`` 是全局的，所以同一时刻只允许一个搜索任务在跑
（由 :data:`_RUN_LOCK` 保证）。对这个工具来说够用。
"""

import contextlib
import threading
from typing import Optional

from PySide6 import QtCore

from imgsearch.service import search_with_cache

# 同一时刻只允许一个搜索任务（stdout 是全局资源）
_RUN_LOCK = threading.Lock()


class _SignalWriter:
    """
    把 write() 的每一行转成回调。

    特意声明 ``encoding = "utf-8"``：这样任何「把非 UTF-8 标准流重新包装」
    的代码（如 imgsearch.cli 顶部那两行）都会认为无需处理，
    不会来访问并不存在的 ``buffer``。
    """

    encoding = "utf-8"

    def __init__(self, sink):
        self._sink = sink
        self._buf = ""

    def write(self, text: str) -> int:
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._sink(line)
        return len(text)

    def flush(self) -> None:
        if self._buf.strip():
            self._sink(self._buf)
        self._buf = ""


class SearchWorker(QtCore.QThread):
    """在后台执行「查缓存 → 联网搜索 → 入库」"""

    progress = QtCore.Signal(str)          # 一行进度/日志
    done = QtCore.Signal(object)           # SearchOutcome
    failed = QtCore.Signal(str)            # 面向用户的错误说明

    def __init__(self, image_path: str, *, engine: str = "auto",
                 refresh: bool = False, min_similarity: Optional[int] = None,
                 parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.engine = engine
        self.refresh = refresh
        self.min_similarity = min_similarity

    def run(self) -> None:  # noqa: D102 - QThread 入口
        if not _RUN_LOCK.acquire(blocking=False):
            self.failed.emit("已有搜索任务在进行中，请等它结束。")
            return
        try:
            writer = _SignalWriter(self.progress.emit)
            with contextlib.redirect_stdout(writer):
                try:
                    outcome = search_with_cache(
                        self.image_path,
                        engine=self.engine,
                        refresh=self.refresh,
                        min_similarity=self.min_similarity,
                    )
                except Exception as e:                # noqa: BLE001
                    # 引擎的报错信息大多是多行、面向用户的，原样传出
                    lines = [ln for ln in str(e).strip().splitlines() if ln.strip()]
                    detail = "\n".join(lines[:1] + [f"   {l}" for l in lines[1:]])
                    self.progress.emit(f"❌ {detail}")
                    self.failed.emit(detail or repr(e))
                    return
                finally:
                    writer.flush()
            self.done.emit(outcome)
        finally:
            _RUN_LOCK.release()


class ProbeWorker(QtCore.QThread):
    """
    引擎「测试」按钮的后台探针。

    做两件事，都**不消耗搜索配额**：
      1. 配置自检：必填字段、凭据来源（配置里 / .env / 缺失）、类可否解析
      2. 端点连通：GET 该引擎的 api_url，报告状态码与耗时（含是否经代理）
    """

    done = QtCore.Signal(list)      # List[Tuple[bool, str]] → (是否通过, 说明)

    def __init__(self, engine_name: str, parent=None):
        super().__init__(parent)
        self.engine_name = engine_name

    def run(self) -> None:  # noqa: D102
        from imgsearch.engines.registry import resolve_engine_class
        from imgsearch.engines.store import get_store
        from imgsearch.engines.schema import BOOL
        from imgsearch import secrets

        checks = []
        store = get_store()
        ec = store.get(self.engine_name)
        if ec is None:
            self.done.emit([(False, f"未找到引擎：{self.engine_name}")])
            return

        # ── 1) 类能否解析 ──
        cls = resolve_engine_class(ec)
        if cls is None:
            checks.append((False, "引擎类无法解析（自定义引擎请检查 module_path / class_name）"))
        else:
            checks.append((True, f"引擎类已解析：{cls.__name__}"))

        # ── 2) 字段与凭据 ──
        schema = ec.schema()
        for f in schema:
            if f.key in ("enabled", "priority"):
                continue
            value = ec.get(f.key, f.default)
            if isinstance(value, str):
                value = value.strip()

            if f.type == BOOL:
                continue
            if value:
                if f.is_secret:
                    checks.append((True, f"{f.label}：已在本机配置中设置"))
                continue
            # 值为空 → 看能否从 .env 回退
            if f.env_var and secrets.is_set(f.env_var):
                checks.append((True, f"{f.label}：留空，将使用 .env 的 {f.env_var}"
                                     f"（{secrets.masked(f.env_var)}）"))
            elif f.required or f.env_var:
                checks.append((False, f"{f.label}：未设置"
                                      + (f"（可在「凭据」页填写，或配置 .env 的 {f.env_var}）"
                                         if f.env_var else "")))

        # ── 3) 端点连通性（不发图，不消耗配额）──
        url = (ec.get("api_url", "") or "").strip() or getattr(cls, "DEFAULT_API_URL", "")
        if not url:
            checks.append((False, "未配置 API 地址，且引擎没有内置默认地址"))
            self.done.emit(checks)
            return

        mode = str(ec.get("proxy_mode", "auto") or "auto")
        proxies = None
        if mode != "off":
            from imgsearch.config import get_proxies
            proxies = get_proxies()
            if proxies:
                from imgsearch.config import check_proxy
                if not check_proxy(proxies):
                    proxies = None
                    checks.append((False, "代理已配置但探测不通，本次探针将直连"))
            elif mode == "on":
                checks.append((False, "设为强制走代理，但没有配置代理地址"))

        how = "经代理" if proxies else "直连"
        checks.append((True, f"正在探测端点（{how}）：{url}"))
        self.done.emit(checks)          # 先把已有结论发出去，让界面立刻有反馈

        import time
        import requests
        try:
            t0 = time.time()
            resp = requests.get(url, proxies=proxies, timeout=15,
                                headers={"User-Agent": "Mozilla/5.0"})
            cost = (time.time() - t0) * 1000
            ok = resp.status_code < 500
            checks.append((ok, f"端点响应 HTTP {resp.status_code}（{cost:.0f} ms，{how}）"))
            if resp.status_code in (401, 403):
                checks.append((False, "401/403：凭据可能无效，或该站点拦截了本机出口 IP"))
        except Exception as e:                            # noqa: BLE001
            checks.append((False, f"端点不可达：{type(e).__name__}: {str(e)[:120]}"))

        self.done.emit(checks)
