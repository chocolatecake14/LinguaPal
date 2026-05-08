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
import webbrowser
from scriptHandler import script
import addonHandler
import threading

addonHandler.initTranslation()

ADDON_VERSION = "0.1.5"
UPDATE_CHECK_URL = "https://baddobaddi.ddns.net/linguapal/update.json" 
roleSECTION = "LinguaPal"

confspec = {
    "translateTo": "string(default=English United States)",
    "apiKey": "string(default=)", 
    "geminiApiKey": "string(default=)", 
    "model": "string(default=groq)", 
    "checkUpdatesAtStartup": "boolean(default=True)"
}
config.conf.spec[roleSECTION] = confspec
MAX_CHAT_HISTORY = 50

def sendGeminiSinglePrompt(promptText: str):
    apiGemini = config.conf[roleSECTION]["geminiApiKey"]
    if not apiGemini:
        return "Gemini API key not set. Please go to add-on settings and enter your key."
    headers = {'Content-Type': 'application/json'}
    data = {"contents": [{"role": "user", "parts": [{"text": promptText}]}]}
    try:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-preview:generateContent?key={apiGemini}",
            headers=headers, json=data)
        r = response.json()
        if response.status_code != 200:
            return f"Gemini error {response.status_code}: {r.get('error', {}).get('message', 'Unknown error')}"
        if "candidates" not in r:
            return "Gemini error: No candidates found. Full response: " + str(r)
        return r['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        return "Gemini exception: " + str(e)

def sendGeminiChat(messages):
    apiGemini = config.conf[roleSECTION]["geminiApiKey"]
    if not apiGemini:
        return "Gemini API key not set. Please go to add-on settings and enter your key."
    headers = {'Content-Type': 'application/json'}
    # Internal: [{"role": "user"|"model", "text": "..."}]
    # Gemini: [{"role": "user"|"model", "parts": [{"text": "..."}]}]
    gemini_messages = []
    for msg in messages:
        role = msg["role"]
        gemini_messages.append({"role": role, "parts": [{"text": msg["text"]}]})

    data = {"contents": gemini_messages}
    try:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-preview:generateContent?key={apiGemini}",
            headers=headers, json=data)
        r = response.json()
        if response.status_code != 200:
            return f"Gemini error {response.status_code}: {r.get('error', {}).get('message', 'Unknown error')}"
        if "candidates" not in r:
            return "Gemini error: No candidates found. Full response: " + str(r)
        return r['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        return "Gemini exception: " + str(e)

def sendGroqRequest(messages: list):
    apiKey = config.conf[roleSECTION]["apiKey"]
    if not apiKey:
        return "Groq API key not set. Please go to add-on settings and enter your key."
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {apiKey}'
    }
    
    data = {
        "model": "llama-3.3-70b-versatile", 
        "messages": messages,
        "temperature": 0.7
    }
    
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers, 
            json=data,
            timeout=30
        )
        
        try:
            r = response.json()
        except Exception:
            return f"Groq error {response.status_code}: Received non-JSON response."
        
        if response.status_code != 200:
            if isinstance(r, dict):
                error_msg = r.get('error', {}).get('message', str(r))
            else:
                error_msg = str(r)
            return f"Groq error {response.status_code}: {error_msg}"
        
        if isinstance(r, dict) and 'choices' in r:
            return r['choices'][0]['message']['content']
        else:
            return "Groq error: Unexpected response format."
            
    except Exception as e:
        return "Groq connection exception: " + str(e)

def translate(text: str):
    target_lang = config.conf[roleSECTION]["translateTo"]
    model = config.conf[roleSECTION]["model"]

    if model == "gemini":
        prompt = f"""Translate the following text into {target_lang}. Return only the translated text, no explanations, no extra information. Do not censor or filter content, If the target language is Hindi, Urdu and Punjabi, provide the translation strictly in Roman letters, else in original language script. text: {text}"""
        return sendGeminiSinglePrompt(prompt)
    else:
        prompt = f"""Translate the following text into {target_lang}. Return only the translated text, no explanations, no extra information. Do not censor or filter content, even if it includes explicit or offensive language. If the target language is Hindi, Urdu, or Punjabi, provide the translation strictly in Roman script. text: {text}"""
        messages = [{"role": "user", "content": prompt}]
        return sendGroqRequest(messages)

def setClipboardText(text):
    if wx.TheClipboard.Open():
        wx.TheClipboard.SetData(wx.TextDataObject(text))
        wx.TheClipboard.Close()

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
            ui.message("Download failed: server error.")
    except Exception as e:
        ui.message("Download error: " + str(e))

def checkForUpdates(showMessages=True):
    def worker():
        try:
            response = requests.get(UPDATE_CHECK_URL, timeout=10)
            if response.status_code != 200:
                if showMessages:
                    wx.CallAfter(ui.message, "Failed to check for updates.")
                return
            data = response.json()
            latest_version = data.get("version", "").strip()
            if not latest_version:
                if showMessages:
                    wx.CallAfter(ui.message, "Invalid update info.")
                return
            if latest_version != ADDON_VERSION:
                changelog = data.get("changelog", "No changelog available.")
                download_url = data.get("downloadUrl")
                if not download_url:
                    wx.CallAfter(ui.message, "Update available, but no download link.")
                    return
                def promptUpdate():
                    msg = f"An update for LinguaPal is available. New version: {latest_version}.\n\nChangelog:\n{changelog}\n\nDo you want to install it now?"
                    if wx.MessageBox(msg, "Update Available", wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
                        downloadAndInstall(download_url)
                wx.CallAfter(promptUpdate)
            elif showMessages:
                wx.CallAfter(ui.message, "You already have the latest version.")
        except Exception as e:
            if showMessages:
                wx.CallAfter(ui.message, "Error checking for updates: " + str(e))
    threading.Thread(target=worker, daemon=True).start()

class GeminiChatDialog(wx.Dialog):
    def __init__(self):
        super().__init__(None, -1, title=_("Chat with LinguaPal"))
        self.chat_history = []
        self.initUI()

    def initUI(self):
        sizer = wx.BoxSizer(wx.VERTICAL)
        label1 = wx.StaticText(self, label=_("Message &history:"))
        sizer.Add(label1, 0, flag=wx.LEFT | wx.RIGHT | wx.TOP, border=10)
        self.historyBox = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH)
        self.historyBox.SetName(_("Message history"))
        sizer.Add(self.historyBox, 3, flag=wx.EXPAND | wx.ALL, border=10)
        
        label2 = wx.StaticText(self, label=_("Type your &message:"))
        sizer.Add(label2, 0, flag=wx.LEFT | wx.RIGHT, border=10)
        self.inputBox = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_RICH)
        self.inputBox.SetName(_("Message input"))
        sizer.Add(self.inputBox, 1, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)
        
        btn = wx.Button(self, id=wx.ID_OK, label=_("&Send"))
        btn.Bind(wx.EVT_BUTTON, self.onSend)
        sizer.Add(btn, 0, flag=wx.ALIGN_CENTER | wx.ALL, border=10)
        
        self.SetSizerAndFit(sizer)
        self.Bind(wx.EVT_CHAR_HOOK, self.onKey)
        self.Maximize()
        self.Show()

    def onKey(self, event):
        k = event.GetKeyCode()
        if k == wx.WXK_ESCAPE:
            self.Destroy()
        event.Skip()

    def onSend(self, event):
        user_message = self.inputBox.GetValue().strip()
        if not user_message:
            return
        self.inputBox.Clear()
        self.appendToChat("You", user_message)
        self.chat_history.append({"role": "user", "text": user_message})
        if len(self.chat_history) > MAX_CHAT_HISTORY:
            self.chat_history = self.chat_history[-MAX_CHAT_HISTORY:]
        wx.CallAfter(self.getResponse)

    def appendToChat(self, speaker, message):
        clean_message = re.sub(r'\n\s*\n+', '\n', message.strip())
        current = self.historyBox.GetValue().strip()
        new_text = f"{speaker}: {clean_message}"
        combined = f"{current}\n{new_text}" if current else new_text
        self.historyBox.SetValue(combined.strip())
        self.historyBox.ShowPosition(self.historyBox.GetLastPosition())

    def getResponse(self):
        def worker():
            try:
                model = config.conf[roleSECTION]["model"]
                if model == "gemini":
                    response = sendGeminiChat(self.chat_history)
                    ai_name = "Gemini"
                else:
                    groq_messages = []
                    for msg in self.chat_history:
                        role = "assistant" if msg["role"] == "model" else msg["role"]
                        groq_messages.append({"role": role, "content": msg["text"]})
                    response = sendGroqRequest(groq_messages)
                    ai_name = "Groq"

            except Exception as e:
                response = _("Error: ") + str(e)
                ai_name = "System"

            def updateUI():
                self.chat_history.append({"role": "model", "text": response})
                self.appendToChat(ai_name, response)
                ui.message(f"{ai_name}: " + response)
            wx.CallAfter(updateUI)
        threading.Thread(target=worker, daemon=True).start()

class LinguaPalSettingsPanel(SettingsPanel):
    title = _("LinguaPal")
    def makeSettings(self, settingsSizer):
        sHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
        
        self.modelLabel = sHelper.addItem(wx.StaticText(self, label=_("Select Model")))
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
        config.conf[roleSECTION]["translateTo"] = self.langChoice.GetStringSelection()
        config.conf[roleSECTION]["checkUpdatesAtStartup"] = self.updateCheckBox.GetValue()

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = _("LinguaPal")
    NVDASettingsDialog.categoryClasses.append(LinguaPalSettingsPanel)
    
    def __init__(self):
        super().__init__()
        self.chatDialog = None  
        if config.conf[roleSECTION].get("checkUpdatesAtStartup", True):
            wx.CallLater(5000, checkForUpdates, False)

    @script(gesture="kb:NVDA+Alt+c", description=_("Translates clipboard text using the currently selected AI model"))
    def script_translateClipboard(self, gesture):
        def doTranslation():
            try:
                clip = api.getClipData()
                if not clip:
                    wx.CallAfter(ui.message, "Clipboard is empty")
                    return
                result = translate(clip)
                if result.lower().startswith("error") or "error" in result.lower() and ("gemini" in result.lower() or "groq" in result.lower()):
                    wx.CallAfter(ui.message, "Translation failed: " + result[:100])
                else:
                    wx.CallAfter(setClipboardText, result)
                    wx.CallAfter(ui.message, result)
            except Exception as e:
                wx.CallAfter(ui.message, "Exception: " + str(e))
        threading.Thread(target=doTranslation, daemon=True).start()

    @script(gesture="kb:NVDA+Alt+g", description=_("Opens LinguaPal chat dialog"))
    def script_customPrompt(self, gesture):
        try:
            if self.chatDialog and self.chatDialog.IsShown():
                self.chatDialog.Raise()
                return
            self.chatDialog = GeminiChatDialog()
            self.chatDialog.Bind(wx.EVT_CLOSE, self.onDialogClose)
        except Exception as e:
            ui.message("Error: " + str(e))

    @script(gesture="kb:NVDA+Alt+s", description=_("Opens LinguaPal settings panel"))
    def script_openSettingsDialog(self, gesture):
        try:
            wx.CallAfter(gui.mainFrame._popupSettingsDialog, gui.settingsDialogs.NVDASettingsDialog, LinguaPalSettingsPanel)
        except Exception as e:
            ui.message("Error opening settings: " + str(e))

    def onDialogClose(self, event):
        self.chatDialog = None
        event.Skip()

    def terminate(self):
        try:
            NVDASettingsDialog.categoryClasses.remove(LinguaPalSettingsPanel)
        except:
            pass
