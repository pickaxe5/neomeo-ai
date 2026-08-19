"""B-002 확장 2: BE의 personal_progress_summaries(브리핑 3단계, 팀 진행 상황)에서
content가 비어있는 행을 모아 (closure_run_id, language) 단위로 묶는다.

같은 team_card(summary_cards.content, 이미 사실이 확정된 객관 요약)를 읽는
여러 사람이 있을 수 있으므로, 같은 team_card는 한 번만 담고 각 사람의 프로필
(역할·담당 영역)만 배열로 붙인다 — LLM 호출을 (closure_run_id, language) 당
1회로 묶기 위함.

사람의 역할·담당 영역은 이 진행 상황을 만든 팀이 아니라 "이 사람이 속한, 이
프로젝트에 참여 중인 자기 팀"의 team_memberships에서 가져온다 (S-005 다국어로
다른 팀 카드도 자기 언어로 볼 수 있기 때문에, 카드를 만든 팀과 읽는 사람의
팀이 다를 수 있다).
"""
from sqlalchemy import text
from sqlalchemy.engine import Engine

_PENDING_SQL = text(
    """
    SELECT pps.id AS row_id, pps.closure_run_id, pps.language, pps.user_id,
           sc.content AS card_content, cr.project_id,
           tm.job_role, tm.job_role_label, tm.assigned_area
    FROM personal_progress_summaries pps
    JOIN closure_runs cr ON cr.id = pps.closure_run_id
    JOIN summary_cards sc ON sc.closure_run_id = pps.closure_run_id AND sc.language = pps.language
    JOIN project_teams pt ON pt.project_id = cr.project_id
    JOIN team_memberships tm ON tm.user_id = pps.user_id AND tm.team_id = pt.team_id
    WHERE pps.content IS NULL
      AND sc.content IS NOT NULL
    ORDER BY pps.id
    """
)

_DOCUMENT_SQL = text("SELECT content FROM project_documents WHERE project_id = :project_id")


def _effective_role(job_role: str | None, job_role_label: str | None) -> str | None:
    if job_role == "custom":
        return job_role_label or None
    return job_role


def build_pending_groups(engine: Engine) -> dict[tuple[str, str], dict]:
    """반환: {(closure_run_id, language): {"card_content", "planning_document", "profiles": [...]}}"""
    with engine.connect() as conn:
        rows = conn.execute(_PENDING_SQL).mappings().all()
        if not rows:
            return {}

        # row_id 중복(사용자가 같은 프로젝트에 팀을 둘 이상 두는 예외적인 경우) 방지 — 먼저
        # 매칭된 팀 소속을 그대로 쓴다.
        seen_row_ids: set[str] = set()

        project_ids = {str(row["project_id"]) for row in rows}
        documents: dict[str, str | None] = {}
        for project_id in project_ids:
            doc_row = conn.execute(_DOCUMENT_SQL, {"project_id": project_id}).mappings().first()
            documents[project_id] = doc_row["content"] if doc_row else None

    grouped: dict[tuple[str, str], dict] = {}
    for row in rows:
        row_id = str(row["row_id"])
        if row_id in seen_row_ids:
            continue
        seen_row_ids.add(row_id)

        key = (str(row["closure_run_id"]), row["language"])
        if key not in grouped:
            grouped[key] = {
                "card_content": row["card_content"],
                "planning_document": documents.get(str(row["project_id"])),
                "profiles": [],
            }
        grouped[key]["profiles"].append(
            {
                "id": row_id,
                "job_role": _effective_role(row["job_role"], row["job_role_label"]),
                "assigned_area": row["assigned_area"],
            }
        )
    return grouped
