from sqlmodel import SQLModel, create_engine
from .config import settings
from sqlalchemy import text

engine = create_engine(settings.DATABASE_URL, echo=False)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE `user` ADD COLUMN `parent_id` INT NULL"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE `user` ADD COLUMN `permissions` TEXT NULL"))
        except Exception:
            pass
