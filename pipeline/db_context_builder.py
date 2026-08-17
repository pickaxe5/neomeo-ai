"""실 DB 연동: BE의 raw_events 테이블(flat, 스레드 구분 없음)에서 S-004가 기대하는
context 형태({"commits": [...], "threads": [...]})를 조립한다.

mock_layer0.json은 PR/이슈별로 comments가 이미 중첩된 "스레드" 구조지만, 실제
raw_events는 이벤트 1건 = 행 1개인 flat 테이블이다. PR/이슈 번호는 url에서
정규식으로 뽑아 그룹 키로 쓴다 (BE의 unanswered_service.py와 동일한 관례).

PR/이슈는 "생성"과 "머지/종료"가 별도 행으로 기록되므로(github_collector.py),
":created" 행만 스레드의 root(제목·작성자·리뷰어)로 쓰고, ":merged"/":closed" 행은
본문이 PR 설명 재수록이라 "코멘트"로 취급하면 왜곡된다 — 대신 thread["state"]로
따로 반영해, "머지됐다"는 사실 자체는 잃지 않는다.

root는 윈도우 밖(예: 어제 생성된 PR이 오늘 머지)일 수 있어 project 전체에서
별도로 조회한다 — 윈도우로만 조회하면 그런 PR의 제목·URL을 잃는다.
"""
import re
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine

_THREAD_URL_RE = re.compile(r"/(pull|issues)/(\d+)")
# BE의 unanswered_service.py와 같은 패턴을 쓰되 밑줄을 추가했다 — 실제 GitHub
# 계정명엔 밑줄이 없지만 데모 시드 핸들(jieun_k 등)엔 있어, 원본 패턴대로면
# "tobias_w" 멘션이 "tobias"에서 잘린다 (BE 쪽에도 동일 버그 있음, 팀에 공유 필요).
_MENTION_RE = re.compile(r"@([A-Za-z0-9_-]+)")

_WINDOW_EVENTS_SQL = text(
    """
    SELECT type, github_id, actor_handle, title, body, url, file_paths,
           state, gh_created_at, raw_payload
    FROM raw_events
    WHERE project_id = :project_id
      AND team_id = :team_id
      AND gh_created_at >= :range_start
      AND gh_created_at < :range_end
    ORDER BY gh_created_at ASC
    """
)

# 스레드 root는 프로젝트 전체에서 찾는다 (":created" 행이 이번 윈도우 밖일 수 있어서).
_ROOTS_SQL = text(
    r"""
    SELECT type, github_id, actor_handle, title, body, url, state, raw_payload, gh_created_at
    FROM raw_events
    WHERE project_id = :project_id
      AND type IN ('PR', 'ISSUE')
      AND github_id LIKE '%\:created'
    """
)


def _thread_key(url: str | None) -> tuple[str, int] | None:
    if not url:
        return None
    m = _THREAD_URL_RE.search(url)
    if not m:
        return None
    kind = "pr" if m.group(1) == "pull" else "issue"
    return kind, int(m.group(2))


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def build_context_from_db(
    engine: Engine, project_id: str, team_id: str, range_start: datetime, range_end: datetime
) -> dict:
    """closure_run 1건의 [range_start, range_end) 구간에 해당하는 context를 조립한다.
    project_id/team_id는 raw_events.project_id/team_id와 같은 문자열(uuid str)이어야 한다."""
    with engine.connect() as conn:
        window_rows = conn.execute(
            _WINDOW_EVENTS_SQL,
            {"project_id": project_id, "team_id": team_id, "range_start": range_start, "range_end": range_end},
        ).mappings().all()
        root_rows = conn.execute(_ROOTS_SQL, {"project_id": project_id}).mappings().all()

    return assemble_context(window_rows, root_rows, team_id, range_start, range_end)


def assemble_context(
    window_rows: list, root_rows: list, team_id: str, range_start: datetime, range_end: datetime
) -> dict:
    """DB 조회 없이 순수하게 grouping만 수행 — 단위 테스트용으로 분리."""
    roots: dict[tuple[str, int], dict] = {}
    for row in root_rows:
        key = _thread_key(row["url"])
        if key is not None:
            roots[key] = row

    commits: list[dict] = []
    grouped: dict[tuple[str, int], list[dict]] = {}
    for row in window_rows:
        if row["type"] == "COMMIT":
            commits.append(
                {
                    "sha": row["github_id"],
                    "author": row["actor_handle"],
                    "timestamp": _iso(row["gh_created_at"]),
                    "message": row["title"] or "",
                    "file_paths": row["file_paths"] or [],
                    "url": row["url"],
                }
            )
            continue
        key = _thread_key(row["url"])
        if key is None:
            continue
        grouped.setdefault(key, []).append(row)

    threads: list[dict] = []
    for key, events in grouped.items():
        root = roots.get(key)
        if root is None:
            # 프로젝트 전체 조회에도 :created 행이 없는 예외 상황 — 윈도우 내 가장 이른
            # 이벤트를 임시 root로 삼아 최소한의 정보는 남긴다.
            root = min(events, key=lambda e: e["gh_created_at"])

        kind, number = key
        mentioned: set[str] = set(_MENTION_RE.findall(root.get("body") or ""))
        comments = []
        state_change = None  # 이번 윈도우 안에서 :merged/:closed 행을 만나면 여기 기록
        for event in events:
            # PR/이슈의 :created·:merged·:closed 행은 본문이 PR/이슈 설명 재수록이라
            # "코멘트"가 아니다. 실제 코멘트는 REVIEW_COMMENT 타입뿐이다.
            if event["type"] != "REVIEW_COMMENT":
                if event["github_id"] != root["github_id"]:
                    # :created가 아닌 PR/이슈 행 = 상태가 바뀐 사실(머지/종료) 자체.
                    # 같은 스레드에 여러 개면(드묾) 가장 늦은 것을 최종 상태로 본다.
                    if state_change is None or event["gh_created_at"] > state_change["gh_created_at"]:
                        state_change = event
                continue
            body = event["body"]
            mentioned.update(_MENTION_RE.findall(body or ""))
            comments.append(
                {
                    "author": event["actor_handle"],
                    "timestamp": _iso(event["gh_created_at"]),
                    "type": "comment" if body else "reaction",
                    "body": body,
                }
            )

        requested_reviewers = [
            r.get("login")
            for r in (root.get("raw_payload") or {}).get("requested_reviewers", [])
            if r.get("login")
        ]

        threads.append(
            {
                "thread_id": f"{kind}_{number}",
                "type": kind,
                "number": number,
                "title": root.get("title") or "",
                "url": root["url"],
                "author": root.get("actor_handle"),
                "file_paths": [],
                "created_at": _iso(root["gh_created_at"]),
                "mentioned_handles": sorted(mentioned),
                "requested_reviewers": requested_reviewers,
                "comments": comments,
                # 현재 알려진 상태(open/merged/closed)와, 그 상태가 "이번 윈도우 안에서"
                # 바뀌었는지. LLM이 "머지됐습니다" 같은 사실을 놓치지 않게 명시적으로 전달.
                "state": (state_change or root).get("state"),
                "state_changed_in_window": state_change is not None,
            }
        )

    window = {"team_id": team_id, "start_utc": _iso(range_start), "end_utc": _iso(range_end)}
    return {"window": window, "commits": commits, "threads": threads}
