# SensAI Backend

A Django-based backend service for the SensAI application, providing authentication, note management, and AI-powered features.

## Features

- User authentication and registration
- RESTful API endpoints
- CORS support for frontend integration
- File upload capabilities
- AI-powered note generation
- Daily generation limits
- Secure file handling

## Tech Stack

- Python 3.x
- Django 5.2.1
- Django REST Framework
- SQLite (Development)
- Google Gemini AI Integration
- JWT Authentication

## Prerequisites

- Python 3.x
- pip (Python package manager)
- Virtual environment (recommended)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/JATorres-zxc/Cognify-AI-Backend.git
cd cognify_ai
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file in the project root with the following variables:
```
SECRET_KEY=your_django_secret_key
DEBUG=True
GEMINI_API_KEY=your_gemini_api_key
```

## Configuration

The project uses environment variables for sensitive configuration. Make sure to set up the following in your `.env` file:

- `SECRET_KEY`: Django secret key
- `DEBUG`: Set to False in production
- `GEMINI_API_KEY`: Your Google Gemini API key

## Running the Development Server

```bash
python manage.py migrate
python manage.py runserver
```

The server will start at `http://localhost:8000`

## API Endpoints

The API includes endpoints for:
- User authentication and registration
- Note management
- AI-powered features

## Security Features

- Token-based authentication
- CORS configuration
- File size limits (10MB max)
- Daily generation limits
- Secure password validation

## Development

### Project Structure
```
cognify_ai/
├── accounts/         # User authentication and management
├── notes/           # Note management and AI features
├── cognify_ai/      # Project configuration
├── media/           # Uploaded files
└── requirements.txt # Project dependencies
```

### Key Settings

- Maximum file size: 10MB
- Daily generation limit: 5 generations per user
- CORS allowed origins: http://localhost:3000 (configurable)
