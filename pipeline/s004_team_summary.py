"""S-004: 팀 요약 카드 생성 — 0층 데이터에서 팀 언어로 직접 생성 (번역 아님).

사용법:
    python src/s004_team_summary.py --team team_seoul --lang ko
"""
import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from layer0_loader import load_layer0
from team_context import build_team_window_context
from schemas import TEAM_SUMMARY_SCHEMA
from evidence_validator import validate_evidence
from response_check import check_threads
from card_metadata import NO_ACTIVITY_HEADLINE, activity_counts, source_manifest

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
DEFAULT_MODEL = os.environ.get("NEOMEO_MODEL", "gpt-4o-mini")
MAX_ATTEMPTS = 2  # 근거 링크 검증 실패 시 1회 재시도

# S-005에서 언어별 프롬프트가 늘어날 것을 대비해 매핑으로 관리한다.
SYSTEM_PROMPT_FILES = {
    "ko": "s004_team_summary_ko.md",
    "en": "s004_team_summary_en.md",
}


def _load_system_prompt(language: str) -> str:
    filename = SYSTEM_PROMPT_FILES.get(language)
    if not filename:
        raise ValueError(f"지원하지 않는 언어: {language}")
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8")


class EvidenceValidationError(Exception):
    """근거 링크 검증이 재시도 후에도 실패했을 때. 호출부는 이 경우 캐시된
    폴백 브리핑으로 대체해야 한다 (데모 중 라이브 생성 실패 대비)."""


def _unresolved_question_payload(item) -> dict:
    return {
        "handle": item.handle,
        "assigned_team": item.assigned_team,
        "thread_type": item.thread_type,
        "number": item.number,
        "title": item.title,
        "url": item.url,
        "reasons": [r.value for r in item.reasons],
    }


def generate_team_summary(
    team_id: str,
    language: str = "ko",
    layer0: dict | None = None,
    context: dict | None = None,
    model: str = DEFAULT_MODEL,
) -> dict:
    """context를 직접 넘기면(BE DB 연동 경로, db_context_builder 참고) mock layer0를
    거치지 않는다. context는 {"window": {...}, "commits": [...], "threads": [...]} 형태여야
    한다 — window는 메타데이터 표기용이라 실제 필터링에는 쓰이지 않는다."""
    load_dotenv()
    if context is None:
        layer0 = layer0 or load_layer0()
        context = build_team_window_context(layer0, team_id)

    metadata = {"window": context["window"], "activity_counts": activity_counts(context)}
    # 미응답 질문은 B-003이 코드로 이미 판정한 결과를 그대로 붙인다 (LLM 관여 없음).
    unresolved_questions = [_unresolved_question_payload(i) for i in check_threads(context["threads"])]

    if not context["commits"] and not context["threads"]:
        return {
            "team_id": team_id,
            "language": language,
            "status": "no_activity",
            "headline": NO_ACTIVITY_HEADLINE.get(language, NO_ACTIVITY_HEADLINE["ko"]),
            "items": [],
            "unresolved_questions": unresolved_questions,
            "metadata": metadata,
            "source_manifest": [],
        }

    system_prompt = _load_system_prompt(language)
    context_block = json.dumps(context, ensure_ascii=False, indent=2)
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                "다음은 이번 윈도우의 0층 구조화 데이터입니다. 이 데이터에 있는 사실만 "
                "사용해서 팀 요약 카드를 작성하세요.\n\n" + context_block
            ),
        },
    ]

    client = OpenAI()
    problems: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if problems:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "방금 응답의 evidence 링크가 컨텍스트의 실제 PR/이슈/커밋 URL과 "
                        "일치하지 않습니다. 아래 문제를 고쳐서 다시 작성하세요. summary와 "
                        "evidence가 같은 사실을 가리키도록 정확히 매칭하세요.\n\n"
                        + "\n".join(problems)
                    ),
                }
            )

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_schema", "json_schema": TEAM_SUMMARY_SCHEMA},
        )
        content = response.choices[0].message.content
        result = json.loads(content)

        problems = validate_evidence(result, context)
        if not problems:
            return {
                "team_id": team_id,
                "language": language,
                "status": "ok",
                "headline": result["headline"],
                "items": result["items"],
                "unresolved_questions": unresolved_questions,
                "metadata": metadata,
                "source_manifest": source_manifest(context),
            }

        messages.append({"role": "assistant", "content": content})

    raise EvidenceValidationError(
        f"{MAX_ATTEMPTS}회 시도 후에도 근거 링크 검증 실패:\n" + "\n".join(problems)
    )


def _main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--team", default="team_seoul")
    parser.add_argument("--lang", default="ko")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    result = generate_team_summary(args.team, args.lang, model=args.model)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
