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
    """一个只会按指定状态码与响应体失败的假会话"""

    def __init__(self, status, body=""):
        self.status = status
        self.body = body
        self.headers = {}

    def post(self, *a, **k):
        import requests
        resp = requests.Response()
        resp.status_code = self.status
        resp._content = self.body.encode("utf-8")
        raise requests.HTTPError(f"{self.status} error", response=resp)

    def close(self):
        pass


class TestPermissionVersusAuthErrors:
    """
    403 有两种完全不同的成因，提示必须分开 —— 否则会把用户引到错误的方向。

    实测（用真实账号）：
        凭据有效但账号等级不足 → 403 {"error": "Access denied"}
        凭据无效               → 401 {"error": "Invalid API key"}
        UA 被判定为伪装        → 403 + "Can't verify CSRF token authenticity"

    我第一版把 403 一律说成「UA 被判为伪装浏览器」—— 对着
    Access denied 的响应给出这个提示，等于让用户去改一个没问题的东西。
    """

    def _engine(self):
        from imgsearch.engines.danbooru import Danbooru
        return Danbooru(login="some_user", api_key="x" * 32)

    def test_privilege_error_means_restricted_key(self, monkeypatch):
        """
        403 PrivilegeError 既不等于「账号等级不够」，也不等于 UA 问题。

        依据 Danbooru 源码 ApiKey#has_permission? = ip_permitted? && action_permitted?，
        两个列表默认为空即不限制。实测同一把 Key 打 posts/counts/tags/iqdb
        **全部** 403，而匿名 GET /iqdb_queries.json 返回 200 ——
        所以是「这把 Key 被限制了」，提示必须这么说。
        """
        eng = self._engine()
        body = '{"success":false,"error":"User::PrivilegeError","message":"Access denied"}'
        monkeypatch.setattr(eng, "make_session",
                            lambda **k: _FailingSession(403, body))
        with pytest.raises(ConnectionError) as ei:
            eng.search_by_url("https://example.com/x.jpg")
        msg = str(ei.value)
        assert "API Key 被限制" in msg
        assert "出口 IP" in msg and "权限列表" in msg
        assert "IQDB 引擎" in msg, "要给出不需要账号的替代方案"
        assert "User-Agent" not in msg, "别把用户引去改没问题的东西"
        assert "等级" not in msg, "别再说是账号等级问题 —— 已证伪"

    def test_csrf_403_mentions_user_agent(self, monkeypatch):
        eng = self._engine()
        body = '{"error":"ActionController::InvalidAuthenticityToken"}'
        monkeypatch.setattr(eng, "make_session",
                            lambda **k: _FailingSession(403, body))
        with pytest.raises(ConnectionError) as ei:
            eng.search_by_url("https://example.com/x.jpg")
        assert "User-Agent" in str(ei.value)

    def test_original_response_is_included(self, monkeypatch):
        """把对方原话带上，便于用户自己搜或反馈"""
        eng = self._engine()
        monkeypatch.setattr(eng, "make_session",
                            lambda **k: _FailingSession(403, '{"error":"Access denied"}'))
        with pytest.raises(ConnectionError) as ei:
            eng.search_by_url("https://example.com/x.jpg")
        assert "Access denied" in str(ei.value)


class TestUsageNote:
    """
    停用这个引擎是为了「有账号的人可以启用」，所以**前提条件必须看得见** ——
    否则下一个人启用后照样撞 403，又要重走一遍我走过的弯路。
    """

    def test_danbooru_is_disabled_by_default(self):
        """新装环境不该默认启用它：门槛比别的引擎高"""
        from imgsearch.engines.danbooru import Danbooru
        assert Danbooru.ENABLED_BY_DEFAULT is False

    def test_declares_a_usage_note(self):
        from imgsearch.engines.danbooru import Danbooru
        note = Danbooru.USAGE_NOTE
        assert note
        assert "API Key" in note
        assert "IP" in note and "权限" in note
        # 要指出「两个列表默认为空=不限制」这个关键语义
        assert "空" in note
        # 要给出不需要账号的替代方案
        assert "IQDB" in note

    def test_other_engines_have_no_note(self):
        """没有前提条件的引擎不该显示须知，免得噪声"""
        from imgsearch.engines.base import SearchEngine
        from imgsearch.engines.iqdb import Iqdb
        assert SearchEngine.USAGE_NOTE == ""
        assert Iqdb.USAGE_NOTE == ""

    def test_cli_note_shows_for_disabled_engine(self):
        """停用的引擎也要给提示 —— 想启用的人需要先知道前提条件"""
        from imgsearch.cli import _engine_note
        from imgsearch.engines.store import get_store
        ec = get_store().get("danbooru")
        note = _engine_note(ec)
        assert note.startswith("ℹ️")
        assert "API Key" in note

    def test_cli_note_empty_for_engines_without_note_when_disabled(self):
        from imgsearch.cli import _engine_note
        from imgsearch.engines.store import get_store
        ec = get_store().get("iqdb")
        if not ec.enabled:
            assert _engine_note(ec) == ""
        else:
            assert "ℹ️" not in _engine_note(ec)

    def test_missing_credentials_still_wins_over_usage_note(self):
        """真缺凭据时，「缺 XX」比使用须知更该优先显示"""
        from imgsearch.cli import _engine_note
        from imgsearch.engines.store import get_store
        ec = get_store().get("danbooru")
        # 临时清掉凭据环境变量，模拟未填写
        import imgsearch.secrets as sec
        saved = dict(sec._cache) if sec._cache else None
        try:
            sec._cache = {}
            import os
            for k in ("DANBOORU_LOGIN", "DANBOORU_API_KEY"):
                os.environ.pop(k, None)
            ec.settings.pop("login", None)
            note = _engine_note(ec)
            assert note  # 至少要有提示
        finally:
            sec._cache = saved
            sec.invalidate_cache()


class TestGuiUsageNote:
    """GUI 里须知要单独一行显示（它较长，混在「·」分隔的行里读不动）"""

    @staticmethod
    def _select(page, name: str) -> None:
        """按配置名选中某个引擎"""
        page._load_detail(name)

    # ⚠️ 用 isHidden() 而不是 isVisible()：后者在父窗口未 show 时恒为 False，
    # 测不出「自己有没有被显式隐藏」。
    def test_label_shows_note_for_danbooru(self, qapp):
        from imgsearch_gui.pages.engines_page import EnginesPage
        page = EnginesPage()
        self._select(page, "danbooru")
        assert "API Key" in page.usage_label.text()
        assert page.usage_label.isHidden() is False

    def test_label_hidden_for_engine_without_note(self, qapp):
        from imgsearch_gui.pages.engines_page import EnginesPage
        page = EnginesPage()
        self._select(page, "ascii2d")
        assert page.usage_label.text() == ""
        assert page.usage_label.isHidden() is True

    def test_cleared_when_leaving(self, qapp):
        from imgsearch_gui.pages.engines_page import EnginesPage
        page = EnginesPage()
        self._select(page, "danbooru")
        assert page.usage_label.text()
        page._clear_detail()
        assert page.usage_label.text() == ""
        assert page.usage_label.isHidden() is True

    def test_note_survives_being_disabled(self, qapp):
        """停用时更要显示 —— 想启用的人需要先知道前提条件"""
        from imgsearch.engines.store import get_store
        from imgsearch_gui.pages.engines_page import EnginesPage
        get_store().set_enabled("danbooru", False)
        page = EnginesPage()
        self._select(page, "danbooru")
        assert "API Key" in page.usage_label.text()
