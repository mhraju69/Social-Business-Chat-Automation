import json
from channels.generic.websocket import AsyncWebsocketConsumer
from Whatsapp.models import *

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_id = self.scope['url_route']['kwargs']['room_id']
        self.room_group_name = f"chat_{self.room_id}"

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()
        print(f"✅ WebSocket connected to room {self.room_id}")

    async def disconnect(self, close_code):
        # Leave room
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        print(f"❌ WebSocket disconnected from room {self.room_id}")

    # When message is received from WebSocket
    async def receive(self, text_data):
        data = json.loads(text_data)
        message = data.get('message', '')
        sender_type = data.get('sender_type', 'client')  # 'client' or 'bot'

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': message,
                'sender_type': sender_type,
            }
        )

    # Send message to WebSocket
    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'message': event['message'],
            'sender_type': event['sender_type'],
        }))
