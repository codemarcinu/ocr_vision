"""Repository for agent call logs."""

from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentCallLog


class AgentCallLogRepository:
    """Repository for agent call logs."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        user_input: str,
        model_used: str,
        sanitized_input: Optional[str] = None,
        raw_response: Optional[str] = None,
        parsed_tool: Optional[str] = None,
        parsed_arguments: Optional[dict] = None,
        validation_success: bool = False,
        validation_error: Optional[str] = None,
        execution_success: bool = False,
        execution_error: Optional[str] = None,
        confidence: Optional[float] = None,
        retry_count: int = 0,
        total_time_ms: int = 0,
        injection_risk: str = "none",
        source: str = "api",
        telegram_chat_id: Optional[int] = None,
    ) -> AgentCallLog:
        """Create a new agent call log entry."""
        log = AgentCallLog(
            user_input=user_input,
            sanitized_input=sanitized_input,
            model_used=model_used,
            raw_response=raw_response[:2000] if raw_response else None,
            parsed_tool=parsed_tool,
            parsed_arguments=parsed_arguments,
            validation_success=validation_success,
            validation_error=validation_error,
            execution_success=execution_success,
            execution_error=execution_error,
            confidence=confidence,
            retry_count=retry_count,
            total_time_ms=total_time_ms,
            injection_risk=injection_risk,
            source=source,
            telegram_chat_id=telegram_chat_id,
        )
        self.session.add(log)
        await self.session.commit()
        await self.session.refresh(log)
        return log

    async def get_by_id(self, log_id: UUID) -> Optional[AgentCallLog]:
        """Get log by ID."""
        result = await self.session.execute(
            select(AgentCallLog).where(AgentCallLog.id == log_id)
        )
        return result.scalar_one_or_none()

    async def get_recent(
        self,
        limit: int = 100,
        source: Optional[str] = None,
        tool: Optional[str] = None,
        success_only: bool = False,
    ) -> list[AgentCallLog]:
        """Get recent logs with optional filters."""
        query = select(AgentCallLog).order_by(AgentCallLog.created_at.desc())

        if source:
            query = query.where(AgentCallLog.source == source)
        if tool:
            query = query.where(AgentCallLog.parsed_tool == tool)
        if success_only:
            query = query.where(AgentCallLog.execution_success == True)

        query = query.limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_suspicious(
        self,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[AgentCallLog]:
        """Get logs with suspicious injection risk."""
        if since is None:
            since = datetime.utcnow() - timedelta(days=7)

        query = (
            select(AgentCallLog)
            .where(AgentCallLog.injection_risk.in_(["low", "medium", "high"]))
            .where(AgentCallLog.created_at >= since)
            .order_by(AgentCallLog.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_stats(
        self,
        since: Optional[datetime] = None,
    ) -> dict:
        """Get aggregated stats for agent calls."""
        if since is None:
            since = datetime.utcnow() - timedelta(days=30)

        # Total calls
        total_result = await self.session.execute(
            select(func.count(AgentCallLog.id)).where(
                AgentCallLog.created_at >= since
            )
        )
        total = total_result.scalar() or 0

        # Success rate
        success_result = await self.session.execute(
            select(func.count(AgentCallLog.id)).where(
                AgentCallLog.created_at >= since,
                AgentCallLog.execution_success == True,
            )
        )
        success = success_result.scalar() or 0

        # Per-tool breakdown
        tool_result = await self.session.execute(
            select(
                AgentCallLog.parsed_tool,
                func.count(AgentCallLog.id).label("count"),
            )
            .where(AgentCallLog.created_at >= since)
            .where(AgentCallLog.parsed_tool.isnot(None))
            .group_by(AgentCallLog.parsed_tool)
            .order_by(func.count(AgentCallLog.id).desc())
        )
        tools = {row.parsed_tool: row.count for row in tool_result}

        # Average latency
        latency_result = await self.session.execute(
            select(func.avg(AgentCallLog.total_time_ms)).where(
                AgentCallLog.created_at >= since,
                AgentCallLog.total_time_ms > 0,
            )
        )
        avg_latency = latency_result.scalar() or 0

        # Injection attempts
        injection_result = await self.session.execute(
            select(
                AgentCallLog.injection_risk,
                func.count(AgentCallLog.id).label("count"),
            )
            .where(AgentCallLog.created_at >= since)
            .group_by(AgentCallLog.injection_risk)
        )
        injection = {row.injection_risk: row.count for row in injection_result}

        return {
            "total_calls": total,
            "success_calls": success,
            "success_rate": round(success / total * 100, 1) if total > 0 else 0,
            "avg_latency_ms": round(avg_latency, 1),
            "tools": tools,
            "injection_risk": injection,
            "period_days": (datetime.utcnow() - since).days,
        }
