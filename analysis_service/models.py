from sqlalchemy import Column, Integer, String, Text, DateTime, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from datetime import datetime

Base = declarative_base()


class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, index=True)
    owner = Column(String(255), nullable=False)
    repo = Column(String(255), nullable=False)
    ref = Column(String(255), nullable=False)
    summary = Column(Text, nullable=True)
    analysis = Column(Text, nullable=False)
    files_analyzed = Column(Integer, nullable=False)
    batches_processed = Column(Integer, nullable=True)
    batches_failed = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('owner', 'repo', 'ref', name='uq_analyses_owner_repo_ref'),
    )

