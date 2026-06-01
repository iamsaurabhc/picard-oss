import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Workspace
from app.services.constraint_planner import Constraint
from app.services.entity_index import intersect_page_sets, lookup_pages_for_constraint


@pytest.mark.slow
def test_carp_scale_intersection(tmp_path):
    out = tmp_path / "scale.db"
    script = Path(__file__).resolve().parents[1] / "scripts" / "generate_scale_fixture.py"
    subprocess.run(
        [sys.executable, str(script), "--pages", "1000", "--out", str(out)],
        check=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )

    engine = create_engine(
        f"sqlite:///{out}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Session = sessionmaker(bind=engine)
    db = Session()
    ws_id = db.scalar(select(Workspace.id))
    constraints = [
        Constraint("party", "abc", ["ABC"]),
        Constraint("date", "2019-05-18", ["18/05/2019"]),
        Constraint("condition", "condition c", ["Condition C"]),
    ]
    t0 = time.perf_counter()
    sets = [lookup_pages_for_constraint(db, ws_id, c.type, c.canonical, None) for c in constraints]
    pages = intersect_page_sets(sets)
    elapsed = (time.perf_counter() - t0) * 1000
    db.close()
    assert len(pages) >= 1
    assert elapsed < 500
