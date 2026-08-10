"""B-003: 내가 답해야 할 것 — 미응답 판정 (규칙 기반, 결정론적)

판정 기준 (확정, 명세 F-XTSROT 반영):
  1. 멘션/리뷰 요청 이후, 대상자 본인이 해당 스레드에 "텍스트 코멘트"를 남기지
     않은 상태를 미응답으로 처리한다.
  2. 본인 PR/이슈에 달린 코멘트에 본인(작성자)의 후속 텍스트 코멘트가 없는 경우도
     미응답으로 처리한다 — 마지막 텍스트 코멘트가 작성자 본인이 아니면 트리거.
  - 시간 임계값 없음 (현재 시점 기준 즉시 판단)
  - 타인의 답변은 응답으로 불인정
  - 리액션(reaction)은 응답으로 불인정
  - 코멘트 없는 Approve(approve_no_comment)는 응답으로 불인정
  → 보수적으로 잡는 것이 안전한 방향이라는 원칙에 따름. (2번 규칙은 "lgtm"처럼
    저정보 코멘트도 문자 그대로 응답 대기로 잡을 수 있음 — 의도된 보수적 동작.)

  대상자를 명시적 신호(멘션/리뷰어 지정)로 특정할 수 없는 경우(알 수 없는
  핸들 등)는 스레드 작성자의 팀 전체로 폴백하고, 그마저 불가하면 미배정
  상태로만 남긴다 (_resolve_fallback).

이 모듈은 "판정"만 한다. "왜 중요한지"는 B-002 브리핑 단계에서 LLM이 해석한다.
"""
from dataclasses import dataclass
from enum import Enum


class ReasonType(str, Enum):
    MENTION = "mention"
    REVIEW_REQUEST = "review_request"
    OWN_PR_COMMENT = "own_pr_comment"


TEXT_COMMENT_TYPE = "comment"  # 이 타입만 "응답"으로 인정한다.


@dataclass
class UnrespondedItem:
    handle: str | None
    thread_id: str
    thread_type: str          # "pr" | "issue"
    number: int
    title: str
    url: str
    file_paths: list
    reasons: list             # list[ReasonType] — 멘션/리뷰요청/본인PR코멘트 복수일 수 있음
    triggered_at: str         # 신호 발생 시각 (멘션/리뷰요청은 스레드 생성 시각, 본인PR코멘트는 마지막 코멘트 시각)
    assigned_team: str | None = None  # 대상자 특정 불가 시 폴백된 팀 (평소엔 None)


def _has_text_comment(thread: dict, handle: str) -> bool:
    """대상자 본인이 해당 스레드에 텍스트 코멘트를 남겼는지 확인."""
    return any(
        c.get("author") == handle and c.get("type") == TEXT_COMMENT_TYPE
        for c in thread.get("comments", [])
    )


def _make_item(thread: dict, handle: str, reasons: set, triggered_at: str) -> UnrespondedItem:
    return UnrespondedItem(
        handle=handle,
        thread_id=thread["thread_id"],
        thread_type=thread["type"],
        number=thread["number"],
        title=thread["title"],
        url=thread["url"],
        file_paths=thread.get("file_paths", []),
        reasons=sorted(reasons),
        triggered_at=triggered_at,
    )


def check_thread(thread: dict) -> list[UnrespondedItem]:
    """단일 스레드에서 미응답 대상자 목록을 판정한다."""
    targets: dict[str, set] = {}
    triggered_at: dict[str, str] = {}
    for h in thread.get("mentioned_handles", []):
        targets.setdefault(h, set()).add(ReasonType.MENTION)
        triggered_at.setdefault(h, thread["created_at"])
    for h in thread.get("requested_reviewers", []):
        targets.setdefault(h, set()).add(ReasonType.REVIEW_REQUEST)
        triggered_at.setdefault(h, thread["created_at"])

    unresolved: dict[str, set] = {}
    for handle, reasons in targets.items():
        if not _has_text_comment(thread, handle):
            unresolved[handle] = reasons

    # 본인 PR/이슈에 달린 코멘트에 본인 후속 응답이 없는 경우: 마지막 텍스트
    # 코멘트가 스레드 작성자 본인이 아니면 작성자를 미응답 대상으로 잡는다.
    author = thread.get("author")
    text_comments = [c for c in thread.get("comments", []) if c.get("type") == TEXT_COMMENT_TYPE]
    if author and text_comments and text_comments[-1].get("author") != author:
        unresolved.setdefault(author, set()).add(ReasonType.OWN_PR_COMMENT)
        triggered_at[author] = text_comments[-1]["timestamp"]

    return [
        _make_item(thread, handle, reasons, triggered_at.get(handle, thread["created_at"]))
        for handle, reasons in unresolved.items()
    ]


def check_threads(threads: list) -> list[UnrespondedItem]:
    """스레드 목록(윈도우로 이미 스코핑된 것이어도 됨)에 대해 판정만 수행."""
    items = []
    for thread in threads:
        items.extend(check_thread(thread))
    return items


def check_all_threads(layer0: dict) -> list[UnrespondedItem]:
    return check_threads(layer0.get("threads", []))


def _resolve_fallback(items: list[UnrespondedItem], layer0: dict) -> list[UnrespondedItem]:
    """대상자 핸들이 알려진 멤버가 아니면 스레드 작성자의 팀으로 폴백, 그마저
    불가하면 미배정(handle=None)으로 남긴다."""
    known_handles = {m["handle"] for m in layer0.get("members", [])}
    handle_to_team = {m["handle"]: m["team_id"] for m in layer0.get("members", [])}
    thread_author_by_id = {t["thread_id"]: t.get("author") for t in layer0.get("threads", [])}

    for item in items:
        if item.handle in known_handles:
            continue
        author_team = handle_to_team.get(thread_author_by_id.get(item.thread_id))
        item.assigned_team = author_team
        item.handle = None
    return items


def get_unresponded_for_member(layer0: dict, handle: str) -> list[UnrespondedItem]:
    """특정 멤버 기준 미응답 항목만 필터링, 발생 시각순 정렬."""
    items = _resolve_fallback(check_all_threads(layer0), layer0)
    items = [i for i in items if i.handle == handle]
    return sorted(items, key=lambda i: i.triggered_at)
