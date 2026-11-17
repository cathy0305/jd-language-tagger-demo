"""
Ennoia API 호출 + Google Sheets 처리 (async)
"""
import asyncio
import json
import re
import logging
from typing import Optional, Callable

import aiohttp
import gspread
from google.oauth2.service_account import Credentials

log = logging.getLogger("classifier")

ENNOIA_ENDPOINT = "https://api.ennoia.so/api/preset/v2/chat/completions"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


def init_gspread(creds_path: str):
    """Google Sheets API client 초기화."""
    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return gspread.authorize(creds)


class Classifier:
    def __init__(self, api_key: str, project: str, preset_hash: str, max_concurrent: int = 30):
        self.api_key = api_key
        self.project = project
        self.preset_hash = preset_hash
        self.max_concurrent = max_concurrent

    async def classify_one(self, session: aiohttp.ClientSession, position: str, jd: str, semaphore: asyncio.Semaphore):
        async with semaphore:
            payload = {
                "hash": self.preset_hash,
                "params": {
                    "position": str(position or "")[:1000],
                    "jd": str(jd or "")[:8000],
                },
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "분류하라"}]}
                ],
            }
            headers = {
                "project": self.project,
                "apiKey": self.api_key,
                "Content-Type": "application/json; charset=utf-8",
            }

            delays = [1, 3, 7]
            last_err = None
            for attempt in range(3):
                try:
                    async with session.post(
                        ENNOIA_ENDPOINT,
                        json=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=90),
                    ) as resp:
                        text = await resp.text()
                        if resp.status == 200:
                            return self._parse_response(text)
                        elif resp.status == 429 or 500 <= resp.status < 600:
                            # 429(속도제한)·5xx(서버오류)는 재시도
                            last_err = f"HTTP {resp.status}"
                            if attempt < 2:
                                await asyncio.sleep(delays[attempt])
                                continue
                            return None, f"HTTP {resp.status}"
                        else:
                            return None, f"HTTP {resp.status}: {text[:120]}"
                except asyncio.TimeoutError:
                    last_err = "TIMEOUT"
                    if attempt < 2:
                        await asyncio.sleep(delays[attempt])
                        continue
                    return None, "TIMEOUT"
                except Exception as e:
                    last_err = f"EXCEPTION: {e}"
                    if attempt < 2:
                        await asyncio.sleep(delays[attempt])
                        continue
                    return None, f"EXCEPTION: {e}"
            return None, last_err or "UNKNOWN"

    def _parse_response(self, text: str):
        try:
            data = json.loads(text)
            content_arr = data["choices"][0]["message"]["content"]
            if isinstance(content_arr, list):
                content_text = "".join(c.get("text", "") for c in content_arr)
            else:
                content_text = content_arr
            try:
                return json.loads(content_text), None
            except json.JSONDecodeError:
                m = re.search(r"\{[\s\S]*\}", content_text)
                if m:
                    try:
                        return json.loads(m.group()), None
                    except json.JSONDecodeError:
                        pass
                return None, "PARSE_ERROR"
        except Exception as e:
            return None, f"RESP_ERR: {e}"


def _col_letter(n: int) -> str:
    """0-indexed column number -> letter (0->A, 1->B, ...)."""
    result = ""
    n = n + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def _extract_sheet_id_and_gid(url: str):
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
    sheet_id = m.group(1) if m else None
    g = re.search(r"[#?&]gid=(\d+)", url)
    gid = int(g.group(1)) if g else None
    return sheet_id, gid


REQUIRED = ["position", "jd", "Language"]

# 이 값들이 Language 칸에 있으면 "에러로 실패한 행"으로 보고 재실행 시 다시 처리
ERROR_MARKERS = ("HTTP", "TIMEOUT", "PARSE_ERROR", "EXCEPTION", "RESP_ERR", "UNKNOWN")


async def process_sheet(
    sheet_url: str,
    gc,
    classifier: Classifier,
    on_start: Optional[Callable[[str, int], None]] = None,
):
    """Google Sheet 분류 처리 — async."""
    sheet_id, gid = _extract_sheet_id_and_gid(sheet_url)
    if not sheet_id:
        raise ValueError("Google Sheets URL 인식 실패")

    sh = await asyncio.to_thread(gc.open_by_key, sheet_id)

    # 대상 시트 찾기
    target_ws = None
    if gid is not None:
        for ws in sh.worksheets():
            if ws.id == gid:
                headers = await asyncio.to_thread(ws.row_values, 1)
                if all(h in headers for h in REQUIRED):
                    target_ws = ws
                    break

    if target_ws is None:
        for ws in sh.worksheets():
            headers = await asyncio.to_thread(ws.row_values, 1)
            if all(h in headers for h in REQUIRED):
                target_ws = ws
                break

    if target_ws is None:
        all_tabs = [ws.title for ws in sh.worksheets()]
        raise ValueError(f"position, jd, Language 헤더가 있는 시트가 없음. 탭들: {all_tabs}")

    sheet_name = target_ws.title
    log.info("대상 시트: %s", sheet_name)

    # 전체 데이터 읽기
    all_data = await asyncio.to_thread(target_ws.get_all_values)
    headers = all_data[0]
    pos_col = headers.index("position")
    jd_col = headers.index("jd")
    lang_col = headers.index("Language")
    lang_letter = _col_letter(lang_col)

    to_process = []
    for i, row in enumerate(all_data[1:], start=2):
        if len(row) <= max(pos_col, jd_col):
            continue
        jd = row[jd_col] if len(row) > jd_col else ""
        existing = row[lang_col].strip() if len(row) > lang_col else ""
        # 에러 마커가 적힌 행은 비어있는 것으로 간주 → 재실행 시 자동 재처리
        is_error = any(existing.startswith(m) for m in ERROR_MARKERS)
        if not jd or (existing and not is_error):
            continue
        to_process.append((i, row[pos_col] if len(row) > pos_col else "", jd))

    total = len(to_process)
    log.info("처리 대상: %d건", total)

    if on_start:
        try:
            on_start(sheet_name, total)
        except Exception:
            pass

    if total == 0:
        return {"sheet_name": sheet_name, "total": 0, "errors": 0, "gray": 0, "ok": 0}

    # 병렬 호출 — Semaphore는 현재 실행 루프에서 생성 (루프 충돌 방지)
    semaphore = asyncio.Semaphore(classifier.max_concurrent)

    async def _run_one(row_info):
        row_num, position, jd = row_info
        result, error = await classifier.classify_one(session, position, jd, semaphore)
        return row_num, result, error

    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(*(_run_one(r) for r in to_process))

    # 배치 업데이트 준비
    updates = []
    gray_cells = []
    errors = 0
    gray = 0
    ok = 0

    for row_num, result, error in results:
        cell_a1 = f"{lang_letter}{row_num}"
        if error:
            value = error.split(":")[0]
            errors += 1
        else:
            value = result.get("language", "") or ""
            status = result.get("status", "ok")
            if status == "gray":
                gray += 1
                gray_cells.append(cell_a1)
            elif status == "x":
                value = "X"
            else:
                ok += 1
        updates.append({"range": cell_a1, "values": [[value]]})

    # 배치로 한 번에 업데이트
    if updates:
        await asyncio.to_thread(target_ws.batch_update, updates)

    # 회색 셀 배경색 적용 (gspread는 cell formatting 지원)
    if gray_cells:
        # gspread.format은 한 셀씩 호출되므로 비동기 thread로
        for cell_a1 in gray_cells:
            try:
                await asyncio.to_thread(
                    target_ws.format,
                    cell_a1,
                    {"backgroundColor": {"red": 0.85, "green": 0.85, "blue": 0.85}},
                )
            except Exception as e:
                log.warning("gray fill 실패 %s: %s", cell_a1, e)

    log.info("완료 — ok=%d gray=%d errors=%d", ok, gray, errors)
    return {
        "sheet_name": sheet_name,
        "total": total,
        "errors": errors,
        "gray": gray,
        "ok": ok,
    }
