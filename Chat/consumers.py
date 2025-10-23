import json
from channels.generic.websocket import AsyncWebsocketConsumer
from Whatsapp.models import WPRoom
from Facebook.models import FBRoom
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


class Consumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Extract platform and room_id from URL
        self.platform = self.scope['url_route']['kwargs']['platform']  # 'whatsapp', 'facebook', 'instagram'
        self.room_id = self.scope['url_route']['kwargs']['room_id']
        self.room_group_name = f"{self.platform}_chat_{self.room_id}"

        # Join the group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()
        print(f"✅ WebSocket connected to {self.platform} room {self.room_id}")

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        print(f"❌ WebSocket disconnected from {self.platform} room {self.room_id}")

    async def receive(self, text_data):
        """
        When frontend sends a message (optional)
        """
        data = json.loads(text_data)
        message = data.get('message', '')
        sender_type = data.get('sender_type', 'client')
        platform = data.get('from', self.platform)

        # Forward it to group (this triggers chat_message)
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',  # must match async def chat_message
                'message': message,
                'sender_type': sender_type,
                'platform': platform,  # consistent key name
            }
        )

    async def chat_message(self, event):
        """
        Called whenever a message is sent to this group
        """
        # Prevent cross-platform broadcasting
        if event.get('platform') != self.platform:
            return

        message = event.get('message', '')
        sender_type = event.get('sender_type', 'client')
        platform = event.get('platform', 'unknown')

        await self.send(text_data=json.dumps({
            'message': message,
            'sender_type': sender_type,
            'platform': platform,
        }))
        print(f"📤 Sent to {self.platform} socket:", message)


# 🟢 Broadcast Helper (used by webhooks)
def broadcast_message(profile, client, message, platform,sender_type):
    """
    Broadcasts messages from Django views/webhooks to WebSocket clients
    """
    try:
        if platform == 'whatsapp':
            room_model = WPRoom
        elif platform == 'facebook':
            room_model = FBRoom
        else:
            print("⚠️ Unsupported platform:", platform)
            return

        room = room_model.objects.filter(user=profile, client=client).first()
        if not room:
            room = room_model.objects.create(user=profile, client=client)

        channel_layer = get_channel_layer()
        group_name = f"{platform}_chat_{room.id}"
        data = {
            "type": "chat_message",   # must match consumer method
            "message": message,
            "sender_type": sender_type,
            "platform": platform,     # consistent with consumer
        }

        async_to_sync(channel_layer.group_send)(group_name, data)
        print(f"🚀 Broadcasted to {group_name}: {message}")

    except Exception as e:
        print(f"⚠️ Error broadcasting message ({platform}): {e}")
