"""S-005: ko/en 독립 생성 결과의 사실관계 일관성 검증 (규칙 기반, 결정론적).

번역이 아니라 언어별로 각각 생성하기 때문에, 같은 0층 데이터를 보고도 두 언어
버전이 서로 다른 사실을 언급하거나 누락할 위험이 있다. 각 언어 버전은 이미
evidence_validator를 통과했으므로 (모든 evidence.url이 컨텍스트에 실존) 두
결과에서 사용된 evidence url 집합을 비교하는 것만으로 "같은 근거를 참조하는지"
확인할 수 있다.

완전히 같은 항목 개수/구성일 필요는 없다 (언어별로 압축 방식이 다를 수 있음).
다만 한쪽에만 있고 다른 쪽엔 전혀 없는 근거가 있다면, 핵심 사실이 한 언어에서
빠졌을 가능성이 있으므로 경고로 보고한다.
"""
from dataclasses import dataclass


@dataclass
class ConsistencyReport:
    common: set
    only_in_ko: set
    only_in_en: set

    @property
    def is_consistent(self) -> bool:
        return not self.only_in_ko and not self.only_in_en


def _evidence_urls(result: dict) -> set:
    return {
        ev["url"]
        for item in result.get("items", [])
        for ev in item.get("evidence", [])
    }


def check_consistency(ko_result: dict, en_result: dict) -> ConsistencyReport:
    ko_urls = _evidence_urls(ko_result)
    en_urls = _evidence_urls(en_result)
    return ConsistencyReport(
        common=ko_urls & en_urls,
        only_in_ko=ko_urls - en_urls,
        only_in_en=en_urls - ko_urls,
    )
