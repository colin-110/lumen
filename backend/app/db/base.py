"""Import every model so Base.metadata is complete for Alembic autogenerate."""

from app.db.base_class import Base  # noqa: F401
from app.models.organization import Organization  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.document import Document  # noqa: F401
from app.models.conversation import Conversation, Message  # noqa: F401
