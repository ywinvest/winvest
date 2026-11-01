from typing import Annotated
from fastapi import Depends
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.core.config import TEMPLATES_DIR
from app.core.db import get_session

SessionDep = Annotated[Session, Depends(get_session)]
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

