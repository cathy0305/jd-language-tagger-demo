"""로컬 데모 — 구글 시트·Slack·API 키 없이 예시 CSV로 분류 흐름을 보여준다.

    python demo_local.py                 # 규칙 기반 목업 분류 (표준 라이브러리만)
    python demo_local.py --live          # .env 에 preset API 키가 있으면 실제 LLM 호출

운영 버전과 같은 원칙을 따른다.
- 이미 채워진 행은 건너뛰고, 에러 마커가 적힌 행만 다시 처리한다.
- 확신할 수 없는 공고는 추측하지 않고 'gray'(사람 확인 필요)로 남긴다.
결과는 demo/output.csv 에 저장된다.
"""

from __future__ import annotations

import asyncio
import csv
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "demo" / "sample_jobs.csv"
OUT = ROOT / "demo" / "output.csv"
ERROR_MARKERS = ("HTTP", "TIMEOUT", "PARSE_ERROR", "EXCEPTION", "RESP_ERR", "UNKNOWN")

# 목업 분류 규칙 — 실제 운영에서는 LLM preset 이 이 판단을 한다 (prompt_example.md 참고)
PATTERNS = {
    "en": r"\benglish\b|영어(?!권)|英語",
    "ja": r"\bjapanese\b|일본어|日本語",
    "zh": r"\bchinese\b|중국어|中国語|中文",
}
AMBIGUOUS = r"영어권 거주|해외 문서|global mindset"


def mock_classify(position: str, jd: str) -> dict:
    text = f"{position}\n{jd}".lower()
    langs = [code for code, pat in PATTERNS.items() if re.search(pat, text, re.I)]
    if re.search(AMBIGUOUS, text, re.I) and not langs:
        return {"language": "", "status": "gray"}
    if re.search(AMBIGUOUS, text, re.I):
        # 명시된 언어는 채우되, 해석이 필요한 표현이 섞이면 사람 확인으로 넘긴다
        return {"language": ", ".join(langs), "status": "gray"}
    if not langs:
        return {"language": "", "status": "x"}
    return {"language": ", ".join(langs), "status": "ok"}


async def live_classify(rows):
    import aiohttp
    from classifier import Classifier

    clf = Classifier(
        api_key=os.environ["ENNOIA_API_KEY"],
        project=os.environ["ENNOIA_PROJECT"],
        preset_hash=os.environ["PRESET_HASH"],
        max_concurrent=int(os.environ.get("MAX_CONCURRENT", "20")),
    )
    sem = asyncio.Semaphore(clf.max_concurrent)
    async with aiohttp.ClientSession() as s:
        return await asyncio.gather(*(clf.classify_one(s, r["position"], r["jd"], sem) for r in rows))


def main() -> None:
    live = "--live" in sys.argv
    with SRC.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    todo = [r for r in rows if r["jd"] and (not r["Language"].strip()
            or r["Language"].startswith(ERROR_MARKERS))]
    print(f"[모드] {'LLM 실호출' if live else '규칙 기반 목업'} · 대상 {len(todo)}건 / 전체 {len(rows)}건\n")

    if live:
        results = asyncio.run(live_classify(todo))
    else:
        results = [(mock_classify(r["position"], r["jd"]), None) for r in todo]

    counts = {"ok": 0, "gray": 0, "x": 0, "error": 0}
    for r, (res, err) in zip(todo, results):
        if err:
            r["Language"] = err.split(":")[0]
            counts["error"] += 1
            continue
        status = res.get("status", "ok")
        r["Language"] = "X" if status == "x" else (res.get("language") or "")
        counts[status] = counts.get(status, 0) + 1
        mark = {"ok": "  ", "gray": "👀", "x": "– "}.get(status, "  ")
        print(f"{mark} {r['position']:<28} → {r['Language'] or '(사람 확인 필요)'}")

    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["position", "jd", "Language"])
        w.writeheader()
        w.writerows(rows)

    print(f"\n완료 — 분류 {counts['ok']}건 · 사람 확인 {counts['gray']}건 · 언어 없음 {counts['x']}건 · 에러 {counts['error']}건")
    print(f"결과 파일: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
