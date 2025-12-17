# Ollama Connection Setup for Dev Containers

## Problem
Your Ollama is running on Windows (127.0.0.1:11434), but the dev container cannot reach it because:
1. Windows firewall may be blocking external connections
2. Ollama is bound to localhost only (127.0.0.1)
3. The container needs to reach the **host machine**, not localhost

## Solution Options

### Option 1: Bind Ollama to All Interfaces (Recommended for Dev)
```powershell
# Windows PowerShell (run as Administrator):
$env:OLLAMA_HOST="0.0.0.0"
ollama serve
```

Or permanently in Windows:
```powershell
# Set system environment variable:
[System.Environment]::SetEnvironmentVariable('OLLAMA_HOST','0.0.0.0:11434','Machine')
# Restart Ollama service or run: ollama serve
```

### Option 2: Windows Firewall Rule
```powershell
# Windows PowerShell (Administrator):
New-NetFirewallRule -DisplayName "Ollama" -Direction Inbound -LocalPort 11434 -Protocol TCP -Action Allow
```

### Option 3: Use Port Forwarding (Codespaces Specific)
If using GitHub Codespaces:
```bash
# In codespace terminal:
gh codespace ports forward 11434:11434 --codespace $CODESPACE_NAME
```

## Testing Connection

### 1. From Windows (verify Ollama is running):
```powershell
curl http://127.0.0.1:11434/api/tags
```
Should return JSON with model list.

### 2. From Dev Container:
```bash
# Test all potential host addresses:
curl http://host.docker.internal:11434/api/tags
curl http://10.0.0.1:11434/api/tags
curl http://172.17.0.1:11434/api/tags
```

At least one should work if properly configured.

### 3. Check VAMP Logs:
```bash
# In codespace:
curl http://localhost:5000/api/health
```

Look for Ollama connection status in the response.

## VAMP Auto-Detection

VAMP now automatically tries multiple host addresses:
1. `http://host.docker.internal:11434` (Docker Desktop)
2. `http://172.17.0.1:11434` (Docker bridge)
3. `http://10.0.0.1:11434` (Codespaces gateway)
4. `http://127.0.0.1:11434` (fallback)

The first one that responds will be used.

## Verification

Once Ollama is accessible:
1. Refresh VAMP web interface (http://localhost:5000)
2. Go to Expectations tab
3. Click "Scan Evidence" button
4. Upload a test file with "Use Ollama" checked
5. Should see: "Scanning..." → "Complete" without errors

## Current Issue

Based on your terminal output:
```
OLLAMA_HOST:http://127.0.0.1:11434
```

Ollama is bound to **localhost only**. The container cannot reach this.

**Fix:** Set `OLLAMA_HOST=0.0.0.0` and restart Ollama.

## Alternative: Run Ollama in Container

If Windows binding continues to fail:
```bash
# In codespace:
docker run -d -p 11434:11434 --name ollama ollama/ollama
docker exec ollama ollama pull llama2
```

Then update VAMP:
```bash
export OLLAMA_HOST=http://localhost:11434
python run_web.py
```

---

**Next Step:** Apply Option 1 above, restart Ollama, and test connection.
