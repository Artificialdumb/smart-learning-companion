"""Account credentials and per-batch access rules."""

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from ipaddress import ip_address
from pathlib import Path
from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.contracts import ContractError

BASIC = HTTPBasic(auto_error=False, realm="study")


@dataclass(frozen=True)
class Access:
    role: str
    student_id: str | None = None
    class_ids: tuple[str, ...] = ()

    def can_view(self, student):
        return (self.role == "demo"
                or (self.role == "teacher" and student["class_id"] in self.class_ids)
                or (self.role == "student" and student["student_id"] == self.student_id))

    def require_student(self, batch, student_id):
        if self.role == "demo":
            return
        student = batch["students"].get(student_id)
        if student is None or not self.can_view(student):
            raise ContractError("forbidden", "没有权限访问该学生的数据。", 403)

    def can_compare(self, classes):
        return self.role == "demo" or (self.role == "teacher" and classes <= set(self.class_ids))


def load_accounts(path):
    accounts = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(accounts, dict) or not accounts:
        raise ValueError("账号文件须包含至少一个账号。")
    result = {}
    for username, entry in accounts.items():
        if (not re.fullmatch(r"[A-Za-z0-9_.-]+", username) or not isinstance(entry, dict)
                or not isinstance(entry.get("token_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", entry["token_sha256"])):
            raise ValueError("账号名或访问令牌摘要格式无效。")
        role = entry.get("role")
        if role == "teacher":
            classes = entry.get("class_ids")
            if (not isinstance(classes, list) or not classes
                    or any(not isinstance(value, str) or not value.strip() for value in classes)):
                raise ValueError("教师账号须指定授权班级。")
            access = Access(role, class_ids=tuple(classes))
        elif role == "student":
            student_id = entry.get("student_id")
            if not isinstance(student_id, str) or not student_id.strip():
                raise ValueError("学生账号须绑定学生编号。")
            access = Access(role, student_id=student_id)
        else:
            raise ValueError("账号角色须为 teacher 或 student。")
        result[username] = (entry["token_sha256"], access)
    return result


def is_local(request):
    if request.client is None or request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return False
    if any(name == "forwarded" or name.startswith("x-forwarded-") for name in request.headers):
        return False
    try:
        return ip_address(request.client.host).is_loopback
    except ValueError:
        return False


def require_access(accounts):
    def authenticate(request: Request, credentials: Annotated[HTTPBasicCredentials | None, Depends(BASIC)]):
        if accounts is None:
            if is_local(request):
                return Access("demo")
            raise ContractError("local_only", "请在本机访问，或配置共享服务账号。", 403)
        if request.url.scheme != "https" and not is_local(request):
            raise ContractError("https_required", "共享服务须使用 HTTPS。", 403)
        if credentials:
            digest, access = accounts.get(credentials.username, ("0" * 64, None))
            if compare_digest(sha256(credentials.password.encode()).hexdigest(), digest) and access:
                return access
        raise HTTPException(401, "请使用正确的账号和访问令牌。",
                            headers={"WWW-Authenticate": 'Basic realm="study"'})

    return authenticate
