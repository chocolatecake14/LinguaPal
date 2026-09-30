import base64
import io
import os
import re
import threading
import wx
import gui
import ui
import api
import config
from .config_spec import roleSECTION, MAX_CHAT_HISTORY, MAX_CONTEXT_MESSAGES
from .api_client import geminiStream, groqStream, pickVisionModel
from .streaming import ThinkFilter, SpeechStreamer, collapse
from .screen_capture import is_image_black


def _activeImageIndex(history):
    """Index of the most recent message carrying an image, or -1."""
    for i in range(len(history) - 1, -1, -1):
        if history[i].get("image_b64"):
            return i
    return -1


def _contextSlice(history):
    """The tail of the conversation that is actually worth uploading."""
    if len(history) <= MAX_CONTEXT_MESSAGES:
        return history
    window = history[-MAX_CONTEXT_MESSAGES:]
    imgIdx = _activeImageIndex(history)
    if 0 <= imgIdx < len(history) - MAX_CONTEXT_MESSAGES:
        # The attached image outranks an old text turn; keep it in view.
        window = [history[imgIdx]] + window
    # Gemini rejects a conversation that opens on a model turn.
    while window and window[0]["role"] != "user":
        window = window[1:]
    return window


def showWhatsNew():
    changes_path = os.path.join(os.path.dirname(__file__), "changes.txt")
    if not os.path.exists(changes_path):
        changes_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "doc", "en", "changes.txt")
    content = ""
    if os.path.exists(changes_path):
        try:
            with open(changes_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            content = _("Error reading changelog: ") + str(e)
    else:
        content = _("No changelog file found.")

    def _open():
        dlg = WhatsNewDialog(gui.mainFrame, content)
        dlg.ShowModal()
        dlg.Destroy()
    wx.CallAfter(_open)


class WhatsNewDialog(wx.Dialog):
    def __init__(self, parent, text):
        super().__init__(parent, -1, title=_("What's New in LinguaPal"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.text = text
        self.initUI()

    def initUI(self):
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.textBox = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH)
        self.textBox.SetValue(self.text)
        self.textBox.SetName(_("What's new content"))
        sizer.Add(self.textBox, 1, flag=wx.EXPAND | wx.ALL, border=10)
        btn = wx.Button(self, id=wx.ID_OK, label=_("&Close"))
        sizer.Add(btn, 0, flag=wx.ALIGN_CENTER | wx.BOTTOM, border=10)
        self.SetSizer(sizer)
        self.SetMinSize((450, 350))
        self.SetSize((650, 500))
        self.CenterOnParent()
        self.Bind(wx.EVT_CHAR_HOOK, self.onKey)
        self.textBox.SetFocus()

    def onKey(self, event):
        k = event.GetKeyCode()
        if k == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_OK)
        else:
            event.Skip()


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
        self.last_sent_image_name = None
        self._is_generating = False
        self._cancel_requested = False
        self._is_closed = False
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

        btnSizer = wx.BoxSizer(wx.HORIZONTAL)
        self.sendBtn = wx.Button(self, id=wx.ID_OK, label=_("&Send"))
        self.sendBtn.Bind(wx.EVT_BUTTON, self.onSend)
        btnSizer.Add(self.sendBtn, 0, flag=wx.RIGHT, border=10)

        self.clearBtn = wx.Button(self, label=_("Clear History"))
        self.clearBtn.Bind(wx.EVT_BUTTON, self.onClearHistory)
        btnSizer.Add(self.clearBtn, 0)

        sizer.Add(btnSizer, 0, flag=wx.ALIGN_CENTER | wx.ALL, border=10)
        self.SetSizerAndFit(sizer)
        self.Bind(wx.EVT_CHAR_HOOK, self.onKey)
        self.Maximize()
        self.Show()
        self.inputBox.SetFocus()

    def onKey(self, event):
        k = event.GetKeyCode()
        if k == wx.WXK_ESCAPE:
            if self._is_generating:
                self.stopGeneration()
                return
            self._is_closed = True
            self._cancel_requested = True
            self.Destroy()
            return
        elif k == wx.WXK_F4 and event.AltDown():
            self._is_closed = True
            self._cancel_requested = True
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
        elif event.ControlDown() and k in (ord('C'), ord('c')):
            focus_win = wx.Window.FindFocus()
            if focus_win == self.historyBox:
                self.copySelectedMessage()
                return
            event.Skip()
        elif (event.ControlDown() and k in (ord('V'), ord('v'), 22)) or (k == 22):
            focus_win = wx.Window.FindFocus()
            if focus_win == self.inputBox:
                if self._tryPasteClipboardImage():
                    return
            event.Skip()
        else:
            event.Skip()

    def _tryPasteClipboardImage(self):
        """Check if clipboard holds an image and attach it for the next message."""
        if not wx.TheClipboard.IsOpened():
            if not wx.TheClipboard.Open():
                return False
            opened = True
        else:
            opened = False

        try:
            # 1. Check for raw bitmap data (e.g. Snipping tool, Copy Image in browser)
            if wx.TheClipboard.IsSupported(wx.DataFormat(wx.DF_BITMAP)):
                bmp_data = wx.BitmapDataObject()
                if wx.TheClipboard.GetData(bmp_data):
                    bmp = bmp_data.GetBitmap()
                    if bmp.IsOk() and bmp.GetWidth() > 0 and bmp.GetHeight() > 0:
                        image = bmp.ConvertToImage()
                        if not is_image_black(image):
                            longest = max(image.GetWidth(), image.GetHeight())
                            if longest > 1400:
                                scale = 1400.0 / float(longest)
                                image = image.Scale(
                                    max(1, int(image.GetWidth() * scale)),
                                    max(1, int(image.GetHeight() * scale)),
                                    wx.IMAGE_QUALITY_HIGH
                                )
                            buf = io.BytesIO()
                            if image.SaveFile(buf, wx.BITMAP_TYPE_PNG):
                                raw = buf.getvalue()
                                self.pending_image_b64 = base64.b64encode(raw).decode('utf-8')
                                self.pending_image_mime = 'image/png'
                                self.pending_image_name = _("clipboard_image.png")
                                self.imgStatusLabel.SetLabel(_("Attached for next message: ") + self.pending_image_name)
                                self.removeImgBtn.Show()
                                self.Layout()
                                ui.message(_("Image attached from clipboard: ") + self.pending_image_name)
                                return True

            # 2. Check for copied image file (e.g. copied .png or .jpg in Explorer)
            if wx.TheClipboard.IsSupported(wx.DataFormat(wx.DF_FILENAME)):
                file_data = wx.FileDataObject()
                if wx.TheClipboard.GetData(file_data):
                    filenames = file_data.GetFilenames()
                    if filenames:
                        path = filenames[0]
                        ext = os.path.splitext(path)[1].lower()
                        mime_map = {
                            '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                            '.png': 'image/png', '.gif': 'image/gif',
                            '.webp': 'image/webp', '.bmp': 'image/bmp'
                        }
                        if ext in mime_map and os.path.exists(path):
                            with open(path, 'rb') as f:
                                raw = f.read()
                            self.pending_image_b64 = base64.b64encode(raw).decode('utf-8')
                            self.pending_image_mime = mime_map[ext]
                            self.pending_image_name = os.path.basename(path)
                            self.imgStatusLabel.SetLabel(_("Attached for next message: ") + self.pending_image_name)
                            self.removeImgBtn.Show()
                            self.Layout()
                            ui.message(_("Image attached from clipboard: ") + self.pending_image_name)
                            return True
        except Exception:
            pass
        finally:
            if opened:
                wx.TheClipboard.Close()
        return False

    def copySelectedMessage(self):
        selection = self.historyBox.GetSelection()
        if selection == wx.NOT_FOUND or selection >= len(self.full_messages):
            ui.message(_("No message selected."))
            return
        text = self.full_messages[selection]
        api.copyToClip(text)
        ui.message(_("Message copied to clipboard."))

    def onClearHistory(self, event):
        if self._is_generating:
            self.stopGeneration()
        self.chat_history = []
        self.full_messages = []
        self.historyBox.Clear()
        self.pending_image_b64 = None
        self.pending_image_mime = None
        self.pending_image_name = None
        self.last_sent_image_name = None
        self.imgStatusLabel.SetLabel(_("No image attached"))
        self.removeImgBtn.Hide()
        self.Layout()
        ui.message(_("Chat history cleared."))
        self.inputBox.SetFocus()

    def stopGeneration(self):
        if self._is_generating:
            self._cancel_requested = True
            ui.message(_("Stopping response..."))

    def onDoubleClick(self, event):
        self.showFullMessage()

    def showFullMessage(self):
        selection = self.historyBox.GetSelection()
        if selection == wx.NOT_FOUND or selection >= len(self.full_messages):
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
            self.imgStatusLabel.SetLabel(_("Attached for next message: ") + self.pending_image_name)
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
        if self.last_sent_image_name:
            self.imgStatusLabel.SetLabel(_("Active image in chat: ") + self.last_sent_image_name)
        else:
            self.imgStatusLabel.SetLabel(_("No image attached"))
        self.removeImgBtn.Hide()
        self.Layout()
        ui.message(_("Pending image removed."))

    def onSend(self, event):
        if self._is_generating:
            self.stopGeneration()
            return
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

        if img_name:
            self.last_sent_image_name = img_name
            self.imgStatusLabel.SetLabel(_("Active image in chat: ") + img_name)
            self.removeImgBtn.Hide()
            self.Layout()
        elif self.last_sent_image_name:
            self.imgStatusLabel.SetLabel(_("Active image in chat: ") + self.last_sent_image_name)
        else:
            self.imgStatusLabel.SetLabel(_("No image attached"))

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

        self._is_generating = True
        self._cancel_requested = False
        self.sendBtn.SetLabel(_("S&top"))
        wx.CallAfter(self.getResponse)

    def injectMessage(self, message):
        def doSend():
            self.inputBox.SetValue(message)
            self.onSend(None)

        if self._is_generating:
            self.stopGeneration()
            wx.CallLater(300, doSend)
            return
        doSend()

    def injectScreenshot(self, b64, mime, name, prompt=None):
        self.pending_image_b64 = b64
        self.pending_image_mime = mime
        self.pending_image_name = name
        if not prompt:
            prompt = _(
                "Please describe this screenshot in detail for a blind user. "
                "Include all visible text, UI controls and their states, "
                "any error messages, and the application name if visible. "
                "If the image is completely black, blank, or obscured, state only that the screen is black or blank, and do not guess or hallucinate any UI elements."
            )
        def doSend():
            self.inputBox.SetValue(prompt)
            self.onSend(None)

        if self._is_generating:
            self.stopGeneration()
            wx.CallLater(300, doSend)
            return
        doSend()

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

    def _setLastLine(self, text):
        count = self.historyBox.GetCount()
        if count > 0 and self.full_messages:
            self.full_messages[-1] = text
            display = text
            if len(display) > 1500:
                display = display[:1500] + _("... [Press Enter to read full message]")
            self.historyBox.SetString(count - 1, display)

    def _buildGeminiContents(self):
        history = _contextSlice(self.chat_history)
        imgIdx = _activeImageIndex(history)
        contents = []
        for i, msg in enumerate(history):
            if i == imgIdx:
                parts = [
                    {"inline_data": {"mime_type": msg["image_mime"], "data": msg["image_b64"]}},
                    {"text": msg["text"]}
                ]
            else:
                parts = [{"text": msg["text"]}]
            contents.append({"role": msg["role"], "parts": parts})
        return contents

    def _buildGroqMessages(self):
        history = _contextSlice(self.chat_history)
        imgIdx = _activeImageIndex(history)
        messages = []
        for i, msg in enumerate(history):
            role = "assistant" if msg["role"] == "model" else msg["role"]
            if i == imgIdx:
                content = [
                    {"type": "image_url", "image_url": {
                        "url": f"data:{msg['image_mime']};base64,{msg['image_b64']}"
                    }},
                    {"type": "text", "text": msg["text"]}
                ]
            else:
                content = msg["text"]
            messages.append({"role": role, "content": content})
        return messages, imgIdx >= 0

    def getResponse(self):
        def worker():
            ai_name = "System"
            try:
                sys_prompt = config.conf[roleSECTION].get("systemPrompt", "").strip()
                if config.conf[roleSECTION]["model"] == "gemini":
                    ai_name = "Gemini"
                    stream = geminiStream(self._buildGeminiContents(),
                                          systemPrompt=sys_prompt or None)
                else:
                    ai_name = "Groq"
                    messages, has_image = self._buildGroqMessages()
                    model = None
                    if has_image:
                        model = pickVisionModel(config.conf[roleSECTION]["groqModel"])
                    stream = groqStream(messages, model=model, systemPrompt=sys_prompt or None)

                if self._cancel_requested or self._is_closed:
                    return

                wx.CallAfter(self.appendToChat, ai_name, "")
                wx.CallAfter(ui.message, f"{ai_name}: ")

                think = ThinkFilter()
                speaker = SpeechStreamer(guard=lambda: not self._cancel_requested and not self._is_closed, eagerFirst=90)
                visible = []
                visible_len = 0
                last_ui_len = 0

                for chunk in stream:
                    if self._cancel_requested or self._is_closed:
                        break
                    text = think.feed(chunk)
                    if not text:
                        continue
                    visible.append(text)
                    visible_len += len(text)
                    speaker.feed(text)
                    if visible_len - last_ui_len >= 200:
                        last_ui_len = visible_len
                        wx.CallAfter(self._setLastLine, f"{ai_name}: {collapse(''.join(visible))}")

                if not (self._cancel_requested or self._is_closed):
                    tail = think.flush()
                    if tail:
                        visible.append(tail)
                        speaker.feed(tail)
                    speaker.flush()

                final = collapse("".join(visible))
                if self._cancel_requested:
                    final_display = f"{final} [{_('Stopped')}]" if final else _("[Stopped]")
                    wx.CallAfter(self._setLastLine, f"{ai_name}: {final_display}")
                    self.chat_history.append({"role": "model", "text": final_display})
                else:
                    wx.CallAfter(self._setLastLine, f"{ai_name}: {final or _('(No response)')}")
                    self.chat_history.append({"role": "model", "text": final})

            except Exception as e:
                if not (self._cancel_requested or self._is_closed):
                    response_text = _("Error: ") + str(e)

                    def updateErrorUI():
                        self.chat_history.append({"role": "model", "text": response_text})
                        self.appendToChat(ai_name, response_text)
                        ui.message(f"{ai_name}: " + response_text)
                    wx.CallAfter(updateErrorUI)
            finally:
                def finish():
                    self._is_generating = False
                    self._cancel_requested = False
                    try:
                        self.sendBtn.SetLabel(_("&Send"))
                    except Exception:
                        pass
                wx.CallAfter(finish)

        threading.Thread(target=worker, daemon=True).start()
