"""물성 추출 — 이슈 텍스트 → 화학식/조성/물질군 (T-111, US-B1 전처리).

전략 (정규식 우선 + LLM 보강):
1. 정규식으로 명확한 화학식(GaN, SiC, Al2O3, Si3N4 ...)을 안정적으로 추출.
2. 알려진 반도체 물질명 사전(sapphire→Al2O3 ...)으로 이름→화학식 매핑.
3. 위에서 아무것도 못 잡으면 LLM(지금은 MockLLMClient)에게 물어 보강.
4. 화학식으로부터 물질군(III-V, oxide, nitride, carbide, elemental ...)을 규칙 분류.

정규식만으로도 명확한 화학식/물질명은 안정적으로 뽑히도록 설계한다. LLM 은
모호하거나 서술형인 경우를 위한 보강 수단이며, 실제 Bedrock 연동 전에는 Mock 을 쓴다.
"""

from __future__ import annotations

import re

from matcause.core.llm.base import LLMClient, system, user
from matcause.core.models import MaterialExtraction

# ── 원소 기호 집합 (화학식 검증용) ──
_ELEMENTS = {
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca",
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr",
    "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn",
    "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
    "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
    "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    "Tl", "Pb", "Bi", "Po", "At", "Rn", "Th", "U",
}

# ── 알려진 반도체 물질명 → 화학식 사전 ──
_NAME_TO_FORMULA: dict[str, str] = {
    "sapphire": "Al2O3",
    "alumina": "Al2O3",
    "silicon carbide": "SiC",
    "silicon nitride": "Si3N4",
    "gallium nitride": "GaN",
    "gallium arsenide": "GaAs",
    "indium phosphide": "InP",
    "silicon dioxide": "SiO2",
    "silica": "SiO2",
    "quartz": "SiO2",
    "hafnium oxide": "HfO2",
    "hafnia": "HfO2",
    "titanium dioxide": "TiO2",
    "titania": "TiO2",
    "zinc oxide": "ZnO",
    "aluminum nitride": "AlN",
    "aluminium nitride": "AlN",
    "boron nitride": "BN",
    "indium gallium arsenide": "InGaAs",
    "silicon germanium": "SiGe",
    # 한글 물질명
    "사파이어": "Al2O3",
    "탄화규소": "SiC",
    "질화갈륨": "GaN",
    "질화규소": "Si3N4",
    "질화알루미늄": "AlN",
    "이산화규소": "SiO2",
    "산화하프늄": "HfO2",
    "이산화티타늄": "TiO2",
    "산화아연": "ZnO",
}

# ── 원소 단독 물질명(순수 원소 반도체) ──
_ELEMENT_NAMES: dict[str, str] = {
    "silicon": "Si",
    "실리콘": "Si",
    "규소": "Si",
    "germanium": "Ge",
    "저마늄": "Ge",
    "게르마늄": "Ge",
    "carbon": "C",
    "gallium": "Ga",
    "graphite": "C",
    "diamond": "C",
}

# 화학식 토큰: (대문자+소문자?)(숫자?) 가 2회 이상 반복. 예: GaN, Al2O3, Si3N4, HfO2
_FORMULA_TOKEN = re.compile(r"\b((?:[A-Z][a-z]?\d*){2,})\b")
# 단일 원소 단어(대문자 시작)로 오검출되는 일반 단어를 걸러내기 위한 흔한 영어 단어
_STOPWORDS = {
    "As", "In", "At", "No", "Be", "Os", "Pa",  # 원소 기호지만 영어 단어와 충돌
}


def _looks_like_formula(token: str) -> bool:
    """토큰이 원소 기호 + 숫자로만 구성된 유효 화학식인지 검사."""
    parts = re.findall(r"[A-Z][a-z]?", token)
    if len(parts) < 2:
        return False
    return all(p in _ELEMENTS for p in parts)


def _classify_group(formula: str) -> str | None:
    """화학식에서 물질군을 규칙 분류."""
    elems = set(re.findall(r"[A-Z][a-z]?", formula))
    if not elems:
        return None
    group13 = {"B", "Al", "Ga", "In"}
    group15 = {"N", "P", "As", "Sb"}
    if elems & group13 and elems & group15 and "O" not in elems:
        return "III-V"
    if "O" in elems and len(elems) >= 2:
        return "oxide"
    if "N" in elems and elems != {"N"}:
        return "nitride"
    if "C" in elems and len(elems) >= 2:
        return "carbide"
    if len(elems) == 1:
        return "elemental"
    return None


def extract_by_regex(text: str) -> MaterialExtraction:
    """정규식 + 사전 기반 추출 (LLM 불필요)."""
    formulas: list[str] = []
    names: list[str] = []
    low = text.lower()

    # 1) 물질명 사전 (화합물 → 화학식)
    for name, formula in _NAME_TO_FORMULA.items():
        if name in low:
            names.append(name)
            if formula not in formulas:
                formulas.append(formula)

    # 2) 원소 물질명
    for name, sym in _ELEMENT_NAMES.items():
        if re.search(rf"\b{name}\b", low) if name.isascii() else (name in text):
            if sym not in formulas:
                formulas.append(sym)
            names.append(name)

    # 3) 화학식 토큰 정규식
    for m in _FORMULA_TOKEN.finditer(text):
        token = m.group(1)
        if token in _STOPWORDS:
            continue
        if _looks_like_formula(token) and token not in formulas:
            formulas.append(token)

    group = _classify_group(formulas[0]) if formulas else None
    confidence = 0.9 if formulas else 0.0
    return MaterialExtraction(
        formulas=formulas,
        material_names=names,
        material_group=group,
        confidence=confidence,
        method="regex" if formulas else "none",
        rationale=(
            f"정규식/사전으로 {len(formulas)}개 화학식 추출"
            if formulas
            else "정규식으로 화학식을 찾지 못함"
        ),
    )


_LLM_SYSTEM = (
    "너는 반도체 소재 텍스트에서 화학식과 물질군을 추출하는 도우미다. "
    "제공된 텍스트에 실제로 등장하는 소재만 추출하고, 없으면 빈 배열을 반환하라."
)

_LLM_PROMPT = """\
다음 텍스트에서 소재 화학식과 물질군을 추출하라.

[텍스트]
{text}

JSON으로만 답하라:
{{"formulas": ["..."], "material_group": "III-V|oxide|nitride|carbide|elemental|null", "confidence": 0~1}}
"""


def extract_by_llm(text: str, llm: LLMClient) -> MaterialExtraction:
    """LLM 기반 추출 (지금은 MockLLMClient). 정규식이 실패했을 때 보강용."""
    messages = [system(_LLM_SYSTEM), user(_LLM_PROMPT.format(text=text))]
    try:
        data = llm.complete_json(messages)
    except Exception as exc:  # noqa: BLE001
        return MaterialExtraction(method="llm", rationale=f"LLM 추출 실패: {exc}")

    formulas = [f for f in data.get("formulas", []) if isinstance(f, str) and f.strip()]
    group = data.get("material_group")
    if group in (None, "null", ""):
        group = _classify_group(formulas[0]) if formulas else None
    try:
        conf = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    return MaterialExtraction(
        formulas=formulas,
        material_group=group,
        confidence=conf if formulas else 0.0,
        method="llm",
        rationale="LLM 보강 추출",
    )


def extract_materials(text: str, llm: LLMClient | None = None) -> MaterialExtraction:
    """이슈 텍스트에서 소재를 추출한다 (정규식 우선, 필요 시 LLM 보강).

    - 정규식이 화학식을 잡으면 그대로 사용(신뢰도 높음).
    - 못 잡고 llm 이 주어지면 LLM 으로 보강.
    - 둘 다 실패하면 빈 결과(has_result()==False).
    """
    if not text or not text.strip():
        return MaterialExtraction(method="none", rationale="빈 입력")

    regex_result = extract_by_regex(text)
    if regex_result.has_result():
        return regex_result

    if llm is not None:
        llm_result = extract_by_llm(text, llm)
        if llm_result.has_result():
            # 정규식이 못 잡고 LLM 이 잡은 경우 method 표기
            llm_result.method = "regex+llm"
            return llm_result

    return regex_result  # 빈 결과 (method="none")
