"""근거 링크 정확성 검증 (규칙 기반, 결정론적).

LLM이 "근거 링크가 있다"까지는 잘 지키지만, 그 링크가 실제로 올바른 사실을
가리키는지는 보장하지 않는다. 실제로 두 종류의 실패를 확인함:
  1. url 자체가 컨텍스트에 없는 엉뚱한 값 (다른 커밋의 URL을 잘못 붙임)
  2. url은 맞는데 label이 다른 걸 가리킴 (label="Commit a1b2c3d"인데 url은
     i7j8k9l 커밋) — url만 검증해서는 못 잡는 케이스.
두 가지를 모두 코드로 확인한다. summary 문장의 의미가 url이 가리키는 사실과
맞는지까지는 검증하지 않는다 — 그건 사람이 최종 리뷰할 영역.
"""


def _url_metadata(context: dict) -> dict:
    """url -> {"type", "number"|"sha"} 매핑. label이 이 정보를 담고 있는지 대조하는 데 쓴다."""
    meta = {}
    for t in context.get("threads", []):
        meta[t["url"]] = {"type": t["type"], "number": t["number"]}
    for c in context.get("commits", []):
        meta[c["url"]] = {"type": "commit", "sha": c["sha"]}
    return meta


def validate_evidence(result: dict, context: dict) -> list[str]:
    """근거 문제 목록(문제 설명 문자열)을 반환. 비어 있으면 통과."""
    url_meta = _url_metadata(context)
    problems = []
    for idx, item in enumerate(result.get("items", [])):
        for ev in item.get("evidence", []):
            url = ev.get("url")
            label = ev.get("label", "")
            tag = f'item[{idx}] summary="{item.get("summary", "")[:40]}..." evidence label="{label}" url={url}'

            meta = url_meta.get(url)
            if meta is None:
                problems.append(f"{tag} — url이 이번 윈도우 컨텍스트에 존재하지 않습니다.")
                continue

            if meta["type"] == "commit":
                identifiers = {meta["sha"], meta["sha"][:7]}
                display = meta["sha"]
            else:
                identifiers = {f"#{meta['number']}", str(meta["number"])}
                display = f"#{meta['number']}"
            if not any(ident in label for ident in identifiers):
                problems.append(
                    f"{tag} — label이 url이 실제로 가리키는 대상({meta['type']} {display})과 "
                    f"일치하지 않습니다."
                )
    return problems
