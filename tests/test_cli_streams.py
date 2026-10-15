"""
标准流处理回归测试

背景（真实故障）：GUI 里跑批量识别，前 16 张（缓存命中）正常，
第 17 张起全部报 `AttributeError: 'NoneType' object has no attribute 'upper'`。

链路：
    run_batch(quiet=True) → contextlib.redirect_stdout(io.StringIO())
      → 首次惰性导入 imgsearch.cli
        → 模块级 `sys.stdout = _force_utf8(sys.stdout)`
          → io.StringIO **有** encoding 属性、值是 None
            → getattr(stream, "encoding", "") 拿到 None（默认值只在属性缺失时生效）
              → None.upper() 崩
    → 模块导入失败不入 sys.modules → 之后每张重试都崩，所以是「全部失败」

两个根因都修掉：判定 None 安全 + 去掉模块级副作用。
"""

import contextlib
import importlib
import io
import sys


class TestForceUtf8:
    def test_stringio_does_not_crash(self):
        """io.StringIO.encoding 是 None —— 这是原故障的直接触发点"""
        from imgsearch.cli import _force_utf8
        stream = io.StringIO()
        assert _force_utf8(stream) is stream

    def test_stream_with_encoding_none_attribute(self):
        """属性存在但为 None：getattr 的默认值救不了，必须自己兜"""
        class Weird:
            encoding = None
            buffer = io.BytesIO(b"")

        from imgsearch.cli import _force_utf8
        stream = Weird()
        # 不该抛；有 buffer 所以会被包装
        assert _force_utf8(stream) is not None

    def test_stream_without_encoding_attribute(self):
        class Bare:
            def write(self, _text):
                return 0

        from imgsearch.cli import _force_utf8
        stream = Bare()
        assert _force_utf8(stream) is stream      # 没有 buffer，原样返回

    def test_utf8_stream_passes_through(self):
        from imgsearch.cli import _force_utf8
        stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        assert _force_utf8(stream) is stream

    def test_utf8_spellings_are_case_insensitive(self):
        """
        UTF-8 的各种写法都该原样透传。

        ⚠️ TextIOWrapper.encoding 是只读属性，赋值没用，
        所以用一个替身来控制 encoding 的取值。
        """
        from imgsearch.cli import _force_utf8

        class Stub:
            def __init__(self, encoding):
                self.encoding = encoding
                self.buffer = io.BytesIO(b"")

        for name in ("utf-8", "UTF-8", "utf8", "UTF8"):
            stream = Stub(name)
            assert _force_utf8(stream) is stream, name

    def test_non_utf8_with_buffer_gets_wrapped(self):
        from imgsearch.cli import _force_utf8

        class Stub:
            encoding = "cp936"
            buffer = io.BytesIO(b"")

        wrapped = _force_utf8(Stub())
        assert isinstance(wrapped, io.TextIOWrapper)
        assert wrapped.encoding.lower().replace("-", "") == "utf8"


class TestNoImportSideEffects:
    """
    导入 imgsearch.cli 不该替换全局 stdout。

    这正是原故障的根因：模块级副作用让「导入」的结果取决于
    此刻 sys.stdout 是谁，而 GUI 批量恰好在重定向之下导入它。
    """

    def test_import_does_not_replace_stdout(self):
        import imgsearch.cli
        before_out, before_err = sys.stdout, sys.stderr
        importlib.reload(imgsearch.cli)
        assert sys.stdout is before_out, "导入时替换了 sys.stdout"
        assert sys.stderr is before_err, "导入时替换了 sys.stderr"

    def test_import_under_redirect_stdout_is_safe(self):
        """回归：这就是 GUI 批量踩到的那条路径"""
        import imgsearch.cli
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            importlib.reload(imgsearch.cli)      # 不该抛
        # 重定向结束后 stdout 应恢复
        assert sys.stdout is not buffer

    def test_import_under_redirect_works_repeatedly(self):
        """原故障里每张图都会重试导入（导入失败不入 sys.modules）"""
        import imgsearch.cli
        for _ in range(3):
            with contextlib.redirect_stdout(io.StringIO()):
                importlib.reload(imgsearch.cli)

    def test_main_wraps_streams(self):
        """包装改到 main() 里 —— 只有 CLI 真正驱动时才动全局流"""
        import inspect
        import imgsearch.cli
        source = inspect.getsource(imgsearch.cli.main)
        assert "_force_utf8(sys.stdout)" in source
        assert "_force_utf8(sys.stderr)" in source


class TestBatchPreloadsBeforeRedirect:
    """
    防御：run_batch 在进入 redirect_stdout 之前先把惰性导入做完。

    即使将来又有模块在导入期依赖「当前 stdout 是谁」，
    也不会发生在被重定向的流之下。
    """

    def test_batch_module_preloads_cli(self):
        import inspect
        from imgsearch import batch
        source = inspect.getsource(batch.run_batch)
        assert "import imgsearch.cli" in source
        # 预加载必须出现在 for 循环（即 redirect_stdout）之前
        assert source.index("import imgsearch.cli") < source.index("for index, path in enumerate")

    def test_quiet_run_uses_stringio_and_survives(self, tmp_path, monkeypatch):
        """在不预先导入 cli 的前提下跑一遍 quiet 模式"""
        from imgsearch import batch as B
        from imgsearch.service import SearchOutcome

        (tmp_path / "a.jpg").write_bytes(b"\xff\xd8\xff")
        monkeypatch.setattr(B, "search_with_cache",
                            lambda p, **k: SearchOutcome(results=[], dhash="x"))
        store = _FakeEngineStore()
        monkeypatch.setattr(B, "_engines", lambda *_: store)

        report = B.run_batch(tmp_path, engine_store=store, quiet=True)
        assert report.failed == 0
        assert report.searched == 1


class _FakeConfig:
    name = "fake"
    display_name = "Fake"

    def get(self, key, default=None):
        return default


class _FakeEngine:
    """够用的替身：run_batch 会问它额度与请求间隔"""

    def quota_state(self):
        return []

    def request_interval(self):
        return 0.0


class _FakeEngineStore:
    """
    ⚠️ 必须至少给一个可用引擎：run_batch 现在会在开跑前确认「确实有引擎能用」，
    否则一张都不跑直接返回 stopped="no_engine"（这是刻意的，
    免得 389 张逐张失败、日志里 389 行同样的话）。
    """

    def get_enabled(self):
        return [_FakeConfig()]

    def build_engine(self, config):
        return _FakeEngine()
