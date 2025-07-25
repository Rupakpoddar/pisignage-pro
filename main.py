#!/usr/bin/env python3
"""
PiSignage Pro - Open Source Digital Signage System for Raspberry Pi
Smooth, hardware-accelerated digital signage with web-based management
"""

import os
import sys
import json
import asyncio
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Any
from enum import Enum
import uuid
import shutil
import aiofiles
import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel, Field
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import vlc
from PIL import Image
import hashlib

# Configuration
BASE_DIR = Path(__file__).parent
CONTENT_DIR = BASE_DIR / "content"
STATIC_DIR = BASE_DIR / "static"
DB_FILE = BASE_DIR / "pisignage.db"
LOG_FILE = BASE_DIR / "pisignage.log"

# Ensure directories exist
CONTENT_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)
(CONTENT_DIR / "images").mkdir(exist_ok=True)
(CONTENT_DIR / "videos").mkdir(exist_ok=True)
(CONTENT_DIR / "web").mkdir(exist_ok=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Models
class ContentType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    WEB = "web"

class Content(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    type: ContentType
    path: str
    duration: int = 10  # seconds
    created_at: datetime = Field(default_factory=datetime.now)
    file_hash: Optional[str] = None

class Schedule(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    content_ids: List[str]
    start_time: Optional[str] = None  # cron format
    end_time: Optional[str] = None
    enabled: bool = True
    priority: int = 0

class PlayerState(BaseModel):
    current_content: Optional[str] = None
    is_playing: bool = False
    volume: int = 50
    last_update: datetime = Field(default_factory=datetime.now)

# VLC Player Manager
class VLCPlayerManager:
    def __init__(self):
        self.instance = vlc.Instance('--intf', 'dummy', '--fullscreen', '--no-video-title-show')
        self.player = self.instance.media_player_new()
        self.current_media = None
        self.is_transitioning = False
        
    async def play_content(self, content: Content):
        """Play content with smooth transitions"""
        try:
            self.is_transitioning = True
            
            # Fade out current content
            if self.player.is_playing():
                await self._fade_out()
            
            # Load new media
            if content.type == ContentType.VIDEO:
                media = self.instance.media_new(content.path)
                media.add_option('input-repeat=65535')  # Loop video
            elif content.type == ContentType.IMAGE:
                media = self.instance.media_new(content.path)
            else:  # WEB
                # For web content, we'll use a different approach
                await self._show_web_content(content.path)
                return
                
            self.player.set_media(media)
            self.current_media = media
            
            # Start playback with fade in
            self.player.play()
            await self._fade_in()
            
            self.is_transitioning = False
            
        except Exception as e:
            logger.error(f"Error playing content: {e}")
            self.is_transitioning = False
            
    async def _fade_out(self, duration=0.5):
        """Smooth fade out"""
        steps = 20
        current_volume = self.player.audio_get_volume()
        for i in range(steps, 0, -1):
            self.player.audio_set_volume(int(current_volume * i / steps))
            await asyncio.sleep(duration / steps)
            
    async def _fade_in(self, duration=0.5):
        """Smooth fade in"""
        steps = 20
        target_volume = 100
        for i in range(1, steps + 1):
            self.player.audio_set_volume(int(target_volume * i / steps))
            await asyncio.sleep(duration / steps)
            
    async def _show_web_content(self, url: str):
        """Display web content using Chromium kiosk mode"""
        # Kill any existing browser
        subprocess.run(['pkill', '-f', 'chromium'], capture_output=True)
        
        # Launch Chromium in kiosk mode with hardware acceleration
        cmd = [
            'chromium-browser',
            '--kiosk',
            '--noerrdialogs',
            '--disable-infobars',
            '--no-first-run',
            '--enable-features=VaapiVideoDecoder',
            '--use-gl=egl',
            '--ignore-gpu-blacklist',
            '--disable-quic',
            '--enable-fast-unload',
            '--enable-tcp-fast-open',
            '--disable-features=TranslateUI',
            '--disk-cache-size=64000000',
            '--disable-component-extensions-with-background-pages',
            url
        ]
        subprocess.Popen(cmd)
        
    def stop(self):
        """Stop playback"""
        self.player.stop()
        subprocess.run(['pkill', '-f', 'chromium'], capture_output=True)

# Content Scheduler
class ContentScheduler:
    def __init__(self, player_manager: VLCPlayerManager):
        self.scheduler = AsyncIOScheduler()
        self.player_manager = player_manager
        self.current_playlist = []
        self.current_index = 0
        self.content_db = {}
        self.schedules = {}
        self.play_task = None
        
    async def start(self):
        """Start the scheduler"""
        self.scheduler.start()
        # Start playing default content
        await self.play_next()
        
    async def play_next(self):
        """Play next content in playlist"""
        if not self.current_playlist:
            # Load default playlist
            self.current_playlist = list(self.content_db.values())
            
        if not self.current_playlist:
            await asyncio.sleep(5)  # Wait if no content
            asyncio.create_task(self.play_next())
            return
            
        # Get current content
        content = self.current_playlist[self.current_index]
        
        # Play content
        await self.player_manager.play_content(content)
        
        # Schedule next content
        self.current_index = (self.current_index + 1) % len(self.current_playlist)
        
        # Wait for duration
        await asyncio.sleep(content.duration)
        
        # Play next
        asyncio.create_task(self.play_next())
        
    def add_content(self, content: Content):
        """Add content to database"""
        self.content_db[content.id] = content
        
    def remove_content(self, content_id: str):
        """Remove content from database"""
        if content_id in self.content_db:
            del self.content_db[content_id]
            
    def update_playlist(self, content_ids: List[str]):
        """Update current playlist"""
        self.current_playlist = [
            self.content_db[cid] for cid in content_ids 
            if cid in self.content_db
        ]
        self.current_index = 0

# FastAPI Application
app = FastAPI(title="PiSignage Pro API")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances
player_manager = VLCPlayerManager()
scheduler = ContentScheduler(player_manager)
websocket_clients = []

# API Routes
@app.on_event("startup")
async def startup_event():
    """Initialize system on startup"""
    logger.info("Starting PiSignage Pro...")
    await scheduler.start()
    
@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    player_manager.stop()
    scheduler.scheduler.shutdown()

@app.get("/")
async def read_root():
    """Serve the web interface"""
    return HTMLResponse(content=open(STATIC_DIR / "index.html").read())

@app.post("/api/content/upload")
async def upload_content(
    file: UploadFile = File(...),
    duration: int = 10
):
    """Upload new content"""
    try:
        # Determine content type
        content_type = None
        if file.content_type.startswith("image/"):
            content_type = ContentType.IMAGE
            save_dir = CONTENT_DIR / "images"
        elif file.content_type.startswith("video/"):
            content_type = ContentType.VIDEO
            save_dir = CONTENT_DIR / "videos"
        else:
            raise HTTPException(400, "Unsupported file type")
            
        # Generate unique filename
        file_hash = hashlib.md5(file.filename.encode()).hexdigest()[:8]
        filename = f"{file_hash}_{file.filename}"
        file_path = save_dir / filename
        
        # Save file
        async with aiofiles.open(file_path, 'wb') as f:
            content = await file.read()
            await f.write(content)
            
        # Create thumbnail for images
        if content_type == ContentType.IMAGE:
            img = Image.open(file_path)
            img.thumbnail((320, 180))
            thumb_path = save_dir / f"thumb_{filename}"
            img.save(thumb_path)
            
        # Create content object
        content = Content(
            name=file.filename,
            type=content_type,
            path=str(file_path),
            duration=duration,
            file_hash=file_hash
        )
        
        # Add to scheduler
        scheduler.add_content(content)
        
        # Notify websocket clients
        await notify_clients({"type": "content_added", "content": content.dict()})
        
        return content
        
    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(500, str(e))

@app.get("/api/content")
async def list_content():
    """List all content"""
    return list(scheduler.content_db.values())

@app.delete("/api/content/{content_id}")
async def delete_content(content_id: str):
    """Delete content"""
    if content_id not in scheduler.content_db:
        raise HTTPException(404, "Content not found")
        
    content = scheduler.content_db[content_id]
    
    # Delete file
    try:
        os.remove(content.path)
    except:
        pass
        
    # Remove from scheduler
    scheduler.remove_content(content_id)
    
    await notify_clients({"type": "content_deleted", "content_id": content_id})
    
    return {"status": "deleted"}

@app.post("/api/playlist")
async def update_playlist(content_ids: List[str]):
    """Update current playlist"""
    scheduler.update_playlist(content_ids)
    await notify_clients({"type": "playlist_updated", "content_ids": content_ids})
    return {"status": "updated"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time updates"""
    await websocket.accept()
    websocket_clients.append(websocket)
    
    try:
        while True:
            data = await websocket.receive_text()
            # Handle incoming messages if needed
    except WebSocketDisconnect:
        websocket_clients.remove(websocket)

async def notify_clients(message: dict):
    """Send message to all websocket clients"""
    disconnected = []
    for client in websocket_clients:
        try:
            await client.send_json(message)
        except:
            disconnected.append(client)
            
    for client in disconnected:
        websocket_clients.remove(client)

# HTML Interface
HTML_CONTENT = """
<!DOCTYPE html>
<html>
<head>
    <title>PiSignage Pro</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.jsdelivr.net/npm/vue@3/dist/vue.global.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { font-family: 'Inter', sans-serif; }
        .fade-enter-active, .fade-leave-active { transition: opacity 0.3s; }
        .fade-enter-from, .fade-leave-to { opacity: 0; }
    </style>
</head>
<body class="bg-gray-50">
    <div id="app" class="min-h-screen">
        <!-- Header -->
        <header class="bg-white shadow-sm border-b">
            <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                <div class="flex justify-between items-center h-16">
                    <h1 class="text-2xl font-bold text-gray-900">PiSignage Pro</h1>
                    <div class="flex items-center space-x-4">
                        <div class="flex items-center">
                            <div class="w-3 h-3 rounded-full mr-2" :class="connected ? 'bg-green-500' : 'bg-red-500'"></div>
                            <span class="text-sm text-gray-600">{{ connected ? 'Connected' : 'Disconnected' }}</span>
                        </div>
                    </div>
                </div>
            </div>
        </header>

        <!-- Main Content -->
        <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
            <!-- Upload Section -->
            <div class="bg-white rounded-lg shadow-sm p-6 mb-8">
                <h2 class="text-lg font-semibold mb-4">Upload Content</h2>
                <div class="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center">
                    <input type="file" @change="handleFileUpload" accept="image/*,video/*" class="hidden" ref="fileInput">
                    <svg class="mx-auto h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                    </svg>
                    <p class="mt-2 text-sm text-gray-600">
                        <button @click="$refs.fileInput.click()" class="text-indigo-600 hover:text-indigo-500">
                            Upload a file
                        </button>
                        or drag and drop
                    </p>
                    <p class="text-xs text-gray-500">Images and videos up to 100MB</p>
                </div>
                <div v-if="uploadProgress > 0" class="mt-4">
                    <div class="bg-gray-200 rounded-full h-2">
                        <div class="bg-indigo-600 h-2 rounded-full transition-all" :style="{width: uploadProgress + '%'}"></div>
                    </div>
                </div>
            </div>

            <!-- Content Grid -->
            <div class="bg-white rounded-lg shadow-sm p-6">
                <div class="flex justify-between items-center mb-4">
                    <h2 class="text-lg font-semibold">Content Library</h2>
                    <button @click="updatePlaylist" class="bg-indigo-600 text-white px-4 py-2 rounded-md text-sm hover:bg-indigo-700">
                        Update Playlist
                    </button>
                </div>
                
                <div v-if="content.length === 0" class="text-center py-12 text-gray-500">
                    No content uploaded yet
                </div>
                
                <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    <div v-for="item in content" :key="item.id" 
                         class="border rounded-lg p-4 cursor-pointer transition-all"
                         :class="{'ring-2 ring-indigo-500': selectedContent.includes(item.id)}"
                         @click="toggleSelection(item.id)">
                        <div class="aspect-video bg-gray-100 rounded mb-3 flex items-center justify-center">
                            <svg v-if="item.type === 'video'" class="w-12 h-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                            <svg v-else class="w-12 h-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                            </svg>
                        </div>
                        <h3 class="font-medium text-sm truncate">{{ item.name }}</h3>
                        <div class="flex items-center justify-between mt-2">
                            <span class="text-xs text-gray-500">{{ item.duration }}s</span>
                            <button @click.stop="deleteContent(item.id)" class="text-red-600 hover:text-red-700 text-xs">
                                Delete
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </main>
    </div>

    <script>
        const { createApp } = Vue;
        
        createApp({
            data() {
                return {
                    connected: false,
                    content: [],
                    selectedContent: [],
                    uploadProgress: 0,
                    ws: null
                }
            },
            mounted() {
                this.loadContent();
                this.connectWebSocket();
            },
            methods: {
                async loadContent() {
                    try {
                        const response = await fetch('/api/content');
                        this.content = await response.json();
                    } catch (error) {
                        console.error('Failed to load content:', error);
                    }
                },
                
                connectWebSocket() {
                    this.ws = new WebSocket(`ws://${window.location.host}/ws`);
                    
                    this.ws.onopen = () => {
                        this.connected = true;
                    };
                    
                    this.ws.onclose = () => {
                        this.connected = false;
                        setTimeout(() => this.connectWebSocket(), 5000);
                    };
                    
                    this.ws.onmessage = (event) => {
                        const data = JSON.parse(event.data);
                        if (data.type === 'content_added') {
                            this.content.push(data.content);
                        } else if (data.type === 'content_deleted') {
                            this.content = this.content.filter(c => c.id !== data.content_id);
                        }
                    };
                },
                
                async handleFileUpload(event) {
                    const file = event.target.files[0];
                    if (!file) return;
                    
                    const formData = new FormData();
                    formData.append('file', file);
                    formData.append('duration', '10');
                    
                    try {
                        this.uploadProgress = 10;
                        const response = await fetch('/api/content/upload', {
                            method: 'POST',
                            body: formData
                        });
                        
                        if (response.ok) {
                            this.uploadProgress = 100;
                            setTimeout(() => {
                                this.uploadProgress = 0;
                                event.target.value = '';
                            }, 1000);
                        }
                    } catch (error) {
                        console.error('Upload failed:', error);
                        this.uploadProgress = 0;
                    }
                },
                
                toggleSelection(id) {
                    const index = this.selectedContent.indexOf(id);
                    if (index > -1) {
                        this.selectedContent.splice(index, 1);
                    } else {
                        this.selectedContent.push(id);
                    }
                },
                
                async updatePlaylist() {
                    if (this.selectedContent.length === 0) {
                        alert('Please select content for the playlist');
                        return;
                    }
                    
                    try {
                        await fetch('/api/playlist', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify(this.selectedContent)
                        });
                        alert('Playlist updated successfully');
                    } catch (error) {
                        console.error('Failed to update playlist:', error);
                    }
                },
                
                async deleteContent(id) {
                    if (!confirm('Delete this content?')) return;
                    
                    try {
                        await fetch(`/api/content/${id}`, {method: 'DELETE'});
                        this.selectedContent = this.selectedContent.filter(sid => sid !== id);
                    } catch (error) {
                        console.error('Failed to delete content:', error);
                    }
                }
            }
        }).mount('#app');
    </script>
</body>
</html>
"""

# Save HTML interface
with open(STATIC_DIR / "index.html", "w") as f:
    f.write(HTML_CONTENT)

# Installation script
INSTALL_SCRIPT = """#!/bin/bash
# PiSignage Pro Installation Script

echo "Installing PiSignage Pro..."

# Update system
sudo apt-get update

# Install dependencies
sudo apt-get install -y python3-pip python3-venv vlc chromium-browser

# Create virtual environment
python3 -m venv /opt/pisignage-pro/venv

# Activate virtual environment
source /opt/pisignage-pro/venv/bin/activate

# Install Python packages
pip install fastapi uvicorn aiofiles pillow python-vlc apscheduler

# Create systemd service
sudo tee /etc/systemd/system/pisignage-pro.service > /dev/null << EOF
[Unit]
Description=PiSignage Pro Digital Signage
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/opt/pisignage-pro
Environment="PATH=/opt/pisignage-pro/venv/bin"
ExecStart=/opt/pisignage-pro/venv/bin/python /opt/pisignage-pro/main.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable pisignage-pro
sudo systemctl start pisignage-pro

echo "PiSignage Pro installed successfully!"
echo "Access the web interface at http://localhost:8000"
"""

# Main entry point
if __name__ == "__main__":
    # Check if running as service or standalone
    if os.environ.get("PISIGNAGE_SERVICE"):
        # Production mode - bind to all interfaces
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
    else:
        # Development mode
        uvicorn.run(app, host="127.0.0.1", port=8000, reload=True, log_level="debug")
