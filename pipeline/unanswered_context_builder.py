"""B-002 확장: BE의 unanswered_items(3.3)에서 why_it_matters가 비어있는 행을 모아
언어별 컨텍스트로 묶는다. 판정(무엇이 미응답인지)은 BE의 unanswered_service.py가
이미 끝냈으므로, 여기서는 그 결과에 "왜 중요한지" 설명을 붙이기 위한 원본 사실만
조립한다 — db_context_builder.py와 동일하게 raw_events가 유일한 사실 원천이다.

REVIEW_COMMENT 이벤트는 title이 비어있어서, 소속된 PR/이슈의 제목을 함께 찾아
붙인다 (db_context_builder.py의 root 조회와 같은 방식, 다만 project별로 캐시한다
— unanswered_items는 여러 프로젝트에 걸쳐 있을 수 있어 스레드 번호가 프로젝트
사이에서 겹칠 수 있기 때문).
"""
from sqlalchemy import text
from sqlalchemy.engine import Engine

from db_context_builder import _thread_key

_PENDING_ITEMS_SQL = text(
    """
    SELECT ui.id AS item_id, ui.signal_type, ui.target_team_id, re.project_id,
           re.type AS event_type, re.title, re.body, re.url, re.actor_handle, re.gh_created_at
    FROM unanswered_items ui
    JOIN raw_events re ON re.id = ui.raw_event_id
    WHERE ui.why_it_matters IS NULL
      AND ui.resolved = false
      AND ui.target_team_id IS NOT NULL
    ORDER BY ui.detected_at ASC
    """
)

# db_context_builder._ROOTS_SQL과 동일한 이스케이프 필요 (SQLAlchemy text()가
# '%:created'의 ':created'를 바인드 파라미터로 오인하는 것을 방지).
_ROOTS_SQL = text(
    r"""
    SELECT title, url
    FROM raw_events
    WHERE project_id = :project_id
      AND type IN ('PR', 'ISSUE')
      AND github_id LIKE '%\:created'
    """
)

_TEAM_LANGUAGE_SQL = text("SELECT id, default_language FROM teams WHERE id = ANY(:team_ids)")


def build_pending_items(engine: Engine) -> dict[str, list[dict]]:
    """반환: {language: [item, ...]}. 프로젝트 여러 개에 걸친 항목을 한 번에 처리한다."""
    with engine.connect() as conn:
        rows = conn.execute(_PENDING_ITEMS_SQL).mappings().all()
        if not rows:
            return {}

        team_ids = {row["target_team_id"] for row in rows}
        team_rows = conn.execute(_TEAM_LANGUAGE_SQL, {"team_ids": list(team_ids)}).mappings().all()

        roots_by_project: dict[str, dict] = {}
        for project_id in {row["project_id"] for row in rows}:
            root_rows = conn.execute(_ROOTS_SQL, {"project_id": project_id}).mappings().all()
            roots: dict = {}
            for r in root_rows:
                key = _thread_key(r["url"])
                if key is not None:
                    roots[key] = r
            roots_by_project[str(project_id)] = roots

    language_by_team = {str(t["id"]): t["default_language"] for t in team_rows}

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        language = language_by_team.get(str(row["target_team_id"]))
        if language is None:
            continue

        title = row["title"]
        if not title:
            key = _thread_key(row["url"])
            root = roots_by_project.get(str(row["project_id"]), {}).get(key) if key else None
            title = root["title"] if root else ""

        grouped.setdefault(language, []).append(
            {
                "id": str(row["item_id"]),
                "signal_type": row["signal_type"],
                "type": row["event_type"],
                "title": title or "",
                "url": row["url"],
            }
        )
    return grouped
