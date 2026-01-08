import time
import os
import json
import base64
import asyncio
import websockets
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Connect
from dotenv import load_dotenv

load_dotenv()

# Store call context (issue description) keyed by call SID
call_contexts = {}


def load_prompt(file_name):
    dir_path = os.path.dirname(os.path.realpath(__file__))
    prompt_path = os.path.join(dir_path, "prompts", f"{file_name}.txt")

    try:
        with open(prompt_path, "r", encoding="utf-8") as file:
            return file.read().strip()
    except FileNotFoundError:
        print(f"Could not find file: {prompt_path}")
        raise


# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # requires OpenAI Realtime API Access
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
NGROK_URL = os.getenv("NGROK_URL")
PORT = int(os.getenv("PORT", 5050))

SYSTEM_MESSAGE = load_prompt("system_prompt")
VOICE = "echo"
LOG_EVENT_TYPES = [
    "response.content.done",
    "rate_limits.updated",
    "response.done",
    "input_audio_buffer.committed",
    "input_audio_buffer.speech_stopped",
    "input_audio_buffer.speech_started",
    "session.created",
]

app = FastAPI()

if not OPENAI_API_KEY:
    raise ValueError("Missing the OpenAI API key. Please set it in the .env file.")

if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_PHONE_NUMBER:
    raise ValueError("Missing Twilio configuration. Please set it in the .env file.")


@app.get("/", response_class=HTMLResponse)
async def index_page():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>AI Call Agent</title>
        <style>
            * { box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                max-width: 500px;
                margin: 50px auto;
                padding: 20px;
                background: #f5f5f5;
            }
            h1 { color: #333; margin-bottom: 30px; }
            label {
                display: block;
                margin-bottom: 5px;
                font-weight: 600;
                color: #555;
            }
            input, textarea {
                width: 100%;
                padding: 12px;
                margin-bottom: 20px;
                border: 1px solid #ddd;
                border-radius: 6px;
                font-size: 16px;
            }
            textarea {
                height: 150px;
                resize: vertical;
            }
            button {
                width: 100%;
                padding: 14px;
                background: #007bff;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 16px;
                cursor: pointer;
            }
            button:hover { background: #0056b3; }
            button:disabled { background: #ccc; cursor: not-allowed; }
            #status {
                margin-top: 20px;
                padding: 15px;
                border-radius: 6px;
                display: none;
            }
            .success { background: #d4edda; color: #155724; }
            .error { background: #f8d7da; color: #721c24; }
        </style>
    </head>
    <body>
        <h1>AI Call Agent</h1>
        <form id="callForm">
            <label for="phone">Phone Number to Call</label>
            <input type="tel" id="phone" placeholder="+1234567890" required>

            <label for="context">What's your issue?</label>
            <textarea id="context" placeholder="Describe the issue you want resolved. Include any relevant details like account numbers, dates, or previous case numbers."></textarea>

            <button type="submit" id="submitBtn">Start Call</button>
        </form>
        <div id="status"></div>

        <script>
            document.getElementById('callForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                const btn = document.getElementById('submitBtn');
                const status = document.getElementById('status');
                const phone = document.getElementById('phone').value;
                const context = document.getElementById('context').value;

                btn.disabled = true;
                btn.textContent = 'Calling...';
                status.style.display = 'none';

                try {
                    const params = new URLSearchParams({ to_phone_number: phone });
                    if (context) params.append('context', context);

                    const res = await fetch('/make-call?' + params.toString(), { method: 'POST' });
                    const data = await res.json();

                    if (data.error) {
                        status.className = 'error';
                        status.textContent = 'Error: ' + data.error;
                    } else {
                        status.className = 'success';
                        status.textContent = 'Call initiated! ID: ' + data.call_sid;
                    }
                } catch (err) {
                    status.className = 'error';
                    status.textContent = 'Failed to start call: ' + err.message;
                }

                status.style.display = 'block';
                btn.disabled = false;
                btn.textContent = 'Start Call';
            });
        </script>
    </body>
    </html>
    """


@app.post("/make-call")
async def make_call(to_phone_number: str, context: str = ""):
    """Make an outgoing call to the specified phone number."""
    if not to_phone_number:
        return {"error": "Phone number is required"}
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        call = client.calls.create(
            url=f"{NGROK_URL}/outgoing-call",
            to=to_phone_number,
            from_=TWILIO_PHONE_NUMBER,
        )
        print(f"Call initiated with SID: {call.sid}")

        # Store the context for this call
        if context:
            call_contexts[call.sid] = context
            print(f"Stored context for call {call.sid}: {context}")
    except Exception as e:
        print(f"Error initiating call: {e}")
        return {"error": str(e)}

    return {"call_sid": call.sid}


@app.api_route("/outgoing-call", methods=["GET", "POST"])
async def handle_outgoing_call(request: Request):
    """Handle outgoing call and return TwiML response to connect to Media Stream."""
    # Get call SID from Twilio's request
    form_data = await request.form()
    call_sid = form_data.get("CallSid", "")

    response = VoiceResponse()
    response.say("Please hold while I connect you to our support agent.")
    response.pause(length=1)
    connect = Connect()
    connect.stream(url=f"wss://{request.url.hostname}/media-stream?call_sid={call_sid}")
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")


@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    """Handle WebSocket connections between Twilio and OpenAI."""
    print("Client connected")
    await websocket.accept()

    # Get call SID from query params and retrieve context
    call_sid = websocket.query_params.get("call_sid", "")
    user_context = call_contexts.pop(call_sid, "") if call_sid else ""
    if user_context:
        print(f"Retrieved context for call {call_sid}: {user_context}")

    async with websockets.connect(
        "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01",
        extra_headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v1",
        },
    ) as openai_ws:
        await send_session_update(openai_ws, user_context)
        stream_sid = None
        session_id = None

        async def receive_from_twilio():
            """Receive audio data from Twilio and send it to the OpenAI Realtime API."""
            nonlocal stream_sid
            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)
                    if data["event"] == "media" and openai_ws.open:
                        audio_append = {
                            "type": "input_audio_buffer.append",
                            "audio": data["media"]["payload"],
                        }
                        await openai_ws.send(json.dumps(audio_append))
                    elif data["event"] == "start":
                        stream_sid = data["start"]["streamSid"]
                        print(f"Incoming stream has started {stream_sid}")
            except WebSocketDisconnect:
                print("Client disconnected.")
                if openai_ws.open:
                    await openai_ws.close()

        async def send_to_twilio():
            """Receive events from the OpenAI Realtime API, send audio back to Twilio."""
            nonlocal stream_sid, session_id
            try:
                async for openai_message in openai_ws:
                    response = json.loads(openai_message)
                    if response["type"] in LOG_EVENT_TYPES:
                        print(f"Received event: {response['type']}", response)
                    if response["type"] == "session.created":
                        session_id = response["session"]["id"]
                    if response["type"] == "session.updated":
                        print("Session updated successfully:", response)
                    if response["type"] == "response.audio.delta" and response.get(
                        "delta"
                    ):
                        try:
                            audio_payload = base64.b64encode(
                                base64.b64decode(response["delta"])
                            ).decode("utf-8")
                            audio_delta = {
                                "event": "media",
                                "streamSid": stream_sid,
                                "media": {"payload": audio_payload},
                            }
                            await websocket.send_json(audio_delta)
                        except Exception as e:
                            print(f"Error processing audio data: {e}")
                    if response["type"] == "conversation.item.created":
                        print(f"conversation.item.created event: {response}")
                    if response["type"] == "input_audio_buffer.speech_started":
                        print("Speech Start:", response["type"])

                        # Send clear event to Twilio
                        await websocket.send_json(
                            {"streamSid": stream_sid, "event": "clear"}
                        )

                        print("Cancelling AI speech from the server")

                        # Send cancel message to OpenAI
                        interrupt_message = {"type": "response.cancel"}
                        await openai_ws.send(json.dumps(interrupt_message))
            except Exception as e:
                print(f"Error in send_to_twilio: {e}")

        await asyncio.gather(receive_from_twilio(), send_to_twilio())


async def send_session_update(openai_ws, user_context=""):
    """Send session update to OpenAI WebSocket."""
    instructions = SYSTEM_MESSAGE
    if user_context:
        instructions = f"{SYSTEM_MESSAGE}\n\n---\nUSER'S ISSUE:\n{user_context}\n---"

    session_update = {
        "type": "session.update",
        "session": {
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "voice": VOICE,
            "instructions": instructions,
            "modalities": ["text", "audio"],
            "temperature": 0.2,
        },
    }
    print("Sending session update:", json.dumps(session_update))
    await openai_ws.send(json.dumps(session_update))
