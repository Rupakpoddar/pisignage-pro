# PiSignage Pro - Open Source Digital Signage for Raspberry Pi

A smooth, professional-grade digital signage system designed specifically for Raspberry Pi with hardware acceleration and easy web-based management.

## 🚀 Why PiSignage Pro?

- **Buttery Smooth Playback**: Hardware-accelerated video through VLC ensures no lag or stuttering
- **Professional Transitions**: Fade effects between content for a polished look
- **Zero Configuration**: Works out of the box on Raspberry Pi OS
- **Web-Based Management**: Modern, responsive interface accessible from any device
- **Real-Time Updates**: WebSocket-based instant content updates
- **Open Source**: MIT licensed, free forever, no hidden costs

## 📋 Requirements

- Raspberry Pi 4 or 5 (2GB+ RAM recommended)
- Raspberry Pi OS (64-bit recommended for Pi 4/5)
- MicroSD card (16GB+ Class 10)
- Internet connection for initial setup

## 🔧 Quick Installation

### Option 1: One-Line Installer (Recommended)

```bash
curl -sSL https://raw.githubusercontent.com/yourusername/pisignage-pro/main/install.sh | bash
```

### Option 2: Manual Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/pisignage-pro.git
cd pisignage-pro

# Run the installer
chmod +x install.sh
./install.sh
```

### Option 3: Docker Installation

```bash
docker run -d \
  --name pisignage-pro \
  --restart unless-stopped \
  --privileged \
  -p 8000:8000 \
  -v /opt/pisignage-content:/content \
  yourusername/pisignage-pro:latest
```

## 🎯 Performance Optimization

### Enable GPU Memory Split (Important!)
```bash
sudo raspi-config
# Navigate to: Advanced Options > Memory Split
# Set to 256 (for 4K content) or 128 (for 1080p)
```

### Configure for Smooth Performance
```bash
# Edit boot config
sudo nano /boot/config.txt

# Add these lines:
gpu_mem=256
hdmi_force_hotplug=1
hdmi_group=2
hdmi_mode=82  # 1080p 60Hz
dtoverlay=vc4-fkms-v3d
max_framebuffers=2

# For 4K displays:
# hdmi_enable_4kp60=1
```

### Auto-Start on Boot
```bash
# Already configured by installer, but to verify:
sudo systemctl enable pisignage-pro
sudo systemctl start pisignage-pro
```

## 💻 Usage

1. **Access the Web Interface**
   - Open browser: `http://your-pi-ip:8000`
   - Default: `http://raspberrypi.local:8000`

2. **Upload Content**
   - Click "Upload a file" or drag & drop
   - Supports: JPG, PNG, MP4, MOV, MKV, WebM
   - Set duration for images (videos loop automatically)

3. **Create Playlist**
   - Click content to select (blue border = selected)
   - Click "Update Playlist" to apply
   - Content plays in selection order

4. **Advanced Features**
   - Schedule content by time/date (coming soon)
   - Multi-zone layouts (coming soon)
   - Remote management API

## 🛠️ API Documentation

### Upload Content
```bash
curl -X POST http://localhost:8000/api/content/upload \
  -F "file=@video.mp4" \
  -F "duration=30"
```

### Update Playlist
```bash
curl -X POST http://localhost:8000/api/playlist \
  -H "Content-Type: application/json" \
  -d '["content-id-1", "content-id-2"]'
```

### WebSocket Events
```javascript
const ws = new WebSocket('ws://localhost:8000/ws');
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  // Handle: content_added, content_deleted, playlist_updated
};
```

## 🎨 Customization

### Custom Themes
Edit `/opt/pisignage-pro/static/index.html` to modify the interface.

### Content Zones
Create multi-zone layouts by modifying the player logic in `main.py`.

### Plugins
Add custom content types by extending the `ContentType` enum and player logic.

## 🐛 Troubleshooting

### Black Screen / No Display
```bash
# Check service status
sudo systemctl status pisignage-pro

# View logs
sudo journalctl -u pisignage-pro -f

# Restart service
sudo systemctl restart pisignage-pro
```

### Choppy Video Playback
1. Ensure GPU memory split is configured (256MB)
2. Check CPU temperature: `vcgencmd measure_temp`
3. Use H.264 encoded videos for best performance
4. Reduce resolution if needed

### Cannot Access Web Interface
```bash
# Check if service is running
sudo netstat -tlnp | grep 8000

# Allow through firewall
sudo ufw allow 8000

# Check Pi's IP address
hostname -I
```

## 📁 Project Structure

```
/opt/pisignage-pro/
├── main.py              # Core application
├── content/             # Uploaded content
│   ├── images/
│   ├── videos/
│   └── web/
├── static/              # Web interface
│   └── index.html
├── pisignage.db         # SQLite database
└── pisignage.log        # Application logs
```

## 🚀 Advanced Deployment

### Multi-Screen Setup
```python
# In main.py, modify VLCPlayerManager:
self.instance = vlc.Instance(
    '--intf', 'dummy',
    '--fullscreen',
    '--no-video-title-show',
    '--vout', 'mmal_vout',  # Force MMAL output
    '--mmal-display', 'hdmi-2'  # Second HDMI output
)
```

### Network Storage
```bash
# Mount network drive
sudo mkdir /mnt/content
sudo mount -t cifs //server/share /mnt/content -o user=username

# Update content directory in main.py
CONTENT_DIR = Path("/mnt/content")
```

### Offline Fallback
The system automatically plays cached content when network is unavailable.

## 🤝 Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature/amazing-feature`
3. Commit changes: `git commit -m 'Add amazing feature'`
4. Push to branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

## 📄 License

MIT License - see LICENSE file for details

## 🙏 Acknowledgments

- Built with FastAPI, Vue.js, and python-vlc
- Inspired by the digital signage community
- Optimized for Raspberry Pi hardware

## 💬 Support

- GitHub Issues: [github.com/yourusername/pisignage-pro/issues](https://github.com/yourusername/pisignage-pro/issues)
- Discord: [Join our community](https://discord.gg/pisignage)
- Email: support@pisignage-pro.org

---

**Made with ❤️ for the Raspberry Pi community**
