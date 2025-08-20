
We need to start Celerity
----------------------------
PYTHONPATH=. celery -A app.workers.task_queue worker --loglevel=info > "$CELERY_LOG" 2>&1 &


We need to start Uvicorn
----------------------------
uvicorn app.backend.main:app --host 0.0.0.0 --port 8080 --reload

We need to star Redis
----------------------
redis-server


