# main.py
import os
import django
import jwt
from django.contrib.auth import get_user_model
User = get_user_model()

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "your_django_project.settings")
django.setup()

from Others.models import Alert  # import Django model

SECRET_KEY = "your_django_secret_key"

def get_user_from_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("user_id")
        return User.objects.get(id=user_id)
    except Exception:
        return None
    
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query

app = FastAPI()

class ConnectionManager:
    def __init__(self):
        self.active_connections = {}  # user_id → [websockets]

    async def connect(self, user_id, websocket: WebSocket):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

    def disconnect(self, user_id, websocket: WebSocket):
        if user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_personal_alert(self, user_id: int, message: dict):
        if user_id in self.active_connections:
            for ws in self.active_connections[user_id]:
                await ws.send_json(message)

manager = ConnectionManager()
