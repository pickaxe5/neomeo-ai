"""OpenAI Structured Outputs용 JSON 스키마.

근거 링크 누락을 코드 레벨에서 막기 위해 evidence를 required로 강제한다 (L-004 대응).
"""

TEAM_SUMMARY_SCHEMA = {
    "name": "team_summary_card",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "headline": {
                "type": "string",
                "description": "오늘 팀 활동을 압축한 한 문장",
            },
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": ["change", "decision"],
                            "description": "change: 무엇을 바꿨는지(코드/기능 변경). decision: 여러 대안 중 하나를 선택했거나 논의를 결론지은 의사결정.",
                        },
                        "summary": {
                            "type": "string",
                            "description": "팀 언어로 직접 작성한 요약 문장 1~2개",
                        },
                        "evidence": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label": {
                                        "type": "string",
                                        "description": "예: 'PR #101', 'Issue #55'",
                                    },
                                    "url": {"type": "string"},
                                },
                                "required": ["label", "url"],
                                "additionalProperties": False,
                            },
                            "minItems": 1,
                        },
                    },
                    "required": ["category", "summary", "evidence"],
                    "additionalProperties": False,
                },
                "minItems": 1,
            },
        },
        "required": ["headline", "items"],
        "additionalProperties": False,
    },
}

# B-002: LLM은 "왜 중요한지" 해석 문장만 생성한다. 사실/링크는 B-003·B-004가
# 코드로 이미 확정했으므로, LLM 출력은 입력으로 준 id에 대응하는 설명 텍스트뿐이고
# 링크는 절대 다시 만들지 않는다 (id 매칭 여부는 코드로 검증).
BRIEFING_EXPLANATION_SCHEMA = {
    "name": "briefing_explanations",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "must_respond_explanations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "입력으로 준 thread_id를 그대로 사용"},
                        "why_it_matters": {
                            "type": "string",
                            "description": "이 항목이 왜 인수인계 아이템으로 중요한지 1~2문장",
                        },
                    },
                    "required": ["id", "why_it_matters"],
                    "additionalProperties": False,
                },
            },
            "impact_explanations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "입력으로 준 source_id를 그대로 사용"},
                        "why_it_matters": {
                            "type": "string",
                            "description": "이 변경이 내 작업에 왜 영향을 주는지 1~2문장",
                        },
                    },
                    "required": ["id", "why_it_matters"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["must_respond_explanations", "impact_explanations"],
        "additionalProperties": False,
    },
}

# 팀 진행 상황(브리핑 3단계) 개인화: 같은 team_card를 역할·담당 영역이 다른 여러
# 사람에게 각자 다르게 풀어쓴다. 사실은 team_card가 이미 확정했으므로 LLM은
# "어떤 항목이 이 사람에게 왜 중요한지"를 고르고 설명하는 역할만 한다.
PERSONAL_PROGRESS_SCHEMA = {
    "name": "personal_progress_summaries",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "summaries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "입력으로 준 id를 그대로 사용"},
                        "why_it_matters": {
                            "type": "string",
                            "description": "이 팀 진행 상황이 역할·담당 영역·기획 의도 관점에서 이 사람에게 왜 중요한지 2~4문장",
                        },
                    },
                    "required": ["id", "why_it_matters"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["summaries"],
        "additionalProperties": False,
    },
}
