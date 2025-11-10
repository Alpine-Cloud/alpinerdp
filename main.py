from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import os
import json
import uuid
from datetime import datetime, timedelta
import threading
import time

app = Flask(__name__)
CORS(app)

# Config
DATA_DIR = 'data'
AVAILABLE_FILE = os.path.join(DATA_DIR, 'available_python.txt')
IN_USE_FILE = os.path.join(DATA_DIR, 'in_use_python.txt')
LOG_FILE = os.path.join(DATA_DIR, 'python_pool_log.txt')

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

# Initialize files
for file in [AVAILABLE_FILE, IN_USE_FILE, LOG_FILE]:
    if not os.path.exists(file):
        open(file, 'w').close()

def log_event(message):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] {message}\n")
    except:
        pass

def get_available_envs():
    if not os.path.exists(AVAILABLE_FILE):
        return []
    
    try:
        with open(AVAILABLE_FILE, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]
        
        available = []
        for line in lines:
            parts = line.split(' | ')
            if len(parts) >= 4:
                available.append({
                    'url': parts[0],
                    'username': parts[1],
                    'password': parts[2],
                    'python_version': parts[3],
                    'resources': parts[4] if len(parts) > 4 else '2vCPU 4GB RAM',
                    'added_at': parts[5] if len(parts) > 5 else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
        return available
    except Exception as e:
        log_event(f"ERROR reading available: {str(e)}")
        return []

def get_in_use_envs():
    if not os.path.exists(IN_USE_FILE):
        return []
    
    try:
        with open(IN_USE_FILE, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]
        
        in_use = []
        for line in lines:
            parts = line.split(' | ')
            if len(parts) >= 5:
                in_use.append({
                    'url': parts[0],
                    'username': parts[1],
                    'password': parts[2],
                    'python_version': parts[3],
                    'user_id': parts[4],
                    'claimed_at': parts[5] if len(parts) > 5 else datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'resources': parts[6] if len(parts) > 6 else '2vCPU 4GB RAM'
                })
        return in_use
    except Exception as e:
        log_event(f"ERROR reading in-use: {str(e)}")
        return []

def save_available_envs(envs):
    try:
        lines = []
        for env in envs:
            line_parts = [
                env['url'],
                env['username'],
                env['password'],
                env['python_version'],
                env.get('resources', '2vCPU 4GB RAM'),
                env.get('added_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            ]
            lines.append(' | '.join(line_parts))
        
        with open(AVAILABLE_FILE, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        return True
    except Exception as e:
        log_event(f"ERROR saving available: {str(e)}")
        return False

def save_in_use_envs(envs):
    try:
        lines = []
        for env in envs:
            line_parts = [
                env['url'],
                env['username'],
                env['password'],
                env['python_version'],
                env['user_id'],
                env.get('claimed_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                env.get('resources', '2vCPU 4GB RAM')
            ]
            lines.append(' | '.join(line_parts))
        
        with open(IN_USE_FILE, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        return True
    except Exception as e:
        log_event(f"ERROR saving in-use: {str(e)}")
        return False

def generate_user_id():
    return f"user_{uuid.uuid4().hex[:12]}"

def cleanup_expired():
    in_use = get_in_use_envs()
    available = get_available_envs()
    now = datetime.now()
    expired_found = False
    
    for env in in_use[:]:
        try:
            claimed_time = datetime.strptime(env['claimed_at'], '%Y-%m-%d %H:%M:%S')
            if (now - claimed_time) > timedelta(hours=4):
                available.append({
                    'url': env['url'],
                    'username': env['username'],
                    'password': env['password'],
                    'python_version': env['python_version'],
                    'resources': env.get('resources', '2vCPU 4GB RAM'),
                    'added_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
                in_use.remove(env)
                expired_found = True
                log_event(f"ENV EXPIRED: {env['url']}")
        except:
            continue
    
    if expired_found:
        save_in_use_envs(in_use)
        save_available_envs(available)
    
    return expired_found

# Auto-cleanup thread
def cleanup_worker():
    while True:
        try:
            cleanup_expired()
            time.sleep(300)  # Check every 5 minutes
        except:
            time.sleep(60)

cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
cleanup_thread.start()

# API Routes
@app.route('/api/add', methods=['POST'])
def add_env():
    try:
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form
        
        url = data.get('url', '').strip()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        python_version = data.get('python_version', '3.11').strip()
        resources = data.get('resources', '2vCPU 4GB RAM').strip()
        
        if not all([url, username, password]):
            return jsonify({
                'success': False,
                'error': 'Missing url, username, or password'
            }), 400
        
        cleanup_expired()
        available = get_available_envs()
        
        # Check if URL already exists
        for env in available:
            if env['url'] == url:
                return jsonify({
                    'success': False,
                    'error': 'Environment with this URL already exists'
                }), 409
        
        new_env = {
            'url': url,
            'username': username,
            'password': password,
            'python_version': python_version,
            'resources': resources,
            'added_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        available.append(new_env)
        
        if save_available_envs(available):
            log_event(f"ENV ADDED: {url} - Python {python_version}")
            return jsonify({
                'success': True,
                'message': 'Python environment added to pool',
                'env': new_env,
                'total_available': len(available)
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to save environment'
            }), 500
            
    except Exception as e:
        log_event(f"ADD ERROR: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@app.route('/api/claim', methods=['GET'])
def claim_env():
    try:
        cleanup_expired()
        available = get_available_envs()
        
        if not available:
            return jsonify({
                'success': False,
                'error': 'No Python environments available',
                'available_count': 0,
                'message': 'All environments are currently in use'
            }), 404
        
        env = available.pop(0)
        user_id = generate_user_id()
        
        in_use = get_in_use_envs()
        env['user_id'] = user_id
        env['claimed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        in_use.append(env)
        
        if save_available_envs(available) and save_in_use_envs(in_use):
            log_event(f"ENV CLAIMED: {env['url']} by {user_id}")
            
            return jsonify({
                'success': True,
                'env': {
                    'url': env['url'],
                    'username': env['username'],
                    'password': env['password'],
                    'python_version': env['python_version'],
                    'resources': env['resources'],
                    'user_id': user_id,
                    'claimed_at': env['claimed_at'],
                    'expires_at': (datetime.now() + timedelta(hours=4)).strftime('%Y-%m-%d %H:%M:%S')
                },
                'remaining': len(available),
                'message': 'Python environment claimed successfully!'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to claim environment'
            }), 500
            
    except Exception as e:
        log_event(f"CLAIM ERROR: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@app.route('/api/release', methods=['GET'])
def release_env():
    try:
        user_id = request.args.get('user_id', '').strip()
        
        if not user_id:
            return jsonify({
                'success': False,
                'error': 'Missing user_id parameter'
            }), 400
        
        in_use = get_in_use_envs()
        available = get_available_envs()
        released_env = None
        
        for env in in_use[:]:
            if env['user_id'] == user_id:
                released_env = env
                in_use.remove(env)
                
                available.append({
                    'url': env['url'],
                    'username': env['username'],
                    'password': env['password'],
                    'python_version': env['python_version'],
                    'resources': env['resources'],
                    'added_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
                break
        
        if released_env:
            if save_in_use_envs(in_use) and save_available_envs(available):
                log_event(f"ENV RELEASED: {released_env['url']} by {user_id}")
                return jsonify({
                    'success': True,
                    'message': 'Environment released back to pool',
                    'released_env': {
                        'url': released_env['url'],
                        'python_version': released_env['python_version']
                    },
                    'available_count': len(available)
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'Failed to save pool data'
                }), 500
        else:
            return jsonify({
                'success': False,
                'error': 'Environment not found or already released'
            }), 404
            
    except Exception as e:
        log_event(f"RELEASE ERROR: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@app.route('/api/status', methods=['GET'])
def get_status():
    try:
        cleanup_expired()
        available = get_available_envs()
        in_use = get_in_use_envs()
        
        return jsonify({
            'success': True,
            'pool_status': {
                'available_count': len(available),
                'in_use_count': len(in_use),
                'total_count': len(available) + len(in_use),
                'available_urls': [env['url'] for env in available],
                'in_use_urls': [env['url'] for env in in_use],
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        })
    except Exception as e:
        log_event(f"STATUS ERROR: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@app.route('/api/test', methods=['GET'])
def test_api():
    return jsonify({
        'success': True,
        'message': 'Python Environment Pool API is working!',
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'version': '1.0'
    })

# Frontend Route
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

# HTML Template
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Alpine Cloud Python - Instant Python Environments</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: 'Inter', sans-serif; 
            background: linear-gradient(135deg, #0c0c0c 0%, #1a1a2e 50%, #16213e 100%);
            color: #ffffff; line-height: 1.6; 
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 0 20px; }
        header { padding: 2rem 0; text-align: center; background: rgba(255,255,255,0.05); backdrop-filter: blur(10px); border-bottom: 1px solid rgba(255,255,255,0.1); }
        .logo { font-size: 2.5rem; font-weight: 700; background: linear-gradient(135deg, #00d4ff, #0099cc); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 0.5rem; }
        .tagline { font-size: 1.2rem; color: #a0a0a0; font-weight: 300; }
        .hero { text-align: center; padding: 4rem 0; }
        .hero h1 { font-size: 3.5rem; font-weight: 700; margin-bottom: 1rem; background: linear-gradient(135deg, #ffffff, #a0a0a0); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .hero p { font-size: 1.3rem; color: #b0b0b0; max-width: 600px; margin: 0 auto 2rem; }
        .pricing-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 2rem; padding: 2rem 0; }
        .pricing-card { background: rgba(255,255,255,0.08); border-radius: 20px; padding: 2.5rem; text-align: center; border: 1px solid rgba(255,255,255,0.1); transition: all 0.3s ease; }
        .pricing-card:hover { transform: translateY(-10px); background: rgba(255,255,255,0.12); border-color: rgba(0,212,255,0.3); }
        .plan-name { font-size: 1.8rem; font-weight: 600; margin-bottom: 1rem; }
        .plan-price { font-size: 3rem; font-weight: 700; margin-bottom: 1.5rem; background: linear-gradient(135deg, #00d4ff, #0099cc); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .specs { list-style: none; margin: 2rem 0; }
        .specs li { padding: 0.8rem 0; border-bottom: 1px solid rgba(255,255,255,0.1); display: flex; align-items: center; justify-content: center; gap: 0.5rem; }
        .material-icons { color: #00d4ff; }
        .cta-button { display: inline-block; padding: 1rem 2rem; background: linear-gradient(135deg, #00d4ff, #0099cc); color: white; border: none; border-radius: 50px; font-weight: 600; font-size: 1.1rem; cursor: pointer; width: 100%; transition: all 0.3s ease; }
        .cta-button:hover { transform: scale(1.05); box-shadow: 0 10px 25px rgba(0,212,255,0.3); }
        .cta-button:disabled { background: #666; cursor: not-allowed; transform: none; box-shadow: none; }
        .status-badge { display: inline-block; padding: 0.5rem 1rem; border-radius: 20px; font-size: 0.9rem; font-weight: 600; margin-bottom: 1rem; background: rgba(0,255,0,0.2); color: #00ff00; border: 1px solid rgba(0,255,0,0.3); }
        .deploy-status { margin-top: 1rem; padding: 1rem; background: rgba(255,255,255,0.05); border-radius: 10px; border-left: 4px solid #00d4ff; }
        .deploy-log { background: rgba(0,0,0,0.5); padding: 1rem; border-radius: 5px; margin-top: 1rem; font-family: monospace; font-size: 0.9rem; max-height: 200px; overflow-y: auto; text-align: left; }
        .connection-details { background: rgba(0,212,255,0.1); border: 1px solid rgba(0,212,255,0.3); border-radius: 10px; padding: 1.5rem; margin-top: 1rem; text-align: left; }
        .connection-item { display: flex; justify-content: space-between; padding: 0.5rem 0; border-bottom: 1px solid rgba(255,255,255,0.1); }
        .copy-btn { background: rgba(255,255,255,0.1); border: none; color: white; padding: 0.25rem 0.75rem; border-radius: 5px; cursor: pointer; margin-left: 1rem; }
        footer { text-align: center; padding: 2rem 0; border-top: 1px solid rgba(255,255,255,0.1); color: #a0a0a0; margin-top: 4rem; }
        .pulse { animation: pulse 2s infinite; }
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }
        @media (max-width: 768px) { .hero h1 { font-size: 2.5rem; } .pricing-grid { grid-template-columns: 1fr; } }
    </style>
</head>
<body>
    <header>
        <div class="container">
            <div class="logo">Alpine Cloud Python</div>
            <div class="tagline">Instant Python Development Environments - No Signup Required</div>
        </div>
    </header>

    <section class="hero">
        <div class="container">
            <h1>Code in Python. Instantly.</h1>
            <p>Get instant Python environments with pre-configured IDEs. Perfect for development, testing, and learning.</p>
        </div>
    </section>

    <section class="pricing">
        <div class="container">
            <div class="pricing-grid">
                <div class="pricing-card">
                    <div class="status-badge" id="status-badge">READY</div>
                    <div class="plan-name">Python Cloud IDE</div>
                    <div class="plan-price">$0<span style="font-size: 1rem; color: #a0a0a0;">/month</span></div>
                    <ul class="specs">
                        <li><span class="material-icons">code</span> Python 3.11 Environment</li>
                        <li><span class="material-icons">memory</span> 2 vCPU Cores</li>
                        <li><span class="material-icons">sd_storage</span> 4 GB RAM</li>
                        <li><span class="material-icons">storage</span> 10 GB Storage</li>
                        <li><span class="material-icons">web_asset</span> Web-based IDE</li>
                        <li><span class="material-icons">schedule</span> 4 Hour Sessions</li>
                    </ul>
                    <button class="cta-button" onclick="claimEnvironment()" id="claim-btn">
                        <span class="material-icons" style="vertical-align: middle;">rocket_launch</span>
                        Launch Python IDE
                    </button>
                    <div id="deploy-status" class="deploy-status" style="display: none;">
                        <div style="display: flex; align-items: center; gap: 0.5rem;">
                            <span class="material-icons">sync</span>
                            <span id="status-text">Getting Python environment...</span>
                        </div>
                        <div id="deploy-log" class="deploy-log"></div>
                        <div id="connection-details" class="connection-details" style="display: none;"></div>
                    </div>
                </div>
            </div>
        </div>
    </section>

    <footer>
        <div class="container">
            <p>&copy; 2024 Alpine Cloud Python. Instant development environments for everyone.</p>
        </div>
    </footer>

    <script>
        const API_BASE = '/api';
        let currentUserId = null;
        let checkInterval = null;

        async function claimEnvironment() {
            const statusDiv = document.getElementById('deploy-status');
            const logDiv = document.getElementById('deploy-log');
            const button = document.getElementById('claim-btn');
            const statusBadge = document.getElementById('status-badge');
            const statusText = document.getElementById('status-text');
            
            statusDiv.style.display = 'block';
            logDiv.innerHTML = '🚀 Launching Python environment...\\n';
            button.disabled = true;
            button.innerHTML = '<span class="material-icons">hourglass_empty</span> Connecting...';
            statusBadge.textContent = 'CONNECTING';
            statusBadge.classList.add('pulse');
            statusText.textContent = 'Connecting to Python environment...';

            try {
                const response = await fetch(`${API_BASE}/claim`);
                const data = await response.json();

                if (data.success) {
                    currentUserId = data.env.user_id;
                    showEnvironmentDetails(data.env, logDiv);
                    statusBadge.textContent = 'ACTIVE';
                    statusBadge.classList.remove('pulse');
                    statusText.textContent = 'Python environment ready!';
                    
                    logDiv.innerHTML += `✅ ${data.message}\\n`;
                    logDiv.innerHTML += `🌐 URL: ${data.env.url}\\n`;
                    logDiv.innerHTML += `👤 Username: ${data.env.username}\\n`;
                    logDiv.innerHTML += `🔑 Password: ${data.env.password}\\n`;
                    logDiv.innerHTML += `🐍 Python: ${data.env.python_version}\\n`;
                    logDiv.innerHTML += `⏰ Session active for 4 hours\\n`;
                    
                    button.innerHTML = '<span class="material-icons">check</span> Environment Active';
                    
                } else {
                    logDiv.innerHTML += `⏳ ${data.message}\\n`;
                    statusText.textContent = data.message;
                    startWaitingForEnvironment(logDiv, button, statusBadge, statusText);
                }
            } catch (error) {
                logDiv.innerHTML += `❌ Error: ${error.message}\\n`;
                button.disabled = false;
                button.innerHTML = '<span class="material-icons">rocket_launch</span> Launch Python IDE';
                statusBadge.textContent = 'READY';
                statusBadge.classList.remove('pulse');
            }
        }

        function startWaitingForEnvironment(logDiv, button, statusBadge, statusText) {
            let waitTime = 0;
            
            checkInterval = setInterval(async () => {
                waitTime += 5;
                logDiv.innerHTML += `⏰ Waiting... ${waitTime}s\\n`;
                
                try {
                    const response = await fetch(`${API_BASE}/claim`);
                    const data = await response.json();
                    
                    if (data.success) {
                        clearInterval(checkInterval);
                        currentUserId = data.env.user_id;
                        showEnvironmentDetails(data.env, logDiv);
                        statusBadge.textContent = 'ACTIVE';
                        statusBadge.classList.remove('pulse');
                        statusText.textContent = 'Python environment ready!';
                        
                        logDiv.innerHTML += `🎉 Environment available!\\n`;
                        button.innerHTML = '<span class="material-icons">check</span> Environment Active';
                    }
                } catch (error) {
                    logDiv.innerHTML += `⚠️ Check failed: ${error.message}\\n`;
                }
                
                logDiv.scrollTop = logDiv.scrollHeight;
            }, 5000);
        }

        function showEnvironmentDetails(env, logDiv) {
            const connectionDiv = document.getElementById('connection-details');
            connectionDiv.style.display = 'block';
            connectionDiv.innerHTML = `
                <h4><span class="material-icons">terminal</span> Your Python Environment</h4>
                <div class="connection-item">
                    <strong>Access URL:</strong>
                    <span><a href="${env.url}" target="_blank" style="color: #00d4ff;">${env.url}</a> <button class="copy-btn" onclick="copyToClipboard('${env.url}')">Copy</button></span>
                </div>
                <div class="connection-item">
                    <strong>Username:</strong>
                    <span>${env.username} <button class="copy-btn" onclick="copyToClipboard('${env.username}')">Copy</button></span>
                </div>
                <div class="connection-item">
                    <strong>Password:</strong>
                    <span>${env.password} <button class="copy-btn" onclick="copyToClipboard('${env.password}')">Copy</button></span>
                </div>
                <div class="connection-item">
                    <strong>Python Version:</strong>
                    <span>${env.python_version}</span>
                </div>
                <div class="connection-item">
                    <strong>Resources:</strong>
                    <span>${env.resources}</span>
                </div>
                <div class="connection-item">
                    <strong>Expires:</strong>
                    <span>${env.expires_at}</span>
                </div>
                <div style="margin-top: 1rem; padding: 1rem; background: rgba(0,255,0,0.1); border-radius: 5px;">
                    <strong>🚀 Ready to code!</strong><br>
                    Click the URL above to access your Python IDE. Install any packages you need.
                </div>
                <button class="cta-button" onclick="releaseEnvironment()" style="margin-top: 1rem; background: linear-gradient(135deg, #ff6b6b, #ee5a52);">
                    <span class="material-icons">logout</span>
                    Release Environment
                </button>
            `;
        }

        async function releaseEnvironment() {
            if (!currentUserId) return;
            
            try {
                const response = await fetch(`${API_BASE}/release?user_id=${currentUserId}`);
                const data = await response.json();
                
                if (data.success) {
                    alert('Environment released. Thank you!');
                    location.reload();
                }
            } catch (error) {
                alert('Error: ' + error.message);
            }
        }

        function copyToClipboard(text) {
            navigator.clipboard.writeText(text);
        }

        // Cleanup on page leave
        window.addEventListener('beforeunload', () => {
            if (checkInterval) clearInterval(checkInterval);
        });
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    print("🚀 Alpine Cloud Python Server Starting...")
    print("📍 Access the site at: http://localhost:5000")
    print("🔧 API available at: http://localhost:5000/api")
    app.run(host='0.0.0.0', port=5000, debug=True)
