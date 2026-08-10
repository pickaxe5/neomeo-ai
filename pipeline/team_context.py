"""팀별 "하루 끝" 윈도우에 해당하는 0층 이벤트만 추려내는 필터.

Neomeo의 핵심 차별점: 요약 경계선은 UTC 자정이 아니라 각 팀의 업무 종료 시점.
여기서는 이벤트의 author가 해당 팀 소속이고, 발생 시각이 팀의 window(start/end) 안에
있는 것만 그 팀의 "오늘" 활동으로 취급한다.
"""


def _team_member_handles(layer0: dict, team_id: str) -> set:
    return {m["handle"] for m in layer0.get("members", []) if m["team_id"] == team_id}


def _in_window(timestamp: str, start: str, end: str) -> bool:
    return start <= timestamp <= end


def build_team_window_context(layer0: dict, team_id: str) -> dict:
    """해당 팀 멤버가 만든, window 시간대 안의 커밋/스레드만 남긴 축소 컨텍스트를 반환."""
    window = layer0["window"]
    if window["team_id"] != team_id:
        raise ValueError(
            f"mock 데이터의 window는 team_id={window['team_id']} 기준입니다. "
            f"실제 연동 시에는 팀별 window를 BE에서 각각 받아야 합니다."
        )

    handles = _team_member_handles(layer0, team_id)
    start, end = window["start_utc"], window["end_utc"]

    commits = [
        c for c in layer0.get("commits", [])
        if c["author"] in handles and _in_window(c["timestamp"], start, end)
    ]
    threads = [
        t for t in layer0.get("threads", [])
        if t["author"] in handles and _in_window(t["created_at"], start, end)
    ]

    return {
        "team_id": team_id,
        "window": window,
        "commits": commits,
        "threads": threads,
    }
