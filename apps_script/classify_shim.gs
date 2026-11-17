/**
 * Slack 슬래시 커맨드 → GitHub Actions(Python) 트리거 (신호 전달기)
 *
 * 분류 로직은 여기 없음. Slack 명령을 받아 즉시 응답하고,
 * GitHub Actions를 깨워 Python(run_once.py)을 실행시킨다.
 *
 * ── 설정 방법 ──
 * 1. script.google.com → 새 프로젝트 → 이 코드 붙여넣기
 * 2. 프로젝트 설정 → 스크립트 속성에 2개 추가:
 *      GITHUB_REPO  = <your-github-id>/<this-repo>
 *      GITHUB_TOKEN = (GitHub Personal Access Token, repo 권한)
 * 3. 배포 → 새 배포 → 유형: 웹 앱
 *      - 실행: 나
 *      - 액세스: 모든 사용자
 *    → 생성된 웹 앱 URL 복사
 * 4. Slack 앱 설정에서:
 *      - Socket Mode 끄기 (OFF)
 *      - Slash Commands → /classify → Request URL 에 위 웹 앱 URL 붙여넣기
 */

// 헬스체크 — 브라우저나 curl로 GET 하면 설정 상태 확인 가능 (토큰 값은 노출 안 함)
function doGet() {
  const props = PropertiesService.getScriptProperties();
  return ContentService
    .createTextOutput(JSON.stringify({
      ok: true,
      has_repo: !!props.getProperty("GITHUB_REPO"),
      has_token: !!props.getProperty("GITHUB_TOKEN")
    }))
    .setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  try {
    const text = (e.parameter.text || "").trim();
    const userName = e.parameter.user_name || "user";
    const responseUrl = e.parameter.response_url || "";

    if (text.indexOf("/spreadsheets/d/") < 0) {
      return slackJson("ephemeral", "❌ Google Sheets URL을 입력해주세요.");
    }

    const props = PropertiesService.getScriptProperties();
    const repo = props.getProperty("GITHUB_REPO");
    const token = props.getProperty("GITHUB_TOKEN");

    const res = UrlFetchApp.fetch("https://api.github.com/repos/" + repo + "/dispatches", {
      method: "post",
      contentType: "application/json",
      headers: { Authorization: "Bearer " + token, Accept: "application/vnd.github+json" },
      payload: JSON.stringify({
        event_type: "classify",
        client_payload: { sheet_url: text, response_url: responseUrl }
      }),
      muteHttpExceptions: true
    });

    if (res.getResponseCode() >= 300) {
      return slackJson("ephemeral", "❌ GitHub 트리거 실패 (" + res.getResponseCode() + ")");
    }

    return slackJson("in_channel", ":robot_face: *" + userName + "* 요청 접수! 분류 시작합니다 (1~2분 소요)");
  } catch (err) {
    return slackJson("ephemeral", "❌ 에러: " + err.message);
  }
}

function slackJson(type, text) {
  return ContentService
    .createTextOutput(JSON.stringify({ response_type: type, text: text }))
    .setMimeType(ContentService.MimeType.JSON);
}
