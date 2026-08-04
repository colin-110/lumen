from prometheus_client import make_asgi_app
from fastapi import APIRouter

router = APIRouter()

# Create Prometheus metrics ASGI app
metrics_app = make_asgi_app()
