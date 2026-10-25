"""
图库根路径管理测试

重点：嵌套拒绝、失效路径标记、重新指定位置时顺带改写记录路径。
"""

import os

import pytest

from imgsearch.library import LibraryDB, LibraryError, RootManager


@pytest.fixture
def roots(tmp_path):
    with LibraryDB(tmp_path / "lib.db") as db:
        yield RootManager(db)


@pytest.fixture
def dirs(tmp_path):
    a = tmp_path / "库A"
    b = tmp_path / "库B"
    a.mkdir()
    b.mkdir()
    return a, b


class TestAdd:
    def test_add_existing(self, roots, dirs):
        a, _ = dirs
        root = roots.add(str(a), label="库A")
        assert root.path == os.path.realpath(str(a))
        assert root.label == "库A"
        assert root.exists is True
        assert len(roots.list()) == 1

    def test_add_missing_path_is_allowed(self, roots, tmp_path):
        """允许先登记尚未挂载的外接盘，只是标记为失效"""
        ghost = tmp_path / "还没挂载的盘"
        root = roots.add(str(ghost))
        assert root.exists is False
        assert len(roots.list()) == 1
        assert len(roots.list(only_existing=True)) == 0

    def test_duplicate_rejected(self, roots, dirs):
        a, _ = dirs
        roots.add(str(a))
        with pytest.raises(LibraryError, match="已经登记过了"):
            roots.add(str(a))

    def test_empty_rejected(self, roots):
        with pytest.raises(LibraryError, match="不能为空"):
            roots.add("   ")

    def test_tilde_expanded(self, roots):
        root = roots.add("~")
        assert "~" not in root.path
        assert root.path == os.path.realpath(os.path.expanduser("~"))

    def test_trailing_slash_normalized(self, roots, dirs):
        a, _ = dirs
        roots.add(str(a) + "/")
        with pytest.raises(LibraryError, match="已经登记过了"):
            roots.add(str(a))


class TestNesting:
    """嵌套会让同一张图被两条路径覆盖，必须拒绝"""

    def test_child_inside_parent_rejected(self, roots, dirs):
        a, _ = dirs
        roots.add(str(a))
        child = a / "子目录"
        child.mkdir()
        with pytest.raises(LibraryError, match="位于已登记的根路径之内"):
            roots.add(str(child))

    def test_parent_containing_child_rejected(self, roots, dirs):
        a, _ = dirs
        child = a / "子目录"
        child.mkdir()
        roots.add(str(child))
        with pytest.raises(LibraryError, match="包含了已登记的根路径"):
            roots.add(str(a))

    def test_non_overlapping_ok(self, roots, dirs):
        a, b = dirs
        roots.add(str(a))
        roots.add(str(b))
        assert len(roots.list()) == 2

    def test_find_conflict_none_when_clean(self, roots, dirs, tmp_path):
        a, _ = dirs
        roots.add(str(a))
        assert roots.find_conflict(str(tmp_path / "别处")) is None

    def test_relocate_into_existing_rejected(self, roots, dirs):
        a, b = dirs
        r1 = roots.add(str(a))
        roots.add(str(b))
        with pytest.raises(LibraryError, match="重叠"):
            roots.relocate(r1.id, str(b / "里面"))


class TestLookup:
    def test_get_by_id_and_path(self, roots, dirs):
        a, _ = dirs
        root = roots.add(str(a))
        assert roots.get(root.id).id == root.id
        assert roots.get(str(a)).id == root.id
        assert roots.get(9999) is None

    def test_roots_containing_prefers_most_specific(self, roots, dirs):
        a, _ = dirs
        roots.add(str(a))
        deep_file = str(a / "x" / "y.jpg")
        hits = roots.roots_containing(deep_file)
        assert len(hits) == 1
        assert hits[0].path == os.path.realpath(str(a))

    def test_roots_containing_empty_outside(self, roots, dirs, tmp_path):
        a, _ = dirs
        roots.add(str(a))
        assert roots.roots_containing(str(tmp_path / "别处" / "z.jpg")) == []


class TestRemove:
    def test_remove(self, roots, dirs):
        a, _ = dirs
        root = roots.add(str(a))
        assert roots.remove(root.id) is True
        assert roots.list() == []

    def test_remove_missing(self, roots):
        assert roots.remove(9999) is False


class TestRelocate:
    def test_relocate_updates_path(self, roots, dirs, tmp_path):
        a, _ = dirs
        root = roots.add(str(a))
        moved = tmp_path / "改名后的库"
        moved.mkdir()
        roots.relocate(root.id, str(moved))
        assert roots.get(root.id).path == os.path.realpath(str(moved))

    def test_relocate_rewrites_record_paths(self, roots, dirs, tmp_path):
        """目录改名/搬走后，名下记录的绝对路径应一起改写，无需重新扫描"""
        a, _ = dirs
        root = roots.add(str(a))
        from imgsearch.library import LibraryStore

        with LibraryDB(roots.db.path) as db2:
            store = LibraryStore(db2)
            img = a / "pic.jpg"
            _write_pattern_image(img, seed=1)
            rec = store.upsert_image(str(img))
            assert rec.abs_path == os.path.realpath(str(img))

            moved = tmp_path / "搬走的库"
            moved.mkdir()
            (moved / "pic.jpg").write_bytes(img.read_bytes())

            updated = RootManager(db2).relocate(root.id, str(moved))
            assert updated == 1
            after = store.get_image(rec.id)
            assert after.abs_path == os.path.realpath(str(moved / "pic.jpg"))
            assert after.missing is False


class TestRefreshMissing:
    def test_detects_moved_file_without_deleting_record(self, roots, dirs, tmp_path):
        a, _ = dirs
        root = roots.add(str(a))
        from imgsearch.library import LibraryStore

        with LibraryDB(roots.db.path) as db2:
            store = LibraryStore(db2)
            img = a / "pic.jpg"
            _write_pattern_image(img, seed=2)
            rec = store.upsert_image(str(img))

            # 文件被移走（模拟用户的「搜完移走」工作流）
            img.rename(tmp_path / "别处.jpg")

            missing = RootManager(db2).refresh_missing(root.id)
            assert missing == 1
            after = store.get_image(rec.id)
            assert after.missing is True
            # 关键：记录没有被删掉，仍能凭 dHash 命中缓存
            assert store.get_image(rec.id) is not None
            assert store.lookup(str(tmp_path / "别处.jpg")) is not None


def _write_pattern_image(path, seed=0, size=(90, 70)):
    """生成有结构的测试图（纯色图的 dHash 全为 0，无法区分）"""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    for i in range(6):
        x = (seed * 17 + i * 13) % size[0]
        d.rectangle((x, 0, x + 6 + (seed % 7), size[1]),
                    fill=((i * 40 + seed * 11) % 256, (seed * 30) % 256, 120))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


class TestCaseInsensitivePaths:
    """
    Windows 的路径**不区分大小写**，POSIX 区分。

    之前所有路径比较都是直接的字符串比较，于是 Windows 上
    ``C:\\Images`` 与 ``c:\\images`` 会被当成两条不同路径 ——
    「重复登记」与「嵌套检测」双双失效，同一张图会被记两次。

    用显式参数开启该语义，而不是依赖 os.name，这样在 Linux 上也能验证。
    """

    def test_default_follows_platform(self, roots):
        assert roots.case_insensitive == (os.name == "nt")

    def test_duplicate_detected_across_case(self, tmp_path):
        (tmp_path / "Images").mkdir()
        if os.name != "nt":
            # POSIX 上 `Images` 与 `images` 可以并存；
            # Windows 上它们是**同一个目录**，第二句 mkdir 会抛 FileExistsError
            # —— 而那里恰好是真实场景，不需要造假目录
            (tmp_path / "images").mkdir()
        with LibraryDB(tmp_path / "ci.db") as db:
            rm = RootManager(db, case_insensitive=True)
            rm.add(str(tmp_path / "Images"))
            with pytest.raises(LibraryError, match="已经登记过了"):
                rm.add(str(tmp_path / "images"))

    def test_nesting_detected_across_case(self, tmp_path):
        (tmp_path / "Images" / "Sub").mkdir(parents=True)
        if os.name != "nt":
            (tmp_path / "images").mkdir()
        with LibraryDB(tmp_path / "ci2.db") as db:
            rm = RootManager(db, case_insensitive=True)
            rm.add(str(tmp_path / "Images"))
            with pytest.raises(LibraryError, match="位于已登记的根路径之内"):
                rm.add(str(tmp_path / "images" / "sub"))

    def test_get_finds_root_regardless_of_case(self, tmp_path):
        (tmp_path / "MixedCase").mkdir()
        with LibraryDB(tmp_path / "ci3.db") as db:
            rm = RootManager(db, case_insensitive=True)
            root = rm.add(str(tmp_path / "MixedCase"))
            assert rm.get(str(tmp_path / "MixedCase").upper()) is not None
            assert rm.get(str(tmp_path / "mixedcase")) is not None
            assert rm.get(root.id).id == root.id

    def test_roots_containing_across_case(self, tmp_path):
        (tmp_path / "Images").mkdir()
        with LibraryDB(tmp_path / "ci4.db") as db:
            rm = RootManager(db, case_insensitive=True)
            rm.add(str(tmp_path / "Images"))
            hits = rm.roots_containing(str(tmp_path / "IMAGES" / "a.png"))
            assert len(hits) == 1

    def test_posix_semantics_keep_them_distinct(self, tmp_path):
        """POSIX 下大小写不同就是两条路径，不该被误判为重复"""
        if os.name == "nt":
            pytest.skip("仅验证 POSIX 语义")
        (tmp_path / "Images").mkdir()
        (tmp_path / "images").mkdir()
        with LibraryDB(tmp_path / "cs.db") as db:
            rm = RootManager(db, case_insensitive=False)
            rm.add(str(tmp_path / "Images"))
            rm.add(str(tmp_path / "images"))   # 应当允许
            assert len(rm.list()) == 2

    def test_relocate_respects_case_semantics(self, tmp_path):
        """
        搬到「大小写不同但实为同一路径」的位置时也要拦住。

        注意要**存在另一条根路径**才构成冲突 —— 只把自己改个名不算冲突
        （自己会被 exclude 掉）。
        """
        (tmp_path / "A").mkdir()
        (tmp_path / "B").mkdir()
        if os.name != "nt":
            # Windows 上 `B` 与 `b` 是同一个目录，不需要（也不能）再建一个
            (tmp_path / "b").mkdir()
        with LibraryDB(tmp_path / "ci5.db") as db:
            rm = RootManager(db, case_insensitive=True)
            root_a = rm.add(str(tmp_path / "A"))
            rm.add(str(tmp_path / "B"))
            # 把 A 搬到 b/inside —— 按 Windows 语义这落在 B 里面
            with pytest.raises(LibraryError, match="重叠"):
                rm.relocate(root_a.id, str(tmp_path / "b" / "inside"))

    def test_path_key_helper(self):
        from imgsearch.library.paths import path_key
        assert path_key("/a/B", case_insensitive=True) == path_key("/a/b", True)
        assert path_key("/a/B", case_insensitive=False) != path_key("/a/b", False)


class TestWindowsPathSemantics:
    """
    用 ``ntpath`` 在 Linux 上验证 Windows 的路径语义。

    这个项目的另一个工具（compress）就栽在**手写反斜杠处理**上，
    所以这里把两件事都钉死：分隔符归一、跨盘符处理。
    """

    def test_mixed_separators_give_same_key(self):
        import ntpath
        from imgsearch.library.paths import path_key
        a = path_key(r"C:\Images\Sub", case_insensitive=True, path_module=ntpath)
        b = path_key("C:/Images/Sub", case_insensitive=True, path_module=ntpath)
        c = path_key(r"C:\Images/Sub" + "/", case_insensitive=True, path_module=ntpath)
        assert a == b == c == r"c:\images\sub"

    def test_forward_slashes_canonicalized_to_backslashes(self):
        import ntpath
        from imgsearch.library.paths import path_key
        assert "\\" in path_key("C:/a/b", case_insensitive=False, path_module=ntpath)

    def test_dotdot_resolved(self):
        import ntpath
        from imgsearch.library.paths import path_key
        assert path_key("C:/a/../b", case_insensitive=False,
                        path_module=ntpath) == r"C:\b"

    def test_ancestor_with_mixed_separators(self):
        import ntpath
        from imgsearch.library.paths import _is_ancestor_or_same
        assert _is_ancestor_or_same("C:/Images", r"C:\Images\Sub", True, ntpath)
        assert _is_ancestor_or_same(r"C:\Images", "C:/Images/Sub/Deep", True, ntpath)
        assert not _is_ancestor_or_same("C:/Images", "C:/Other", True, ntpath)

    def test_different_drives_are_not_ancestors(self):
        """C: 与 D: 是不同挂载点，不能当成父子关系（代码里已捕获 ValueError）"""
        import ntpath
        from imgsearch.library.paths import _is_ancestor_or_same
        assert _is_ancestor_or_same("C:/x", "D:/x/sub", False, ntpath) is False

    def test_root_manager_uses_injected_module(self, tmp_path):
        """整条链路（登记 → 冲突检测）都要走注入的语义"""
        import ntpath
        (tmp_path / "Images" / "Sub").mkdir(parents=True)
        with LibraryDB(tmp_path / "w.db") as db:
            rm = RootManager(db, case_insensitive=True, path_module=ntpath)
            key_a = rm._key(r"C:\Images")
            key_b = rm._key("C:/IMAGES")
            assert key_a == key_b

    def test_no_handwritten_separator_manipulation(self):
        """
        守住根因：文件路径的分隔符处理必须全部交给 os.path，不许手写。

        ⚠️ 只扫描真正处理**文件系统路径**的模块。
        `imgsearch/engines/` 里有对 **URL** 与 **HTML 文本** 做斜杠操作的地方
        （如 `api_url.rstrip("/")`、解析链接文本），那是另一回事，不该被误伤。
        """
        import re
        import pathlib as _pathlib

        root = _pathlib.Path(__file__).resolve().parent.parent / "imgsearch"
        targets = [root / "library", root / "config.py", root / "secrets.py",
                   root / "processor", root / "service.py"]

        suspicious = re.compile(
            r'\.split\(\s*["\'][/\\]'          # .split("/")  .split("\\")
            r'|\.replace\(\s*["\'][/\\]'       # .replace("\\", "/")
            r'|["\'][/\\]["\']\s*\+'           # "/" + ...
            r'|\+\s*["\'][/\\]["\']'           # ... + "/"
            r'|\.strip\(\s*["\'][/\\]'         # .strip("/")
        )

        hits = []
        for target in targets:
            files = target.rglob("*.py") if target.is_dir() else [target]
            for f in files:
                for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                    code = line.split("#", 1)[0]
                    if suspicious.search(code):
                        hits.append(f"{f.relative_to(root)}:{n}: {line.strip()[:72]}")
        assert not hits, (
            "发现手写的路径分隔符处理 —— 请改用 os.path / pathlib：\n  "
            + "\n  ".join(hits)
        )
