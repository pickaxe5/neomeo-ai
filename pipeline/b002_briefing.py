"""B-002: 개인 브리핑 온디맨드 생성.

절대 원칙: 개인 브리핑(2층)을 팀 요약(1층)에서 파생시키지 않는다. B-003/B-004는
0층 데이터에서 직접 코드로 판정하고, 1층 팀 요약은 LLM 해석 단계에 "맥락 참고용"
으로만 곁들인다.

3단 우선순위:
  1. 내가 답해야 할 것 (B-003)
  2. 내 작업에 영향 있는 변경 (B-004)
  3. 팀 전체 진행 상황 (1층 요약 발췌 — 여기서는 패스스루만 하고 렌더링은 FE(B-005) 담당)
"""
import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from layer0_loader import load_layer0
from response_check import get_unresponded_for_member
from impact_filter import find_impacts_for_member
from s004_team_summary import generate_team_summary
from schemas import BRIEFING_EXPLANATION_SCHEMA
from briefing_validator import validate_explanation_ids

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
DEFAULT_MODEL = os.environ.get("NEOMEO_MODEL", "gpt-4o-mini")
MAX_ATTEMPTS = 2

SYSTEM_PROMPT_FILES = {
    "ko": "b002_briefing_ko.md",
    "en": "b002_briefing_en.md",
}


def _load_system_prompt(language: str) -> str:
    filename = SYSTEM_PROMPT_FILES.get(language)
    if not filename:
        raise ValueError(f"지원하지 않는 언어: {language}")
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8")


def _member_language(layer0: dict, handle: str) -> str:
    member = next(m for m in layer0["members"] if m["handle"] == handle)
    team = next(t for t in layer0["teams"] if t["team_id"] == member["team_id"])
    return team["language"]


class BriefingValidationError(Exception):
    """id 매칭 검증이 재시도 후에도 실패했을 때. 데모 중에는 캐시된 폴백 브리핑으로 대체."""


def generate_personal_briefing(
    handle: str,
    layer0: dict | None = None,
    model: str = DEFAULT_MODEL,
    since: str | None = None,
) -> dict:
    """since: 이 사용자의 "부재 구간" 시작 시각(마지막 브리핑 열람 시각, ISO 8601).
    명세 F-OOVQZC 기준 — 미응답(B-003)은 시간 무관 현재 상태 판정이라 영향을
    받지 않고, 영향받는 변경(B-004)만 이 시각 이후 활동으로 스코핑된다."""
    load_dotenv()
    layer0 = layer0 or load_layer0()
    language = _member_language(layer0, handle)

    must_respond = get_unresponded_for_member(layer0, handle)
    impacts = find_impacts_for_member(layer0, handle, since=since)

    team_id = next(m for m in layer0["members"] if m["handle"] == handle)["team_id"]
    team_summary = generate_team_summary(team_id, language, layer0=layer0)

    # 이벤트 없는 구간은 LLM 호출 없이 고정 템플릿으로 처리 (비용·안정성, S-006과 동일 원칙)
    if not must_respond and not impacts:
        return {
            "handle": handle,
            "must_respond": [],
            "impacted_by": [],
            "team_summary_excerpt": team_summary,
            "note": "미응답 항목도, 영향받는 변경도 없습니다.",
        }

    mr_payload = [
        {
            "id": item.thread_id,
            "type": item.thread_type,
            "number": item.number,
            "title": item.title,
            "url": item.url,
            "reasons": [r.value for r in item.reasons],
        }
        for item in must_respond
    ]
    impact_payload = [
        {
            "id": f"{item.source_type}:{item.source_id}",
            "source_type": item.source_type,
            "author": item.author,
            "matched_paths": item.matched_paths,
            "title": item.title,
            "url": item.url,
        }
        for item in impacts
    ]

    system_prompt = _load_system_prompt(language)
    user_payload = {
        "must_respond": mr_payload,
        "impacts": impact_payload,
        "team_summary_for_context_only": team_summary,
    }
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                "다음 항목들에 대해 각각 왜 이 사람에게 중요한지 설명을 작성하세요.\n\n"
                + json.dumps(user_payload, ensure_ascii=False, indent=2)
            ),
        },
    ]

    expected_mr_ids = {p["id"] for p in mr_payload}
    expected_impact_ids = {p["id"] for p in impact_payload}

    client = OpenAI()
    problems: list[str] = []
    llm_result = None
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
        llm_result = json.loads(content)

        problems = validate_explanation_ids(llm_result, expected_mr_ids, expected_impact_ids)
        if not problems:
            break
        messages.append({"role": "assistant", "content": content})
    else:
        raise BriefingValidationError(
            f"{MAX_ATTEMPTS}회 시도 후에도 id 검증 실패:\n" + "\n".join(problems)
        )

    mr_explanations = {e["id"]: e["why_it_matters"] for e in llm_result["must_respond_explanations"]}
    impact_explanations = {e["id"]: e["why_it_matters"] for e in llm_result["impact_explanations"]}

    return {
        "handle": handle,
        "must_respond": [
            {**p, "why_it_matters": mr_explanations[p["id"]]} for p in mr_payload
        ],
        "impacted_by": [
            {**p, "why_it_matters": impact_explanations[p["id"]]} for p in impact_payload
        ],
        "team_summary_excerpt": team_summary,
    }


def _main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--handle", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    result = generate_personal_briefing(args.handle, model=args.model)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
