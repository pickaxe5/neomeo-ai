"""S-005: 다국어 직접 생성 — ko/en 각각 0층 데이터에서 독립적으로 원문 생성.

번역 API를 쓰지 않는다. 같은 컨텍스트로 언어별 프롬프트를 따로 호출하고,
결과 사실관계가 어긋나지 않는지 consistency_check로 검증한다.

사용법:
    python src/s005_multilingual_summary.py --team team_seoul
"""
import argparse
import json

from layer0_loader import load_layer0
from s004_team_summary import generate_team_summary
from consistency_check import check_consistency


def generate_bilingual_team_summary(team_id: str, layer0: dict | None = None) -> dict:
    layer0 = layer0 or load_layer0()
    ko_result = generate_team_summary(team_id, "ko", layer0=layer0)
    en_result = generate_team_summary(team_id, "en", layer0=layer0)
    report = check_consistency(ko_result, en_result)

    return {
        "ko": ko_result,
        "en": en_result,
        "consistency": {
            "is_consistent": report.is_consistent,
            "common_evidence_count": len(report.common),
            "only_in_ko": sorted(report.only_in_ko),
            "only_in_en": sorted(report.only_in_en),
        },
    }


def _main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--team", default="team_seoul")
    args = parser.parse_args()

    result = generate_bilingual_team_summary(args.team)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
