"""B-004: 내 작업에 영향 있는 변경 — 1차 필터링 (규칙 기반, 결정론적)

판정 기준:
  - 1차 필터는 "파일 경로 정확 일치"만 본다. 의미적 관련성(경로가 정확히
    겹치지 않아도 관련 있는 경우) 판단은 LLM의 몫이며 이 모듈의 책임이 아니다.
  - 비교 대상은 (a) 멤버의 담당 영역(owned_paths, B-007 확정값/추론값 포함) 과
    (b) 이번 윈도우에서 멤버 본인이 직접 건드린 파일 경로 두 가지 모두. 담당
    영역으로 등록되지 않았더라도 내가 이번 윈도우에 직접 수정한 파일을 남이
    건드리면 영향으로 본다.
  - 본인이 만든 변경(source author == member)은 제외한다.
  - since가 주어지면(개인 브리핑의 "부재 구간" 시작 시각) 그 이후 활동만
    대상으로 한다 — 명세 F-OOVQZC: 부재 구간은 사용자별 마지막 열람 시점
    기준이라 팀 마감 윈도우와 다를 수 있다.
"""
from dataclasses import dataclass

from owned_area_inference import resolve_owned_paths


@dataclass
class ImpactItem:
    handle: str
    source_type: str        # "commit" | "pr"
    source_id: str          # sha 또는 thread_id
    author: str
    matched_paths: list
    title: str = ""
    url: str = ""
    number: int | None = None
    timestamp: str = ""


def _owned_paths(layer0: dict, handle: str) -> set:
    for m in layer0.get("members", []):
        if m["handle"] == handle:
            paths, _confirmed = resolve_owned_paths(layer0, m)
            return set(paths)
    return set()


def _member_own_touched_paths(layer0: dict, handle: str) -> set:
    """이번 윈도우에서 멤버 본인이 건드린 파일 경로 (커밋 + 본인 작성 스레드)."""
    paths = set()
    for c in layer0.get("commits", []):
        if c.get("author") == handle:
            paths.update(c.get("file_paths", []))
    for t in layer0.get("threads", []):
        if t.get("author") == handle:
            paths.update(t.get("file_paths", []))
    return paths


def _path_prefix_match(changed_path: str, watched_paths: set) -> bool:
    """정확 일치: watched_paths의 항목이 디렉터리 접두사이거나 파일명 완전 일치인 경우만."""
    for w in watched_paths:
        if w == changed_path:
            return True
        if w.endswith("/") and changed_path.startswith(w):
            return True
    return False


def find_impacts_for_member(layer0: dict, handle: str, since: str | None = None) -> list[ImpactItem]:
    watch_set = _owned_paths(layer0, handle) | _member_own_touched_paths(layer0, handle)
    if not watch_set:
        return []

    impacts: list[ImpactItem] = []

    for c in layer0.get("commits", []):
        if c.get("author") == handle:
            continue
        if since and c.get("timestamp", "") <= since:
            continue
        matched = [p for p in c.get("file_paths", []) if _path_prefix_match(p, watch_set)]
        if matched:
            impacts.append(
                ImpactItem(
                    handle=handle,
                    source_type="commit",
                    source_id=c["sha"],
                    author=c["author"],
                    matched_paths=matched,
                    title=c.get("message", ""),
                    url=c.get("url", ""),
                    timestamp=c.get("timestamp", ""),
                )
            )

    for t in layer0.get("threads", []):
        if t.get("author") == handle:
            continue
        if since and t.get("created_at", "") <= since:
            continue
        matched = [p for p in t.get("file_paths", []) if _path_prefix_match(p, watch_set)]
        if matched:
            impacts.append(
                ImpactItem(
                    handle=handle,
                    source_type="pr" if t["type"] == "pr" else "issue",
                    source_id=t["thread_id"],
                    author=t["author"],
                    matched_paths=matched,
                    title=t.get("title", ""),
                    url=t.get("url", ""),
                    number=t.get("number"),
                    timestamp=t.get("created_at", ""),
                )
            )

    # 같은 PR/이슈에 스레드가 여러 개로 쪼개져 있어도 번호 기준으로 한 번만 노출
    seen = set()
    deduped = []
    for item in sorted(impacts, key=lambda i: i.timestamp):
        key = (item.source_type, item.number if item.number is not None else item.source_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
