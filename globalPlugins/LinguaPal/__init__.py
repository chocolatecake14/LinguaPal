from gui import SettingsPanel, NVDASettingsDialog, guiHelper
import config
import wx
import gui
import globalPluginHandler
import ui
import requests
import api
import re
import os
import tempfile
import time
from scriptHandler import script
import addonHandler
import threading
import json
import tones
import base64
import ctypes
import ctypes.wintypes

addonHandler.initTranslation()

ADDON_VERSION = "1.0.0"
UPDATE_CHECK_URL = "https://raw.githubusercontent.com/chocolatecake14/LinguaPal/refs/heads/main/update.json"
roleSECTION = "LinguaPal"

confspec = {
    "translateTo": "string(default=English United States)",
    "apiKey": "string(default=)",
    "geminiApiKey": "string(default=)",
    "model": "string(default=groq)",
    "geminiModel": "string(default=gemini-3.1-flash-lite)",
    "groqModel": "string(default=openai/gpt-oss-20b)",
    "systemPrompt": "string(default=You are a helpful AI assistant.)",
    "checkUpdatesAtStartup": "boolean(default=True)",
    "geminiModelCache": "string(default=)",
    "groqModelCache": "string(default=)"
}
config.conf.spec[roleSECTION] = confspec
MAX_CHAT_HISTORY = 50


def _parse_version(v):
    try:
        return tuple(int(x) for x in v.strip().split('.'))
    except (ValueError, AttributeError):
        return (0,)


def _strip_thinking(text):
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'<think>.*$', '', text, flags=re.DOTALL)
    return text.strip()


def _call_gemini_api(data: dict, stream=False):
    apiGemini = config.conf[roleSECTION]["geminiApiKey"]
    geminiModel = config.conf[roleSECTION]["geminiModel"]
    if not apiGemini:
        raise Exception(_("Gemini API key not set. Please go to add-on settings and enter your key."))
    headers = {
        'Content-Type': 'application/json',
        'x-goog-api-key': apiGemini
    }
    endpoint = "streamGenerateContent?alt=sse" if stream else "generateContent"
    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{geminiModel}:{endpoint}",
        headers=headers, json=data, timeout=30, stream=stream
    )
    if response.status_code != 200:
        try:
            r = response.json()
            error_msg = r.get('error', {}).get('message', str(r))
        except Exception:
            error_msg = f"Received non-JSON response: {response.text[:100]}"
        raise Exception(f"Gemini error {response.status_code}: {error_msg}")
    if stream:
        def generate():
            buf = b""
            for raw in response.iter_content(chunk_size=None):
                if not raw:
                    continue
                buf += raw
                while b"\n" in buf:
                    line_bytes, buf = buf.split(b"\n", 1)
                    line = line_bytes.decode("utf-8", errors="replace").strip()
                    if line.startswith("data: "):
                        try:
                            obj = json.loads(line[6:])
                            if "candidates" in obj and obj["candidates"]:
                                parts = obj["candidates"][0]["content"]["parts"]
                                if parts and "text" in parts[0]:
                                    yield parts[0]["text"]
                        except Exception:
                            pass
        return generate()
    else:
        try:
            r = response.json()
        except Exception:
            raise Exception(f"Gemini error {response.status_code}: Received non-JSON response.")
        if "candidates" not in r:
            raise Exception("Gemini error: No candidates found. Full response: " + str(r))
        return r['candidates'][0]['content']['parts'][0]['text']


def sendGeminiSinglePrompt(promptText: str):
    data = {"contents": [{"role": "user", "parts": [{"text": promptText}]}]}
    return _call_gemini_api(data)


def sendGeminiChat(messages, stream=False):
    gemini_messages = []
    for msg in messages:
        gemini_messages.append({"role": msg["role"], "parts": [{"text": msg["text"]}]})
    data = {"contents": gemini_messages}
    sys_prompt = config.conf[roleSECTION].get("systemPrompt", "").strip()
    if sys_prompt:
        data["system_instruction"] = {"parts": [{"text": sys_prompt}]}
    return _call_gemini_api(data, stream=stream)


def sendGroqRequest(messages: list, stream=False, use_system_prompt=True, model_override=None):
    apiKey = config.conf[roleSECTION]["apiKey"]
    groqModel = model_override if model_override else config.conf[roleSECTION]["groqModel"]
    if not apiKey:
        raise Exception(_("Groq API key not set. Please go to add-on settings and enter your key."))
    if use_system_prompt:
        sys_prompt = config.conf[roleSECTION].get("systemPrompt", "").strip()
        if sys_prompt:
            messages = [{"role": "system", "content": sys_prompt}] + messages
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {apiKey}'
    }
    data = {
        "model": groqModel,
        "messages": messages,
        "temperature": 0.7,
        "stream": stream
    }
    url = "https://api.groq.com/openai/v1/chat/completions"
    response = requests.post(url, headers=headers, json=data, timeout=30, stream=stream)
    if response.status_code != 200:
        try:
            r = response.json()
            error_msg = r.get('error', {}).get('message', str(r))
        except Exception:
            error_msg = f"Received non-JSON response: {response.text[:100]}"
        if response.status_code == 400 and any(x in error_msg.lower() for x in ["text classification", "single user message"]):
            raise Exception(_(("The selected Groq model is a text classification model and cannot generate text. "
                                "Please open LinguaPal settings and choose a different model such as openai/gpt-oss-20b.")))
        if response.status_code == 400 and "content must be a string" in error_msg.lower():
            raise Exception(_(("The selected Groq model does not support image inputs. "
                                "Please select a vision-capable model such as meta-llama/llama-4-scout-17b-16e-instruct "
                                "or qwen/qwen3-vl-32b-instruct in LinguaPal settings, then try again.")))
        if response.status_code == 400 and "requires terms acceptance" in error_msg.lower():
            raise Exception(_(("This Groq model requires terms acceptance before it can be used. "
                                "Please visit console.groq.com, find the model in the playground, "
                                "accept its terms as org admin, then try again. "
                                "Or switch to a different model in LinguaPal settings.")))
        raise Exception(f"Groq error {response.status_code}: {error_msg}")
    if stream:
        def generate():
            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            chunk = json.loads(line[6:])
                            if "choices" in chunk and len(chunk["choices"]) > 0:
                                delta = chunk["choices"][0].get("delta", {})
                                if "content" in delta:
                                    yield delta["content"]
                        except Exception:
                            pass
        return generate()
    else:
        try:
            r = response.json()
        except Exception:
            raise Exception(f"Groq error {response.status_code}: Received non-JSON response.")
        if isinstance(r, dict) and 'choices' in r:
            return r['choices'][0]['message']['content']
        else:
            raise Exception("Groq error: Unexpected response format.")


def translate(text: str):
    target_lang = config.conf[roleSECTION]["translateTo"]
    model = config.conf[roleSECTION]["model"]
    roman_note = (
        " If the target language is Hindi, Urdu or Punjabi, "
        "provide the translation strictly in Roman letters; otherwise use the original script."
    )
    sys_instruction = (
        f"You are a translation engine. Translate the user's text into {target_lang}. "
        "Return ONLY the raw translated text — no introductions, no explanations, "
        f"no extra formatting. Do not censor or filter content.{roman_note}"
    )
    if model == "gemini":
        data = {
            "system_instruction": {"parts": [{"text": sys_instruction}]},
            "contents": [{"role": "user", "parts": [{"text": text}]}]
        }
        return _call_gemini_api(data)
    else:
        groq_target_lang = target_lang
        if any(l in target_lang.lower() for l in ["urdu", "hindi", "punjabi"]):
            groq_target_lang = "Roman " + target_lang.split()[0]
        sys_msg = (
            f"You are a translation engine. Your only job is to translate text into {groq_target_lang}. "
            "Return ONLY the raw translated text. No introductions, no explanations, "
            "no extra formatting. Do not censor or filter content."
        )
        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": text}
        ]
        return _strip_thinking(sendGroqRequest(messages, use_system_prompt=False))


def downloadAndInstall(url):
    try:
        filename = os.path.basename(url)
        path = os.path.join(tempfile.gettempdir(), filename)
        r = requests.get(url, stream=True, timeout=20)
        if r.status_code == 200:
            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            os.startfile(path)
        else:
            wx.CallAfter(ui.message, _("Download failed: server error."))
    except Exception as e:
        wx.CallAfter(ui.message, _("Download error: ") + str(e))


def checkForUpdates(showMessages=True):
    def worker():
        try:
            cache_bust_url = f"{UPDATE_CHECK_URL}?t={int(time.time())}"
            response = requests.get(cache_bust_url, timeout=10)
            if response.status_code != 200:
                if showMessages:
                    wx.CallAfter(ui.message, _("Failed to check for updates."))
                return
            data = response.json()
            latest_version = data.get("version", "").strip()
            if not latest_version:
                if showMessages:
                    wx.CallAfter(ui.message, _("Invalid update info."))
                return
            if _parse_version(latest_version) > _parse_version(ADDON_VERSION):
                changelog = data.get("changelog", _("No changelog available."))
                download_url = data.get("downloadUrl")
                if not download_url:
                    wx.CallAfter(ui.message, _("Update available, but no download link."))
                    return
                def promptUpdate():
                    dlg = UpdateDialog(gui.mainFrame, latest_version, changelog)
                    if dlg.ShowModal() == wx.ID_YES:
                        downloadAndInstall(download_url)
                    dlg.Destroy()
                wx.CallAfter(promptUpdate)
            elif showMessages:
                wx.CallAfter(ui.message, _("You already have the latest version."))
        except Exception as e:
            if showMessages:
                wx.CallAfter(ui.message, _("Error checking for updates: ") + str(e))
    threading.Thread(target=worker, daemon=True).start()


class UpdateDialog(wx.Dialog):
    def __init__(self, parent, version, changelog):
        super().__init__(parent, -1, title=_("Update Available"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        sizer = wx.BoxSizer(wx.VERTICAL)
        msg = _("An update for LinguaPal is available. New version: {version}.\n\nDo you want to install it now?").format(version=version)
        msgLabel = wx.StaticText(self, label=msg)
        sizer.Add(msgLabel, 0, flag=wx.ALL, border=10)
        changelogLabel = wx.StaticText(self, label=_("Changelog:"))
        sizer.Add(changelogLabel, 0, flag=wx.LEFT | wx.RIGHT, border=10)
        self.changelogBox = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH)
        self.changelogBox.SetValue(changelog)
        self.changelogBox.SetName(_("Changelog"))
        sizer.Add(self.changelogBox, 1, flag=wx.EXPAND | wx.ALL, border=10)
        btnSizer = wx.BoxSizer(wx.HORIZONTAL)
        self.yesBtn = wx.Button(self, wx.ID_YES, label=_("&Yes"))
        self.noBtn = wx.Button(self, wx.ID_NO, label=_("&No"))
        self.yesBtn.Bind(wx.EVT_BUTTON, lambda evt: self.EndModal(wx.ID_YES))
        self.noBtn.Bind(wx.EVT_BUTTON, lambda evt: self.EndModal(wx.ID_NO))
        btnSizer.Add(self.yesBtn, 0, flag=wx.RIGHT, border=10)
        btnSizer.Add(self.noBtn, 0)
        sizer.Add(btnSizer, 0, flag=wx.ALIGN_CENTER | wx.BOTTOM, border=10)
        self.SetSizer(sizer)
        self.SetMinSize((400, 300))
        self.CenterOnParent()


def _capture_foreground_window():
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    rect = ctypes.wintypes.RECT()
    ok = ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    if ok and (rect.right - rect.left) > 0 and (rect.bottom - rect.top) > 0:
        x, y = rect.left, rect.top
        w, h = rect.right - rect.left, rect.bottom - rect.top
    else:
        x, y = 0, 0
        w = wx.SystemSettings.GetMetric(wx.SYS_SCREEN_X)
        h = wx.SystemSettings.GetMetric(wx.SYS_SCREEN_Y)
    screen_dc = wx.ScreenDC()
    bitmap = wx.Bitmap(w, h)
    mem_dc = wx.MemoryDC()
    mem_dc.SelectObject(bitmap)
    mem_dc.Blit(0, 0, w, h, screen_dc, x, y)
    mem_dc.SelectObject(wx.NullBitmap)
    tmp = tempfile.mktemp(suffix='.png')
    try:
        bitmap.SaveFile(tmp, wx.BITMAP_TYPE_PNG)
        with open(tmp, 'rb') as f:
            data = f.read()
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass
    return base64.b64encode(data).decode('utf-8'), 'image/png'


class MessageViewerDialog(wx.Dialog):
    def __init__(self, parent, text):
        super().__init__(parent, -1, title=_("Full Message"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.text = text
        self.initUI()

    def initUI(self):
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.textBox = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH)
        self.textBox.SetValue(self.text)
        self.textBox.SetName(_("Message content"))
        sizer.Add(self.textBox, 1, flag=wx.EXPAND | wx.ALL, border=10)
        btn = wx.Button(self, id=wx.ID_OK, label=_("&Close"))
        sizer.Add(btn, 0, flag=wx.ALIGN_CENTER | wx.BOTTOM, border=10)
        self.SetSizer(sizer)
        self.SetMinSize((400, 300))
        self.SetSize((600, 450))
        self.CenterOnParent()
        self.Bind(wx.EVT_CHAR_HOOK, self.onKey)
        self.textBox.SetFocus()

    def onKey(self, event):
        k = event.GetKeyCode()
        if k == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_OK)
        else:
            event.Skip()


class GeminiChatDialog(wx.Dialog):
    def __init__(self):
        model = config.conf[roleSECTION].get("model", "groq").capitalize()
        title = f"{_('Chat with LinguaPal')} - {model}"
        super().__init__(gui.mainFrame, -1, title=title)
        self.chat_history = []
        self.full_messages = []
        self.pending_image_b64 = None
        self.pending_image_mime = None
        self.pending_image_name = None
        self.initUI()

    def initUI(self):
        sizer = wx.BoxSizer(wx.VERTICAL)
        label1 = wx.StaticText(self, label=_("Message &history:"))
        sizer.Add(label1, 0, flag=wx.LEFT | wx.RIGHT | wx.TOP, border=10)
        self.historyBox = wx.ListBox(self, style=wx.LB_SINGLE)
        self.historyBox.SetName(_("Message history"))
        self.historyBox.Bind(wx.EVT_LISTBOX_DCLICK, self.onDoubleClick)
        sizer.Add(self.historyBox, 3, flag=wx.EXPAND | wx.ALL, border=10)
        label2 = wx.StaticText(self, label=_("Type your &message:"))
        sizer.Add(label2, 0, flag=wx.LEFT | wx.RIGHT, border=10)
        self.inputBox = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_RICH)
        self.inputBox.SetName(_("Message input"))
        sizer.Add(self.inputBox, 1, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        imgSizer = wx.BoxSizer(wx.HORIZONTAL)
        self.attachBtn = wx.Button(self, label=_("&Attach Image"))
        self.attachBtn.Bind(wx.EVT_BUTTON, self.onAttachImage)
        imgSizer.Add(self.attachBtn, 0, flag=wx.RIGHT, border=6)
        self.removeImgBtn = wx.Button(self, label=_("&Remove Image"))
        self.removeImgBtn.Bind(wx.EVT_BUTTON, self.onRemoveImage)
        self.removeImgBtn.Hide()
        imgSizer.Add(self.removeImgBtn, 0, flag=wx.RIGHT, border=10)
        self.imgStatusLabel = wx.StaticText(self, label=_("No image attached"))
        self.imgStatusLabel.SetName(_("Image attachment status"))
        imgSizer.Add(self.imgStatusLabel, 1, flag=wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(imgSizer, 0, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, border=10)

        btn = wx.Button(self, id=wx.ID_OK, label=_("&Send"))
        btn.Bind(wx.EVT_BUTTON, self.onSend)
        sizer.Add(btn, 0, flag=wx.ALIGN_CENTER | wx.ALL, border=10)
        self.SetSizerAndFit(sizer)
        self.Bind(wx.EVT_CHAR_HOOK, self.onKey)
        self.Maximize()
        self.Show()

    def onKey(self, event):
        k = event.GetKeyCode()
        if k == wx.WXK_ESCAPE or (k == wx.WXK_F4 and event.AltDown()):
            self.Destroy()
            return
        elif k in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            focus_win = wx.Window.FindFocus()
            if focus_win == self.historyBox:
                self.showFullMessage()
                return
            elif focus_win == self.inputBox:
                if event.ShiftDown():
                    event.Skip()
                else:
                    self.onSend(None)
                return
        event.Skip()

    def onDoubleClick(self, event):
        self.showFullMessage()

    def showFullMessage(self):
        selection = self.historyBox.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        full_text = self.full_messages[selection]
        dlg = MessageViewerDialog(self, full_text)
        dlg.ShowModal()
        dlg.Destroy()

    def onAttachImage(self, event):
        wildcard = _("Images (*.jpg;*.jpeg;*.png;*.gif;*.webp)|*.jpg;*.jpeg;*.png;*.gif;*.webp|All files (*.*)|*.*")
        with wx.FileDialog(self, _("Select Image to Attach"), wildcard=wildcard,
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        try:
            ext = os.path.splitext(path)[1].lower()
            mime_map = {
                '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                '.png': 'image/png', '.gif': 'image/gif', '.webp': 'image/webp'
            }
            mime = mime_map.get(ext, 'image/jpeg')
            with open(path, 'rb') as f:
                raw = f.read()
            self.pending_image_b64 = base64.b64encode(raw).decode('utf-8')
            self.pending_image_mime = mime
            self.pending_image_name = os.path.basename(path)
            self.imgStatusLabel.SetLabel(_("Attached: ") + self.pending_image_name)
            self.removeImgBtn.Show()
            self.Layout()
            ui.message(_("Image attached: ") + self.pending_image_name)
        except Exception as e:
            ui.message(_("Could not load image: ") + str(e))

    def onRemoveImage(self, event):
        if self.pending_image_b64 is None:
            ui.message(_("No image attached."))
            return
        self.pending_image_b64 = None
        self.pending_image_mime = None
        self.pending_image_name = None
        self.imgStatusLabel.SetLabel(_("No image attached"))
        self.removeImgBtn.Hide()
        self.Layout()
        ui.message(_("Image removed."))

    def onSend(self, event):
        user_message = self.inputBox.GetValue().strip()
        if not user_message and self.pending_image_b64 is None:
            return
        if not user_message:
            user_message = _("(Image attached)")
        self.inputBox.Clear()

        img_b64 = self.pending_image_b64
        img_mime = self.pending_image_mime
        img_name = self.pending_image_name
        self.pending_image_b64 = None
        self.pending_image_mime = None
        self.pending_image_name = None
        self.imgStatusLabel.SetLabel(_("No image attached"))
        if img_name:
            self.removeImgBtn.Hide()
            self.Layout()

        display_msg = f"[{_('Image')}: {img_name}] {user_message}" if img_name else user_message
        self.appendToChat("You", display_msg)
        self.chat_history.append({"role": "user", "text": user_message,
                                   "image_b64": img_b64, "image_mime": img_mime})

        if len(self.chat_history) > MAX_CHAT_HISTORY:
            excess = len(self.chat_history) - MAX_CHAT_HISTORY
            self.chat_history = self.chat_history[-MAX_CHAT_HISTORY:]
            for _i in range(excess):
                if self.historyBox.GetCount() > 0:
                    self.historyBox.Delete(0)
                if self.full_messages:
                    self.full_messages.pop(0)
        wx.CallAfter(self.getResponse)

    def injectScreenshot(self, b64, mime, name):
        self.pending_image_b64 = b64
        self.pending_image_mime = mime
        self.pending_image_name = name
        self.imgStatusLabel.SetLabel(_("Attached: ") + name)
        self.removeImgBtn.Show()
        self.Layout()
        self.inputBox.SetValue(_(
            "Please describe this screenshot in detail for a blind user. "
            "Include all visible text, UI controls and their states, "
            "any error messages, and the application name if visible."
        ))
        self.onSend(None)

    def appendToChat(self, speaker, message):
        clean_message = re.sub(r'\n\s*\n+', '\n', message.strip())
        full_text = f"{speaker}: {clean_message}"
        self.full_messages.append(full_text)
        display_text = full_text
        if len(display_text) > 1500:
            display_text = display_text[:1500] + _("... [Press Enter to read full message]")
        self.historyBox.Append(display_text)
        count = self.historyBox.GetCount()
        if count > 0:
            self.historyBox.SetSelection(count - 1)

    def getResponse(self):
        def worker():
            ai_name = "System"
            try:
                model = config.conf[roleSECTION]["model"]
                if model == "gemini":
                    ai_name = "Gemini"
                    gemini_messages = []
                    for i, msg in enumerate(self.chat_history):
                        is_last = (i == len(self.chat_history) - 1)
                        if is_last and msg.get("image_b64"):
                            parts = [
                                {"inline_data": {"mime_type": msg["image_mime"], "data": msg["image_b64"]}},
                                {"text": msg["text"]}
                            ]
                        else:
                            parts = [{"text": msg["text"]}]
                        gemini_messages.append({"role": msg["role"], "parts": parts})
                    data = {"contents": gemini_messages}
                    sys_prompt = config.conf[roleSECTION].get("systemPrompt", "").strip()
                    if sys_prompt:
                        data["system_instruction"] = {"parts": [{"text": sys_prompt}]}
                    stream = _call_gemini_api(data, stream=True)
                else:
                    ai_name = "Groq"
                    groq_messages = []
                    has_image = any(msg.get("image_b64") for msg in self.chat_history)
                    vision_model = "qwen/qwen3.6-27b" if has_image else None
                    for i, msg in enumerate(self.chat_history):
                        role = "assistant" if msg["role"] == "model" else msg["role"]
                        is_last = (i == len(self.chat_history) - 1)
                        if is_last and msg.get("image_b64"):
                            content = [
                                {"type": "image_url", "image_url": {
                                    "url": f"data:{msg['image_mime']};base64,{msg['image_b64']}"
                                }},
                                {"type": "text", "text": msg["text"]}
                            ]
                        else:
                            content = msg["text"]
                        groq_messages.append({"role": role, "content": content})
                    stream = sendGroqRequest(groq_messages, stream=True, model_override=vision_model)

                full_response = ""
                sentence_buffer = ""
                last_spoken_len = 0
                last_ui_len = 0

                def initUI():
                    self.appendToChat(ai_name, "")
                wx.CallAfter(initUI)
                wx.CallAfter(ui.message, f"{ai_name}: ")

                for chunk in stream:
                    if not chunk:
                        continue
                    full_response += chunk

                    if len(full_response) - last_ui_len >= 150:
                        last_ui_len = len(full_response)
                        def updateUI(text):
                            count = self.historyBox.GetCount()
                            if count > 0:
                                clean = re.sub(r'\n\s*\n+', '\n', _strip_thinking(text).strip())
                                display = f"{ai_name}: {clean}"
                                self.full_messages[-1] = display
                                if len(display) > 1500:
                                    display = display[:1500] + _("... [Press Enter to read full message]")
                                self.historyBox.SetString(count - 1, display)
                        wx.CallAfter(updateUI, full_response)

                    stripped_now = _strip_thinking(full_response)
                    sentence_buffer += stripped_now[last_spoken_len:]
                    last_spoken_len = len(stripped_now)

                    drained = True
                    while drained:
                        drained = False
                        for p in ('.', '!', '?', '\n'):
                            if p in sentence_buffer:
                                parts = sentence_buffer.split(p, 1)
                                to_speak = parts[0] + p
                                sentence_buffer = parts[1] if len(parts) > 1 else ""
                                if to_speak.strip():
                                    wx.CallAfter(ui.message, to_speak.strip())
                                drained = True
                                break

                final_stripped = _strip_thinking(full_response)

                def finalUpdate():
                    count = self.historyBox.GetCount()
                    if count > 0:
                        clean = re.sub(r'\n\s*\n+', '\n', final_stripped.strip())
                        text = clean if clean.strip() else _("(No response)")
                        self.full_messages[-1] = f"{ai_name}: {text}"
                        display = self.full_messages[-1]
                        if len(display) > 1500:
                            display = display[:1500] + _("... [Press Enter to read full message]")
                        self.historyBox.SetString(count - 1, display)
                wx.CallAfter(finalUpdate)

                if sentence_buffer.strip():
                    wx.CallAfter(ui.message, sentence_buffer.strip())

                stored = final_stripped if final_stripped.strip() else full_response
                self.chat_history.append({"role": "model", "text": stored})

            except Exception as e:
                response_text = _("Error: ") + str(e)
                def updateErrorUI():
                    self.chat_history.append({"role": "model", "text": response_text})
                    self.appendToChat(ai_name, response_text)
                    ui.message(f"{ai_name}: " + response_text)
                wx.CallAfter(updateErrorUI)

        threading.Thread(target=worker, daemon=True).start()


class LinguaPalSettingsPanel(SettingsPanel):
    title = _("LinguaPal")

    def makeSettings(self, settingsSizer):
        sHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

        self.modelLabel = sHelper.addItem(wx.StaticText(self, label=_("Select AI Provider")))
        self.modelChoice = sHelper.addItem(wx.Choice(self, choices=["Groq", "Gemini"]))
        self.currentModel = config.conf[roleSECTION].get("model", "groq").lower()

        selection_idx = 0 if self.currentModel == "groq" else 1
        self.modelChoice.SetSelection(selection_idx)
        self.modelChoice.Bind(wx.EVT_CHOICE, self.onModelChange)

        self.keys = {
            "groq": config.conf[roleSECTION].get("apiKey", ""),
            "gemini": config.conf[roleSECTION].get("geminiApiKey", "")
        }

        initialLabel = _("Groq API Key") if self.currentModel == "groq" else _("Gemini API Key")
        self.apiKeyLabel = sHelper.addItem(wx.StaticText(self, label=initialLabel))
        self.apiKeyField = sHelper.addItem(wx.TextCtrl(self, value=self.keys[self.currentModel], style=wx.TE_PASSWORD))

        self.groqModelLabel = sHelper.addItem(wx.StaticText(self, label=_("Groq Model")))

        cached_groq = config.conf[roleSECTION].get("groqModelCache", "")
        if cached_groq:
            groq_choices = cached_groq.split(",")
        else:
            groq_choices = [
                "openai/gpt-oss-20b",
                "openai/gpt-oss-120b",
                "meta-llama/llama-4-scout-17b-16e-instruct",
                "meta-llama/llama-4-maverick-17b-128e-instruct",
                "qwen/qwen3-vl-32b-instruct",
                "groq/compound-mini",
                "groq/compound",
                "minimaxai/minimax-m2.5",
                "moonshotai/kimi-k2-instruct"
            ]

        saved_groq = config.conf[roleSECTION].get("groqModel", "openai/gpt-oss-20b")
        if saved_groq not in groq_choices:
            groq_choices.insert(0, saved_groq)

        self.groqModelChoice = sHelper.addItem(wx.Choice(self, choices=groq_choices))
        self.groqModelChoice.SetStringSelection(saved_groq)

        self.geminiModelLabel = sHelper.addItem(wx.StaticText(self, label=_("Gemini Model")))

        cached_gemini = config.conf[roleSECTION].get("geminiModelCache", "")
        if cached_gemini:
            gemini_choices = cached_gemini.split(",")
        else:
            gemini_choices = [
                "gemini-3.1-flash-lite",
                "gemini-3.1-flash",
                "gemini-3.5-flash",
                "gemini-3.6-flash",
                "gemini-3.7-flash"
            ]

        saved_gemini = config.conf[roleSECTION].get("geminiModel", "gemini-3.1-flash-lite")
        if saved_gemini not in gemini_choices:
            gemini_choices.insert(0, saved_gemini)

        self.geminiModelChoice = sHelper.addItem(wx.Choice(self, choices=gemini_choices))
        self.geminiModelChoice.SetStringSelection(saved_gemini)

        self.fetchModelsButton = sHelper.addItem(wx.Button(self, label=_("Fetch Available Models (Requires API Key)")))
        self.fetchModelsButton.Bind(wx.EVT_BUTTON, self.onFetchModels)

        self.promptLabel = sHelper.addItem(wx.StaticText(self, label=_("System Prompt (Persona)")))
        self.promptField = sHelper.addItem(wx.TextCtrl(
            self,
            value=config.conf[roleSECTION].get("systemPrompt", "You are a helpful AI assistant."),
            style=wx.TE_MULTILINE
        ))

        languages = [
            "English United States", "German Germany", "Urdu Pakistan", "French France",
            "Spanish Spain", "Arabic Standard", "Hindi India", "Chinese Mandarin (Simplified)",
            "Russian Russia", "Portuguese Brazil", "Bengali Bangladesh", "Japanese Japan",
            "Korean South Korea", "Italian Italy", "Turkish Turkey", "Persian Iran",
            "Malay Malaysia", "Swahili Kenya", "Tamil India", "Punjabi Pakistan",
            "Vietnamese Vietnam", "Indonesian Indonesia", "Dutch Netherlands", "Polish Poland",
            "Filipino Philippines", "Thai Thailand", "Ukrainian Ukraine", "Romanian Romania",
            "Greek Greece", "Amharic Ethiopia"
        ]
        languages.sort()
        self.langLabel = sHelper.addItem(wx.StaticText(self, label=_("Translate to")))
        self.langChoice = sHelper.addItem(wx.Choice(self))
        self.langChoice.Set(languages)
        self.langChoice.SetStringSelection(config.conf[roleSECTION]["translateTo"])

        self.updateCheckBox = sHelper.addItem(wx.CheckBox(self, label=_("Check for updates at NVDA startup")))
        self.updateCheckBox.SetValue(config.conf[roleSECTION].get("checkUpdatesAtStartup", True))

        self.updateButton = sHelper.addItem(wx.Button(self, label=_("Check for updates now")))
        self.updateButton.Bind(wx.EVT_BUTTON, lambda evt: checkForUpdates(showMessages=True))

    def _updateChoices(self, choice_ctrl, new_choices):
        current_selection = choice_ctrl.GetStringSelection()
        choice_ctrl.SetItems(new_choices)
        if current_selection and choice_ctrl.FindString(current_selection) != wx.NOT_FOUND:
            choice_ctrl.SetStringSelection(current_selection)
        elif new_choices:
            choice_ctrl.SetSelection(0)

    def onFetchModels(self, event):
        def worker():
            groq_ok = False
            gemini_ok = False

            groqKey = self.apiKeyField.GetValue() if self.currentModel == "groq" else self.keys["groq"]
            if groqKey:
                try:
                    r = requests.get(
                        "https://api.groq.com/openai/v1/models",
                        headers={"Authorization": f"Bearer {groqKey}"},
                        timeout=10
                    )
                    if r.status_code == 200:
                        models = r.json().get("data", [])
                        groq_names = []
                        exclude = ["whisper", "embed", "audio", "image", "tts", "guard", "orpheus", "canopylabs"]
                        for m in models:
                            mid = m["id"].lower()
                            if not any(x in mid for x in exclude):
                                groq_names.append(m["id"])
                        if groq_names:
                            config.conf[roleSECTION]["groqModelCache"] = ",".join(groq_names)
                            wx.CallAfter(self._updateChoices, self.groqModelChoice, groq_names)
                            groq_ok = True
                except Exception:
                    pass

            geminiKey = self.apiKeyField.GetValue() if self.currentModel == "gemini" else self.keys["gemini"]
            if geminiKey:
                try:
                    r = requests.get(
                        f"https://generativelanguage.googleapis.com/v1beta/models?key={geminiKey}",
                        timeout=10
                    )
                    if r.status_code == 200:
                        models = r.json().get("models", [])
                        gemini_names = []
                        for m in models:
                            if "generateContent" in m.get("supportedGenerationMethods", []):
                                name = m["name"].replace("models/", "")
                                nl = name.lower()
                                if "gemini" in nl and not any(x in nl for x in [
                                    "embed", "aqa", "vision", "audio", "image",
                                    "tts", "learnlm", "video", "robotics",
                                    "bison", "gecko", "omni", "customtool"
                                ]):
                                    gemini_names.append(name)
                        if gemini_names:
                            config.conf[roleSECTION]["geminiModelCache"] = ",".join(gemini_names)
                            wx.CallAfter(self._updateChoices, self.geminiModelChoice, gemini_names)
                            gemini_ok = True
                except Exception:
                    pass

            if groq_ok or gemini_ok:
                wx.CallAfter(ui.message, _("Models refreshed successfully."))
            else:
                wx.CallAfter(ui.message, _("Could not fetch models. Check your API keys."))

        threading.Thread(target=worker, daemon=True).start()

    def onModelChange(self, event):
        newModel = self.modelChoice.GetStringSelection().lower()
        if newModel == self.currentModel:
            return
        self.keys[self.currentModel] = self.apiKeyField.GetValue()
        self.currentModel = newModel
        if self.currentModel == "groq":
            self.apiKeyLabel.SetLabel(_("Groq API Key"))
        else:
            self.apiKeyLabel.SetLabel(_("Gemini API Key"))
        self.apiKeyField.SetValue(self.keys[self.currentModel])

    def onSave(self):
        self.keys[self.currentModel] = self.apiKeyField.GetValue()
        config.conf[roleSECTION]["model"] = self.modelChoice.GetStringSelection().lower()
        config.conf[roleSECTION]["apiKey"] = self.keys["groq"]
        config.conf[roleSECTION]["geminiApiKey"] = self.keys["gemini"]
        config.conf[roleSECTION]["groqModel"] = self.groqModelChoice.GetStringSelection()
        config.conf[roleSECTION]["geminiModel"] = self.geminiModelChoice.GetStringSelection()
        config.conf[roleSECTION]["systemPrompt"] = self.promptField.GetValue()
        config.conf[roleSECTION]["translateTo"] = self.langChoice.GetStringSelection()
        config.conf[roleSECTION]["checkUpdatesAtStartup"] = self.updateCheckBox.GetValue()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = _("LinguaPal")

    def __init__(self):
        super().__init__()
        NVDASettingsDialog.categoryClasses.append(LinguaPalSettingsPanel)
        self.chatDialog = None
        if config.conf[roleSECTION].get("checkUpdatesAtStartup", True):
            wx.CallLater(5000, checkForUpdates, False)

    @script(gesture="kb:NVDA+Alt+c", description=_("Translates clipboard text using the currently selected AI model"))
    def script_translateClipboard(self, gesture):
        try:
            clip = api.getClipData()
        except Exception:
            clip = None

        if not clip:
            wx.CallAfter(ui.message, _("Clipboard is empty"))
            return

        def doTranslation(text_to_translate):
            try:
                tones.beep(440, 50)
                tones.beep(880, 50)
                result = translate(text_to_translate)
                tones.beep(523, 100)
                tones.beep(659, 100)
                wx.CallAfter(api.copyToClip, result)
                wx.CallAfter(ui.message, result)
            except Exception as e:
                tones.beep(200, 200)
                wx.CallAfter(ui.message, _("Translation failed: ") + str(e)[:200])

        threading.Thread(target=doTranslation, args=(clip,), daemon=True).start()

    @script(gesture="kb:NVDA+Alt+g", description=_("Opens LinguaPal chat dialog"))
    def script_customPrompt(self, gesture):
        try:
            if self.chatDialog is not None:
                try:
                    if self.chatDialog.IsShown():
                        self.chatDialog.Raise()
                        return
                except Exception:
                    self.chatDialog = None
            self.chatDialog = GeminiChatDialog()
            self.chatDialog.Bind(wx.EVT_CLOSE, self.onDialogClose)
        except Exception as e:
            ui.message(_("Error: ") + str(e))

    @script(gesture="kb:NVDA+Alt+d", description=_("Describe focused window using AI vision"))
    def script_describeScreen(self, gesture):
        tones.beep(500, 80)
        try:
            b64, mime = _capture_foreground_window()
        except Exception as e:
            ui.message(_("Screen capture failed: ") + str(e))
            return
        try:
            if self.chatDialog is not None:
                try:
                    if not self.chatDialog.IsShown():
                        self.chatDialog = None
                except Exception:
                    self.chatDialog = None
            if self.chatDialog is None:
                self.chatDialog = GeminiChatDialog()
                self.chatDialog.Bind(wx.EVT_CLOSE, self.onDialogClose)
            else:
                self.chatDialog.Raise()
            self.chatDialog.injectScreenshot(b64, mime, _("screenshot.png"))
        except Exception as e:
            ui.message(_("Error: ") + str(e))

    @script(gesture="kb:NVDA+Alt+s", description=_("Opens LinguaPal settings panel"))
    def script_openSettingsDialog(self, gesture):
        try:
            wx.CallAfter(gui.mainFrame._popupSettingsDialog, gui.settingsDialogs.NVDASettingsDialog, LinguaPalSettingsPanel)
        except Exception as e:
            ui.message(_("Error opening settings: ") + str(e))

    def onDialogClose(self, event):
        self.chatDialog = None
        event.Skip()

    def terminate(self):
        try:
            NVDASettingsDialog.categoryClasses.remove(LinguaPalSettingsPanel)
        except Exception:
            pass

