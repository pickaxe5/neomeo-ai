"""B-007: 담당 영역 자동 추론 (규칙 기반, 결정론적. LLM 사용하지 않음).

우선순위(명세 F-YFIQBW 기준):
  1. 사용자가 확인/확정한 값 (confirmed=True) — 이후 추론이 절대 덮어쓰지 않는다.
  2. 저장소의 담당 선언 파일(CODEOWNERS류) — project.codeowners에 있으면 최우선 반영.
  3. 커밋의 변경 파일 경로 집계로 자동 추론.
  4. 위 어느 것도 없으면 미설정([]).

활동 이력(커밋)이 없는 신규 팀원은 추론하지 않는다. 변경 파일 경로가 특정
디렉터리로 몰리지 않고 너무 분산돼 있으면(top 디렉터리 비중이 min_share 미만)
추정하지 않는다 — "추정 안 함"도 결정론적 규칙이지 LLM의 판단이 아니다.
"""
from collections import Counter


def _top_level_dir(path: str) -> str:
    parts = path.split("/")
    return "/".join(parts[:2]) + "/" if len(parts) > 1 else path


def infer_owned_paths(layer0: dict, handle: str, min_share: float = 0.4) -> list[str] | None:
    """커밋 파일 경로 집계 기반 추정. 추정 불가(이력 없음/너무 분산)면 None."""
    commits = [c for c in layer0.get("commits", []) if c.get("author") == handle]
    if not commits:
        return None

    dir_counts: Counter = Counter()
    total = 0
    for c in commits:
        for p in c.get("file_paths", []):
            dir_counts[_top_level_dir(p)] += 1
            total += 1

    if total == 0:
        return None

    ranked = sorted(dir_counts.items(), key=lambda kv: -kv[1])
    top_dir, top_count = ranked[0]
    if top_count / total < min_share:
        return None

    return [d for d, cnt in ranked if cnt / total >= min_share]


def resolve_owned_paths(layer0: dict, member: dict) -> tuple[list[str], bool]:
    """반환: (owned_paths, confirmed 여부).

    우선순위: 확정값 > 담당 선언 파일 > 자동 추론 > 미설정([]).
    """
    if member.get("confirmed"):
        return member.get("owned_paths", []), True

    declared = layer0.get("project", {}).get("codeowners", {}).get(member["handle"])
    if declared:
        return declared, False

    if member.get("owned_paths"):
        return member["owned_paths"], False

    inferred = infer_owned_paths(layer0, member["handle"])
    if inferred:
        return inferred, False

    return [], False
