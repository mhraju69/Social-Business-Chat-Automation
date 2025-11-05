import json
from channels.generic.websocket import AsyncWebsocketConsumer
from Others.models import Alert
from Others.serializers import AlertSerializer
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.db import database_sync_to_async
from rest_framework_simplejwt.tokens import UntypedToken
from django.contrib.auth import get_user_model
import jwt
from django.conf import settings
from openai import OpenAI
from Socials.models import *
from rest_framework_simplejwt.tokens import AccessToken
User = get_user_model()

class GlobalChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        try:
            # Token থেকে user verify করি
            token = self.scope['query_string'].decode().split('token=')[-1]
            self.user = await self.get_user_from_token(token)
            
            if not self.user:
                await self.close()
                return

            # User এর সব profile এর জন্য group join করি
            self.groups = []
            profiles = await self.get_user_profiles(self.user)
            
            for profile in profiles:
                group_name = f"chat_{profile.platform}_{profile.profile_id}"
                self.groups.append(group_name)
                await self.channel_layer.group_add(group_name, self.channel_name)

            await self.accept()
            
            # Connection success message
            await self.send(text_data=json.dumps({
                'type': 'connection_established',
                'message': 'Successfully connected to chat',
                'user_id': self.user.id,
                'profiles': [
                    {
                        'platform': p.platform,
                        'profile_id': p.profile_id,
                        'bot_active': p.bot_active
                    } for p in profiles
                ]
            }))

        except Exception as e:
            print(f"❌ Connection Error: {e}")
            await self.close()

    async def disconnect(self, close_code):
        """WebSocket disconnect হলে"""
        # সব group থেকে remove করি
        for group_name in self.groups:
            await self.channel_layer.group_discard(group_name, self.channel_name)

    async def receive(self, text_data):
        """Client থেকে message receive করে"""
        try:
            data = json.loads(text_data)
            action = data.get('action')

            # --- Action: Send Message ---
            if action == 'send_message':
                platform = data.get('platform')
                client_id = data.get('client_id')
                message_text = data.get('message')

                if not all([platform, client_id, message_text]):
                    await self.send(text_data=json.dumps({
                        'type': 'error',
                        'message': 'Missing required fields'
                    }))
                    return

                # Message send করি
                result = await self.send_outgoing_message(
                    self.user, platform, client_id, message_text
                )

                if result.get('success'):
                    await self.send(text_data=json.dumps({
                        'type': 'message_sent',
                        'message': 'Message sent successfully'
                    }))
                else:
                    await self.send(text_data=json.dumps({
                        'type': 'error',
                        'message': result.get('error', 'Failed to send message')
                    }))

            # --- Action: Get Room List ---
            elif action == 'get_rooms':
                platform = data.get('platform')
                rooms = await self.get_rooms_list(self.user, platform)
                
                await self.send(text_data=json.dumps({
                    'type': 'rooms_list',
                    'rooms': rooms
                }))

            # --- Action: Get Room Messages ---
            elif action == 'get_messages':
                platform = data.get('platform')
                client_id = data.get('client_id')
                limit = data.get('limit', 50)

                messages = await self.get_room_messages(
                    self.user, platform, client_id, limit
                )

                await self.send(text_data=json.dumps({
                    'type': 'room_messages',
                    'platform': platform,
                    'client_id': client_id,
                    'messages': messages
                }))

        except Exception as e:
            print(f"❌ Receive Error: {e}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': str(e)
            }))

    # ----- Group Message Handler (Webhook থেকে broadcast) -----
    async def chat_message(self, event):
        """
        Webhook থেকে broadcast message receive করে
        Channel layer থেকে আসে
        """
        await self.send(text_data=json.dumps({
            'type': 'new_message',
            'platform': event['platform'],
            'client_id': event['client_id'],
            'message': event['message'],
            'message_type': event['message_type'],  # incoming/outgoing
            'timestamp': event['timestamp'],
            'room_id': event.get('room_id')
        }))

    # ----- Database Helper Methods -----
    @database_sync_to_async
    def get_user_from_token(self, token):
        """Token থেকে user বের করে"""
        try:
            access_token = AccessToken(token)
            user_id = access_token['user_id']
            return User.objects.get(id=user_id)
        except Exception as e:
            print(f"❌ Token Error: {e}")
            return None

    @database_sync_to_async
    def get_user_profiles(self, user):
        """User এর সব active profiles"""
        return list(ChatProfile.objects.filter(user=user, bot_active=True))

    @database_sync_to_async
    def get_rooms_list(self, user, platform=None):
        """User এর সব rooms with latest message"""
        profiles = ChatProfile.objects.filter(user=user, bot_active=True)
        if platform:
            profiles = profiles.filter(platform=platform)

        rooms = []
        for profile in profiles:
            profile_rooms = ChatRoom.objects.filter(profile=profile).select_related('client')
            
            for room in profile_rooms:
                last_msg = room.messages.order_by('-timestamp').first()
                
                rooms.append({
                    'room_id': room.id,
                    'platform': profile.platform,
                    'profile_id': profile.profile_id,
                    'client_id': room.client.client_id,
                    'last_message': last_msg.text if last_msg else None,
                    'last_message_time': last_msg.timestamp.isoformat() if last_msg else None,
                    'last_message_type': last_msg.type if last_msg else None,
                })

        # Sort by latest message
        rooms.sort(key=lambda x: x['last_message_time'] or '', reverse=True)
        return rooms

    @database_sync_to_async
    def get_room_messages(self, user, platform, client_id, limit=50):
        """Specific room এর messages"""
        try:
            profile = ChatProfile.objects.get(
                user=user, platform=platform, bot_active=True
            )
            client = ChatClient.objects.get(platform=platform, client_id=client_id)
            room = ChatRoom.objects.get(profile=profile, client=client)

            messages = room.messages.order_by('-timestamp')[:limit]
            messages = reversed(messages)  # Latest last

            return [{
                'id': msg.id,
                'type': msg.type,
                'text': msg.text,
                'message_id': msg.message_id,
                'timestamp': msg.timestamp.isoformat(),
            } for msg in messages]

        except Exception as e:
            print(f"❌ Get Messages Error: {e}")
            return []

    @database_sync_to_async
    def send_outgoing_message(self, user, platform, client_id, message_text):
        """Frontend থেকে message পাঠানো (webhook এর send_message call করবে)"""
        try:
            from .views import send_message  # Your existing function
            
            profile = ChatProfile.objects.get(
                user=user, platform=platform, bot_active=True
            )
            client, _ = ChatClient.objects.get_or_create(
                platform=platform, client_id=client_id
            )

            # Existing send_message function use করি
            result = send_message(profile, client, message_text)
            
            return {'success': True, 'result': result}
        except Exception as e:
            print(f"❌ Send Message Error: {e}")
            return {'success': False, 'error': str(e)}

class AlertConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Get JWT token from query params
        self.token = self.scope['query_string'].decode().split("token=")[-1]
        self.user = await self.get_user_from_token(self.token)

        if self.user:
            self.group_name = f"alerts_{self.user.id}"
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.accept()
        else:
            await self.close()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # Receive alert from group
    async def send_alert(self, event):
        await self.send(text_data=json.dumps(event['alert']))

    @database_sync_to_async
    def get_user_from_token(self, token):
        try:
            # Validate token
            UntypedToken(token)
            decoded_data = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
            user_id = decoded_data['user_id']
            return User.objects.get(id=user_id)
        except Exception:
            return None

def send_alert(user, title, subtitle="", type="info"):
    # 1. Save to DB
    alert = Alert.objects.create(
        user=user,
        title=title,
        subtitle=subtitle,
        type=type
    )

    # 2. Send real-time via WebSocket
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"alerts_{user.id}",  # same group name as in consumer
        {
            "type": "send_alert",  # must match method in consumer
            "alert": AlertSerializer(alert).data
        }
    )
    
    return alert

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.AI_TOKEN,
)

def generate_ai_response(user_message):
    """Generate AI response using OpenRouter (Gemini model)."""
    try:
        completion = client.chat.completions.create(
            model="google/gemini-2.5-flash-lite-preview-09-2025",
            messages=[
                {"role": "system", "content": "You are a helpful WhatsApp assistant."},
                {"role": "user", "content": user_message},
            ],
        )
        return completion.choices[0].message.content or "Sorry, I couldn't generate a response."
    except Exception as e:
        print("⚠️ Error generating AI response:", e)
        return "Sorry, something went wrong while generating a reply."

class TestChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_group_name = "ai_chat"
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        await self.send(text_data=json.dumps({"message": "Welcome to test chat with AI !"}))

    async def disconnect(self, close_code): 
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            user_message = data.get("message")

            if not user_message:
                await self.send(text_data=json.dumps({"error": "No message received."}))
                return

            # Send typing event (optional)
            await self.send(text_data=json.dumps({"status": "typing"}))

            # Run AI in background
            response = await self.get_ai_response(user_message)

            await self.send(text_data=json.dumps({
                "sender": "ai",
                "message": response
            }))

        except Exception as e:
            await self.send(text_data=json.dumps({"error": str(e)}))

    async def get_ai_response(self, user_message):
        from asgiref.sync import sync_to_async
        response = await sync_to_async(generate_ai_response)(user_message)
        return response
    
