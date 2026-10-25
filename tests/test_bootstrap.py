"""
启动引导测试

分发出去的是「解压后直接 ./run.sh 或 run.bat 就能用」，所以引导逻辑
本身也是要保证的代码 —— 而不是一段没跑过的脚本。

把逻辑放进 Python（而不是各写一份 sh/bat）正是为了能在这里被真实测试。
"""

import os
from pathlib import Path

import pytest

import bootstrap


class TestTargets:
    def test_known_targets(self):
        assert set(bootstrap.TARGETS) == {"cli", "gui"}
        assert bootstrap.TARGETS["cli"]["module"] == "imgsearch"
        assert bootstrap.TARGETS["gui"]["module"] == "imgsearch_gui"

    def test_requirements_files_exist(self):
        """回归：改了 requirements 文件名却没改这里，分发出去就装不上"""
        for spec in bootstrap.TARGETS.values():
            path = bootstrap.REPO_DIR / spec["requirements"]
            assert path.is_file(), f"找不到 {path}"

    def test_gui_requirements_include_core(self):
        """GUI 依赖必须包含核心依赖，否则图形界面装好了但搜索跑不起来"""
        text = (bootstrap.REPO_DIR / "requirements-gui.txt").read_text(encoding="utf-8")
        assert "-r requirements.txt" in text

    def test_sentinel_matches_requirements(self):
        cli = (bootstrap.REPO_DIR / "requirements.txt").read_text(encoding="utf-8").lower()
        assert bootstrap.TARGETS["cli"]["sentinel"] in cli
        gui = (bootstrap.REPO_DIR / "requirements-gui.txt").read_text(encoding="utf-8").lower()
        assert bootstrap.TARGETS["gui"]["sentinel"].lower() in gui


class TestVenvLayout:
    def test_posix_layout(self, monkeypatch):
        monkeypatch.setattr(bootstrap, "IS_WINDOWS", False)
        assert bootstrap.venv_python() == bootstrap.VENV_DIR / "bin" / "python"

    def test_windows_layout(self, monkeypatch):
        monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
        assert bootstrap.venv_python() == bootstrap.VENV_DIR / "Scripts" / "python.exe"

    def test_existing_venv_is_reused(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bootstrap, "IS_WINDOWS", False)
        monkeypatch.setattr(bootstrap, "VENV_DIR", tmp_path / ".venv")
        target = tmp_path / ".venv" / "bin" / "python"
        target.parent.mkdir(parents=True)
        target.write_text("", encoding="utf-8")
        # 已存在时不该再去创建
        assert bootstrap.ensure_venv() == target

    def test_reads_version_from_pyvenv_cfg(self, tmp_path):
        (tmp_path / "pyvenv.cfg").write_text(
            "home = /usr/bin\nversion = 3.11.9\n", encoding="utf-8"
        )
        assert bootstrap.venv_version(tmp_path) == (3, 11)

    def test_pyvenv_cfg_with_bom_is_parsed(self, tmp_path):
        """带 BOM 时第一行的键会变成 '\\ufeffversion'，不处理就「读不到」"""
        (tmp_path / "pyvenv.cfg").write_bytes(b"\xef\xbb\xbfversion = 3.12.1\n")
        assert bootstrap.venv_version(tmp_path) == (3, 12)

    def test_missing_pyvenv_cfg_is_not_an_error(self, tmp_path):
        """取不到版本就不判断 —— 不能因为读不到文件就拒绝启动"""
        assert bootstrap.venv_version(tmp_path) is None

    def test_stale_venv_is_refused_with_instructions(self, tmp_path, monkeypatch, capsys):
        """
        旧解释器建的 venv 会被一直复用，症状是「和版本毫无关系的 ImportError」。

        实测来源：修好 `py -3` 之前跑过一次的机器，`.venv` 是 3.9 建的，
        之后即使解释器换对了也还是拿那个坏 venv 去跑。
        """
        monkeypatch.setattr(bootstrap, "IS_WINDOWS", False)
        monkeypatch.setattr(bootstrap, "VENV_DIR", tmp_path / ".venv")
        (tmp_path / ".venv" / "bin").mkdir(parents=True)
        (tmp_path / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
        (tmp_path / ".venv" / "pyvenv.cfg").write_text(
            "version = 3.9.10\n", encoding="utf-8"
        )

        with pytest.raises(SystemExit) as exc:
            bootstrap.ensure_venv()

        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "3.9" in err and "删除" in err

    def test_failure_explains_how_to_fix(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(bootstrap, "VENV_DIR", tmp_path / "nope")
        monkeypatch.setattr(bootstrap, "venv_python",
                            lambda: tmp_path / "nope" / "bin" / "python")
        monkeypatch.setattr(bootstrap.subprocess, "run",
                            lambda *a, **k: type("R", (), {"returncode": 1})())
        with pytest.raises(SystemExit):
            bootstrap.ensure_venv()
        err = capsys.readouterr().err
        assert "python3-venv" in err          # Debian 的提示
        assert "PATH" in err                  # Windows 的提示


class TestDependencyCheck:
    def test_skips_install_when_sentinel_present(self, monkeypatch):
        calls = []
        monkeypatch.setattr(bootstrap, "has_module", lambda py, mod: True)
        monkeypatch.setattr(bootstrap, "pip", lambda *a: calls.append(a) or 0)
        bootstrap.ensure_dependencies(Path("py"), bootstrap.TARGETS["cli"])
        assert calls == [], "依赖齐备时不该装任何东西"

    def test_installs_when_sentinel_missing(self, monkeypatch):
        calls = []
        monkeypatch.setattr(bootstrap, "has_module", lambda py, mod: False)
        monkeypatch.setattr(bootstrap, "pip", lambda *a: calls.append(a) or 0)
        bootstrap.ensure_dependencies(Path("py"), bootstrap.TARGETS["gui"])
        joined = [" ".join(map(str, c)) for c in calls]
        assert any("requirements-gui.txt" in j for j in joined)
        assert any("--upgrade" in j and "pip" in j for j in joined)

    def test_install_failure_exits_with_hint(self, monkeypatch, capsys):
        monkeypatch.setattr(bootstrap, "has_module", lambda py, mod: False)

        def fake_pip(py, *args):
            return 1 if "-r" in args else 0

        monkeypatch.setattr(bootstrap, "pip", fake_pip)
        with pytest.raises(SystemExit):
            bootstrap.ensure_dependencies(Path("py"), bootstrap.TARGETS["cli"])
        err = capsys.readouterr().err
        assert "代理" in err or "网络" in err


class TestEnvironment:
    def test_pythonpath_points_at_repo(self, monkeypatch):
        monkeypatch.delenv("PYTHONPATH", raising=False)
        env = bootstrap.build_env()
        assert str(bootstrap.REPO_DIR) in env["PYTHONPATH"].split(os.pathsep)

    def test_existing_pythonpath_preserved(self, monkeypatch):
        monkeypatch.setenv("PYTHONPATH", "/somewhere/else")
        env = bootstrap.build_env()
        parts = env["PYTHONPATH"].split(os.pathsep)
        assert str(bootstrap.REPO_DIR) in parts
        assert "/somewhere/else" in parts

    def test_does_not_change_cwd(self):
        """用 PYTHONPATH 而不是 chdir —— 否则调用者传的相对路径会指向别处"""
        before = os.getcwd()
        bootstrap.build_env()
        assert os.getcwd() == before


class TestMain:
    def test_no_args_prints_usage(self, capsys):
        assert bootstrap.main([]) == 2
        assert "bootstrap.py cli" in capsys.readouterr().out

    def test_unknown_target(self, capsys):
        assert bootstrap.main(["nope"]) == 2

    def test_dispatches_to_target_module(self, monkeypatch):
        recorded = {}
        monkeypatch.setattr(bootstrap, "ensure_venv", lambda: Path("py"))
        monkeypatch.setattr(bootstrap, "ensure_dependencies", lambda py, spec: None)

        def fake_run(cmd, env=None):
            recorded["cmd"] = cmd
            recorded["env"] = env
            return type("R", (), {"returncode": 7})()

        monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
        rc = bootstrap.main(["cli", "search", "a.jpg"])

        assert rc == 7
        assert recorded["cmd"][1:4] == ["-m", "imgsearch", "search"]
        assert "a.jpg" in recorded["cmd"]
        assert str(bootstrap.REPO_DIR) in recorded["env"]["PYTHONPATH"]

    def test_gui_target_uses_gui_module(self, monkeypatch):
        recorded = {}
        monkeypatch.setattr(bootstrap, "ensure_venv", lambda: Path("py"))
        monkeypatch.setattr(bootstrap, "ensure_dependencies", lambda py, spec: None)
        monkeypatch.setattr(bootstrap.subprocess, "run",
                            lambda cmd, env=None: recorded.update(cmd=cmd)
                            or type("R", (), {"returncode": 0})())
        bootstrap.main(["gui"])
        assert recorded["cmd"][1:] == ["-m", "imgsearch_gui"]


class TestLaunchers:
    """薄封装必须真的指向 bootstrap，且 batch 保持纯 ASCII"""

    def test_run_scripts_call_bootstrap(self):
        for name in ("run.sh", "run-gui.sh"):
            text = (bootstrap.REPO_DIR / name).read_text(encoding="utf-8")
            assert "bootstrap.py" in text, name

    @pytest.mark.parametrize("name", ["run.bat", "run-gui.bat", "start_gui.bat"])
    def test_batch_files_are_ascii_only(self, name):
        """
        cmd.exe 按当前代码页逐行解析批处理文件，中文在 if 块里容易出错。
        所有面向用户的消息都交给 Python 打印，batch 保持纯 ASCII。
        """
        raw = (bootstrap.REPO_DIR / name).read_bytes()
        assert all(b < 128 for b in raw), f"{name} 含非 ASCII 字节"

    def test_batch_supports_py_launcher(self):
        """Windows 上 `python` 未必在 PATH，但 `py` 通常有"""
        for name in ("run.bat", "run-gui.bat"):
            text = (bootstrap.REPO_DIR / name).read_text(encoding="ascii")
            assert "where py" in text and "py -3" in text
            assert "where python" in text

    def test_batch_has_no_bom(self):
        """UTF-8 BOM 会让 cmd 把第一行当成乱码命令"""
        for name in ("run.bat", "run-gui.bat", "start_gui.bat"):
            assert not (bootstrap.REPO_DIR / name).read_bytes().startswith(b"\xef\xbb\xbf")

    def test_start_gui_delegates_to_new_gui(self):
        """旧入口原先启动 tkinter 版，现在应转交 Qt6 版"""
        text = (bootstrap.REPO_DIR / "start_gui.bat").read_text(encoding="ascii")
        assert "run-gui.bat" in text

    def test_shell_scripts_handle_missing_python(self):
        for name in ("run.sh", "run-gui.sh"):
            text = (bootstrap.REPO_DIR / name).read_text(encoding="utf-8")
            assert "python3" in text and "找不到 Python" in text


class TestPythonVersionGuard:
    """
    解释器太旧时必须**立刻**说清楚，而不是等到装依赖失败。

    实机复现（Windows，2026-10）：机器上装着 3.9 与 3.14，但 ``py -3``
    解析到 3.9 —— `run.bat` 拿 3.9 建 venv，`pip install` 找不到轮子后
    退回源码编译，十几分钟没有输出，看起来完全像卡死。
    """

    def test_min_python_matches_pyproject(self):
        """两处声明同一件事，改一处漏一处就会自相矛盾"""
        import re

        text = (bootstrap.REPO_DIR / "pyproject.toml").read_text(encoding="utf-8")
        found = re.search(r'requires-python\s*=\s*">=\s*(\d+)\.(\d+)"', text)
        assert found, "pyproject 里找不到 requires-python"
        assert (int(found.group(1)), int(found.group(2))) == bootstrap.MIN_PYTHON

    def test_current_interpreter_passes_the_guard(self):
        """测试本身就要求 3.10+，所以这里不该判成「太旧」"""
        assert bootstrap._too_old() is False

    def test_too_old_without_alternative_exits_with_instructions(self, monkeypatch, capsys):
        monkeypatch.setattr(bootstrap, "_too_old", lambda: True)
        monkeypatch.setattr(bootstrap, "find_newer_python", lambda: None)
        monkeypatch.delenv(bootstrap._REEXEC_FLAG, raising=False)

        with pytest.raises(SystemExit) as exc:
            bootstrap.main(["cli"])

        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "3.10" in err
        assert "当前解释器" in err
        # 必须给出可照抄的命令，而不是「请升级 Python」这种空话
        assert "py -3.14" in err or "apt install" in err

    def test_too_old_with_newer_interpreter_reexecs(self, monkeypatch):
        """Windows 上能换就换：换过去重跑自己，用户什么都不用做"""
        recorded = {}

        monkeypatch.setattr(bootstrap, "_too_old", lambda: True)
        monkeypatch.setattr(bootstrap, "find_newer_python", lambda: "/fake/python3.14")
        monkeypatch.delenv(bootstrap._REEXEC_FLAG, raising=False)

        def fake_run(cmd, **kwargs):
            recorded["cmd"] = cmd
            recorded["env"] = kwargs.get("env") or {}
            return type("R", (), {"returncode": 0})()

        monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)

        with pytest.raises(SystemExit) as exc:
            bootstrap.main(["gui"])

        assert exc.value.code == 0
        assert recorded["cmd"][0] == "/fake/python3.14"
        assert recorded["cmd"][1].endswith("bootstrap.py")
        assert recorded["cmd"][2:] == ["gui"]
        # 标记必须传下去，否则新旧解释器之间会无限套娃
        assert recorded["env"][bootstrap._REEXEC_FLAG] == "1"

    def test_reexec_flag_prevents_infinite_loop(self, monkeypatch, capsys):
        monkeypatch.setattr(bootstrap, "_too_old", lambda: True)
        monkeypatch.setenv(bootstrap._REEXEC_FLAG, "1")
        # 即使还能找到一个更新的解释器，也不能再换
        monkeypatch.setattr(bootstrap, "find_newer_python", lambda: "/fake/python3.14")

        with pytest.raises(SystemExit) as exc:
            bootstrap.main(["cli"])

        assert exc.value.code == 2

    def test_no_launcher_probing_on_posix(self, monkeypatch):
        """POSIX 没有 py 启动器，不该去猜 —— 直接返回 None"""
        monkeypatch.setattr(bootstrap, "IS_WINDOWS", False)
        assert bootstrap.find_newer_python() is None
