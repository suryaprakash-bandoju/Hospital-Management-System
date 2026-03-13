# 🏥 Hospital Management System

An enterprise-grade, decoupled backend system for hospital appointment scheduling. This project demonstrates advanced cloud architecture patterns, including strict database concurrency controls, third-party OAuth 2.0 integrations, and serverless microservices.

## 🚀 Key Engineering Features

* **Pessimistic Database Locking:** Utilizes Django's `transaction.atomic()` and PostgreSQL's `select_for_update()` to prevent race conditions. Guarantees zero double-bookings even under heavy concurrent API requests.
* **Decoupled Microservice Architecture:** The core Django monolith is offloaded. Email notifications are triggered via asynchronous HTTP payloads sent to a standalone Node.js microservice built with the Serverless Framework.
* **Google OAuth 2.0 Integration:** Securely handles user authentication state and tokens to automatically generate and attach Google Calendar meeting invites to both doctors and patients upon confirmed bookings.
* **Role-Based Access Control:** Custom user models ensuring strict permissions between Doctor and Patient endpoints.

## 📸 System Architecture & Proof of Execution

*(Drag and drop your screenshots right below these headers! GitHub will automatically format them).*

### 1. The Automated API Booking & Microservice Trigger
> **[Drop your VS Code Terminal Screenshot/GIF here]**
> *Demonstrating the REST API payload triggering the database lock and firing the payload to the Serverless Node.js endpoint.*

### 2. Automated Google Calendar Sync
> **[Drop your Google Calendar Screenshot here]**
> *The resulting Google Meet invite automatically pushed to the user's schedule via OAuth tokens.*

### 3. Asynchronous Email Delivery
> **[Drop your Gmail Inbox Screenshot here]**
> *The booking confirmation email successfully processed and delivered by the decoupled Serverless microservice.*

## 💻 Tech Stack
* **Core Backend:** Python, Django, PostgreSQL
* **Microservice:** Node.js, Serverless Framework
* **Integrations:** Google Cloud Console, Google Calendar API, OAuth 2.0
* **API Testing:** Python `django.test.Client`

## ⚙️ Local Setup Instructions
1. Clone the repository.
2. Install Python dependencies: `pip install -r requirements.txt`
3. Install Microservice dependencies: `cd email_service && npm install`
4. Run the Serverless Microservice: `npx serverless@3 offline --host 127.0.0.1`
5. Run the Django Server: `python manage.py runserver`
