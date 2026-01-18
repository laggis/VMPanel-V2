from sqlmodel import Session, text
from app.core.database import engine

def migrate():
    with Session(engine) as session:
        try:
            # Check if column exists
            session.exec(text("SELECT vnc_port FROM vm LIMIT 1"))
            print("Columns already exist.")
        except Exception:
            print("Migrating database...")
            try:
                session.exec(text("ALTER TABLE vm ADD COLUMN vnc_port INTEGER DEFAULT NULL"))
                session.exec(text("ALTER TABLE vm ADD COLUMN vnc_password VARCHAR(8) DEFAULT NULL"))
                session.exec(text("ALTER TABLE vm ADD COLUMN vnc_enabled BOOLEAN DEFAULT 0"))
                session.commit()
                print("Migration successful.")
            except Exception as e:
                print(f"Migration failed: {e}")

if __name__ == "__main__":
    migrate()
