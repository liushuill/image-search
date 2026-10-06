"""
Danbooru 引擎：请求礼节与认证错误提示

覆盖两处曾经真实存在的问题：
  · User-Agent 伪装浏览器 → Danbooru 直接 403（引擎必然不可用）
  · 「自定义请求头 / 自定义查询参数」两个配置项从未被任何引擎使用

以及 401/403 这两种最可能撞上的错误是否给出了可操作的提示。
"""

import pytest


class TestUserAgentEtiquette:
    """
    回归：Danbooru 明确要求客户端表明身份，并**会拒掉伪造浏览器的 UA**。

    实测（同一代理、同一端点 /posts.json，只改 UA）：
        伪造 Chrome UA → HTTP 403
        诚实 UA        → HTTP 200

    而 create_session 的全局默认正是一个伪造的 Chrome UA ——
    所以 Danbooru 引擎以前是**必然 403**（我曾把这个 403 误判为代理节点问题）。
    """

    def test_user_agent_identifies_the_account(self):
        from imgsearch.engines.danbooru import Danbooru
        eng = Danbooru(login="some_user", api_key="x" * 32)
        ua = eng.user_agent()
        assert "some_user" in ua
        assert "Mozilla" not in ua, "不能伪装成浏览器"

    def test_user_agent_is_not_a_browser_default(self):
        from imgsearch.engines.danbooru import Danbooru
        eng = Danbooru(login="someone", api_key="x" * 32)
        assert "Chrome" not in eng.user_agent()
        assert "Safari" not in eng.user_agent()

    def test_session_uses_that_user_agent(self):
        """make_session 必须把它真的挂上去，否则只是写了个没人用的方法"""
        from imgsearch.engines.danbooru import Danbooru
        eng = Danbooru(login="someone", api_key="x" * 32)
        session = eng.make_session()
        try:
            ua = session.headers.get("User-Agent", "")
            assert "someone" in ua and "Chrome" not in ua
        finally:
            session.close()

    def test_other_engines_keep_the_global_default(self):
        """只给 Danbooru 换 UA —— 其他引擎可能依赖浏览器 UA 过 Cloudflare"""
        from imgsearch.engines.iqdb import Iqdb
        assert Iqdb().user_agent() == ""


class TestCustomHeadersAndParams:
    """
    回归：「自定义请求头」「自定义查询参数」两个配置项以前是**死的** ——
    base.py 存了下来，但没有任何引擎用过；GUI 里能填却毫无作用。
    """

    def test_custom_headers_reach_the_session(self):
        from imgsearch.engines.iqdb import Iqdb
        eng = Iqdb(headers={"X-My-Header": "hello"})
        session = eng.make_session()
        try:
            assert session.headers.get("X-My-Header") == "hello"
        finally:
            session.close()

    def test_custom_headers_override_user_agent(self):
        """用户可以自己指定 UA（例如按文档写进数字 user id）"""
        from imgsearch.engines.iqdb import Iqdb
        eng = Iqdb(headers={"User-Agent": "my-bot/1.0 (user #12345)"})
        session = eng.make_session()
        try:
            assert session.headers["User-Agent"] == "my-bot/1.0 (user #12345)"
        finally:
            session.close()

    def test_no_headers_is_fine(self):
        from imgsearch.engines.iqdb import Iqdb
        session = Iqdb().make_session()
        session.close()

    def test_merge_params_adds_custom_keys(self):
        from imgsearch.engines.iqdb import Iqdb
        eng = Iqdb(params={"extra": "1"})
        assert eng.merge_params({"limit": 20}) == {"extra": "1", "limit": 20}

    def test_engine_params_win_on_conflict(self):
        """
        引擎自身的参数优先：用户手滑覆盖了 url/limit 会静默搜错东西，
        比"自定义项没生效"更难排查。
        """
        from imgsearch.engines.iqdb import Iqdb
        eng = Iqdb(params={"limit": "999", "extra": "1"})
        merged = eng.merge_params({"limit": 20})
        assert merged["limit"] == 20
        assert merged["extra"] == "1"

    def test_merge_params_without_custom(self):
        from imgsearch.engines.iqdb import Iqdb
        assert Iqdb().merge_params({"a": 1}) == {"a": 1}

    def test_danbooru_applies_custom_params(self):
        """Danbooru 的 payload 也要过一遍 merge_params"""
        import inspect
        from imgsearch.engines import danbooru
        src = inspect.getsource(danbooru.Danbooru._call_api)
        assert "merge_params" in src


class TestAuthErrorMessages:
    """401/403 是最可能撞上的两个错误，提示必须能直接指导下一步"""

    def _engine(self):
        from imgsearch.engines.danbooru import Danbooru
        return Danbooru(login="some_user", api_key="x" * 32)

    def _fake_error(self, status):
        import requests
        resp = requests.Response()
        resp.status_code = status
        err = requests.HTTPError(f"{status} Client Error", response=resp)
        err.response = resp
        return err

    def test_401_explains_which_field(self, monkeypatch):
        eng = self._engine()
        monkeypatch.setattr(eng, "make_session", lambda **k: _FailingSession(401))
        with pytest.raises(ConnectionError) as ei:
            eng.search_by_url("https://example.com/x.jpg")
        msg = str(ei.value)
        assert "401" in msg
        assert "用户名" in msg and "账号名" in msg       # 明确用户名不是邮箱
        assert "Generate API key" in msg
        assert "凭据" in msg                            # 告诉他在哪填

    def test_403_mentions_user_agent(self, monkeypatch):
        eng = self._engine()
        monkeypatch.setattr(eng, "make_session", lambda **k: _FailingSession(403))
        with pytest.raises(ConnectionError) as ei:
            eng.search_by_url("https://example.com/x.jpg")
        assert "User-Agent" in str(ei.value)

    def test_401_message_shows_which_username_was_used(self, monkeypatch):
        """出错了要能看见自己填的是什么，便于发现打错"""
        eng = self._engine()
        monkeypatch.setattr(eng, "make_session", lambda **k: _FailingSession(401))
        with pytest.raises(ConnectionError) as ei:
            eng.search_by_url("https://example.com/x.jpg")
        assert "some_user" in str(ei.value)


class _FailingSession:
    """一个只会按指定状态码失败的假会话"""

    def __init__(self, status):
        self.status = status
        self.headers = {}

    def post(self, *a, **k):
        import requests
        resp = requests.Response()
        resp.status_code = self.status
        raise requests.HTTPError(f"{self.status} error", response=resp)

    def close(self):
        pass
