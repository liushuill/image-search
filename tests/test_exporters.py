"""
导出层测试

导出**不下载文件**，只输出地址；支持一次产出多种格式。
"""

import json

import pytest

from imgsearch.engines.base import SearchResult
from imgsearch.exporters import (
    ExportRecord,
    all_formats,
    format_keys,
    from_csv,
    from_library,
    from_results,
    parse_format_list,
    render_name,
    sanitize_filename,
    write_outputs,
)


def sample_record(**kw) -> ExportRecord:
    base = dict(
        file="/图库/a.png", dhash="deadbeefdeadbeef", status="success",
        engine="sauceNAO", similarity=93.28, pixiv_id="74267012", pixiv_page=1,
        artist="画师A", title="标题B", material="出处C",
        urls=["https://danbooru.donmai.us/posts/1", "https://yande.re/post/show/2"],
        highres_url="https://i.pximg.net/x.jpg", thumbnail="https://img/thumb.jpg",
        ids={"danbooru": "1", "gelbooru": "2"}, detail="备注",
        searched_at="2026-01-01 00:00:00",
    )
    base.update(kw)
    return ExportRecord(**base)


class TestRegistry:
    def test_expected_formats_registered(self):
        keys = format_keys()
        for key in ("urls", "csv", "json", "jsonl", "html", "clipboard"):
            assert key in keys, key

    def test_every_format_has_label_and_ext(self):
        for fmt in all_formats():
            assert fmt.label and (fmt.ext or fmt.virtual)

    def test_parse_single_and_multi(self):
        assert [f.key for f in parse_format_list("csv")] == ["csv"]
        assert [f.key for f in parse_format_list("urls,csv")] == ["urls", "csv"]
        assert [f.key for f in parse_format_list(" urls , csv ")] == ["urls", "csv"]

    def test_parse_all(self):
        assert len(parse_format_list("all")) == len(all_formats())

    def test_parse_unknown_lists_available(self):
        with pytest.raises(ValueError, match="未知导出格式"):
            parse_format_list("bogus")
        with pytest.raises(ValueError, match="未知导出格式"):
            parse_format_list("bogus")
        # 报错里要列出可用项，便于纠正
        try:
            parse_format_list("bogus")
        except ValueError as e:
            assert "urls" in str(e)

    def test_parse_empty_rejected(self):
        with pytest.raises(ValueError, match="没有指定"):
            parse_format_list("")


class TestRecord:
    def test_derived_fields(self):
        r = sample_record()
        assert r.pixiv_filename == "74267012_p1.jpg"
        assert r.pixiv_page_url == "https://www.pixiv.net/artworks/74267012"
        assert r.ids_text == "danbooru=1, gelboguu=2".replace("gelboguu", "gelbooru")
        assert r.title_text == "标题B / 出处C"

    def test_all_urls_puts_pixiv_first_and_dedupes(self):
        r = sample_record(urls=["https://x/1", "https://www.pixiv.net/artworks/74267012"])
        urls = r.all_urls
        assert urls[0].endswith("/artworks/74267012")     # Pixiv 作品页在前
        assert len(urls) == len(set(urls))                 # 去重
        assert "https://x/1" in urls

    def test_all_urls_without_pixiv(self):
        r = sample_record(pixiv_id="", urls=["https://x/1"])
        assert r.all_urls == ["https://x/1"]


class TestTemplate:
    def test_sanitize_removes_illegal_chars(self):
        assert "/" not in sanitize_filename("a/b")
        assert ":" not in sanitize_filename('a:b')
        # 全是非法字符 → 没有任何可用信息，给一个中性名字
        assert sanitize_filename('<>:"/\\|?*') == "untitled"

    def test_sanitize_collapses_runs(self):
        """'<>:' 不该变成 '___' 这种没意义的文件名"""
        assert sanitize_filename("a<>:b") == "a_b"

    def test_sanitize_strips_trailing_dots_and_spaces(self):
        """Windows 上结尾的点和空格会被静默丢弃"""
        assert sanitize_filename("a. ") == "a"
        assert not sanitize_filename("name.").endswith(".")

    def test_sanitize_keeps_cjk(self):
        assert sanitize_filename("画师 - 作品") == "画师 - 作品"

    def test_render_default_template(self):
        assert render_name("", sample_record()) == "74267012_p1.jpg"

    def test_render_custom_template(self):
        name = render_name("{artist} - {title} ({pixiv_id})", sample_record())
        assert name == "画师A - 标题B (74267012)"

    def test_render_sanitizes_result(self):
        name = render_name("{artist}", sample_record(artist="a/b:c"))
        assert "/" not in name and ":" not in name

    def test_unknown_placeholder_is_preserved(self):
        """静默丢字段比留个 {unknown} 更难排查"""
        assert "{nope}" in render_name("{nope}-{pixiv_id}", sample_record())

    def test_dhash_and_engine_available(self):
        name = render_name("{engine}_{dhash}", sample_record())
        assert name == "sauceNAO_deadbeefdeadbeef"


class TestUrlsFormat:
    def test_one_url_per_line(self):
        from imgsearch.exporters import urls
        text = urls.render([sample_record()])
        lines = [l for l in text.splitlines() if l]
        assert all(l.startswith("http") for l in lines)
        assert len(lines) == 3          # pixiv 作品页 + 2 条来源

    def test_empty(self):
        from imgsearch.exporters import urls
        assert urls.render([]) == ""


class TestCsvFormat:
    def test_header_and_row(self):
        import csv
        import io
        from imgsearch.exporters import tabular
        text = tabular.render([sample_record()])
        rows = list(csv.DictReader(io.StringIO(text)))
        assert len(rows) == 1
        assert rows[0]["pixiv_id"] == "74267012"
        assert rows[0]["source"] == "sauceNAO"
        assert rows[0]["danbooru_id"] == "1"

    def test_similarity_is_numeric(self):
        """旧版两个写入路径一个存数值一个存 '12.3%'，Excel 里没法排序"""
        import csv
        import io
        from imgsearch.exporters import tabular
        rows = list(csv.DictReader(io.StringIO(tabular.render([sample_record()]))))
        # 保留 2 位（SauceNAO 本身就是两位小数），且不带百分号
        assert float(rows[0]["similarity"]) == 93.28
        assert "%" not in rows[0]["similarity"]

    def test_similarity_trailing_zeros_trimmed(self):
        import csv
        import io
        from imgsearch.exporters import tabular
        rows = list(csv.DictReader(io.StringIO(
            tabular.render([sample_record(similarity=95.0)]))))
        assert rows[0]["similarity"] == "95"

    def test_old_column_names_kept(self):
        """沿用旧列名，避免既有的表格与脚本失效"""
        from imgsearch.exporters.tabular import COLUMNS
        for old in ("file", "status", "source", "similarity", "pixiv_id",
                    "pixiv_page", "pixiv_image_id", "artist", "ext_url",
                    "highres_url", "danbooru_id"):
            assert old in COLUMNS, old

    def test_extra_ids_readable(self):
        import csv
        import io
        from imgsearch.exporters import tabular
        r = sample_record(ids={"danbooru": "1", "anilist": "42"})
        rows = list(csv.DictReader(io.StringIO(tabular.render([r]))))
        assert "anilist=42" in rows[0]["extra_ids"]


class TestStructuredFormats:
    def test_json_is_array_with_nested_pixiv(self):
        from imgsearch.exporters import structured
        data = json.loads(structured.render([sample_record()]))
        assert isinstance(data, list) and len(data) == 1
        assert data[0]["pixiv"]["id"] == "74267012"
        assert data[0]["pixiv"]["filename"] == "74267012_p1.jpg"
        assert len(data[0]["urls"]) == 3

    def test_jsonl_one_object_per_line(self):
        from imgsearch.exporters import structured
        text = structured.render_jsonl([sample_record(), sample_record(dhash="x")])
        lines = [l for l in text.splitlines() if l]
        assert len(lines) == 2
        assert all(json.loads(l)["file"] for l in lines)

    def test_json_keeps_containers_not_stringified(self):
        """与 CSV 不同：结构化格式里容器保持原形，不做字符串摊平"""
        from imgsearch.exporters import structured
        data = json.loads(structured.render([sample_record()]))[0]
        assert isinstance(data["ids"], dict)
        assert isinstance(data["urls"], list)


class TestHtmlReport:
    def test_self_contained_and_has_cards(self):
        from imgsearch.exporters import html_report
        out = html_report.render([sample_record()], thumbnails="none")
        assert out.lstrip().startswith("<!DOCTYPE html>")
        assert '<article class="card"' in out
        assert "id=\"q\"" in out                    # 筛选框
        assert "<script>" in out

    def test_escapes_external_text(self):
        """画师/标题来自第三方接口，直接拼进 HTML 会破坏页面"""
        from imgsearch.exporters import html_report
        out = html_report.render(
            [sample_record(artist="<script>alert(1)</script>",
                           title='" onmouseover="evil')],
            thumbnails="none",
        )
        assert "<script>alert(1)</script>" not in out
        assert "&lt;script&gt;" in out
        assert 'onmouseover="evil' not in out

    def test_escapes_html_in_file_path(self):
        from imgsearch.exporters import html_report
        out = html_report.render([sample_record(file='/x/<b>a</b>.png')],
                                 thumbnails="none")
        assert "<b>a</b>.png" not in out

    def test_empty_records(self):
        from imgsearch.exporters import html_report
        out = html_report.render([], thumbnails="none")
        assert "没有可导出的结果" in out

    def test_thumbnails_none_omits_img(self):
        from imgsearch.exporters import html_report
        out = html_report.render([sample_record()], thumbnails="none")
        assert "<img" not in out

    def test_thumbnails_link_uses_remote_url(self):
        from imgsearch.exporters import html_report
        out = html_report.render([sample_record()], thumbnails="link")
        assert "https://img/thumb.jpg" in out


class TestWriteOutputs:
    def test_writes_multiple_formats(self, tmp_path):
        formats = parse_format_list("urls,csv,json")
        written = write_outputs(formats, [sample_record()], tmp_path, stem="s")
        names = sorted(p.name for p in written)
        assert names == ["s.csv", "s.json", "s.txt"]
        assert all(p.is_file() for p in written)

    def test_csv_has_bom_for_excel(self, tmp_path):
        written = write_outputs(parse_format_list("csv"), [sample_record()],
                                tmp_path, stem="s")
        assert written[0].read_bytes().startswith(b"\xef\xbb\xbf")

    def test_virtual_format_writes_nothing(self, tmp_path):
        # 用子目录：隔离夹具本身会在 tmp_path 里建 data/，不能假设它是空的
        out = tmp_path / "out"
        written = write_outputs(parse_format_list("clipboard"), [sample_record()],
                                out, stem="s")
        assert written == []
        assert not out.exists() or list(out.iterdir()) == []

    def test_creates_outdir(self, tmp_path):
        target = tmp_path / "深层" / "目录"
        write_outputs(parse_format_list("urls"), [sample_record()], target, stem="s")
        assert (target / "s.txt").is_file()


class TestCollectorsFromResults:
    def test_from_results(self):
        results = [SearchResult(source="sauceNAO", similarity=95.0, pixiv_id="1"),
                   SearchResult(source="iqdb", similarity=60.0)]
        records = from_results(results, file="a.jpg", dhash="abc")
        assert len(records) == 2
        assert records[0].engine == "sauceNAO" and records[0].file == "a.jpg"
        assert records[0].dhash == "abc"

    def test_ids_collected_from_result(self):
        results = [SearchResult(source="x", similarity=1, danbooru_id="7",
                                extra_ids={"anilist": "42"})]
        assert from_results(results)[0].ids == {"danbooru": "7", "anilist": "42"}


class TestPixivIdDerivation:
    """
    回归：pixiv_id 字段为空、但来源链接里带着 Pixiv ID 时不能丢。

    实测形状：SauceNAO 命中 Danbooru/Gelbooru 索引时 data 里没有 pixiv_id，
    只有旧式的 member_illust.php?...illust_id=NNN —— 而这个 ID 正是
    生成 pixiv.re / pixiv.cat 下载直链（AriaNg 批量下载）所必需的。
    """

    def test_old_style_url(self):
        r = SearchResult(source="x", similarity=1, ext_urls=[
            "https://danbooru.donmai.us/post/show/1",
            "https://www.pixiv.net/member_illust.php?mode=medium&illust_id=78794621",
        ])
        assert r.pixiv_id == "78794621"

    def test_new_style_url(self):
        r = SearchResult(source="x", similarity=1,
                         ext_urls=["https://www.pixiv.net/artworks/74267012"])
        assert r.pixiv_id == "74267012"

    def test_existing_id_not_overwritten(self):
        r = SearchResult(source="x", similarity=1, pixiv_id="999",
                         ext_urls=["https://www.pixiv.net/artworks/111"])
        assert r.pixiv_id == "999"

    def test_no_pixiv_url_leaves_it_empty(self):
        r = SearchResult(source="x", similarity=1,
                         ext_urls=["https://danbooru.donmai.us/posts/1"])
        assert r.pixiv_id is None

    def test_derivation_reaches_export(self, library, pattern_image):
        """整条链路：图库行 → 导出记录也要能补出来"""
        db, store = library
        rec = store.upsert_image(str(pattern_image("p.png", seed=1)))
        store.save_results(rec.id, [SearchResult(
            source="SauceNAO", similarity=93.3,
            ext_urls=["https://danbooru.donmai.us/post/show/1",
                      "https://www.pixiv.net/member_illust.php?illust_id=78794621"],
        )])
        records = from_library(store)
        assert len(records) == 1
        assert records[0].pixiv_id == "78794621"
        assert records[0].pixiv_filename == "78794621_p0.jpg"


class TestCollectorsFromLibrary:
    def _seed(self, store, pattern_image, image_count=2, results_each=2, seed0=0):
        recs = []
        for i in range(image_count):
            rec = store.upsert_image(str(pattern_image(f"p{i}.png", seed=seed0 + i)))
            store.save_results(rec.id, [
                SearchResult(source=f"e{j}", similarity=90.0 - j,
                             ext_urls=[f"https://site{j}.example/{i}"])
                for j in range(results_each)
            ])
            recs.append(rec)
        return recs

    def test_per_image_takes_best_and_merges_urls(self, library, pattern_image):
        """只留最高相似度那条会丢来源，所以其余结果的链接要合并进来"""
        db, store = library
        self._seed(store, pattern_image, image_count=1, results_each=3)
        records = from_library(store, per_image=True)
        assert len(records) == 1
        assert records[0].engine == "e0"                  # 相似度最高的
        assert len(records[0].urls) == 3                  # 三条来源都在
        assert records[0].from_cache is True
        assert records[0].status == "cached"

    def test_per_result_gives_one_row_each(self, library, pattern_image):
        db, store = library
        self._seed(store, pattern_image, image_count=2, results_each=2)
        assert len(from_library(store, per_image=False)) == 4

    def test_only_resolved_excludes_unsearched(self, library, pattern_image):
        db, store = library
        store.upsert_image(str(pattern_image("noresult.png", seed=77)))
        store.upsert_image(str(pattern_image("withresult.png", seed=78)))
        store.save_results(store.get_by_path(str(pattern_image("withresult.png",
                                                               seed=78))).id,
                           [SearchResult(source="x", similarity=1)])
        assert len(from_library(store, only_resolved=True)) == 1
        assert len(from_library(store, only_resolved=False)) == 2

    def test_limit(self, library, pattern_image):
        db, store = library
        self._seed(store, pattern_image, image_count=3)
        assert len(from_library(store, limit=2)) == 2

    def test_scope_by_root(self, library, pattern_image, tmp_path):
        from imgsearch.library import RootManager
        db, store = library
        a = tmp_path / "库A"
        b = tmp_path / "库B"
        a.mkdir()
        b.mkdir()
        roots = RootManager(db)
        ra = roots.add(str(a))
        rb = roots.add(str(b))
        for idx, (root, sid) in enumerate(((a, 10), (b, 20))):
            rec = store.upsert_image(str(pattern_image(root / f"p{idx}.png",
                                                       seed=sid)))
            store.save_results(rec.id, [SearchResult(source="x", similarity=1)])
        assert len(from_library(store, root_id=ra.id)) == 1
        assert len(from_library(store, root_id=rb.id)) == 1


class TestCollectorsFromCsv:
    def _write(self, tmp_path, text):
        p = tmp_path / "in.csv"
        p.write_text(text, encoding="utf-8-sig")
        return p

    def test_reads_old_column_names(self, tmp_path):
        path = self._write(tmp_path, (
            "file,status,source,similarity,pixiv_id,pixiv_page,pixiv_image_id,"
            "artist,artist_id,title,material,ext_url,highres_url,"
            "danbooru_id,gelbooru_id,twitter_id,error\n"
            "a.jpg,success,sauceNAO,95.2,74267012,1,74267012_p1.jpg,画师A,,标题B,,"
            "https://pixiv.net/artworks/74267012,https://h,1,2,3,\n"
        ))
        records = from_csv(path)
        assert len(records) == 1
        r = records[0]
        assert r.similarity == 95.2                 # 数值而非 "95.2%"
        assert r.pixiv_id == "74267012" and r.pixiv_page == 1
        assert r.artist == "画师A" and r.title == "标题B"
        assert r.ids == {"danbooru": "1", "gelbooru": "2", "twitter": "3"}

    def test_parses_percent_similarity(self, tmp_path):
        """旧版 GUI 写过 '95.2%' 这种字符串"""
        path = self._write(tmp_path, "file,similarity\na.jpg,95.2%\n")
        assert from_csv(path)[0].similarity == 95.2

    def test_missing_columns_tolerated(self, tmp_path):
        path = self._write(tmp_path, "file,pixiv_id\na.jpg,123\n")
        r = from_csv(path)[0]
        assert r.pixiv_id == "123" and r.artist == ""

    def test_custom_id_column(self, tmp_path):
        path = self._write(tmp_path, "file,myid\na.jpg,999\n")
        assert from_csv(path, id_column="myid")[0].pixiv_id == "999"

    def test_all_urls_column_split(self, tmp_path):
        path = self._write(tmp_path, "file,all_urls\na.jpg,https://x/1 | https://x/2\n")
        assert len(from_csv(path)[0].urls) == 2

    def test_empty_csv(self, tmp_path):
        path = self._write(tmp_path, "file,pixiv_id\n")
        assert from_csv(path) == []
