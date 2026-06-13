import os

bind = "0.0.0.0:8000"
workers = 4
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 120
keepalive = 5


def post_fork(server, worker):
    """Hook ejecutado después de que Gunicorn hace fork de un worker."""
    # Asignar ID único a cada worker
    os.environ["WORKER_ID"] = str(worker.age)
    server.log.info(f"Worker iniciado con WORKER_ID={worker.age}")