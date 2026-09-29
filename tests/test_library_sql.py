"""
library sql 测试

目标：不懂 SQL 的人也能安全地看数据（--tables / --schema / 速查），
懂 SQL 的人能直接查（默认只读，防手滑改坏）。
"""

import argparse

import pytest

from imgsearch.engines.base import SearchResult
from imgsearch.library.cli import _cmd_sql, _display_width, run



def make_args(**kw) -> argparse.Namespace:
    base = dict(action="sql", target=None, write=False, tables=False,
                schema=False, db=None, extra=None, label="", purge=None,
                results=False, thumbs=False, images=False, orphans=False,
                yes=True)
    base.update(kw)
    return argparse.Namespace(**base)


@pytest.fixture
def seeded(library, pattern_image):
    db, store = library
    for i in range(3):
        rec = store.upsert_image(str(pattern_image(f"p{i}.png", seed=400 + i)))
        store.save_results(rec.id, [SearchResult(
            source="sauceNAO", similarity=90.0 + i,
            pixiv_id=str(5000 + i), artist=f"画师{i}",
        )])
    return db, store


class TestDisplayWidth:
    def test_ascii(self):
        assert _display_width("abc") == 3

    def test_cjk_counts_double(self):
        """中文/日文是全角，按 2 列算 —— 否则表格会错位"""
        assert _display_width("表") == 2
        assert _display_width("画师") == 4
        assert _display_width("アルデヒド") == 10
        assert _display_width("a表b") == 4


class TestTablesListing:
    def test_lists_tables_with_counts(self, seeded, capsys):
        db, store = seeded
        _cmd_sql(make_args(tables=True), store, db)
        out = capsys.readouterr().out
        for name in ("images", "results", "roots", "meta"):
            assert name in out
        assert "3" in out                      # 3 张图

    def test_gives_next_step_hint(self, seeded, capsys):
        db, store = seeded
        _cmd_sql(make_args(tables=True), store, db)
        assert "--schema" in capsys.readouterr().out


class TestSchemaListing:
    def test_shows_columns(self, seeded, capsys):
        db, store = seeded
        _cmd_sql(make_args(schema=True, target="images"), store, db)
        out = capsys.readouterr().out
        assert "dhash" in out and "root_id" in out and "missing" in out

    def test_shows_all_tables_when_no_target(self, seeded, capsys):
        db, store = seeded
        _cmd_sql(make_args(schema=True), store, db)
        out = capsys.readouterr().out
        assert "images" in out and "results" in out and "roots" in out

    def test_unknown_table_explains(self, seeded, capsys):
        db, store = seeded
        _cmd_sql(make_args(schema=True, target="nope"), store, db)
        assert "没有这张表" in capsys.readouterr().out


class TestCheatsheet:
    def test_no_args_prints_cheatsheet(self, seeded, capsys):
        db, store = seeded
        _cmd_sql(make_args(), store, db)
        out = capsys.readouterr().out
        assert "可用表" in out
        assert "imgsearch library sql" in out
        # 面向不熟 SQL 的人：给出可直接照抄的示例
        assert "SELECT" in out


class TestQueries:
    def test_select_returns_rows(self, seeded, capsys):
        db, store = seeded
        _cmd_sql(make_args(target="SELECT COUNT(*) AS n FROM images"), store, db)
        assert "3" in capsys.readouterr().out

    def test_join_works(self, seeded, capsys):
        db, store = seeded
        _cmd_sql(make_args(
            target="SELECT i.dhash, r.artist FROM images i"
                   " JOIN results r ON r.image_id = i.id ORDER BY r.similarity DESC"
        ), store, db)
        out = capsys.readouterr().out
        assert "画师2" in out

    def test_cjk_columns_align(self, seeded, capsys):
        db, store = seeded
        _cmd_sql(make_args(
            target="SELECT engine AS 引擎, artist AS 画师 FROM results LIMIT 2"
        ), store, db)
        lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
        # 表头分隔线与数据行的起始列应一致
        sep = next(l for l in lines if set(l.strip()) <= {"-", " "})
        assert sep.startswith("  ")

    def test_empty_result_says_zero(self, seeded, capsys):
        db, store = seeded
        _cmd_sql(make_args(target="SELECT * FROM images WHERE id = -1"), store, db)
        assert "0 行" in capsys.readouterr().out

    def test_non_query_statement_reports(self, seeded, capsys):
        db, store = seeded
        _cmd_sql(make_args(target="PRAGMA user_version"), store, db)
        assert capsys.readouterr().out.strip() != ""

    def test_bad_sql_reports_clearly(self, seeded, capsys):
        db, store = seeded
        with pytest.raises(SystemExit):
            _cmd_sql(make_args(target="SELECT * FROM no_such_table"), store, db)
        assert "SQL 执行失败" in capsys.readouterr().out


class TestReadOnlyByDefault:
    """
    默认只读 —— 目的是「防手滑」，不是安全边界。
    真正的护栏是两道：语句筛查 + PRAGMA query_only。
    """

    @pytest.mark.parametrize("statement", [
        "DELETE FROM results",
        "DROP TABLE results",
        "UPDATE images SET missing = 1",
        "INSERT INTO roots(path, added_at) VALUES('x','y')",
        "  delete from results",              # 前导空白也要拦住
    ])
    def test_write_statements_rejected(self, seeded, capsys, statement):
        db, store = seeded
        before = store.count_results()
        with pytest.raises(SystemExit):
            _cmd_sql(make_args(target=statement), store, db)
        assert "默认只读" in capsys.readouterr().out
        assert store.count_results() == before, "数据被改了"

    def test_data_intact_after_rejection(self, seeded):
        db, store = seeded
        with pytest.raises(SystemExit):
            _cmd_sql(make_args(target="DELETE FROM results"), store, db)
        assert store.count_results() == 3

    def test_read_statements_allowed(self, seeded, capsys):
        db, store = seeded
        for stmt in ("SELECT 1 AS a",
                     "WITH x AS (SELECT 1 AS a) SELECT a FROM x",
                     "PRAGMA user_version"):
            _cmd_sql(make_args(target=stmt), store, db)
        assert capsys.readouterr().out

    def test_write_flag_allows_modification(self, seeded, capsys):
        db, store = seeded
        _cmd_sql(make_args(target="DELETE FROM results WHERE similarity > 1000",
                           write=True), store, db)
        # 没有匹配行，但确实执行了
        assert "已执行" in capsys.readouterr().out

    def test_write_flag_actually_writes(self, seeded, capsys):
        db, store = seeded
        _cmd_sql(make_args(target="UPDATE images SET missing = 1", write=True),
                 store, db)
        assert "已执行" in capsys.readouterr().out
        assert store.count_images(only_missing=True) == 3

    def test_query_only_is_set_in_readonly_mode(self, seeded):
        db, store = seeded
        _cmd_sql(make_args(target="SELECT 1"), store, db)
        assert db.scalar("PRAGMA query_only") == 1


class TestMultiStatement:
    def test_rejected_when_readonly(self, seeded, capsys):
        db, store = seeded
        with pytest.raises(SystemExit):
            _cmd_sql(make_args(target="SELECT 1; SELECT 2"), store, db)
        assert "单条语句" in capsys.readouterr().out

    def test_allowed_with_write(self, seeded, capsys):
        db, store = seeded
        _cmd_sql(make_args(target="UPDATE images SET missing=0; UPDATE images SET missing=0",
                           write=True), store, db)
        assert "已执行" in capsys.readouterr().out


class TestDispatch:
    def test_run_dispatches_sql(self, seeded, capsys):
        db, store = seeded
        run(make_args(tables=True), store, db)
        assert "images" in capsys.readouterr().out


class TestPragmaTuning:
    """WAL 下 synchronous=NORMAL 是推荐设置，写入快很多"""

    def test_synchronous_is_normal(self, library):
        db, store = library
        assert db.scalar("PRAGMA synchronous") == 1

    def test_busy_timeout_is_set(self, library):
        db, store = library
        assert db.scalar("PRAGMA busy_timeout") == 10000

    def test_wal_still_enabled(self, library):
        db, store = library
        assert str(db.scalar("PRAGMA journal_mode")).lower() == "wal"

    def test_cache_enlarged(self, library):
        db, store = library
        assert db.scalar("PRAGMA cache_size") == -16000
