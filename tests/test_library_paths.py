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
