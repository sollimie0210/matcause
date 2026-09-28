"""리포트 PDF 내보내기 (순수 파이썬, 외부 바이너리 불필요).

xhtml2pdf(reportlab 기반)를 사용해 리포트 markdown 을 PDF 바이트로 변환한다.
Windows 에서 별도 설치 없이 동작한다. xhtml2pdf import 는 지연 로딩한다.

한글 폰트: xhtml2pdf 는 CJK 폰트를 내장하지 않아 기본 폰트로는 한글이 깨진다.
이를 위해 프로젝트에 포함한 Noto Sans KR(OFL 라이선스, 재배포 가능) TTF 를
@font-face 로 등록하고 전체 요소에 적용한다. 시스템 폰트 경로에 의존하지 않아
다른 PC(팀원/발표 노트북)에서도 동일하게 렌더된다.

폰트 경로: 기본은 리포지토리 루트의 assets/fonts. 환경변수 MATCAUSE_FONT_DIR 로 재정의 가능.

간단한 markdown(제목 #/##, **굵게**, - 목록, 숫자 목록, --- 구분선)만 지원한다.
"""

from __future__ import annotations

import html
import io
import os
import re
from pathlib import Path

_REGULAR = "NotoSansKR-Regular.ttf"
_BOLD = "NotoSansKR-Bold.ttf"


def _font_dir() -> Path:
    """폰트 디렉토리 경로. 환경변수 우선, 없으면 리포지토리 루트/assets/fonts.

    이 파일: src/matcause/core/report_pdf.py → 리포지토리 루트는 parents[3].
    """
    env = os.environ.get("MATCAUSE_FONT_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "assets" / "fonts"


def _font_available() -> bool:
    d = _font_dir()
    return (d / _REGULAR).exists() and (d / _BOLD).exists()


def _as_uri(path: Path) -> str:
    """로컬 파일 경로를 file:// URI 로 (공백/한글 경로 안전)."""
    return path.resolve().as_uri()


def _build_css(with_korean_font: bool) -> str:
    if with_korean_font:
        d = _font_dir()
        reg = _as_uri(d / _REGULAR)
        bold = _as_uri(d / _BOLD)
        font_face = f"""
@font-face {{ font-family: 'NotoSansKR'; src: url('{reg}'); font-weight: normal; }}
@font-face {{ font-family: 'NotoSansKR'; src: url('{bold}'); font-weight: bold; }}
"""
        family = "'NotoSansKR', sans-serif"
    else:
        # 폰트 미포함 환경 폴백(한글 깨질 수 있음) — 시스템 폰트 시도
        font_face = ""
        family = "'Malgun Gothic', sans-serif"

    return f"""
{font_face}
@page {{ size: A4; margin: 2cm; }}
* {{ font-family: {family}; }}
body {{ font-family: {family}; font-size: 11px; color: #222; line-height: 1.5; }}
h1 {{ font-family: {family}; font-size: 20px; border-bottom: 2px solid #2a5; padding-bottom: 6px; }}
h2 {{ font-family: {family}; font-size: 15px; color: #2a5; margin-top: 16px; }}
h3 {{ font-family: {family}; font-size: 13px; margin-top: 12px; }}
p, li, td {{ font-family: {family}; }}
ul {{ margin: 4px 0 8px 0; }}
li {{ margin: 2px 0; }}
hr {{ border: none; border-top: 1px solid #ccc; margin: 12px 0; }}
.footnote {{ color: #666; font-style: italic; font-size: 10px; }}
strong {{ font-family: {family}; font-weight: bold; color: #000; }}
.mc-chart {{ margin: 10px 0 14px 0; text-align: left; }}
.mc-chart img {{ max-width: 100%; border: 1px solid #E4E9F2; border-radius: 6px; padding: 6px; }}
"""


def markdown_to_html(md: str, title: str = "MatCause Report") -> str:
    """리포트 markdown → 최소 HTML (xhtml2pdf 용). 한글 폰트 @font-face 포함."""
    out: list[str] = []
    in_ul = False

    def close_ul():
        nonlocal in_ul
        if in_ul:
            out.append("</ul>")
            in_ul = False

    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            close_ul()
            continue
        if re.match(r"^---+$", line.strip()):
            close_ul()
            out.append("<hr/>")
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            close_ul()
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            continue
        m = re.match(r"^!\[(.*?)\]\((.*?)\)$", line.strip())
        if m:
            close_ul()
            alt, src = m.group(1), m.group(2)
            out.append(f'<div class="mc-chart"><img src="{html.escape(src, quote=True)}" alt="{html.escape(alt)}"/></div>')
            continue
        m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", line)
        if m:
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline(m.group(3))}</li>")
            continue
        close_ul()
        cls = ' class="footnote"' if line.strip().startswith("*") else ""
        out.append(f"<p{cls}>{_inline(line)}</p>")

    close_ul()
    body = "\n".join(out)
    css = _build_css(with_korean_font=_font_available())
    return (
        f"<html><head><meta charset='utf-8'/><style>{css}</style>"
        f"<title>{html.escape(title)}</title></head><body>{body}</body></html>"
    )


def _inline(text: str) -> str:
    escaped = html.escape(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)


def _link_callback(uri: str, rel):
    """xhtml2pdf 가 url(...) 리소스를 로컬 파일로 해석하도록 매핑.

    file:// URI 및 폰트 파일명을 assets/fonts 의 실제 경로로 변환한다.
    """
    # data: URI(임베드된 차트 이미지)는 그대로 xhtml2pdf 내부 로더에 맡긴다.
    if uri.startswith("data:"):
        return uri
    # file:// URI 처리
    if uri.startswith("file:"):
        from urllib.parse import unquote, urlparse

        p = urlparse(uri)
        local = unquote(p.path)
        # Windows: /C:/... → C:/...
        if re.match(r"^/[A-Za-z]:", local):
            local = local[1:]
        if os.path.exists(local):
            return local
    # 폰트 파일명 직접 참조 시
    base = os.path.basename(uri)
    cand = _font_dir() / base
    if cand.exists():
        return str(cand)
    return uri


def report_to_pdf_bytes(markdown: str, title: str = "MatCause Report") -> bytes:
    """리포트 markdown → PDF 바이트. 한글 폰트 등록 포함. xhtml2pdf 미설치 시 에러."""
    try:
        from xhtml2pdf import pisa  # 지연 import
    except ImportError as exc:  # noqa: BLE001
        raise RuntimeError(
            "PDF 내보내기에는 xhtml2pdf 가 필요합니다. `pip install xhtml2pdf`"
        ) from exc

    html_doc = markdown_to_html(markdown, title=title)
    buf = io.BytesIO()
    result = pisa.CreatePDF(
        src=html_doc, dest=buf, encoding="utf-8", link_callback=_link_callback
    )
    if result.err:
        raise RuntimeError(f"PDF 생성 실패(에러 {result.err})")
    return buf.getvalue()
