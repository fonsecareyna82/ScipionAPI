import sys
import os

# Añade la raíz del proyecto al path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.backend.database import SessionLocal
from app.backend.models.user import User


def update_email(username: str, new_email: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            print(f"❌ Usuario '{username}' no encontrado")
            return

        user.email = new_email
        db.commit()
        print(f"✅ Email actualizado para '{username}' → {new_email}")
    except Exception as e:
        print(f"⚠️ Error al actualizar: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    update_email("yunior", "cfonsecareyna82@gmail.com")
