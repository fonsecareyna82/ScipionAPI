import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.backend.database import SessionLocal
from app.backend.models.user_model import User


def update_email(username: str, new_email: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            print(f"❌ User '{username}' not found")
            return

        user.email = new_email
        db.commit()
        print(f"✅ Email update to '{username}' → {new_email}")
    except Exception as e:
        print(f"⚠️ Update with the update: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    update_email("yunior", "cfonsecareyna82@gmail.com")
