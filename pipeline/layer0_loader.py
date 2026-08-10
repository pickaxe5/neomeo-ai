"""0층 구조화 데이터 로더.

BE(neomeo-web)가 넘겨주는 실제 스키마가 확정되기 전까지는 pipeline/fixtures/
mock_layer0.json을 사용한다. 실제 연동 시에는 load_layer0()의 소스만 교체하면
되도록 파일 I/O를 여기에만 둔다.
"""
import json
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent / "fixtures" / "mock_layer0.json"


def load_layer0(path: Path = DEFAULT_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
