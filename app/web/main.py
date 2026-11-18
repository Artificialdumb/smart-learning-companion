"""Local FastAPI application for the teacher workflow."""

import os
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from app._analysis import index, rubric_points
from app.cli import DEFAULT_DB
from app.contracts import ContractError, with_run
from app.diagnosis.paths import learning_paths
from app.recommendations import plan_id
from app.storage import Store, missing
from app.web.access import Access, load_accounts, require_access

STATIC = Path(__file__).with_name("static")
QueryId = Annotated[str, Query(min_length=1)]


class ActivityEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    recommendation_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    hints: list[str]
    recheck_condition: str


class PlanAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_version: int = Field(ge=0)
    activities: list[ActivityEdit]


class FollowupAnswers(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_version: int = Field(ge=0)
    probe_version: str = Field(min_length=1, max_length=60)
    answers: dict[str, str] = Field(min_length=3, max_length=4)


def lookup(values, key, code):
    if key not in values:
        raise missing(code, key)
    return values[key]


def pick(row, *fields):
    return {field: row[field] for field in fields if field in row}


def public_resource(row):
    return pick(row, "resource_id", "resource_type", "title", "indicator_ids", "source_locator")


def create_app(db_path=None):
    store = Store(Path(db_path or os.environ.get("STUDY_DB", DEFAULT_DB)))
    access_file = os.environ.get("STUDY_ACCESS_FILE")
    authenticate = require_access(load_accounts(access_file) if access_file else None)
    Actor = Annotated[Access, Depends(authenticate)]
    app = FastAPI(title="智慧学伴", dependencies=[Depends(authenticate)])
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.middleware("http")
    async def private_response(request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ContractError)
    def contract_error(request: Request, error: ContractError):
        payload = {"code": error.code, "message": str(error)}
        if error.details is not None:
            payload["details"] = error.details
        return JSONResponse(status_code=error.status, content={"error": payload})

    @app.exception_handler(RequestValidationError)
    def request_error(request: Request, error: RequestValidationError):
        return JSONResponse(status_code=422, content={"error": {
            "code": "invalid_request",
            "message": "请求参数或调整字段不符合接口约定。",
            "details": [pick(e, "loc", "msg") for e in error.errors()],
        }})

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/context")
    def context(actor: Actor):
        batch = store.current()
        catalog = batch["catalog"]
        students = [row for row in batch["students"].values() if actor.can_view(row)]
        return with_run(batch["manifest"]["run_id"], {
            "students": students,
            "classes": sorted({row["class_id"] for row in students}),
            "can_compare": actor.can_compare({row["class_id"] for row in batch["students"].values()}),
            "can_adjust": actor.role in {"teacher", "demo"},
            "nodes": list(index(catalog["nodes"], "node_id").values()),
            "topics": list(index(catalog["topics"], "topic_id").values()),
            "indicators": list(index(catalog["indicators"], "indicator_id").values()),
        })

    @app.get("/api/catalog")
    def catalog(run_id: QueryId):
        data = store.batch(run_id)["catalog"]
        return with_run(run_id, {
            **pick(data, "learning_relations"),
            "topics": list(index(data["topics"], "topic_id").values()),
            "indicators": list(index(data["indicators"], "indicator_id").values()),
            "nodes": list(index(data["nodes"], "node_id").values()),
            "items": [
                pick(row, "item_id", "indicator_ids", "item_type", "prompt", "options", "max_score")
                for row in index(data["items"], "item_id").values()
            ],
            "resources": [public_resource(row) for row in data["resources"]],
        })

    @app.get("/api/students/{student_id}/diagnosis")
    def diagnosis(student_id: str, run_id: QueryId, node_id: QueryId, actor: Actor):
        batch = store.batch(run_id)
        actor.require_student(batch, student_id)
        reports = lookup(batch["diagnoses"], student_id, "student_not_found")
        return with_run(run_id, lookup(reports, node_id, "node_not_found"))

    @app.get("/api/students/{student_id}/learning-paths")
    def paths(student_id: str, run_id: QueryId, node_id: QueryId, actor: Actor):
        batch = store.batch(run_id)
        actor.require_student(batch, student_id)
        reports = lookup(batch["diagnoses"], student_id, "student_not_found")
        lookup(reports, node_id, "node_not_found")
        return with_run(run_id, learning_paths(batch["catalog"], reports, node_id))

    @app.get("/api/students/{student_id}/followups/{indicator_id}")
    def followup(student_id: str, indicator_id: str, run_id: QueryId, node_id: QueryId, actor: Actor):
        return store.followup(run_id, student_id, node_id, indicator_id, authorize=actor.require_student)

    @app.put("/api/students/{student_id}/followups/{indicator_id}")
    def answer_followup(student_id: str, indicator_id: str, run_id: QueryId, node_id: QueryId,
                        request: FollowupAnswers, actor: Actor):
        return store.save_followup(run_id, student_id, node_id, indicator_id, request.expected_version,
                                   request.probe_version, request.answers, authorize=actor.require_student)

    @app.get("/api/classes/compare")
    def compare(run_id: QueryId, node_id: QueryId, actor: Actor):
        batch = store.batch(run_id)
        if not actor.can_compare({row["class_id"] for row in batch["students"].values()}):
            raise ContractError("forbidden", "班级对比需要两个班的访问权限。", 403)
        report = lookup(batch["comparisons"], node_id, "node_not_found")
        return with_run(run_id, report)

    @app.get("/api/records/{record_id}")
    def record(record_id: str, run_id: QueryId, actor: Actor):
        batch = store.batch(run_id)
        row = batch["records"].get(record_id)
        # Hidden and nonexistent records get the same 404 so record ids cannot be probed.
        if row is None or not actor.can_view_student(batch, row["student_id"]):
            raise missing("record_not_found", record_id)
        item = index(batch["catalog"]["items"], "item_id").get(row["item_id"])
        points = rubric_points(item).values() if item else ()
        return with_run(run_id, {
            **row,
            "prompt": item.get("prompt") if item else None,
            "rubric_points": [
                {**point, "awarded": row["rubric_scores"].get(point["rubric_point_id"])}
                for point in points
            ],
        })

    @app.get("/api/resources/{resource_id}")
    def resource(resource_id: str, run_id: QueryId):
        data = store.batch(run_id)["catalog"]
        row = lookup(index(data["resources"], "resource_id"), resource_id, "resource_not_found")
        view = public_resource(row)
        if row["resource_type"] == "item":
            item = index(data["items"], "item_id")[resource_id]
            view.update(pick(item, "prompt", "options", "item_type"))
        elif row["resource_type"] == "learning_card":
            view["content"] = row.get("content", row["title"])
        elif row["resource_type"] == "textbook" and row.get("indicator_locations"):
            view["indicator_locations"] = {
                indicator_id: [
                    pick(ref, "section", "pdf_pages", "printed_page_range", "locator") for ref in refs
                ]
                for indicator_id, refs in row["indicator_locations"].items()
            }
        return with_run(run_id, view)

    @app.get("/api/students/{student_id}/recommendations")
    def recommendations(student_id: str, run_id: QueryId, node_id: QueryId, actor: Actor):
        batch = store.batch(run_id)
        actor.require_student(batch, student_id)
        lookup(batch["students"], student_id, "student_not_found")
        lookup(batch["comparisons"], node_id, "node_not_found")
        plan = lookup(batch["plans"], plan_id(student_id, node_id), "plan_not_found")
        return store.plan(run_id, plan)

    @app.put("/api/plans/{plan_id}/teacher-adjustment")
    def teacher_adjustment(plan_id: str, run_id: QueryId, request: PlanAdjustment, actor: Actor):
        if actor.role == "student":
            raise ContractError("forbidden", "只有教师可以调整学习计划。", 403)
        return store.adjust(run_id, plan_id, request.expected_version,
                            [activity.model_dump() for activity in request.activities], authorize=actor.require_student)

    return app


app = create_app()
