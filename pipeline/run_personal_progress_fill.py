"""B-002 확장 2 실행부: BE의 personal_progress_summaries.content(NULL)를 채운다
(브리핑 3단계, 팀 진행 상황의 개인화 버전).

같은 team_card(summary_cards.content)를 읽는 사람마다, 그 사람의 역할·담당
영역·프로젝트 기획 문서를 반영해 "이게 나한테 왜 중요한지"를 다르게 풀어쓴다.
사실 판정은 이미 team_card가 끝냈으므로 여기서는 해석만 개인화한다.

run_briefing_fill.py와 동일한 계약 패턴: NULL인 행을 찾아 UPDATE로 채운다.
BE가 personal_progress_summaries 테이블과, 마감(ClosureRun) 시 프로젝트 참여
멤버 수만큼 NULL row를 만드는 로직을 추가한 뒤에만 실제로 값이 채워진다 —
테이블이 없으면 컨텍스트 빌더의 조회 자체가 실패한다.

사용법:
    python pipeline/run_personal_progress_fill.py            # 계속 실행 (기본 120초 간격)
    python pipeline/run_personal_progress_fill.py --once      # 한 번만 실행하고 종료
"""
import argparse
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from personal_progress_context_builder import build_pending_groups
from schemas import PERSONAL_PROGRESS_SCHEMA

DEFAULT_MODEL = os.environ.get("NEOMEO_MODEL", "gpt-4o-mini")
MAX_ATTEMPTS = 2

SYSTEM_PROMPT_FILES = {"ko": "b002_personal_progress_ko.md", "en": "b002_personal_progress_en.md"}

_UPDATE_SQL = text(
    "UPDATE personal_progress_summaries SET content = :why WHERE id = :row_id AND content IS NULL"
)


def _load_system_prompt(language: str) -> str:
    from s004_team_summary import PROMPTS_DIR as prompts_dir

    return (prompts_dir / SYSTEM_PROMPT_FILES[language]).read_text(encoding="utf-8")


def _validate_ids(result: dict, expected_ids: set[str]) -> list[str]:
    got_ids = {s["id"] for s in result.get("summaries", [])}
    problems = []
    if got_ids != expected_ids:
        missing = expected_ids - got_ids
        extra = got_ids - expected_ids
        if missing:
            problems.append(f"누락된 id: {sorted(missing)}")
        if extra:
            problems.append(f"입력에 없는 id: {sorted(extra)}")
    return problems


def _generate_summaries(group: dict, language: str, model: str) -> dict[str, str]:
    system_prompt = _load_system_prompt(language)
    payload = {
        "team_card": group["card_content"],
        "planning_document": group["planning_document"],
        "profiles": group["profiles"],
    }
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                "다음 팀 요약을 각 프로필의 관점에서 개인화해서 작성하세요.\n\n"
                + json.dumps(payload, ensure_ascii=False, indent=2)
            ),
        },
    ]
    expected_ids = {p["id"] for p in group["profiles"]}

    client = OpenAI()
    problems: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if problems:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "방금 응답의 id가 입력과 일치하지 않습니다. 입력으로 준 id를 정확히 "
                        "그대로 사용해서 다시 작성하세요.\n\n" + "\n".join(problems)
                    ),
                }
            )
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_schema", "json_schema": PERSONAL_PROGRESS_SCHEMA},
        )
        content = response.choices[0].message.content
        result = json.loads(content)
        problems = _validate_ids(result, expected_ids)
        if not problems:
            return {s["id"]: s["why_it_matters"] for s in result["summaries"]}
        messages.append({"role": "assistant", "content": content})

    raise RuntimeError(f"{MAX_ATTEMPTS}회 시도 후에도 id 검증 실패:\n" + "\n".join(problems))


def _fill_pending_groups(engine: Engine, model: str) -> tuple[int, int]:
    groups = build_pending_groups(engine)
    if not groups:
        return 0, 0

    filled, skipped = 0, 0
    for (closure_run_id, language), group in groups.items():
        print(f"[{closure_run_id[:8]}/{language}] 채울 프로필 {len(group['profiles'])}건 발견")
        try:
            summaries = _generate_summaries(group, language, model)
        except Exception as exc:  # noqa: BLE001 — 그룹 1건 실패가 나머지를 막으면 안 됨
            print(f"  [SKIP] 예상치 못한 오류, {len(group['profiles'])}건 다음 순회로 미룸: {exc}")
            skipped += len(group["profiles"])
            continue

        with engine.begin() as conn:
            for profile in group["profiles"]:
                why = summaries.get(profile["id"])
                if not why:
                    skipped += 1
                    continue
                conn.execute(_UPDATE_SQL, {"why": why, "row_id": profile["id"]})
                filled += 1
        print(f"  [OK] {len(group['profiles'])}건 채움")

    print(f"이번 순회 완료: {filled}건 채움, {skipped}건 스킵(다음 순회 때 재시도)")
    return filled, skipped


def run_forever(engine: Engine, model: str, interval_seconds: int) -> None:
    print(f"run_personal_progress_fill 상시 실행 시작 ({interval_seconds}초 간격, Ctrl+C로 종료)")
    while True:
        _fill_pending_groups(engine, model)
        time.sleep(interval_seconds)


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="한 번만 실행하고 종료 (기본은 계속 실행)")
    parser.add_argument("--interval", type=int, default=120, help="순회 간격(초), 기본 120초")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    load_dotenv()
    database_url = os.environ.get("DATABASE_URL", "postgresql+psycopg://neomeo:neomeo@localhost:5432/neomeo")
    engine = create_engine(database_url)

    if args.once:
        _fill_pending_groups(engine, args.model)
    else:
        run_forever(engine, args.model, args.interval)


if __name__ == "__main__":
    _main()
