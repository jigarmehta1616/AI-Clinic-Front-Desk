"""Print PostgreSQL DDL for the current models (used to freeze migration revisions without a live DB).

Usage: python scripts/dump_ddl.py [table ...]
"""

import sys

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from clinicdesk.models import Base

wanted = set(sys.argv[1:])
dialect = postgresql.dialect()
for table in Base.metadata.sorted_tables:
    if wanted and table.name not in wanted:
        continue
    print(str(CreateTable(table).compile(dialect=dialect)).strip() + ";\n")
    for idx in sorted(table.indexes, key=lambda i: i.name or ""):
        print(str(CreateIndex(idx).compile(dialect=dialect)).strip() + ";\n")
