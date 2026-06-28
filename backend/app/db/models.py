import uuid
import datetime

from sqlalchemy import Column, String, Integer, DateTime, Text, Boolean
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def _uuid() -> str:
    return str(uuid.uuid4())


class Run(Base):
    __tablename__ = "runs"

    id = Column(String, primary_key=True, default=_uuid)
    repo_owner = Column(String, nullable=False)
    repo_name = Column(String, nullable=False)
    issue_number = Column(Integer, nullable=False)
    issue_title = Column(String)
    installation_id = Column(Integer)
    # running | success | failed
    status = Column(String, default="running")
    pr_url = Column(String)
    branch_name = Column(String)
    iteration_count = Column(Integer, default=0)
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime)


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id = Column(String, primary_key=True, default=_uuid)
    run_id = Column(String, nullable=False, index=True)
    # architect | coder | reviewer | supervisor | system
    agent = Column(String)
    # thought | tool_call | tool_result | error | status
    log_type = Column(String)
    content = Column(Text)
    extra = Column(Text)  # JSON-encoded extra metadata
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
