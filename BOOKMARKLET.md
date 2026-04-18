# 📌 BaseMem Bookmarklet - Save with One Click

Save any conversation or text to BaseMem instantly using a browser bookmark. No extension, no copy-paste!

## 🚀 Installation (30 seconds)

### Step 1: Copy the bookmarklet code

```javascript
javascript:(function(){const serverUrl=prompt('BaseMem server URL:','http://localhost:5000');const topic=prompt('Topic name:','ai-chat');const text=window.getSelection().toString()||document.body.innerText;if(text.trim()){const payload={topic:topic,content:text,platform:window.location.hostname,url:window.location.href};fetch(serverUrl+'/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}).then(r=>r.json()).then(d=>{alert('✅ Saved to BaseMem!\n\n'+d.message)}).catch(e=>{alert('❌ Error: '+e.message)})}else{alert('❌ Select some text first!')}})();
```

### Step 2: Create the bookmark

**Chrome/Edge/Firefox:**
1. **Right-click bookmarks bar** → "Add page"
2. **Title:** `📚 Save to BaseMem`
3. **URL:** Paste the code above ⬆️
4. **Click Save**

### Step 3: Use it!

1. **Open ChatGPT/Claude/Gemini**
2. **Select text** (or leave blank for entire page)
3. **Click the "📚 Save to BaseMem" bookmark**
4. **Enter BaseMem server URL** (default: `http://localhost:5000`)
5. **Enter topic name** (e.g., `ml-basics`)
6. ✅ **Done!** Saved to your knowledge graph

---

## 💡 How It Works

```
1. Click bookmark
2. Prompts for server URL & topic
3. Captures selected text (or entire page)
4. Sends to BaseMem /api/chat endpoint
5. Shows success/error message
```

---

## 🎯 Use Cases

| Scenario | How to Use |
|----------|-----------|
| Save ChatGPT answer | Select text → Click bookmark |
| Save entire conversation | Click bookmark (captures all) |
| Save Claude response | Highlight response → Click bookmark |
| Save Gemini chat | Select text → Click bookmark |
| Quick note | Paste in ChatGPT → Click bookmark |

---

## ⚙️ Advanced: Customize the Bookmarklet

Edit the bookmarklet code to change defaults:

```javascript
// Change this line:
const serverUrl=prompt('BaseMem server URL:','http://localhost:5000');

// To this (hardcode your server):
const serverUrl='http://localhost:5000';

// Change this line:
const topic=prompt('Topic name:','ai-chat');

// To this (ask only once, remember selection):
const topic=localStorage.getItem('basemem_topic')||prompt('Topic name:');
localStorage.setItem('basemem_topic',topic);
```

---

## 🔧 Troubleshooting

| Issue | Fix |
|-------|-----|
| "No text selected" | Highlight text before clicking bookmark |
| "Can't connect" | Make sure `kb.py serve` is running |
| URL error | Check server URL is exactly `http://localhost:5000` |
| Nothing happens | Check browser console (F12) for errors |

---

## 📝 What Gets Saved

- **content**: The selected text (or entire page)
- **topic**: Your topic name
- **platform**: Where you saved from (chatgpt.com, claude.ai, etc)
- **url**: Direct link to the source
- **timestamp**: When saved (automatic)

---

## 🚀 Next: View Your Saves

```bash
# List all saved topics
./venv/bin/python3 kb.py stats

# View specific topic
./venv/bin/python3 kb.py review "ml-basics"

# Search across all saves
./venv/bin/python3 kb.py search "machine learning"

# Get RAG context
./venv/bin/python3 kb.py ask "What about deep learning?"
```

---

**That's it!** Click, save, done. No extensions, no complexity. 🚀
