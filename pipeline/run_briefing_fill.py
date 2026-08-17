"""B-002 확장 연동 계약 실행부: BE의 unanswered_items.why_it_matters(NULL)를 채운다.

판정(B-003, 무엇이 미응답인지)은 BE의 unanswered_service.py가 이미 끝냈고,
여기서는 각 항목에 "왜 중요한지" 한 줄 설명만 LLM으로 생성해 붙인다.
run_closure_fill.py와 동일한 계약 패턴: NULL인 행을 찾아 UPDATE로 채운다.

BE가 unanswered_items에 why_it_matters(nullable text) 컬럼과, BriefingItem
스키마에 대응 필드를 추가한 뒤에만 실제로 값이 채워진다 — 컬럼이 없으면
UPDATE 자체가 실패한다.

사용법:
    python pipeline/run_briefing_fill.py            # 계속 실행 (기본 120초 간격)
    python pipeline/run_briefing_fill.py --once      # 한 번만 실행하고 종료
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

from briefing_validator import validate_explanation_ids
from s004_team_summary import PROMPTS_DIR
from schemas import BRIEFING_EXPLANATION_SCHEMA
from unanswered_context_builder import build_pending_items

DEFAULT_MODEL = os.environ.get("NEOMEO_MODEL", "gpt-4o-mini")
MAX_ATTEMPTS = 2

SYSTEM_PROMPT_FILES = {"ko": "b002_briefing_ko.md", "en": "b002_briefing_en.md"}

_UPDATE_SQL = text(
    "UPDATE unanswered_items SET why_it_matters = :why WHERE id = :item_id AND why_it_matters IS NULL"
)


def _load_system_prompt(language: str) -> str:
    return (PROMPTS_DIR / SYSTEM_PROMPT_FILES[language]).read_text(encoding="utf-8")


def _generate_explanations(items: list[dict], language: str, model: str) -> dict[str, str]:
    system_prompt = _load_system_prompt(language)
    mr_payload = [
        {
            "id": item["id"],
            "type": item["type"],
            "title": item["title"],
            "url": item["url"],
            "reasons": [item["signal_type"]],
        }
        for item in items
    ]
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                "다음 항목들에 대해 각각 왜 이 사람에게 중요한지 설명을 작성하세요.\n\n"
                + json.dumps({"must_respond": mr_payload, "impacts": []}, ensure_ascii=False, indent=2)
            ),
        },
    ]
    expected_ids = {p["id"] for p in mr_payload}

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
            response_format={"type": "json_schema", "json_schema": BRIEFING_EXPLANATION_SCHEMA},
        )
        content = response.choices[0].message.content
        result = json.loads(content)
        problems = validate_explanation_ids(result, expected_ids, set())
        if not problems:
            return {e["id"]: e["why_it_matters"] for e in result["must_respond_explanations"]}
        messages.append({"role": "assistant", "content": content})

    raise RuntimeError(f"{MAX_ATTEMPTS}회 시도 후에도 id 검증 실패:\n" + "\n".join(problems))


def _fill_pending_items(engine: Engine, model: str) -> tuple[int, int]:
    """한 번 순회: 언어별로 묶어 배치 호출 후 채운다. (채운 건수, 스킵 건수) 반환."""
    grouped = build_pending_items(engine)
    if not grouped:
        return 0, 0

    filled, skipped = 0, 0
    for language, items in grouped.items():
        print(f"[{language}] 채울 항목 {len(items)}건 발견")
        try:
            explanations = _generate_explanations(items, language, model)
        except Exception as exc:  # noqa: BLE001 — 언어 그룹 1건 실패가 나머지를 막으면 안 됨
            print(f"  [SKIP] language={language} 예상치 못한 오류, {len(items)}건 다음 순회로 미룸: {exc}")
            skipped += len(items)
            continue

        with engine.begin() as conn:
            for item in items:
                why = explanations.get(item["id"])
                if not why:
                    skipped += 1
                    continue
                conn.execute(_UPDATE_SQL, {"why": why, "item_id": item["id"]})
                filled += 1
        print(f"  [OK] {language} {len(items)}건 채움")

    print(f"이번 순회 완료: {filled}건 채움, {skipped}건 스킵(다음 순회 때 재시도)")
    return filled, skipped


def run_forever(engine: Engine, model: str, interval_seconds: int) -> None:
    print(f"run_briefing_fill 상시 실행 시작 ({interval_seconds}초 간격, Ctrl+C로 종료)")
    while True:
        _fill_pending_items(engine, model)
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
        _fill_pending_items(engine, args.model)
    else:
        run_forever(engine, args.model, args.interval)


if __name__ == "__main__":
    _main()
