# 🏥 Hospital Management System

An enterprise-grade, decoupled backend system for hospital appointment scheduling. This project demonstrates advanced cloud architecture patterns, including strict database concurrency controls, third-party OAuth 2.0 integrations, and serverless microservices.

## 🚀 Key Engineering Features

* **Pessimistic Database Locking:** Utilizes Django's `transaction.atomic()` and PostgreSQL's `select_for_update()` to prevent race conditions. Guarantees zero double-bookings even under heavy concurrent API requests.
* **Decoupled Microservice Architecture:** The core Django monolith is offloaded. Email notifications are triggered via asynchronous HTTP payloads sent to a standalone Node.js microservice built with the Serverless Framework.
* **Google OAuth 2.0 Integration:** Securely handles user authentication state and tokens to automatically generate and attach Google Calendar meeting invites to both doctors and patients upon confirmed bookings.
* **Role-Based Access Control:** Custom user models ensuring strict permissions between Doctor and Patient endpoints.

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
