import asyncio
import random
from fastapi import FastAPI, UploadFile, File, WebSocket, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from paho.mqtt import client as mqtt_client
import shutil
import fitz 
import os
import json

from models.file import *

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

doc = None
current_page = 0

@app.get("/current_file")
async def get_current_file():
    if doc is None:
        raise HTTPException(status_code=400, detail="No file loaded.")
    return FileResponse(doc.name)

@app.get("/files", response_model=FileList)
def list_files():
    files = os.listdir("resources")
    return {"files": files}

@app.post("/upload/", response_model=FileUpload)
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a PDF file.")

    global doc, current_page
    with open(f"resources/{file.filename}", "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    doc = fitz.open(f"resources/{file.filename}")
    current_page = 0
    await update_info()
    return {"filename": file.filename}

@app.post("/start/{filename}")
async def start_streaming(filename: str):
    global doc, current_page
    if not os.path.exists(f"resources/{filename}"):
        raise HTTPException(status_code=404, detail="File not found.")

    doc = fitz.open(f"resources/{filename}")
    current_page = 0
    await update_info()
    return {"message": f"Started streaming {filename}"}

@app.get("/")
def main():
    def iterfile(): 
        for page in doc:
            yield page.get_pixmap().tobytes()

    return StreamingResponse(iterfile(), media_type="application/pdf")

class PageNumber(BaseModel):
    page_number: int

@app.post("/page/")
async def change_page(page: PageNumber):
    global current_page, doc
    if doc is None:
        raise HTTPException(status_code=400, detail="No file loaded.")
    if page.page_number < 0 or page.page_number >= len(doc):
        raise HTTPException(status_code=400, detail="Invalid page number.")
    current_page = page.page_number
    await update_info()
    return {"message": f"Page changed to {page.page_number}"}

@app.get("/current_page")
def get_current_page():
    global doc, current_page
    if doc is None:
        raise HTTPException(status_code=400, detail="No file loaded.")
    if current_page < 0 or current_page >= len(doc):
        raise HTTPException(status_code=400, detail="Invalid page number.")

    def iterfile(): 
        yield doc[current_page].get_pixmap().tobytes()

    return StreamingResponse(iterfile(), media_type="application/pdf")

@app.get("/users")
def get_users():
    return {"connected_users": len(connected_users)}

async def update_info():
    global doc, current_page
    for user in connected_users:
        if doc is None: 
            info = {
                "current_page": 0,
                "total_pages": 0,
                "filename": "No file loaded",
                "users": len(connected_users)
            }
        else:
            info = {
                "current_page": current_page,
                "total_pages": len(doc),
                "filename": doc.name,
                "users": len(connected_users)
            }
        await user.send_text(json.dumps(info))
        
 
#Websockets
connected_users = set()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_users.add(websocket)
    await update_info()
    try:
        while True:
            data = await websocket.receive_text()
            if data == "get_info":
                info = {
                    "current_page": current_page,
                    "total_pages": len(doc),
                    "filename": doc.name,
                    "users": len(connected_users)
                }
                await websocket.send_text(json.dumps(info))
            
    except:
        connected_users.remove(websocket)
        await update_info()

# Mosquitto
broker = 'broker.emqx.io'
port = 1883
topic = "python/mqtt"
client_id = f'python-mqtt-{random.randint(0, 1000)}'

client = mqtt_client.Client(client_id, userdata="")
client.connect(broker, port)

@app.post("/publish/")
async def publish_message(message: str, sender: str, isOwner: bool):
    client.user_data_set(sender);
    client.publish(topic, message)
    return {"message": "Message sent to broker."}

def on_message(client, userdata, message):
    print(f"`{message.payload.decode()}` de `{message.topic}` recebida. `{userdata}` -- `{client}`")
    
    
client.subscribe(topic) 
client.on_message = on_message
client.loop_start()
