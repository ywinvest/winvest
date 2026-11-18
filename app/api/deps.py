from typing import TYPE_CHECKING, Annotated
from fastapi import Depends
from fastapi.templating import Jinja2Templates

from app.core.config import TEMPLATES_DIR

if TYPE_CHECKING:
    from sqlmodel import Session
    from app.core.db import get_session

    SessionDep = Annotated[Session, Depends(get_session)]

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def __getattr__(name: str):
    if name == "SessionDep":
        from sqlmodel import Session
        from app.core.db import get_session

        return Annotated[Session, Depends(get_session)]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

