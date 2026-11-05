# -*- coding: utf-8 -*-
"""网页首屏的确定性计数（不启动浏览器、不联网依赖）。

对应方法论里的"第二档指标"：真实耗时噪音大，不适合当每一步的闸门；
请求数、阻塞脚本数、字节数这类计数同样的构建跑多少次都是同一个数，
可以进 CI 当棘轮。**它不能替代"打开到能用"的墙钟测量**——那需要真浏览器、
冷缓存和限速，本脚本不假装能测。

用法：

    python3 scripts/web_perf_probe.py --file loomrise/web.html \
        --file loomrise/customer_widget.html --out runs/perf/web-metrics.json

    python3 scripts/web_perf_probe.py --url http://127.0.0.1:8080/ --fetch-refs

只依赖标准库。`--fetch-refs` 会额外请求同源资源，跨域资源只计数不下载。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parents[1]


class PageScan(HTMLParser):
    """只做计数，不解析 DOM 树：够用、确定、没有依赖。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts = 0
        self.blocking_scripts = 0
        self.inline_script_bytes = 0
        self.stylesheets = 0
        self.external_refs: list[str] = []
        self.images = 0
        self.preloads = 0
        self._in_script = False
        self._script_attrs: dict[str, str | None] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k.lower(): v for k, v in attrs}
        if tag == "script":
            self.scripts += 1
            src = attr.get("src")
            if src:
                self.external_refs.append(src)
                # 布尔属性在 HTMLParser 里是 `(name, None)`，只能判键是否存在。
                blocking = not ("defer" in attr or "async" in attr
                                or (attr.get("type") or "").lower() == "module")
                if blocking:
                    self.blocking_scripts += 1
            else:
                self._in_script = True
                self._script_attrs = attr
            return
        if tag == "link":
            rel = (attr.get("rel") or "").lower()
            href = attr.get("href")
            if "stylesheet" in rel:
                self.stylesheets += 1
                if href:
                    self.external_refs.append(href)
            elif "preload" in rel or "modulepreload" in rel:
                self.preloads += 1
                if href:
                    self.external_refs.append(href)
            return
        if tag == "img":
            self.images += 1
            src = attr.get("src")
            if src:
                self.external_refs.append(src)

    def handle_data(self, data: str) -> None:
        if self._in_script:
            # 内联脚本按字节算，不按字符：与传输口径一致。
            self.inline_script_bytes += len(data.encode("utf-8"))

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_script = False
            self._script_attrs = {}


def origin_of(ref: str, base: str) -> str:
    return urlparse(urljoin(base, ref)).netloc or "inline"


def probe_html(html: str, base: str) -> tuple[dict, list[str]]:
    scan = PageScan()
    scan.feed(html)
    doc_bytes = len(html.encode("utf-8"))
    origins = sorted({origin_of(ref, base) for ref in scan.external_refs})
    self_host = urlparse(base).netloc
    external_origins = [o for o in origins if o not in (self_host, "inline", "")]
    metrics = {
        "doc_bytes": doc_bytes,
        "inline_script_bytes": scan.inline_script_bytes,
        "scripts": scan.scripts,
        "blocking_scripts": scan.blocking_scripts,
        "stylesheets": scan.stylesheets,
        "images": scan.images,
        "preloads": scan.preloads,
        "refs": len(scan.external_refs),
        "external_origins": len(external_origins),
        "critical_path_requests": 1 + scan.blocking_scripts + scan.stylesheets,
    }
    return metrics, scan.external_refs


def fetch(url: str, timeout: float = 10.0) -> tuple[str, int]:
    request = urllib.request.Request(url, headers={"User-Agent": "loomrise-perf-probe/1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        body = response.read()
        return body.decode(response.headers.get_content_charset() or "utf-8", errors="replace"), len(body)


def main() -> int:
    parser = argparse.ArgumentParser(description="网页首屏确定性计数")
    parser.add_argument("--file", action="append", default=[], help="本地 HTML 文件，可重复")
    parser.add_argument("--url", action="append", default=[], help="在线页面，可重复")
    parser.add_argument("--fetch-refs", action="store_true", help="额外下载同源资源以统计关键路径字节")
    parser.add_argument("--out", type=Path, default=ROOT / "runs" / "perf" / "web-metrics.json")
    args = parser.parse_args()

    if not args.file and not args.url:
        print("至少给一个 --file 或 --url。")
        return 2

    targets: list[tuple[str, str, str]] = []  # (label, html, base)
    for raw in args.file:
        path = Path(raw) if Path(raw).is_absolute() else ROOT / raw
        if not path.exists():
            print(f"跳过不存在的文件：{raw}")
            continue
        targets.append((raw, path.read_text(encoding="utf-8"), path.as_uri()))
    for url in args.url:
        try:
            html, _ = fetch(url)
        except Exception as exc:  # noqa: BLE001
            print(f"取不到 {url}：{type(exc).__name__}: {exc}")
            continue
        targets.append((url, html, url))

    if not targets:
        print("没有可分析的页面。")
        return 2

    pages: dict[str, dict] = {}
    metrics: dict[str, float] = {}
    for label, html, base in targets:
        found, refs = probe_html(html, base)
        page = {"metrics": found, "refs": refs[:40]}
        if args.fetch_refs:
            self_host = urlparse(base).netloc
            fetched_bytes = 0
            fetched = 0
            for ref in refs:
                target = urljoin(base, ref)
                if urlparse(target).netloc != self_host:
                    continue
                try:
                    _, size = fetch(target)
                except Exception:  # noqa: BLE001
                    continue
                fetched_bytes += size
                fetched += 1
            page["same_origin_bytes"] = fetched_bytes
            page["same_origin_fetched"] = fetched
            found["critical_path_bytes"] = page["metrics"]["doc_bytes"] + fetched_bytes
        pages[label] = page
        safe = label.replace("/", "_").replace(".", "_").replace(":", "_")
        for key, value in found.items():
            metrics[f"web.{safe}.{key}"] = value

    payload = {
        "generated": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "note": "确定性计数（静态扫描），不是墙钟'打开到能用'；后者需真浏览器与限速，见方法文档 §5",
        "pages": pages,
        "metrics": metrics,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("| 页面 | 文档字节 | 内联脚本 | 阻塞脚本 | 样式表 | 外域来源 | 关键路径请求 |")
    print("|---|---|---|---|---|---|---|")
    for label, page in pages.items():
        m = page["metrics"]
        print(f"| `{label}` | {m['doc_bytes']} | {m['inline_script_bytes']} | {m['blocking_scripts']} | "
              f"{m['stylesheets']} | {m['external_origins']} | {m['critical_path_requests']} |")
    print(f"\n指标 JSON → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
