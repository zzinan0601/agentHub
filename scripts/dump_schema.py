"""모델에서 CREATE TABLE 문을 뽑아 화면에 출력한다.

`core/models.py` 를 고쳤다면 이 명령으로 뽑은 결과가 `sql/01_schema.sql` 과
같은지 확인한다. 손으로 옮겨 적으면 언젠가 반드시 어긋나고, 어긋난 것은
폐쇄망에 반입한 뒤에야 드러난다.

    python scripts/dump_schema.py

sql/01_schema.sql 은 이 출력에 주석과 IF NOT EXISTS 를 더한 것이다.
컬럼과 제약이 같은지만 보면 된다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.dialects import postgresql  # noqa: E402
from sqlalchemy.schema import CreateIndex, CreateTable  # noqa: E402

from core.models import Base  # noqa: E402

# 외래키가 가리키는 테이블이 먼저 오도록 SQLAlchemy 가 정렬해 준다.
DIALECT = postgresql.dialect()


def main() -> int:
    for table in Base.metadata.sorted_tables:
        print(str(CreateTable(table).compile(dialect=DIALECT)).strip() + ";")
        for index in table.indexes:
            print(str(CreateIndex(index).compile(dialect=DIALECT)).strip() + ";")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
