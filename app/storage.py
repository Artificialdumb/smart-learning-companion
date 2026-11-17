"""SQLite-backed batch snapshots and teacher adjustments."""

import json
import sqlite3
from contextlib import closing

from app.contracts import ContractError, encode_json, with_run
from app.diagnosis.followup import evaluate_followup, followup_view
from app.recommendations import validate_adjustment

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    run_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS active_batch (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    run_id TEXT NOT NULL REFERENCES batches(run_id)
);
CREATE TABLE IF NOT EXISTS adjustments (
    run_id TEXT NOT NULL REFERENCES batches(run_id),
    plan_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    activities TEXT NOT NULL,
    PRIMARY KEY (run_id, plan_id)
);
CREATE TABLE IF NOT EXISTS followups (
    run_id TEXT NOT NULL REFERENCES batches(run_id),
    student_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    indicator_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    result TEXT NOT NULL,
    PRIMARY KEY (run_id, student_id, node_id, indicator_id)
);
"""


def missing(code, identifier):
    return ContractError(code, f"找不到对应数据（{identifier}）。", 404)


def plan_view(run_id, plan, adjustment=None):
    original = plan["activities"]
    effective, version = adjustment if adjustment else (original, 0)
    return with_run(run_id, {
        "plan_id": plan["plan_id"],
        "student_id": plan["student_id"],
        "node_id": plan["node_id"],
        "original_activities": original,
        "effective_activities": effective,
        "adjustment_version": version,
        "empty_reason": plan["empty_reason"],
    })


class Store:
    def __init__(self, path):
        self.path = path

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        try:
            db.execute("PRAGMA foreign_keys = ON")
            db.executescript(SCHEMA)
        except sqlite3.Error:
            db.close()
            raise
        return db

    def publish(self, batch):
        run_id = batch["manifest"]["run_id"]
        payload = encode_json(batch)
        with closing(self.connect()) as db, db:
            db.execute("INSERT INTO batches VALUES (?, ?)", (run_id, payload))
            db.execute("INSERT INTO active_batch VALUES (1, ?) ON CONFLICT DO UPDATE SET run_id=excluded.run_id",
                       (run_id,))

    def load(self, db, run_id):
        row = db.execute("SELECT payload FROM batches WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise missing("run_not_found", run_id)
        return json.loads(row[0])

    def current(self):
        with closing(self.connect()) as db:
            db.execute("BEGIN")
            row = db.execute("SELECT run_id FROM active_batch WHERE singleton = 1").fetchone()
            if row is None:
                raise ContractError("no_active_run", "暂无可用批次。请先运行 build 导入数据。", 503)
            return self.load(db, row[0])

    def batch(self, run_id):
        with closing(self.connect()) as db:
            return self.load(db, run_id)

    def current_adjustment(self, db, run_id, plan_id):
        row = db.execute("SELECT activities, version FROM adjustments WHERE run_id = ? AND plan_id = ?",
                         (run_id, plan_id)).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    def plan(self, run_id, plan):
        with closing(self.connect()) as db:
            return plan_view(run_id, plan, self.current_adjustment(db, run_id, plan["plan_id"]))

    def adjust(self, run_id, plan_id, expected_version, edits):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            batch = self.load(db, run_id)
            plan = batch["plans"].get(plan_id)
            if plan is None:
                raise missing("plan_not_found", plan_id)
            current = self.current_adjustment(db, run_id, plan_id)
            version = current[1] if current else 0
            if expected_version != version:
                raise ContractError("version_conflict", "计划已更新。请读取最新版本后再保存。", 409,
                                    {"adjustment_version": version})
            activities = validate_adjustment(plan, edits, batch["catalog"])
            db.execute("""
                INSERT INTO adjustments VALUES (?, ?, ?, ?)
                ON CONFLICT (run_id, plan_id) DO UPDATE SET
                    version=excluded.version, activities=excluded.activities
                """, (run_id, plan_id, version + 1, encode_json(activities)))
            return plan_view(run_id, plan, (activities, version + 1))

    def snapshot(self, run_id):
        with closing(self.connect()) as db:
            db.execute("BEGIN")
            batch = self.load(db, run_id)
            adjustments = {
                plan_id: (json.loads(activities), version)
                for plan_id, version, activities in db.execute(
                    "SELECT plan_id, version, activities FROM adjustments WHERE run_id = ?", (run_id,)
                )
            }
            plans = [plan_view(run_id, plan, adjustments.get(pid)) for pid, plan in batch["plans"].items()]
            batch["followups"] = [with_run(run_id, {
                "student_id": student, "node_id": node, "indicator_id": indicator,
                "version": version, "result": json.loads(result),
            }) for student, node, indicator, version, result in db.execute(
                "SELECT student_id, node_id, indicator_id, version, result FROM followups "
                "WHERE run_id = ? ORDER BY student_id, node_id, indicator_id", (run_id,)
            )]
            return batch, plans

    def current_followup(self, db, run_id, student_id, node_id, indicator_id):
        row = db.execute(
            "SELECT version, result FROM followups WHERE run_id = ? AND student_id = ? "
            "AND node_id = ? AND indicator_id = ?", (run_id, student_id, node_id, indicator_id),
        ).fetchone()
        return {"version": row[0], "result": json.loads(row[1])} if row else None

    def followup(self, run_id, student_id, node_id, indicator_id):
        with closing(self.connect()) as db:
            db.execute("BEGIN")
            batch = self.load(db, run_id)
            saved = self.current_followup(db, run_id, student_id, node_id, indicator_id)
            return with_run(run_id, followup_view(batch, student_id, node_id, indicator_id, saved))

    def save_followup(self, run_id, student_id, node_id, indicator_id, expected_version, probe_version, answers):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            batch = self.load(db, run_id)
            saved = self.current_followup(db, run_id, student_id, node_id, indicator_id)
            version = saved["version"] if saved else 0
            if expected_version != version:
                raise ContractError("version_conflict", "追问记录已更新，请重新打开后再提交。", 409)
            result = evaluate_followup(batch, student_id, node_id, indicator_id, probe_version, answers)
            db.execute(
                "INSERT INTO followups VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (run_id, student_id, node_id, indicator_id) DO UPDATE SET "
                "version=excluded.version, result=excluded.result",
                (run_id, student_id, node_id, indicator_id, version + 1, encode_json(result)),
            )
            return with_run(run_id, followup_view(batch, student_id, node_id, indicator_id,
                                                 {"version": version + 1, "result": result}))
