import threading
import ctypes
import wx
import gui
from gui import NVDASettingsDialog
import globalPluginHandler
import ui
import api
import tones
import config
import addonHandler
from scriptHandler import script

addonHandler.initTranslation()

from .config_spec import (
    roleSECTION, resolveTranslateModel, prewarmConnection,
    cacheKey, cacheGet, cachePut,
)
from .api_client import translateStream
from .streaming import ThinkFilter, SpeechStreamer
from .screen_capture import capture_foreground_window
from .updater import checkForUpdates
from .dialogs import GeminiChatDialog, showWhatsNew
from .settings_panel import LinguaPalSettingsPanel


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = _("LinguaPal")

    def __init__(self):
        super().__init__()
        NVDASettingsDialog.categoryClasses.append(LinguaPalSettingsPanel)
        self.chatDialog = None
        self.toolsMenuItem = None
        self._translateGen = 0
        self._initMenu()
        if config.conf[roleSECTION].get("checkUpdatesAtStartup", True):
            wx.CallLater(5000, checkForUpdates, False)
        # Pay the TLS handshake while NVDA is still settling, not on first use.
        wx.CallLater(8000, prewarmConnection)

    def _initMenu(self):
        try:
            self.linguaPalMenu = wx.Menu()

            item_chat = self.linguaPalMenu.Append(wx.ID_ANY, _("&Chat with AI\tNVDA+Alt+G"))
            self._bindMenuItem(item_chat, lambda evt: wx.CallAfter(self.script_customPrompt, None))

            item_trans = self.linguaPalMenu.Append(wx.ID_ANY, _("&Translate Clipboard\tNVDA+Alt+C"))
            self._bindMenuItem(item_trans, lambda evt: wx.CallAfter(self.script_translateClipboard, None))

            item_desc = self.linguaPalMenu.Append(wx.ID_ANY, _("&Describe Focused Window\tNVDA+Alt+D"))
            self._bindMenuItem(item_desc, lambda evt: wx.CallAfter(self.script_describeScreen, None))

            item_swap = self.linguaPalMenu.Append(wx.ID_ANY, _("S&wap Translation Language\tNVDA+Alt+T"))
            self._bindMenuItem(item_swap, lambda evt: wx.CallAfter(self.script_swapLanguages, None))

            self.linguaPalMenu.AppendSeparator()

            item_settings = self.linguaPalMenu.Append(wx.ID_ANY, _("&Settings...\tNVDA+Alt+S"))
            self._bindMenuItem(item_settings, lambda evt: wx.CallAfter(self.script_openSettingsDialog, None))

            item_whatsnew = self.linguaPalMenu.Append(wx.ID_ANY, _("&What's New..."))
            self._bindMenuItem(item_whatsnew, lambda evt: wx.CallAfter(showWhatsNew))

            item_updates = self.linguaPalMenu.Append(wx.ID_ANY, _("Check for &Updates..."))
            self._bindMenuItem(item_updates, lambda evt: wx.CallAfter(checkForUpdates, True))

            self.toolsMenuItem = gui.mainFrame.sysTrayIcon.toolsMenu.AppendSubMenu(self.linguaPalMenu, _("Lingua&Pal"))
        except Exception:
            self.toolsMenuItem = None

    def _bindMenuItem(self, item, handler):
        try:
            gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, handler, id=item.GetId())
        except Exception:
            pass
        try:
            gui.mainFrame.Bind(wx.EVT_MENU, handler, id=item.GetId())
        except Exception:
            pass

    @script(gesture="kb:NVDA+Alt+t", description=_("Swaps active translation target language with the secondary language"))
    def script_swapLanguages(self, gesture):
        current = config.conf[roleSECTION].get("translateTo", "English (United States)")
        secondary = config.conf[roleSECTION].get("secondaryTranslateTo", "Urdu (Pakistan)")

        if current == secondary:
            tones.beep(300, 100)
            ui.message(_("Translation language is already set to {lang}. No changes made.").format(lang=current))
            return

        config.conf[roleSECTION]["translateTo"] = secondary
        config.conf[roleSECTION]["secondaryTranslateTo"] = current

        tones.beep(523, 60)
        ui.message(_("Target language: {lang}").format(lang=secondary))
        # This gesture is nearly always followed by a translation.
        prewarmConnection()

    @script(gesture="kb:NVDA+Alt+c", description=_("Translates clipboard text using the currently selected AI model"))
    def script_translateClipboard(self, gesture):
        try:
            clip = api.getClipData()
        except Exception:
            clip = None

        if not clip or not clip.strip():
            ui.message(_("Clipboard is empty"))
            return

        provider = config.conf[roleSECTION]["model"]
        model = resolveTranslateModel(provider)
        cached = cacheGet(cacheKey(provider, model, clip))
        if cached is not None:
            # Same text, same target, same model: no reason to ask again.
            self._translateGen += 1
            if config.conf[roleSECTION].get("copyTranslationToClipboard", True):
                api.copyToClip(cached)
            ui.message(cached)
            wx.CallAfter(tones.beep, 880, 30)
            return

        # Beep on the main thread so it never delays the request itself.
        tones.beep(660, 40)
        self._translateGen += 1
        threading.Thread(
            target=self._translateWorker,
            args=(clip, provider, model, self._translateGen),
            daemon=True
        ).start()

    def _translateWorker(self, text, provider, model, generation):
        def isCurrent():
            return self._translateGen == generation

        think = ThinkFilter()
        speaker = SpeechStreamer(guard=isCurrent, eagerFirst=60)
        parts = []
        try:
            for chunk in translateStream(text, model=model):
                if not isCurrent():
                    # Superseded by a newer translation; stop reading, stay quiet.
                    return
                visible = think.feed(chunk)
                if visible:
                    parts.append(visible)
                    speaker.feed(visible)
            tail = think.flush()
            if tail:
                parts.append(tail)
                speaker.feed(tail)
            speaker.flush()
            result = "".join(parts).strip()
            if not isCurrent():
                return
            if result:
                cachePut(cacheKey(provider, model, text), result)
                if config.conf[roleSECTION].get("copyTranslationToClipboard", True):
                    wx.CallAfter(api.copyToClip, result)
                tones.beep(880, 30)
            else:
                wx.CallAfter(ui.message, _("No translation returned."))
        except Exception as e:
            if not isCurrent():
                return
            wx.CallAfter(tones.beep, 200, 200)
            wx.CallAfter(ui.message, _("Translation failed: ") + str(e)[:300])

    def _liveChatDialog(self):
        """The open chat dialog, or None, clearing a destroyed reference."""
        if self.chatDialog is None:
            return None
        try:
            if self.chatDialog.IsShown():
                return self.chatDialog
        except Exception:
            pass
        self.chatDialog = None
        return None

    def _openChatDialog(self):
        prewarmConnection()
        self.chatDialog = GeminiChatDialog()
        self.chatDialog.Bind(wx.EVT_CLOSE, self.onDialogClose)
        return self.chatDialog

    @script(gesture="kb:NVDA+Alt+g", description=_("Opens LinguaPal chat dialog"))
    def script_customPrompt(self, gesture):
        try:
            dlg = self._liveChatDialog()
            if dlg is not None:
                dlg.Raise()
                return
            self._openChatDialog()
        except Exception as e:
            ui.message(_("Error: ") + str(e))

    @script(gesture="kb:NVDA+Alt+d", description=_("Describe focused window using AI vision"))
    def script_describeScreen(self, gesture):
        tones.beep(500, 80)
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
        except Exception:
            hwnd = None

        def worker():
            try:
                b64, mime = capture_foreground_window(hwnd=hwnd)
            except Exception as e:
                wx.CallAfter(ui.message, _("Screen capture failed: ") + str(e))
                return

            def openAndInject():
                try:
                    dlg = self._liveChatDialog()
                    if dlg is None:
                        dlg = self._openChatDialog()
                    else:
                        dlg.Raise()
                    dlg.injectScreenshot(b64, mime, _("screenshot.png"))
                except Exception as e:
                    ui.message(_("Error: ") + str(e))

            wx.CallAfter(openAndInject)

        threading.Thread(target=worker, daemon=True).start()

    @script(gesture="kb:NVDA+Alt+s", description=_("Opens LinguaPal settings panel"))
    def script_openSettingsDialog(self, gesture):
        try:
            wx.CallAfter(gui.mainFrame._popupSettingsDialog, NVDASettingsDialog, LinguaPalSettingsPanel)
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
        try:
            if self.toolsMenuItem and hasattr(gui.mainFrame, "sysTrayIcon") and gui.mainFrame.sysTrayIcon:
                gui.mainFrame.sysTrayIcon.toolsMenu.Remove(self.toolsMenuItem)
        except Exception:
            pass
