#!/bin/bash

# Name of the Conda environment
ENV_NAME="scipion3Web"
conda activate $ENV_NAME

echo "📦 Installing backend dependencies..."
pip install fastapi uvicorn psycopg2-binary python-dotenv sqlalchemy bcrypt alembic

echo "📁 Creating .env file..."
cat <<EOF > .env
DATABASE_URL=postgresql://yunior:yourPassword@localhost:5432/bioinfo_db
EOF

echo "🐘 Setting up PostgreSQL..."
sudo service postgresql start
sudo -u postgres psql <<EOF
CREATE USER yunior WITH PASSWORD '1q2w3e4r';
CREATE DATABASE scipion_db OWNER yunior;
GRANT ALL PRIVILEGES ON DATABASE scipion_db TO yunior;
EOF

echo "🧠 Initializing Alembic..."
alembic init alembic

echo "📌 Reminder: Edit alembic.ini and alembic/env.py to connect Alembic to your models"
echo "👉 In alembic/env.py, import your SQLAlchemy models and set target_metadata"
echo "from app.models import Base"
echo "target_metadata = Base.metadata"

echo "✅ Setup complete. You can now create your first migration:"
echo "alembic revision --autogenerate -m 'create users table'"
echo "alembic upgrade head"

echo "🔥 To run the backend:"
echo "uvicorn main:app --reload --host 0.0.0.0 --port 8000"
