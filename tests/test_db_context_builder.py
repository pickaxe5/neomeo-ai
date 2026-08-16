"""assemble_context 검증: mock_layer0.json의 pr_101 시나리오(멘션 미응답,
리뷰어 미응답, 파일 경로 겹침)를 실제 raw_events처럼 flat 행으로 흩어놨을 때
같은 결론(threads 구조)이 나오는지 확인한다. DB 없이 순수 함수만 테스트한다."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

from db_context_builder import assemble_context  # noqa: E402


def _dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def test_pr_thread_groups_review_comments_and_extracts_mentions():
    root_rows = [
        {
            "type": "PR",
            "github_id": "pr:101:created",
            "actor_handle": "jieun_k",
            "title": "feat: add pagination to /api/summaries endpoint",
            "body": "",
            "url": "https://github.com/neomeo-org/neomeo-app/pull/101",
            "raw_payload": {"requested_reviewers": [{"login": "tobias_w"}, {"login": "sam_r"}]},
            "gh_created_at": _dt("2026-08-08T02:20:00Z"),
        }
    ]
    window_rows = [
        root_rows[0],
        {
            "type": "REVIEW_COMMENT",
            "github_id": "review_comment:1",
            "actor_handle": "jieun_k",
            "title": None,
            "body": "@tobias_w 페이지네이션 응답 스키마 리뷰 부탁드려요.",
            "url": "https://github.com/neomeo-org/neomeo-app/pull/101",
            "file_paths": None,
            "raw_payload": {},
            "gh_created_at": _dt("2026-08-08T02:20:00Z"),
        },
        {
            "type": "COMMIT",
            "github_id": "a1b2c3d",
            "actor_handle": "jieun_k",
            "title": "feat: add pagination to /api/summaries endpoint",
            "body": None,
            "url": "https://github.com/neomeo-org/neomeo-app/commit/a1b2c3d",
            "file_paths": ["src/api/summaries.py"],
            "raw_payload": {},
            "gh_created_at": _dt("2026-08-08T02:15:00Z"),
        },
    ]

    context = assemble_context(
        window_rows, root_rows, "team_seoul", _dt("2026-08-08T00:00:00Z"), _dt("2026-08-08T10:00:00Z")
    )

    assert len(context["commits"]) == 1
    assert context["commits"][0]["sha"] == "a1b2c3d"

    assert len(context["threads"]) == 1
    thread = context["threads"][0]
    assert thread["type"] == "pr"
    assert thread["number"] == 101
    assert thread["author"] == "jieun_k"
    assert set(thread["requested_reviewers"]) == {"tobias_w", "sam_r"}
    # 멘션은 root와 REVIEW_COMMENT 본문 양쪽에서 뽑힘
    assert "tobias_w" in thread["mentioned_handles"]
    # root(:created) 자체는 코멘트 목록에 안 들어가고, REVIEW_COMMENT만 들어간다
    assert len(thread["comments"]) == 1
    assert thread["comments"][0]["author"] == "jieun_k"
    assert thread["comments"][0]["type"] == "comment"


def test_merged_event_not_treated_as_comment():
    """:created와 :merged가 같은 PR 번호로 묶여도, :merged는 본문이 PR 설명
    재수록이라 코멘트로 잘못 세어지면 안 된다. 대신 머지 사실은 state로 반영돼야 한다."""
    root = {
        "type": "PR",
        "github_id": "pr:200:created",
        "actor_handle": "lena_s",
        "title": "style: unify button spacing",
        "body": "",
        "url": "https://github.com/neomeo-org/neomeo-app/pull/200",
        "state": "open",
        "raw_payload": {},
        "gh_created_at": _dt("2026-08-07T00:00:00Z"),
    }
    merged = dict(
        root, github_id="pr:200:merged", state="merged", gh_created_at=_dt("2026-08-08T05:00:00Z")
    )

    context = assemble_context(
        [merged], [root], "team_seoul", _dt("2026-08-08T00:00:00Z"), _dt("2026-08-08T10:00:00Z")
    )

    assert len(context["threads"]) == 1
    thread = context["threads"][0]
    assert thread["comments"] == []
    assert thread["state"] == "merged"
    assert thread["state_changed_in_window"] is True


def test_thread_without_state_change_in_window():
    """:created만 윈도우 밖에서 있고, 이번 윈도우엔 리뷰 코멘트만 있는 경우 —
    상태 변화는 없었다는 뜻이므로 state_changed_in_window는 False여야 한다."""
    root = {
        "type": "PR",
        "github_id": "pr:201:created",
        "actor_handle": "lena_s",
        "title": "another PR",
        "body": "",
        "url": "https://github.com/neomeo-org/neomeo-app/pull/201",
        "state": "open",
        "raw_payload": {},
        "gh_created_at": _dt("2026-08-07T00:00:00Z"),
    }
    comment = {
        "type": "REVIEW_COMMENT",
        "github_id": "review_comment:5",
        "actor_handle": "tobias_w",
        "title": None,
        "body": "looks fine",
        "url": root["url"],
        "file_paths": None,
        "raw_payload": {},
        "gh_created_at": _dt("2026-08-08T03:00:00Z"),
    }

    context = assemble_context(
        [comment], [root], "team_seoul", _dt("2026-08-08T00:00:00Z"), _dt("2026-08-08T10:00:00Z")
    )

    thread = context["threads"][0]
    assert thread["state"] == "open"
    assert thread["state_changed_in_window"] is False


def test_no_root_in_project_falls_back_to_earliest_window_event():
    event = {
        "type": "REVIEW_COMMENT",
        "github_id": "review_comment:9",
        "actor_handle": "sam_r",
        "title": None,
        "body": "lgtm",
        "url": "https://github.com/neomeo-org/neomeo-app/pull/999",
        "file_paths": None,
        "raw_payload": {},
        "gh_created_at": _dt("2026-08-08T03:00:00Z"),
    }
    context = assemble_context(
        [event], [], "team_seoul", _dt("2026-08-08T00:00:00Z"), _dt("2026-08-08T10:00:00Z")
    )
    assert len(context["threads"]) == 1
    assert context["threads"][0]["url"] == event["url"]


if __name__ == "__main__":
    test_pr_thread_groups_review_comments_and_extracts_mentions()
    test_merged_event_not_treated_as_comment()
    test_thread_without_state_change_in_window()
    test_no_root_in_project_falls_back_to_earliest_window_event()
    print("모든 테스트 통과")
