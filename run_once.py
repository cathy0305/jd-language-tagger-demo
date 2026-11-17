"""
일회성 분류 실행 (GitHub Actions용)

Socket Mode 봇(bot.py)과 달리, 시트 URL 하나를 받아 분류하고 종료한다.
GitHub Actions가 Slack 슬래시 커맨드(앱스크립트 경유)로 깨워서 실행.

필요한 환경변수:
- ENNOIA_API_KEY, ENNOIA_PROJECT, PRESET_HASH
- GOOGLE_CREDS_JSON  (Service Account JSON 내용 전체)  또는  GOOGLE_CREDS_PATH
- SHEET_URL          (분류할 구글 시트 URL)
- RESPONSE_URL       (Slack 슬래시 커맨드 response_url — 결과 알림 보낼 곳)
- MAX_CONCURRENT     (선택, 기본 20)
"""
import os
import asyncio
import logging
import tempfile

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()  # 로컬 테스트용 (.env). GitHub Actions에선 secrets 사용
except Exception:
    pass

from classifier import Classifier, process_sheet, init_gspread

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("run_once")


def post(response_url, text):
    """Slack response_url로 채널에 메시지 전송."""
    if not response_url:
        log.info("(RESPONSE_URL 없음) %s", text)
        return
    try:
        requests.post(
            response_url,
            json={"response_type": "in_channel", "text": text},
            timeout=10,
        )
    except Exception as e:
        log.error("Slack 전송 실패: %s", e)


def resolve_creds_path():
    """GOOGLE_CREDS_JSON(내용)을 임시 파일로 쓰거나, GOOGLE_CREDS_PATH 사용."""
    raw = os.environ.get("GOOGLE_CREDS_JSON")
    if raw:
        path = os.path.join(tempfile.gettempdir(), "google_creds.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw)
        return path
    return os.environ.get("GOOGLE_CREDS_PATH", "google_creds.json")


async def main():
    sheet_url = os.environ.get("SHEET_URL", "").strip()
    response_url = os.environ.get("RESPONSE_URL", "").strip()

    if not sheet_url:
        log.error("SHEET_URL 환경변수가 없습니다.")
        return

    classifier = Classifier(
        api_key=os.environ["ENNOIA_API_KEY"],
        project=os.environ["ENNOIA_PROJECT"],
        preset_hash=os.environ["PRESET_HASH"],
        max_concurrent=int(os.environ.get("MAX_CONCURRENT", "20")),
    )
    gc = init_gspread(resolve_creds_path())

    try:
        result = await process_sheet(
            sheet_url=sheet_url,
            gc=gc,
            classifier=classifier,
            on_start=lambda name, total: post(
                response_url, f"▶ *{name}* 탭 분류 시작 (대상 *{total}건*)"
            ),
        )

        if result["total"] == 0:
            post(response_url, f"✓ *{result['sheet_name']}* — 이미 모든 행이 분류되어 있어요.")
        elif result["errors"] == 0:
            post(response_url, "🎉 *분류 완료* — 에러 0건")
        else:
            post(
                response_url,
                f"🎉 *분류 완료* — 에러 *{result['errors']}건* "
                f"(같은 시트에 `/classify` 한 번 더 하면 에러 행만 재시도돼요)",
            )
    except Exception as e:
        log.exception("분류 실패")
        post(response_url, f"❌ 에러: {e}")


if __name__ == "__main__":
    asyncio.run(main())
