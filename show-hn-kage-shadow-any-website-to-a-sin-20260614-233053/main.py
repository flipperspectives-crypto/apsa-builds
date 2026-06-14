#!/usr/bin/env python3
"""
KAGE — Shadow any website to a single offline HTML file.
Fetches URL, inlines CSS/JS/images as data URIs, produces one self-contained file.

Builds on the concept from: Show HN: Kage (github.com/tamnd/kage)
Portable Python implementation — no Node.js required.

Usage:
  python kage.py https://example.com                    # single page
  python kage.py https://example.com -o offline.html    # named output
  python kage.py https://example.com --depth 1          # follow same-domain links
"""

import argparse
import base64
import os
import re
import sys
import mimetypes
import urllib.request
import urllib.parse
import urllib.error
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

# ── Config ────────────────────────────────────────────────
USER_AGENT = "Kage/1.0 (Website Shadow Tool)"
MAX_ASSET_SIZE = 10 * 1024 * 1024  # 10MB per asset
TIMEOUT = 15


class AssetCollector(HTMLParser):
    """Parse HTML and collect all external assets that need inlining."""
    
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.base_domain = urlparse(base_url).netloc
        self.assets = {}  # url -> type
        self.transforms = []  # (start, end, url) for inlining
        
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        
        # CSS: <link rel="stylesheet" href="...">
        if tag == "link" and attrs.get("rel") == "stylesheet" and "href" in attrs:
            href = attrs["href"]
            if not href.startswith("data:"):
                url = urljoin(self.base_url, href)
                if self._should_fetch(url):
                    self.assets[url] = "css"
                
        # JS: <script src="...">
        if tag == "script" and "src" in attrs:
            src = attrs["src"]
            if not src.startswith("data:"):
                url = urljoin(self.base_url, src)
                if self._should_fetch(url):
                    self.assets[url] = "js"
                
        # Images: <img src="...">
        if tag == "img" and "src" in attrs:
            src = attrs["src"]
            if not src.startswith("data:"):
                url = urljoin(self.base_url, src)
                if self._should_fetch(url):
                    self.assets[url] = "img"
                
        # Favicon
        if tag == "link" and attrs.get("rel") and "icon" in attrs["rel"] and "href" in attrs:
            href = attrs["href"]
            if not href.startswith("data:"):
                url = urljoin(self.base_url, href)
                if self._should_fetch(url):
                    self.assets[url] = "img"
                
        # Background images in style attributes
        if "style" in attrs:
            style = attrs["style"]
            if style:
                for match in re.finditer(r'url\(["\']?([^)"\']+)["\']?\)', style):
                    img_url = match.group(1)
                    if not img_url.startswith("data:"):
                        url = urljoin(self.base_url, img_url)
                        if self._should_fetch(url):
                            self.assets[url] = "img"
    
    def _should_fetch(self, url: str) -> bool:
        """Only fetch same-domain or explicitly allowed assets."""
        parsed = urlparse(url)
        if not parsed.netloc:
            return True  # relative URL
        return parsed.netloc == self.base_domain


class Kage:
    """Main shadow engine."""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.fetched = {}  # url -> (content_type, data)
        self.errors = []
        
    def log(self, msg: str):
        if self.verbose:
            print(f"  {msg}")
    
    def fetch(self, url: str) -> tuple:
        """Fetch a URL, return (content, content_type)."""
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                content_type = resp.headers.get("Content-Type", "application/octet-stream")
                # Check size
                cl = resp.headers.get("Content-Length")
                if cl and int(cl) > MAX_ASSET_SIZE:
                    self.errors.append(f"Too large ({cl} bytes): {url}")
                    return None, None
                data = resp.read()
                if len(data) > MAX_ASSET_SIZE:
                    self.errors.append(f"Too large ({len(data)} bytes): {url}")
                    return None, None
                return data, content_type.split(";")[0].strip()
        except Exception as e:
            self.errors.append(f"Fetch failed: {url} — {e}")
            return None, None
    
    def to_data_uri(self, data: bytes, content_type: str) -> str:
        """Convert binary data to data: URI."""
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{content_type};base64,{b64}"
    
    def shadow(self, url: str, depth: int = 0) -> str:
        """Fetch URL and inline all assets. Returns self-contained HTML string."""
        print(f"🔍 Shadowing: {url}")
        
        # Fetch main page
        self.log("Fetching main page...")
        html_bytes, ct = self.fetch(url)
        if not html_bytes:
            return f"<!-- ERROR: Could not fetch {url} -->"
        
        html = html_bytes.decode("utf-8", errors="replace")
        original_html = html
        
        # Parse and collect assets
        self.log("Scanning for assets...")
        collector = AssetCollector(url)
        collector.feed(html)
        
        print(f"   Found {len(collector.assets)} assets to inline")
        
        # Fetch all assets
        asset_map = {}
        for asset_url in collector.assets:
            self.log(f"Fetching: {asset_url}")
            data, ct = self.fetch(asset_url)
            if data:
                asset_map[asset_url] = (ct, data)
        
        # Inline CSS
        css_count = 0
        for asset_url, asset_type in collector.assets.items():
            if asset_type == "css" and asset_url in asset_map:
                ct, data = asset_map[asset_url]
                css = data.decode("utf-8", errors="replace")
                replacement = f'<style>\n{css}\n</style>'
                # Replace the <link> tag
                pattern = re.compile(
                    re.escape(f'<link') + r'[^>]*' + re.escape(f'href="{asset_url}"') + r'[^>]*>',
                    re.IGNORECASE
                )
                html = pattern.sub(replacement, html)
                # Also try with single quotes
                pattern2 = re.compile(
                    re.escape(f'<link') + r'[^>]*' + re.escape(f"href='{asset_url}'") + r'[^>]*>',
                    re.IGNORECASE
                )
                html = pattern2.sub(replacement, html)
                css_count += 1
        
        self.log(f"Inlined {css_count} CSS files")
        
        # Inline JS
        js_count = 0
        for asset_url, asset_type in collector.assets.items():
            if asset_type == "js" and asset_url in asset_map:
                ct, data = asset_map[asset_url]
                js = data.decode("utf-8", errors="replace")
                replacement = f'<script>\n{js}\n</script>'
                pattern = re.compile(
                    re.escape(f'<script') + r'[^>]*' + re.escape(f'src="{asset_url}"') + r'[^>]*>\s*</script>',
                    re.IGNORECASE
                )
                html = pattern.sub(replacement, html)
                pattern2 = re.compile(
                    re.escape(f'<script') + r'[^>]*' + re.escape(f"src='{asset_url}'") + r'[^>]*>\s*</script>',
                    re.IGNORECASE
                )
                html = pattern2.sub(replacement, html)
                js_count += 1
        
        self.log(f"Inlined {js_count} JS files")
        
        # Inline images
        img_count = 0
        for asset_url, asset_type in collector.assets.items():
            if asset_type == "img" and asset_url in asset_map:
                ct, data = asset_map[asset_url]
                data_uri = self.to_data_uri(data, ct)
                # Replace src attribute
                html = html.replace(f'src="{asset_url}"', f'src="{data_uri}"')
                html = html.replace(f"src='{asset_url}'", f"src='{data_uri}'")
                # Also handle url() in CSS/styles
                html = html.replace(f'url("{asset_url}")', f'url("{data_uri}")')
                html = html.replace(f"url('{asset_url}')", f"url('{data_uri}')")
                html = html.replace(f"url({asset_url})", f"url({data_uri})")
                img_count += 1
        
        self.log(f"Inlined {img_count} images")
        
        # Add Kage metadata comment
        from datetime import datetime
        meta = f"""
<!--
  ⚡ Shadowed by KAGE
  Source: {url}
  Date: {datetime.now().isoformat()}
  Assets inlined: {len(asset_map)} (CSS: {css_count}, JS: {js_count}, Images: {img_count})
  Errors: {len(self.errors)}
-->
"""
        html = html.replace("</head>", f"{meta}\n</head>", 1)
        if "</head>" not in html:
            html = meta + html
        
        # Report errors
        if self.errors:
            error_comment = "\n".join(f"  <!-- ERR: {e} -->" for e in self.errors)
            html = html.replace("</body>", f"{error_comment}\n</body>", 1)
        
        # Calculate stats
        orig_size = len(original_html.encode())
        new_size = len(html.encode())
        ratio = (new_size / orig_size) if orig_size > 0 else 1
        
        print(f"\n✅ Shadow complete:")
        print(f"   {css_count} CSS, {js_count} JS, {img_count} images inlined")
        print(f"   {orig_size:,} → {new_size:,} bytes ({ratio:.1f}x)")
        if self.errors:
            print(f"   ⚠ {len(self.errors)} errors (see HTML comments)")
        
        return html


def main():
    parser = argparse.ArgumentParser(
        description="KAGE — Shadow any website to a single offline HTML file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python kage.py https://example.com
  python kage.py https://example.com -o offline.html
  python kage.py https://example.com --depth 1 --verbose
        """
    )
    parser.add_argument("url", help="URL to shadow")
    parser.add_argument("-o", "--output", help="Output file (default: auto-generated name)")
    parser.add_argument("--depth", type=int, default=0, help="Follow same-domain links (0 = single page)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()
    
    kage = Kage(verbose=args.verbose)
    html = kage.shadow(args.url, depth=args.depth)
    
    # Determine output filename
    if args.output:
        outpath = Path(args.output)
    else:
        domain = urlparse(args.url).netloc.replace(":", "_").replace(".", "_")
        outpath = Path(f"{domain}_shadow.html")
    
    outpath.write_text(html, encoding="utf-8")
    print(f"\n📄 Saved: {outpath.resolve()}")
    print(f"   Open this file in any browser — works fully offline.")


if __name__ == "__main__":
    main()
