import json
from channels.generic.websocket import AsyncWebsocketConsumer
from Accounts.models import Company, Employee
from Others.models import Alert
from Others.serializers import AlertSerializer
from asgiref.sync import async_to_sync, sync_to_async
from channels.layers import get_channel_layer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils import timezone
from Socials.models import *
from Ai.ai_service import get_ai_response
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

            # Resolve target user (owner if employee)
            self.target_user = await self.get_target_user(self.user)
            if not self.target_user:
                 await self.close()
                 return

            # User এর সব profile এর জন্য group join করি
            self.groups = []
            profiles = await self.get_user_profiles(self.target_user)
            
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
                'target_user_id': self.target_user.id,
                'profiles': await self.get_profiles_data(profiles)

                        
            }))

        except Exception as e:
            print(f"❌ Connection Error: {e}")
            await self.close()

    @database_sync_to_async
    def get_profiles_data(self, profiles):
        from django.db.models import OuterRef, Subquery
        profiles_data = []

        for p in profiles:
            # Annotate rooms with last message details to avoid N+1
            last_message_qs = ChatMessage.objects.filter(room=OuterRef('pk')).order_by('-timestamp')
            
            rooms = p.rooms.select_related('client').annotate(
                last_msg_text=Subquery(last_message_qs.values('text')[:1]),
                last_msg_type=Subquery(last_message_qs.values('type')[:1]),
                last_msg_time=Subquery(last_message_qs.values('timestamp')[:1])
            )

            rooms_list = []
            for room in rooms:
                rooms_list.append({
                    'client_id': room.client.name if room.client.name else room.client.client_id,
                    'room_id': room.id,
                    'last_msg': room.last_msg_text,
                    'type': room.last_msg_type,
                    'timestamp': room.last_msg_time.isoformat() if room.last_msg_time else None
                })
            
            # Sort rooms by timestamp (newest first)
            rooms_list.sort(key=lambda x: x['timestamp'] or "0000-00-00", reverse=True)
            
            profile_info = {
                'platform': p.platform,
                'profile_id': p.profile_id,
                'profile_name': p.name if p.name else p.profile_id,
                'room': rooms_list,
                '_latest_timestamp': rooms_list[0]['timestamp'] if rooms_list else None
            }
            profiles_data.append(profile_info)

        # Sort profiles by latest activity
        profiles_data.sort(key=lambda x: x['_latest_timestamp'] or "0000-00-00", reverse=True)

        # Cleanup internal key
        for p in profiles_data:
            if '_latest_timestamp' in p:
                del p['_latest_timestamp']

        return profiles_data

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
                    self.target_user, platform, client_id, message_text
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
                rooms = await self.get_rooms_list(self.target_user, platform)
                
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
                    self.target_user, platform, client_id, limit
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
    def get_target_user(self, user):
        """If employee, returns company owner. If owner, returns self."""
        if getattr(user, 'role', '') == 'employee':
            try:
                return Employee.objects.get(email=user.email).company.user
            except Employee.DoesNotExist:
                return None
        return user

    @database_sync_to_async
    def get_user_profiles(self, user):
        """User এর সব active profiles"""
        return list(ChatProfile.objects.filter(user=user, bot_active=True))

    @database_sync_to_async
    def get_rooms_list(self, user, platform=None):
        """User এর সব rooms with latest message"""
        from django.db.models import OuterRef, Subquery
        profiles = ChatProfile.objects.filter(user=user, bot_active=True)
        if platform:
            profiles = profiles.filter(platform=platform)

        rooms_result = []
        for profile in profiles:
            last_message_qs = ChatMessage.objects.filter(room=OuterRef('pk')).order_by('-timestamp')
            
            rooms = profile.rooms.select_related('client').annotate(
                last_msg_text=Subquery(last_message_qs.values('text')[:1]),
                last_msg_type=Subquery(last_message_qs.values('type')[:1]),
                last_msg_time=Subquery(last_message_qs.values('timestamp')[:1])
            )
            
            for room in rooms:
                rooms_result.append({
                    'room_id': room.id,
                    'platform': profile.platform,
                    'profile_id': profile.profile_id,
                    'client_id': room.client.name if room.client.name else room.client.client_id,
                    'last_msg': room.last_msg_text,
                    'timestamp': room.last_msg_time.isoformat() if room.last_msg_time else None,
                    'type': room.last_msg_type,
                })

        # Sort by latest message
        rooms_result.sort(key=lambda x: x['timestamp'] or '0000-00-00', reverse=True)
        return rooms_result

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
            from ..Chat.views import send_message  # Your existing function
            
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


def broadcast_message(profile, client_obj, message_text, message_type, room_id=None):
    try:
        channel_layer = get_channel_layer()
        group_name = f"chat_{profile.platform}_{profile.profile_id}"


        
        # Group এ message পাঠাই
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                'type': 'chat_message',  # Consumer এর method name
                'platform': profile.platform,
                'client_id': client_obj.name if client_obj.name else client_obj.client_id,
                'message': message_text,
                'message_type': message_type,
                'timestamp': timezone.now().isoformat(),
                'room_id': room_id
            }
        )
        print(f"✅ Broadcast Success: {group_name}")
        
    except Exception as e:
        print(f"❌ Broadcast Error: {e}")

class AlertConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Get JWT token from query params
        self.token = self.scope['query_string'].decode().split("token=")[-1]
        self.user = await self.get_user_from_token(self.token)

        if self.user:
            self.company = await self.get_company_for_user(self.user)
            if self.company:
                self.group_name = f"alerts_company_{self.company.id}"
                await self.channel_layer.group_add(self.group_name, self.channel_name)
                await self.accept()
            else:
                 await self.close()
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
        """Token থেকে user বের করে"""
        try:
            access_token = AccessToken(token)
            user_id = access_token['user_id']
            return User.objects.get(id=user_id)
        except Exception as e:
            print(f"❌ Token Error: {e}")
            return None
            
    @database_sync_to_async
    def get_company_for_user(self, user):
        if getattr(user, 'role', '') == 'employee':
            try:
                return Employee.objects.get(email=user.email).company
            except Employee.DoesNotExist:
                return None
        return Company.objects.filter(user=user).first()

def send_alert(target, title, subtitle="", type="info"):
    """
    Send an alert to a company. 
    'target' can be a Company instance or a User instance (owner or employee).
    """
    company = None
    
    if isinstance(target, Company):
        company = target
    elif isinstance(target, User):
        # Resolve company from user
        if getattr(target, 'role', '') == 'employee':
            try:
                company = Employee.objects.get(email=target.email).company
            except Employee.DoesNotExist:
                pass
        else:
            company = getattr(target, 'company', None)
            
    if not company:
        print(f"❌ send_alert failed: Could not resolve company for {target}")
        return None

    # 1. Save to DB
    alert = Alert.objects.create(
        company=company,
        title=title,
        subtitle=subtitle,
        type=type,
        time=timezone.now()
    )

    # 2. Send real-time via WebSocket
    channel_layer = get_channel_layer()
    if channel_layer:
        async_to_sync(channel_layer.group_send)(
            f"alerts_company_{company.id}",  
            {
                "type": "send_alert", 
                "alert": AlertSerializer(alert).data
            }
        )
    
    return alert

class TestChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_group_name = "ai_chat"
        try:
            token = self.scope['query_string'].decode().split('token=')[-1]
            self.user = await GlobalChatConsumer.get_user_from_token(token) 
            
            if not self.user:
                await self.close()
                return

            self.company = await self.get_company_from_user(self.user)
            if not self.company:
                await self.close()
                return

            await self.channel_layer.group_add(self.room_group_name, self.channel_name)
            await self.accept()
            await self.send(text_data=json.dumps({"message": "Welcome to test chat with AI !"}))
        except Exception as e:
            print(f"Connection Error: {e}")
            await self.close()

    async def disconnect(self, close_code): 
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            user_message = data.get("message")

            if not user_message:
                await self.send(text_data=json.dumps({"error": "No message received."}))
                return

            # Save incoming message
            await self.save_message(user_message, 'incoming')

            # Send typing event (optional)
            await self.send(text_data=json.dumps({"status": "typing"}))

            # Run AI in background
            response = await self.get_ai_response(user_message)
            
            ai_message = response.get('content', "Sorry, I couldn't generate a response.")

            # Save outgoing (AI) message
            await self.save_message(ai_message, 'outgoing')

            await self.send(text_data=json.dumps({
                "sender": "ai",
                "message": ai_message
            }))

        except Exception as e:
            print(f"Error in TestChat: {e}")
            await self.send(text_data=json.dumps({"error": str(e)}))

    @database_sync_to_async
    def save_message(self, text, msg_type):
        if not self.company:
            return
        TestChat.objects.create(
            company=self.company,
            type=msg_type,
            text=text,
            processed=True
        )

    async def get_ai_response(self, user_message):
        from asgiref.sync import sync_to_async
        from Socials.helper import check_msg_limit

        if not self.company:
             return {"content": "Company not found."}

        # Check Daily Message Limit
        if not await sync_to_async(check_msg_limit)(self.company.id):
            return {"content": "Daily AI response limit reached. Bot has been deactivated."}

        response = await sync_to_async(get_ai_response)(self.company.id, user_message, tone="friendly")
        return response
    
    @database_sync_to_async
    def get_company_from_user(self, user):
        if not user:
            return None
        if getattr(user, 'role', '') == 'employee':
            try:
                return Employee.objects.get(email=user.email).company
            except Employee.DoesNotExist:
                return None
        return Company.objects.filter(user=user).first()