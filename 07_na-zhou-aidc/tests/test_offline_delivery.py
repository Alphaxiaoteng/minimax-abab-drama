"""离线交付自检 —— 评委纯断网沙盒保障。

全部断言只用 Python 标准库（不依赖 fastapi / uvicorn / 浏览器），
保证 ``uv run --python 3.12 --with-requirements requirements.txt pytest tests/``
在零网络环境下可执行：

1. ECharts 已本地化到 src/web/echarts.min.js，且与官方 npm 发行件逐字节同哈希；
2. index.html / app.js / style.css 不含任何 http(s) 外部资源引用；
3. 用标准库 http.server 起本地静态服务，所有被引用资源均返回 200；
4. 关键 DOM 挂载点 #rack-grid / #pue-gauge / .island-banner 存在于页面，
   且 app.js 中有对应的挂载/渲染逻辑。
"""
from __future__ import annotations

import hashlib
import http.server
import re
import threading
import urllib.request
from pathlib import Path

import pytest

WEB_DIR = Path(__file__).resolve().parents[1] / "src" / "web"
ECHARTS_PATH = WEB_DIR / "echarts.min.js"

# echarts-5.5.1 npm 官方 tarball 中 package/dist/echarts.min.js 的 SHA-256
ECHARTS_SHA256 = "e84270bd0cd5bdf60fefc26d00c2a391cb2e81f4d26a7a9ee16185a54773a3cf"

APP_FILES = ["index.html", "app.js", "style.css"]


def _read(name: str) -> str:
    return (WEB_DIR / name).read_text(encoding="utf-8")


def _local_refs(html: str) -> list:
    """index.html 中 src/href 引用的本地资源（相对路径）。"""
    refs = re.findall(r'(?:src|href)="([^"]+)"', html)
    return [r for r in refs if not r.startswith(("#", "mailto:"))]


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):  # 测试静音
        pass


@pytest.fixture(scope="module")
def static_server():
    """标准库静态服务器，仅服务 src/web/ —— 模拟评委本地打开看板。"""
    handler = lambda *a, **k: _QuietHandler(*a, directory=str(WEB_DIR), **k)  # noqa: E731
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield "http://127.0.0.1:{}".format(srv.server_address[1])
    srv.shutdown()


class TestEchartsLocalized:
    def test_echarts_file_exists_and_is_full_build(self):
        assert ECHARTS_PATH.is_file(), "src/web/echarts.min.js 缺失，断网环境无法渲染图表"
        assert ECHARTS_PATH.stat().st_size > 900_000, "echarts.min.js 疑似不完整"

    def test_echarts_matches_official_release(self):
        digest = hashlib.sha256(ECHARTS_PATH.read_bytes()).hexdigest()
        assert digest == ECHARTS_SHA256, "echarts.min.js 与官方 5.5.1 发行件不一致"

    def test_index_uses_relative_echarts(self):
        html = _read("index.html")
        assert 'src="echarts.min.js"' in html
        assert "jsdelivr" not in html and "unpkg" not in html and "cdn." not in html


class TestNoExternalUrls:
    @pytest.mark.parametrize("name", APP_FILES)
    def test_no_http_references(self, name):
        text = _read(name)
        bad = re.findall(r'https?://\S+', text)
        # style.css 的 url() 与 html/js 的 src/href 均不允许外部域
        assert not bad, "{} 含外部 URL: {}".format(name, bad[:3])

    @pytest.mark.parametrize("name", APP_FILES)
    def test_no_protocol_relative_or_css_remote_url(self, name):
        text = _read(name)
        assert not re.findall(r'(?:src|href)="//', text)
        assert not re.findall(r'url\(\s*["\']?https?:', text)


class TestLocalAssetsServe200:
    def test_all_referenced_assets_are_local_200(self, static_server):
        refs = _local_refs(_read("index.html"))
        assert refs, "index.html 应引用 app.js / style.css / echarts.min.js"
        for ref in refs:
            assert not ref.startswith(("http:", "https:", "//"))
            with urllib.request.urlopen(static_server + "/" + ref, timeout=5) as resp:
                assert resp.status == 200, "{} 未能本地 200".format(ref)
                _ = resp.read()

    def test_index_page_itself_is_200(self, static_server):
        with urllib.request.urlopen(static_server + "/", timeout=5) as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8")
        assert "初焰·钠宙" in body


class TestKeyDomMounted:
    def test_rack_grid_mount_point(self):
        html = _read("index.html")
        assert 'id="rack-grid"' in html, "32 机柜热力网格挂载点缺失"
        assert "rack-grid" in _read("app.js"), "app.js 未挂载 rack-grid 渲染逻辑"

    def test_pue_gauge_mount_point(self):
        html = _read("index.html")
        assert 'id="pue-gauge"' in html, "PUE 仪表盘挂载点缺失"
        assert "pue-gauge" in _read("app.js")

    def test_island_banner_mount_point(self):
        html = _read("index.html")
        assert "island-banner" in html, "Island 模式横幅缺失"
        js = _read("app.js")
        assert "island-hint" in js, "app.js 未驱动 island-banner 状态"

    def test_rack_count_is_32_in_backend_layout(self):
        """后端机柜权重模板必须是 32 格（4 排 × 8 列），与热力网格一致。"""
        src = (WEB_DIR.parent / "server.py").read_text(encoding="utf-8")
        body = re.search(r"_RACK_WEIGHTS\s*=\s*\[(.*?)\]", src, re.S).group(1)
        weights = [w for w in re.split(r"[,\s]+", body.strip()) if w]
        assert len(weights) == 32
