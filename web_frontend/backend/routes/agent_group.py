"""
Agent 群聊系统 - HTTP API 路由

提供 REST API 接口：
- GET/POST /api/agent-group/groups - 列表/创建群聊
- GET/PATCH/DELETE /api/agent-group/groups/{id} - 单个群聊操作
- POST /api/agent-group/groups/{id}/members - 添加成员
- DELETE /api/agent-group/groups/{id}/members/{package_id} - 移除成员
- POST /api/agent-group/groups/{id}/messages - 发送消息
- POST /api/agent-group/groups/{id}/runs/{run_id}/start - 启动 run
- POST /api/agent-group/groups/{id}/runs/{run_id}/cancel - 取消 run
- GET /api/agent-group/agents - 可用 Agent 列表
"""

from typing import Any

from fastapi import APIRouter, HTTPException

from agent_factory.agent_group_system import AgentGroupService
from agent_factory.factory_graph.frontend_bridge.runtime_bridge import RuntimeBridge


def create_agent_group_router(
    runtime_bridge: RuntimeBridge, service: AgentGroupService
) -> APIRouter:
    """创建 Agent 群聊路由"""
    router = APIRouter(prefix="/api/agent-group", tags=["agent-group"])

    # ===== 群聊会话管理 =====

    @router.get("/groups")
    async def list_groups() -> dict[str, Any]:
        """列出所有群聊"""
        try:
            groups = service.list_groups()
            return {"groups": groups}
        except Exception as e:
            raise _http_error(e)

    @router.post("/groups")
    async def create_group(payload: dict[str, Any]) -> dict[str, Any]:
        """创建新群聊"""
        try:
            title = payload.get("title", "").strip()
            member_package_ids = payload.get("member_package_ids", [])

            if not title:
                raise HTTPException(status_code=400, detail="title is required")

            group = service.create_group(title, member_package_ids)
            return {"group": group}
        except Exception as e:
            raise _http_error(e)

    @router.get("/groups/{group_id}")
    async def get_group(group_id: str) -> dict[str, Any]:
        """获取群聊详情"""
        try:
            group = service.get_group(group_id)
            return {"group": group}
        except Exception as e:
            raise _http_error(e)

    @router.patch("/groups/{group_id}")
    async def update_group(group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """更新群聊"""
        try:
            group = service.update_group(group_id, payload)
            return {"group": group}
        except Exception as e:
            raise _http_error(e)

    @router.delete("/groups/{group_id}")
    async def delete_group(group_id: str) -> dict[str, Any]:
        """删除群聊"""
        try:
            result = service.delete_group(group_id)

            # 清理 runtime sessions
            runtime_manager = runtime_bridge.agent_package_runtime
            for session_id in result.get("member_session_ids", []):
                try:
                    # TODO: 调用 runtime_manager 清理 session
                    pass
                except Exception:
                    pass

            return {"success": result["deleted"], "group_id": group_id}
        except Exception as e:
            raise _http_error(e)

    # ===== 成员管理 =====

    @router.post("/groups/{group_id}/members")
    async def add_member(group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """添加成员"""
        try:
            package_id = payload.get("package_id", "").strip()
            if not package_id:
                raise HTTPException(status_code=400, detail="package_id is required")

            group = service.add_member(group_id, package_id)
            return {"group": group}
        except Exception as e:
            raise _http_error(e)

    @router.delete("/groups/{group_id}/members/{package_id}")
    async def remove_member(group_id: str, package_id: str) -> dict[str, Any]:
        """移除成员"""
        try:
            result = service.remove_member(group_id, package_id)

            # 清理 runtime session
            removed_session_id = result.get("removed_session_id")
            if removed_session_id:
                # TODO: 清理 runtime session
                pass

            return {"group": result}
        except Exception as e:
            raise _http_error(e)

    # ===== 消息管理 =====

    @router.post("/groups/{group_id}/messages")
    async def send_message(group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """发送用户消息"""
        try:
            content = payload.get("content", "").strip()
            client_message_id = payload.get("client_message_id", "").strip()
            target_package_ids = payload.get("target_package_ids", [])

            if not content:
                raise HTTPException(status_code=400, detail="content is required")
            if not client_message_id:
                raise HTTPException(status_code=400, detail="client_message_id is required")
            if not target_package_ids:
                raise HTTPException(status_code=400, detail="target_package_ids is required")

            group = service.send_user_message(group_id, content, client_message_id, target_package_ids)

            # TODO（阶段7）：触发 orchestrator 执行 runs
            # 当前返回群聊状态，runs 处于 queued

            return {"group": group}
        except Exception as e:
            raise _http_error(e)

    # ===== Run 管理 =====

    @router.post("/groups/{group_id}/runs/{run_id}/start")
    async def start_run(group_id: str, run_id: str) -> dict[str, Any]:
        """启动 run（手动触发，测试用）"""
        try:
            # TODO（阶段7）：调用 orchestrator.start_run(run_id)
            return {"success": False, "message": "Manual run start not implemented yet"}
        except Exception as e:
            raise _http_error(e)

    @router.post("/groups/{group_id}/runs/{run_id}/cancel")
    async def cancel_run(group_id: str, run_id: str) -> dict[str, Any]:
        """取消 run"""
        try:
            service.cancel_run(run_id)
            group = service.get_group(group_id)
            return {"group": group}
        except Exception as e:
            raise _http_error(e)

    # ===== Agent 列表 =====

    @router.get("/agents")
    async def list_agents() -> dict[str, Any]:
        """列出可用 Agent"""
        try:
            # 复用 agent_packages.py 的逻辑
            packages = runtime_bridge.agent_package_runtime.package_registry.list_packages()

            agents = [
                {
                    "package_id": pkg.package_id,
                    "agent_name": pkg.metadata.get("name", pkg.package_id),
                    "agent_description": pkg.metadata.get("description"),
                    "status": "ready" if pkg.ready else "not_ready",
                }
                for pkg in packages
            ]

            return {"agents": agents}
        except Exception as e:
            raise _http_error(e)

    return router


def _http_error(exc: Exception) -> HTTPException:
    """将异常转为 HTTP 错误"""
    if isinstance(exc, HTTPException):
        return exc

    # 简化错误处理
    detail = str(exc)
    if "not found" in detail.lower():
        return HTTPException(status_code=404, detail=detail)
    elif "already exists" in detail.lower():
        return HTTPException(status_code=409, detail=detail)
    else:
        return HTTPException(status_code=500, detail=detail)
