"""2단계 연동 계약 실행부: BE README의 "0층 데이터 계약"을 실제로 수행한다.

summary_cards.content IS NULL AND status='NORMAL' 인 행을 찾아, 해당 closure_run의
[range_start, range_end) 구간 raw_events로 S-004/S-005 콘텐츠를 생성해 DB에 직접
UPDATE로 써넣는다. BE가 별도 제출용 엔드포인트를 두지 않았으므로(README 참고)
DB 직접 접근이 계약 그 자체다.

BE의 10분 폴링 워커(worker/scheduler.py)는 빈 카드(content=NULL)를 만들기만 하고
채우지는 않는다 — 채우는 건 명시적으로 AI 파트 몫이다. 그래서 이 스크립트도
BE 워커처럼 계속 도는 루프로 동작한다 (기본: 2분 간격. BE보다 짧게 잡아 카드가
생성된 직후 빠르게 채워지게 함). 별도 프로세스로 띄운다 — BE 프로세스 안에
합치지 않는 이유는 OpenAI 키·의존성을 AI 파트 저장소 안에만 두기 위해서다
(지금까지의 저장소·역할 분리를 유지).

사용법:
    python pipeline/run_closure_fill.py            # 계속 실행 (기본 120초 간격)
    python pipeline/run_closure_fill.py --once      # 한 번만 실행하고 종료
    python pipeline/run_closure_fill.py --interval 60
"""
import argparse
import os
import time

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from db_context_builder import build_context_from_db
from s004_team_summary import EvidenceValidationError, generate_team_summary

_PENDING_CARDS_SQL = text(
    """
    SELECT sc.id AS card_id, sc.language, cr.project_id, cr.team_id,
           cr.range_start, cr.range_end
    FROM summary_cards sc
    JOIN closure_runs cr ON cr.id = sc.closure_run_id
    WHERE sc.content IS NULL AND sc.status = 'NORMAL'
    ORDER BY cr.range_end ASC
    """
)

# content IS NULL을 다시 조건에 거는 건, 이 스크립트가 동시에 두 개 떠서 같은
# 카드를 두 번 채우려 할 때 나중 실행이 먼저 실행 결과를 덮어쓰지 않게 하는
# 최소한의 방어다 (본격적인 락은 인스턴스를 하나만 띄운다는 전제 하에 생략).
_UPDATE_CARD_SQL = text(
    "UPDATE summary_cards SET content = :content WHERE id = :card_id AND content IS NULL"
)


def _render_content(result: dict) -> str:
    """headline + 항목 요약을 plain text로 펼친다. FE(TimelineCard.tsx)는
    content를 그대로 <p style=\"white-space:pre-wrap\">에 렌더링하므로 줄바꿈은
    살아있다. 항목별 근거 링크는 BE가 source_event_urls로 별도 표기하므로
    본문엔 넣지 않는다."""
    if result["status"] == "no_activity":
        return result["headline"]

    lines = [result["headline"], ""]
    for item in result["items"]:
        labels = ", ".join(ev["label"] for ev in item["evidence"])
        lines.append(f"- {item['summary']} ({labels})")
    return "\n".join(lines)


def _fill_pending_cards(engine: Engine) -> tuple[int, int]:
    """한 번 순회: 대기 중인 카드를 전부 찾아 채운다. (채운 건수, 스킵 건수) 반환."""
    with engine.connect() as conn:
        pending = conn.execute(_PENDING_CARDS_SQL).mappings().all()

    if not pending:
        return 0, 0

    print(f"채울 카드 {len(pending)}건 발견")
    filled, skipped = 0, 0
    for row in pending:
        try:
            context = build_context_from_db(
                engine, str(row["project_id"]), str(row["team_id"]), row["range_start"], row["range_end"]
            )
            result = generate_team_summary(str(row["team_id"]), row["language"], context=context)
        except EvidenceValidationError as exc:
            print(f"  [SKIP] card={row['card_id']} 근거 검증 실패, content는 NULL로 남김: {exc}")
            skipped += 1
            continue
        except Exception as exc:  # noqa: BLE001 — 카드 1건 실패(OpenAI 네트워크 오류 등)가
            # 배치 전체를 멈추면 안 되므로, 나머지 카드는 계속 처리하고 다음 순회 때 재시도한다.
            print(f"  [SKIP] card={row['card_id']} 예상치 못한 오류, content는 NULL로 남김: {exc}")
            skipped += 1
            continue

        content = _render_content(result)
        with engine.begin() as conn:
            conn.execute(_UPDATE_CARD_SQL, {"content": content, "card_id": row["card_id"]})
        print(f"  [OK] card={row['card_id']} lang={row['language']} -> {len(content)}자")
        filled += 1

    print(f"이번 순회 완료: {filled}건 채움, {skipped}건 스킵(다음 순회 때 재시도)")
    return filled, skipped


def run_forever(engine: Engine, interval_seconds: int) -> None:
    print(f"run_closure_fill 상시 실행 시작 ({interval_seconds}초 간격, Ctrl+C로 종료)")
    while True:
        _fill_pending_cards(engine)
        time.sleep(interval_seconds)


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="한 번만 실행하고 종료 (기본은 계속 실행)")
    parser.add_argument("--interval", type=int, default=120, help="순회 간격(초), 기본 120초")
    args = parser.parse_args()

    load_dotenv()
    database_url = os.environ.get("DATABASE_URL", "postgresql+psycopg://neomeo:neomeo@localhost:5432/neomeo")
    engine = create_engine(database_url)

    if args.once:
        _fill_pending_cards(engine)
    else:
        run_forever(engine, args.interval)


if __name__ == "__main__":
    _main()
