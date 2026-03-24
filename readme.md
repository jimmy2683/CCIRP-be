# CCIRP Backend

## Overview

The **CCIRP Backend** powers the **Central Communication and Intelligent Reminder Platform (CCIRP)**.
It is built using **FastAPI** and provides REST APIs for authentication, user management, communication workflows, reminders, notifications, and AI-powered scheduling.

The backend is responsible for:

* Handling authentication and authorization
* Managing users, campaigns, and reminders
* Delivering notifications
* Running AI-based reminder suggestions
* Providing APIs consumed by the Next.js frontend

---

## Tech Stack

* **FastAPI** – High-performance Python API framework
* **Python 3.13** – Latest Python runtime
* **MongoDB** – Primary NoSQL database for flexible data storage
* **Motor** – High-performance asynchronous MongoDB driver
* **ObjectId Serialization**: Integrated robust type checking and string casting for BSON ObjectIDs.
* **Pydantic 2** – Modern data validation and serialization
* **FastAPI-Mail** – Asynchronous email dispatch engine
* **JWT** – Secure authentication tokens
* **Uvicorn** – ASGI server
* **Ruff** – Blazing fast linting and code quality

---

## Project Structure

```
backend
│
├── src
│   ├── ai                # AI reminder and suggestion logic
│   ├── auth              # Authentication and authorization
│   ├── communication     # Communication and messaging services
│   ├── notifications     # Notification delivery logic
│   ├── reminders         # Reminder scheduling and management
│   ├── users             # User management
│   ├── core              # Core configurations and settings
│   ├── db                # Database models and session management
│   ├── templates         # Server-side template rendering
│   └── utils             # Utility functions
│
├── requirements
│   ├── base.txt          # Base dependencies
│   ├── dev.txt           # Development dependencies
│   └── prod.txt          # Production dependencies
│
├── alembic               # Database migration scripts
├── logs                  # Application logs
├── templates             # Email / message templates
└── README.md
```

---

## Features

### Authentication

* Secure login system
* **OAuth2 Password Bearer Flow**: Standardized secure authentication routing.
* JWT-based authentication
* **Extended Session Security**: Access tokens valid for **24 hours**.
* Role-based access control

### User Management

* User registration
* Profile management
* Access control

### Reminder System

* Create and schedule reminders
* Automated reminder execution
* Time-based notifications

### Notifications
* **Real-time Dispatch**: Integrated `EmailService` using `FastMail` for asynchronous delivery.
* **SMTP Integration**: Pre-configured support for modern mail providers (Gmail, SendGrid, etc.).
* **Merge Field Resolution**: Dynamic injection of recipient data and system variables (e.g., `{{timestamp}}`) into rendered HTML.
* Alert delivery system
* Multi-channel communication support

### Template Engine
* **Visual Builder Persistence**: Integrated a `design_json` field capable of natively persisting complex, nested Block/Component hierarchies.
* **Real Email Dispatch & Test Engine**: Logic resolving specific users, hydrating `{{name}}` and `{{email}}` dynamically.
* **Dynamic Rendering**: Server-side template rendering with sample data support.
* **CRUD Operations**: Secure endpoints for managing design blocks and layouts.
* **Version Control**: Automatic version tracking for all template changes.

### Campaign Management (NEW)
* **Workflow Persistence**: Endpoint architecture mapped to save draft and operational communication broadcasts.
* **Relational Integrity**: Campaigns dynamically link User identities and target Assets.
* **List Aggregation**: Designed to securely host `recipients` criteria and `scheduled_at` dispatch timing.

### AI Integration
* AI-powered reminder suggestions
* Task prioritization logic
* Future predictive scheduling support

---

## Installation

### 1. Navigate to Backend Directory

```bash
cd backend
```

---

### 2. Create Virtual Environment

```bash
python3 -m venv .venv
```

Activate it:

**Linux / macOS**

```bash
source .venv/bin/activate
```

**Windows**

```bash
.venv\Scripts\activate
```

---

### 3. Install Dependencies

Install base dependencies:

```bash
pip install -r requirements/base.txt
```

For development environment:

```bash
pip install -r requirements/dev.txt
```

---

## Running the Backend Server

Start the FastAPI server:

```bash
uvicorn src.main:app --reload
```

The backend will run at:

```
http://127.0.0.1:8000
```

---

## API Documentation

FastAPI automatically generates API documentation.

Swagger UI:

```
http://127.0.0.1:8000/docs
```

ReDoc:

```
http://127.0.0.1:8000/redoc
```

---

## Environment Variables

Create a `.env` file in the backend directory.

Example:

```
DATABASE_URL=mongodb://localhost:27017/ccirp
SECRET_KEY=your-secret-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# SMTP Settings
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
MAIL_FROM=your_email@gmail.com
SMTP_TLS=True
SMTP_SSL=False
```

---

## API Modules

| Module            | Description                       |
| ----------------- | --------------------------------- |
| **auth**          | Authentication and authorization  |
| **users**         | User account management           |
| **reminders**     | Reminder scheduling and execution |
| **notifications** | Notification delivery             |
| **communication** | Messaging and campaigns           |
| **ai**            | Intelligent reminder logic        |

---

## Logging

Application logs are stored in:

```
backend/logs
```

Logs help with debugging and monitoring system activity.

---

## Future Improvements

* WhatsApp and SMS notifications
* AI-based scheduling optimization
* Push notification support
* Docker containerization
* Microservices architecture
* Dynamic asset storage integration

---

## Related Project

This backend works with the **CCIRP Frontend** built using:

* Next.js
* React
* TypeScript
* Tailwind CSS

The frontend communicates with the backend through REST APIs.

---

## Authors

Group 6 – Software Engineering Project

Contributors:

* CS23BTECH11007 Arnav Maiti
* CS23BTECH11009 Bhumin Hirpara
* CS23BTECH11023 Karan Gupta
* CS23BTECH11048 Pranjal Prajapati
* CS23BTECH11052 Roshan Y Singh
* CS23BTECH11060 Sujal Meshram

---

## License

This project is developed for **academic and research purposes**.
