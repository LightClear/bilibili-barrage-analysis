import pytest

from src.collector import BilibiliApiError, BilibiliCollector, extract_bvid, normalize_description


class FakeResponse:
    def __init__(self, payload=None, text="", content=None, status_code=200):
        self._payload = payload or {}
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        if "popular" in url:
            return FakeResponse(
                {
                    "code": 0,
                    "data": {
                        "list": [
                            {
                                "bvid": "BV1",
                                "title": "热门视频",
                                "owner": {"name": "UP主"},
                                "desc": "热门简介",
                                "stat": {"view": 100, "danmaku": 9, "like": 8, "favorite": 7, "coin": 6},
                                "duration": 123,
                                "pic": "http://example.com/cover.jpg",
                            }
                        ]
                    },
                }
            )
        if "pagelist" in url:
            return FakeResponse({"code": 0, "data": [{"cid": 456, "page": 1, "part": "P1"}]})
        if "view" in url:
            return FakeResponse(
                {
                    "code": 0,
                    "data": {
                        "title": "详情视频",
                        "owner": {"name": "详情UP"},
                        "desc": "详情简介",
                        "stat": {"view": 200, "danmaku": 19, "like": 18, "favorite": 17, "coin": 16},
                        "duration": 321,
                        "pic": "//example.com/detail.jpg",
                    },
                }
            )
        if "comment.bilibili.com" in url:
            return FakeResponse(text="<i><d p=\"1,1,25,16777215,1716000000,0,a,1\">弹幕</d></i>")
        raise AssertionError(f"unexpected url: {url}")


def test_collector_fetches_popular_videos_and_danmaku_xml():
    session = FakeSession()
    collector = BilibiliCollector(session=session)

    videos = collector.fetch_popular_videos(limit=1)
    cid = collector.fetch_cid("BV1")
    xml = collector.fetch_danmaku_xml(cid)

    assert videos[0]["bvid"] == "BV1"
    assert videos[0]["owner"] == "UP主"
    assert videos[0]["desc"] == "热门简介"
    assert videos[0]["cover_url"] == "https://example.com/cover.jpg"
    assert videos[0]["favorite"] == 7
    assert videos[0]["coin"] == 6
    assert videos[0]["video_url"] == "https://www.bilibili.com/video/BV1"
    assert cid == 456
    assert "弹幕" in xml


def test_fetch_video_info_includes_engagement_metrics_and_cover():
    collector = BilibiliCollector(session=FakeSession())

    video = collector.fetch_video_info("BV1")

    assert video["title"] == "详情视频"
    assert video["owner"] == "详情UP"
    assert video["desc"] == "详情简介"
    assert video["like"] == 18
    assert video["favorite"] == 17
    assert video["coin"] == 16
    assert video["cover_url"] == "https://example.com/detail.jpg"


def test_normalize_description_falls_back_to_desc_v2():
    assert normalize_description({"desc_v2": [{"raw_text": "第一行"}, {"raw_text": "第二行"}]}) == "第一行\n第二行"


def test_fetch_danmaku_xml_decodes_utf8_content():
    class Utf8Session:
        def get(self, url, **kwargs):
            return FakeResponse(content="<i>中文弹幕</i>".encode("utf-8"))

    collector = BilibiliCollector(session=Utf8Session())

    assert collector.fetch_danmaku_xml(123) == "<i>中文弹幕</i>"


def test_extract_bvid_from_plain_bvid_and_video_url():
    assert extract_bvid("BV19iLv6bEKh") == "BV19iLv6bEKh"
    assert extract_bvid("https://www.bilibili.com/video/BV19iLv6bEKh/?spm_id_from=333.1007") == "BV19iLv6bEKh"


def test_extract_bvid_rejects_invalid_input():
    with pytest.raises(ValueError):
        extract_bvid("https://www.bilibili.com/")


def test_history_cookie_from_env_and_history_dates(monkeypatch):
    class HistorySession:
        def __init__(self):
            self.headers = {}
            self.last_params = None

        def get(self, url, **kwargs):
            self.last_params = kwargs.get("params")
            if "history/index" in url:
                return FakeResponse({"code": 0, "data": ["2024-01-01", "2024-01-02"]})
            if "history/seg.so" in url:
                return FakeResponse(content=b"\x00\x01")
            raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setenv("BILI_SESSDATA", "demo_sess")
    session = HistorySession()
    collector = BilibiliCollector(session=session)

    assert session.headers["Cookie"] == "SESSDATA=demo_sess"
    assert collector.has_history_auth()
    assert collector.fetch_history_dates(123, "2024-01") == ["2024-01-01", "2024-01-02"]
    assert collector.fetch_history_segment(123, "2024-01-01") == b"\x00\x01"


def test_injected_history_cookie_overrides_environment(monkeypatch):
    class HeaderSession:
        def __init__(self):
            self.headers = {}

    monkeypatch.setenv("BILI_SESSDATA", "env_sess")
    session = HeaderSession()
    collector = BilibiliCollector(session=session, history_cookie="SESSDATA=account_sess")

    assert session.headers["Cookie"] == "SESSDATA=account_sess"
    assert collector.has_history_auth()


def test_history_index_error_includes_bilibili_code(monkeypatch):
    class ErrorSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, **kwargs):
            return FakeResponse({"code": -400, "message": "请求错误"})

    monkeypatch.setenv("BILI_SESSDATA", "demo_sess")
    collector = BilibiliCollector(session=ErrorSession())

    with pytest.raises(BilibiliApiError, match="code=-400"):
        collector.fetch_history_dates(123, "2024-01")
