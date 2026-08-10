"""S-004 카드에 붙는 결정론적 메타데이터 (규칙 기반, LLM 관여 없음).

와이어프레임의 "카드 메타데이터" 패널(수집 활동 건수 등)과 "이 카드의 전체
활동 출처" 패널을 채우는 데 쓰인다. 둘 다 요약 항목에 실제로 인용됐는지와
무관하게, 이번 윈도우에 수집된 활동 자체를 그대로 집계/나열하는 것이므로
판정(코드) 영역이다.
"""

NO_ACTIVITY_HEADLINE = {
    "ko": "이번 구간에는 새로운 활동이 없습니다.",
    "en": "No new activity in this window.",
}


def activity_counts(context: dict) -> dict:
    threads = context.get("threads", [])
    pr_numbers = {t["number"] for t in threads if t["type"] == "pr"}
    issue_numbers = {t["number"] for t in threads if t["type"] == "issue"}
    review_comments = sum(
        1 for t in threads for c in t.get("comments", []) if c.get("type") == "comment"
    )
    return {
        "pr": len(pr_numbers),
        "issue": len(issue_numbers),
        "review_comment": review_comments,
        "commit": len(context.get("commits", [])),
    }


def source_manifest(context: dict) -> list[dict]:
    """윈도우 내 전체 활동을 (유형, 번호/sha) 기준 중복 제거해 시간순으로 나열."""
    manifest = []
    seen = set()
    for t in sorted(context.get("threads", []), key=lambda t: t["created_at"]):
        key = (t["type"], t["number"])
        if key in seen:
            continue
        seen.add(key)
        manifest.append(
            {
                "type": t["type"],
                "number": t["number"],
                "title": t["title"],
                "url": t["url"],
            }
        )
    for c in sorted(context.get("commits", []), key=lambda c: c["timestamp"]):
        manifest.append(
            {
                "type": "commit",
                "sha": c["sha"],
                "title": c.get("message", ""),
                "url": c["url"],
            }
        )
    return manifest
