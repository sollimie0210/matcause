"""PDF 한글 폰트 렌더 검증.

한글이 포함된 리포트를 PDF 로 만들고, (1) 유효한 PDF 인지, (2) 폰트가 실제로
임베드됐는지, (3) 추출 텍스트에 한글이 포함되는지 확인한다. 검은 네모(tofu)면
폰트 임베드/등록이 실패한 것이므로 이 검사로 걸러낸다.
"""

from __future__ import annotations

import io
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from matcause.core.report_pdf import _font_available, report_to_pdf_bytes

SAMPLE = """# 결함 원인 분석 리포트 (고객사 제출용)

## 판정 원인
GaAs 기반 파워 소자는 밴드갭이 좁아 응용 적합성이 낮습니다.

## 권장 조치
- 와이드 밴드갭 소재(AlN 등) 검토
- **대체 소재** 적용 타당성 평가

*상세 근거는 별첨을 참고하십시오.*
"""


def main() -> int:
    print(f"폰트 포함 여부(_font_available): {_font_available()}")
    pdf = report_to_pdf_bytes(SAMPLE, title="한글 렌더 테스트")
    print(f"PDF 크기: {len(pdf)} bytes, 헤더 OK: {pdf[:5] == b'%PDF-'}")

    # 임베드 폰트명 확인
    try:
        blob = pdf.decode("latin-1", errors="ignore")
    except Exception:  # noqa: BLE001
        blob = ""
    print(f"NotoSansKR 임베드 흔적: {'NotoSansKR' in blob or 'Noto' in blob}")

    # 텍스트 추출로 한글 확인
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(pdf))
        text = "".join(page.extract_text() or "" for page in reader.pages)
        has_hangul = any("\uac00" <= ch <= "\ud7a3" for ch in text)
        print(f"추출 텍스트 길이: {len(text)}")
        print(f"한글 포함(추출): {has_hangul}")
        sample = "".join(ch for ch in text if ("\uac00" <= ch <= "\ud7a3"))[:20]
        print(f"추출된 한글 샘플: {sample}")
    except Exception as exc:  # noqa: BLE001
        print(f"텍스트 추출 실패: {exc}")

    # 데모 결과물을 파일로도 저장
    with open("font_check_output.pdf", "wb") as f:
        f.write(pdf)
    print("→ font_check_output.pdf 저장")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
