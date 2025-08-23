# Scipion Project Installation Guide (FastAPI + React + PostgreSQL)

1. Update your system and install required packages:

    sudo apt update
    sudo apt install nodejs npm python3 python3-pip postgresql postgresql-contrib
    sudo systemctl start postgresql

2. Install Scipion wit conda environment

3. Set up PostgreSQL:

    Start the PostgreSQL service:

        sudo service postgresql start
        sudo -u postgres psql
        CREATE USER userName WITH PASSWORD 'yourPassword';
        CREATE DATABASE scipion_db OWNER yunior;
        GRANT ALL PRIVILEGES ON DATABASE scipion_db TO yunior;
        \q

4. Install backend dependencies (Scipion env):
    pip install fastapi uvicorn psycopg2-binary python-dotenv sqlalchemy bcrypt

6. Create a .env file in your backend folder:

    Add this line:

        DATABASE_URL=postgresql://yunior:yourPassword@localhost:5432/bioinfo_db

7. Run the backend server:

    uvicorn app.backend.main:app --host 0.0.0.0 --port 8080 --reload

8. Set up the frontend:

   Go to your frontend folder:

        npm install
        npm run dev

9. Create an admin user manually (if needed):

    Enter PostgreSQL:

        sudo -u postgres psql

    To generate the hashed password in Python:
        import bcrypt
        hashed = bcrypt.hashpw(b"yourPassword", bcrypt.gensalt())
        print(hashed.decode())

    Copy the output and paste it into the following SQL command.

    Run this SQL command:

        INSERT INTO users (username, email, "hashedPassword", role, "isActive")
        VALUES (
          'admin',
          'admin@bioinfo.com',
          'yourHashedPassword',
          'admin',
          true
        );

10. Test everything:

Backend docs: http://localhost:8000/docs
Frontend: http://localhost:3000
Login page: http://localhost:3000/
Dashboard: http://localhost:3000/home

11. Logout behavior:

    To log out, remove the token from localStorage and redirect:

        localStorage.removeItem("accessToken");
        navigate("/");

12. Optional: export your Conda environment:

    To save it:
        conda env export > environment.yml

    To recreate it on another machine:
        conda env create -f environment.yml



We need to start Celerity
----------------------------
PYTHONPATH=. celery -A app.workers.task_queue worker --loglevel=info > "$CELERY_LOG" 2>&1 &

We need to star Redis
----------------------
redis-server