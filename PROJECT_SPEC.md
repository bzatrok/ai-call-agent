# AI Call Agent - Project Specification

## Business Problem

Customer support calls are time-consuming and frustrating. Users spend hours on hold, repeating their issues to multiple representatives, and navigating complex phone trees. This app automates the process by having an AI make the call on your behalf.

## Solution

A voice AI agent that:
1. Takes your issue description via a web form
2. Calls the support line using Twilio
3. Explains your problem to the representative
4. Works toward a resolution
5. Reports back with the outcome

## Tech Stack

- **Backend**: FastAPI (Python)
- **Voice**: Twilio Voice API
- **AI**: OpenAI Realtime API (gpt-4o-realtime)
- **Audio**: WebSocket streaming, G711 ULAW codec

## Current Features

- [x] Web UI with phone number and issue description fields
- [x] Outbound calls via Twilio
- [x] Real-time voice conversation with OpenAI
- [x] Speech interruption handling
- [x] Context injection into AI instructions

## Architecture

```
User (Web UI)
     │
     ▼
FastAPI Server ──────► Twilio API
     │                     │
     │                     ▼
     │               Phone Call
     │                     │
     ▼                     ▼
OpenAI Realtime ◄──── WebSocket ────► Support Rep
```

## Environment Variables

```
OPENAI_API_KEY=sk-...
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=+1...
NGROK_URL=https://...
PORT=5050
```

## Running Locally

1. Install dependencies: `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in credentials
3. Start ngrok: `ngrok http 5050`
4. Update `NGROK_URL` in `.env`
5. Run server: `python main.py`
6. Open `http://localhost:5050`
