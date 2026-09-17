"""target_tags — the many-to-many join table between targets and tags (Phase 6, prompt 6.4).

No columns beyond the composite primary key, so this is a plain SQLAlchemy Core Table (not a
mapped class) used as the `secondary=` argument for Target.tags <-> Tag.targets — the standard
idiom for a join table that carries no data of its own. Defined in its own module, rather than
inside target.py or tag.py, so neither of those two modules has to import the other just to
reach this table.
"""

from sqlalchemy import Column, ForeignKey, Table

from database import Base

target_tags = Table(
    "target_tags",
    Base.metadata,
    Column("target_id", ForeignKey("targets.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)
