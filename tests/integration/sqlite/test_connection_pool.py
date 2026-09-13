"""WriteExecutor / ReadPool — DB-001's single write connection and
four-connection read pool, against real files and real OS threads
(ADR-036 D3).

The claim: writes are queued through one dedicated worker (in submission
order, never violating `check_same_thread`), reads genuinely use more
than one connection under concurrent load (not merely the appearance of
a pool), and a read connection refuses to write, loudly.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from kang.adapters.sqlite.connection import open_connection, open_read_only_connection
from kang.adapters.sqlite.connection_pool import ReadPool, WriteExecutor


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "kang.db"
    conn = open_connection(path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()
    return path


class TestWriteExecutor:
    def test_start_then_submit_writes_a_real_row(self, db_path):
        async def scenario():
            executor = WriteExecutor(lambda: open_connection(db_path))
            await executor.start()
            try:
                await executor.submit(
                    lambda conn: (
                        conn.execute("INSERT INTO t (value) VALUES ('a')")
                        or conn.commit()
                    )
                )
            finally:
                await executor.stop()

        asyncio.run(scenario())
        conn = open_connection(db_path)
        assert conn.execute("SELECT value FROM t").fetchall() == [("a",)]
        conn.close()

    def test_submissions_run_in_arrival_order(self, db_path):
        async def scenario():
            executor = WriteExecutor(lambda: open_connection(db_path))
            await executor.start()
            order: list[int] = []
            try:
                await asyncio.gather(
                    *(
                        executor.submit(lambda conn, i=i: order.append(i))
                        for i in range(20)
                    )
                )
            finally:
                await executor.stop()
            return order

        order = asyncio.run(scenario())
        # A single dedicated worker + ThreadPoolExecutor's own FIFO queue
        # (DB-001: "queued, explicit transactions") — submission order is
        # run order, even though the calls were issued concurrently from
        # the asyncio side via gather().
        assert order == list(range(20))

    def test_an_exception_in_a_submitted_callable_propagates(self, db_path):
        async def scenario():
            executor = WriteExecutor(lambda: open_connection(db_path))
            await executor.start()
            try:
                with pytest.raises(ValueError, match="boom"):
                    await executor.submit(
                        lambda conn: (_ for _ in ()).throw(ValueError("boom"))
                    )
            finally:
                await executor.stop()

        asyncio.run(scenario())

    def test_stop_shuts_down_and_further_submission_is_refused(self, db_path):
        async def scenario():
            executor = WriteExecutor(lambda: open_connection(db_path))
            await executor.start()
            await executor.stop()
            with pytest.raises(RuntimeError):
                await executor.submit(lambda conn: None)

        asyncio.run(scenario())


class TestReadPool:
    def test_submit_reads_against_a_genuinely_readonly_connection(self, db_path):
        async def scenario():
            pool = ReadPool(lambda: open_read_only_connection(db_path))
            try:
                value = await pool.submit(
                    lambda conn: conn.execute("PRAGMA query_only").fetchone()[0]
                )
            finally:
                await pool.stop()
            return value

        assert asyncio.run(scenario()) == 1

    def test_a_write_attempt_through_the_pool_raises(self, db_path):
        import sqlite3

        async def scenario():
            pool = ReadPool(lambda: open_read_only_connection(db_path))
            try:
                with pytest.raises(sqlite3.OperationalError):
                    await pool.submit(
                        lambda conn: conn.execute("INSERT INTO t (value) VALUES ('x')")
                    )
            finally:
                await pool.stop()

        asyncio.run(scenario())

    def test_concurrent_submissions_genuinely_use_more_than_one_connection(
        self, db_path
    ):
        def _slow_identify(conn):
            time.sleep(0.05)  # a real OS-thread sleep, not asyncio's
            return id(conn)

        async def scenario():
            pool = ReadPool(lambda: open_read_only_connection(db_path), size=4)
            try:
                started = time.monotonic()
                ids = await asyncio.gather(
                    *(pool.submit(_slow_identify) for _ in range(4))
                )
                elapsed = time.monotonic() - started
            finally:
                await pool.stop()
            return ids, elapsed

        ids, elapsed = asyncio.run(scenario())
        # Genuine concurrency, not the appearance of a pool: more than one
        # distinct connection was used, and four 50ms jobs finished in
        # well under 4 * 50ms serialized.
        assert len(set(ids)) > 1, ids
        assert elapsed < 0.15, elapsed

    def test_reads_see_data_the_write_executor_committed(self, db_path):
        async def scenario():
            writer = WriteExecutor(lambda: open_connection(db_path))
            reader = ReadPool(lambda: open_read_only_connection(db_path))
            await writer.start()
            try:
                await writer.submit(
                    lambda conn: (
                        conn.execute("INSERT INTO t (value) VALUES ('committed')")
                        or conn.commit()
                    )
                )
                return await reader.submit(
                    lambda conn: conn.execute(
                        "SELECT value FROM t WHERE value = 'committed'"
                    ).fetchall()
                )
            finally:
                await writer.stop()
                await reader.stop()

        assert asyncio.run(scenario()) == [("committed",)]
