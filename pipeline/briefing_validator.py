"""B-002 해석 결과의 id 매칭 검증 (규칙 기반, 결정론적).

LLM은 입력으로 준 id(thread_id / source_id)에 대해서만 설명을 붙여야 한다.
id가 누락되거나, 존재하지 않는 id를 새로 만들어내면 안 된다 — 만들어낸 id는
곧 존재하지 않는 항목에 대한 서술일 위험이 있다.
"""


def validate_explanation_ids(llm_result: dict, expected_must_respond_ids: set, expected_impact_ids: set) -> list[str]:
    problems = []

    got_mr_ids = {e["id"] for e in llm_result.get("must_respond_explanations", [])}
    if got_mr_ids != expected_must_respond_ids:
        missing = expected_must_respond_ids - got_mr_ids
        extra = got_mr_ids - expected_must_respond_ids
        if missing:
            problems.append(f"must_respond_explanations에 누락된 id: {sorted(missing)}")
        if extra:
            problems.append(f"must_respond_explanations에 존재하지 않는 id가 포함됨: {sorted(extra)}")

    got_imp_ids = {e["id"] for e in llm_result.get("impact_explanations", [])}
    if got_imp_ids != expected_impact_ids:
        missing = expected_impact_ids - got_imp_ids
        extra = got_imp_ids - expected_impact_ids
        if missing:
            problems.append(f"impact_explanations에 누락된 id: {sorted(missing)}")
        if extra:
            problems.append(f"impact_explanations에 존재하지 않는 id가 포함됨: {sorted(extra)}")

    for e in llm_result.get("must_respond_explanations", []) + llm_result.get("impact_explanations", []):
        if not e.get("why_it_matters", "").strip():
            problems.append(f"id={e.get('id')} 의 why_it_matters가 비어 있습니다.")

    return problems
