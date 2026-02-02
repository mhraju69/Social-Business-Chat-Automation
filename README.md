# 🌐 Social-Business Chat Automation

![Version](https://img.shields.io/badge/version-1.0.0-blue.svg?style=for-the-badge)
![Django](https://img.shields.io/badge/Django-5.2-092E20.svg?style=for-the-badge&logo=django&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12-3776AB.svg?style=for-the-badge&logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Enabled-2496ED.svg?style=for-the-badge&logo=docker&logoColor=white)
![License](https://img.shields.io/badge/License-Proprietary-red.svg?style=for-the-badge)

> **The Enterprise-Grade Solution for Unified Communications & Business Operations.**
>
> **Social-Business Chat Automation** is a state-of-the-art platform engineered to centralize customer engagement across Facebook, Instagram, and WhatsApp. Powered by proprietary AI and a robust financial engine, it transforms how businesses interact, transact, and scale.

---

## 📑 Table of Contents

- [✨ Key Features](#-key-features)
- [🏗 System Architecture](#-system-architecture)
- [🔌 API Reference](#-api-reference)
    - [Auth & Accounts](#auth--accounts-apiauth)
    - [Social Intelligence](#social-intelligence-apichat)
    - [Finance & Billing](#finance--billing-apifinance)
    - [Business Operations](#business-operations-api)
    - [Admin Console](#admin-console-apiadmin)
- [⚔️ Technology Stack](#%EF%B8%8F-technology-stack)
- [🚀 Deployment Guide](#-deployment-guide)
- [🛡 Environment Configuration](#-environment-configuration)
- [📊 Admin Dashboard](#-admin-dashboard)

---

## ✨ Key Features

| Domain | Capabilities |
| :--- | :--- |
| **💬 Unified Messaging** | • **Omnichannel**: Single interface for FB, IG, WhatsApp.<br>• **Unified Webhook**: Centralized event processing.<br>• **History API**: Searchable message archives. |
| **🤖 AI Core** | • **RAG Engine**: Context-aware answers via Qdrant & LangChain.<br>• **Smart Training**: Upload documents to update the knowledge base instantly.<br>• **Auto-Pilot**: AI handles level-1 support and queries. |
| **💳 Financial Suite** | • **Subscription Mgmt**: End-to-end Stripe integration (Plans, Checkout).<br>• **Connect Platform**: Marketplace capabilities via Stripe Connect.<br>• **Invoicing**: Automated billing and failure handling. |
| **🏢 Operations** | • **Team Control**: RBAC (Role-Based Access Control) for employees.<br>• **Service Booking**: Google Calendar sync for appointments.<br>• **Support Desk**: Integrated ticketing system. |

---

## 🔌 API Reference

### 🔐 Auth & Accounts (`/api/auth/`)

**Authentication & User Management**

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/login/` | Standard password login. |
| `POST` | `/get-otp/` | Request detailed OTP for passwordless entry. |
| `POST` | `/verify-otp/` | Verify OTP and retrieve Auth Token. |
| `POST` | `/google/login/` | OAuth2 Login via Google. |
| `POST` | `/google/callback/` | Callback handler for Google Auth. |
| `GET` | `/me/` | Retrieve current user's profile and settings. |
| `POST` | `/reset-password/` | Initiate password reset flow. |
| `GET` | `/sessions/` | List all active device sessions. |
| `POST` | `/logout-session/{id}/` | Terminate a specific session. |
| `POST` | `/logout-all-sessions/` | Security panic: Log out all devices. |

**Company & Employee Management**

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET/PUT` | `/company/` | Retrieve or update company details. |
| `GET` | `/company/service/` | List all offered services. |
| `POST` | `/company/service/` | Create a new service offering. |
| `PUT/DEL` | `/company/service/{id}/` | Modify or remove a service. |
| `POST` | `/company/employee/` | Invite/Add a new employee. |
| `GET` | `/company/employee/check-permissions/{id}/` | Audit an employee's access rights. |
| `PUT` | `/company/employee/update-permissions/{id}/` | Modify employee permissions (RBAC). |

**User Registry (Viewset)**

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/users/` | List users (Admin/Manager only). |
| `POST` | `/users/` | Register a new user. |
| `GET` | `/users/{id}/` | Get specific user details. |
| `Put` | `/users/{id}/` | Update user details. |

---

### � Social Intelligence (`/api/chat/`)

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/chat-profile-list/` | List all customer profiles captured from social channels. |
| `GET` | `/chat-profile/` | Detail view of a specific chatter. |
| `GET` | `/question-leaderboard/` | Statistical view of most asked questions (AI Analytics). |
| `GET` | `/old-message/{platform}/{room_id}/` | Retrieve paginated message history. |
| `GET` | `/test-chat/old-message/` | Sandbox endpoint for testing chat history. |
| `POST` | `/subscribe-facebook-page/` | Activates webhook subscription for a page. |

---

### 💰 Finance & Billing (`/api/finance/`)

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/plans/` | List available subscription tiers. |
| `POST` | `/check-plan/` | Verify current user's plan status. |
| `POST` | `/create-checkout/` | Initialize Stripe Checkout (One-time or Service). |
| `POST` | `/create-subscriptions/` | Initialize Stripe Checkout (Recurring). |
| `POST` | `/cancel-subscription/` | Gracefully cancel a running subscription. |
| `GET` | `/payment/{id}/` | Retrieve payment receipt/details. |
| `POST` | `/payments/stripe-webhook/` | **System**: Stripe event listener (Webhook). |
| `POST` | `/connect/onboard/` | Start Stripe Connect onboarding flow. |
| `GET` | `/connect/success/` | Return handler for successful connection. |
| `GET` | `/connect/refresh/` | Handler for expired onboarding links. |

---

### 🏢 Business Operations (`/api/`)

**Support & Tickets**

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET/POST`| `/tickets/` | List or Create new support tickets. |
| `GET/PUT` | `/tickets/{id}/` | Manage ticket lifecycle. |
| `GET` | `/knowledge-base/` | Access AI knowledge base entries. |
| `POST` | `/knowledge-base/` | Add new entry to knowledge base. |
| `POST` | `/sync-knowledge/` | Force sync Vector DB with Knowledge Base. |
| `POST` | `/ai-training-files/` | Bulk upload files (PDF/Doc) for AI training. |

**Dashboard & Analytics**

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/dashboard/` | Aggregated metrics for the verified user. |
| `GET` | `/analytics/` | Deep-dive performance analytics. |
| `GET` | `/finance-data/` | Financial overview for the dashboard. |
| `GET` | `/log/` | User activity audit log. |
| `GET` | `/alerts/` | System notifications for the user. |
| `PUT` | `/alerts/{id}/read/` | Mark notification as read. |

**Scheduling**

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/booking/` | Create a new client booking. |
| `GET` | `/bookings/monthly/` | Calendar view of bookings (Month). |
| `GET` | `/bookings/days/` | Detailed daily booking slots. |
| `POST` | `/opening-hours/` | Define business operating hours. |
| `PUT` | `/opening-hours/{id}/` | Update hours. |
| `POST` | `/google/calendar/connect/` | Link Google Calendar account. |
| `GET` | `/google/calendar/callback/` | OAuth callback for Google Calendar. |

---

### � Admin Console (`/api/admin/`)

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/dashboard/` | Super-admin high-level overview. |
| `GET` | `/users/` | Global user list. |
| `GET` | `/companies/` | List all registered companies. |
| `POST` | `/create-admin/` | Provision new admin staff. |
| `GET` | `/approve-channel/` | Review pending social channel connections. |
| `POST` | `/reject-channel/` | Deny social channel connection. |
| `GET` | `/enable-channels/` | Platform-wide channel switch. |
| `GET` | `/subscription-plan/` | Manage global pricing plans. |
| `POST` | `/create-custom-plan/` | Deploy a bespoke plan for a client. |
| `GET` | `/user-plan-requests/` | Review upgrade/downgrade requests. |
| `POST` | `/approve-user-plan/` | Authorize plan changes. |
| `GET` | `/performance-analytics/` | Platform-wide usage statistics. |

---

## ⚡ Root Webhooks

These endpoints are exposed for external platforms to push data to the system.

- `POST /webhook/{platform}/` - **Unified Entry Point**. Handles validation and routing for `facebook`, `instagram`, `whatsapp`.
- `GET /facebook/callback/` - FB OAuth Callback.
- `GET /instagram/callback/` - IG OAuth Callback.
- `GET /whatsapp/callback/` - WhatsApp OAuth Callback.
- `POST /payment-cancel/` - Generic payment cancellation landing.

---

## ⚔️ Technology Stack

### Backend & API
- **Django 5.2**: The core framework.
- **Django REST Framework**: For building the robust REST API.
- **Drf-Spectacular**: For OpenAPI 3.0 schema generation.
- **Gunicorn & Uvicorn**: Production-grade WSGI/ASGI servers.

### Real-Time & Async
- **Django Channels**: Handling WebSocket connections for real-time chat.
- **Redis (ver 7.0)**: Used as the channel layer and Celery broker.
- **Celery 5.5**: Distributed task queue for scheduling and heavy processing.

### AI & Data
- **LangChain**: Orchestrating AI logic.
- **OpenAI**: Underlying LLM provider.
- **Qdrant**: Vector database for high-performance RAG.
- **Pandas**: Data manipulation for analytics.

---

## � Deployment Guide

### Using Docker (Production Ready)

1. **Clone & Configure**
   ```bash
   git clone <repo_url>
   cd Social-Business-Chat-Automation
   cp .env.example .env
   ```

2. **Launch Services**
   ```bash
   docker-compose up --build -d
   ```
   *This commands spins up: Web Container, Worker Container, Beat Scheduler, and Redis.*

3. **Verify Health**
   ```bash
   docker-compose ps
   ```

### Manual Setup (Dev)

1. **Environment**
   ```bash
   python3.12 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Redis**
   Ensure Redis is running on `localhost:6379`.

3. **Run Server**
   ```bash
   python manage.py migrate
   python manage.py runserver
   ```

---

## 🛡 Environment Configuration

| Variable | Description |
| :--- | :--- |
| `AI_TOKEN` | Internal token for AI services security. |
| `FB_APP_ID` / `_SECRET` | Meta Developer App credentials. |
| `STRIPE_SECRET_KEY` | Stripe Server-side key. |
| `STRIPE_WEBHOOK_SECRET` | Critical for verifying Stripe events. |
| `GOOGLE_CLIENT_ID` | GCP Credentials for Calendar API. |
| `CELERY_BROKER_URL` | Redis URL (e.g., `redis://redis:6379/0`). |
| `FIELD_ENCRYPTION_KEY` | Key for encrypting sensitive DB fields at rest. |

---

## 📊 Admin Dashboard

Access the Django Admin panel at `/admin/` for low-level database management, or the custom built **Admin Console** at `/api/admin/dashboard/` for business-logic oversight.

---

> **Built with ❤️ by the Social-Business Automation Team.**
