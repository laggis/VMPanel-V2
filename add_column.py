from sqlmodel import text
from app.core.database import engine

def add_column():
    print("Attempting to add expiration_date column to vm table...")
    with engine.connect() as connection:
        try:
            connection.execute(text("ALTER TABLE vm ADD COLUMN expiration_date DATETIME"))
            connection.commit()
            print("Column added successfully.")
        except Exception as e:
            print(f"Error adding column (it might already exist): {e}")

if __name__ == "__main__":
    add_column()
