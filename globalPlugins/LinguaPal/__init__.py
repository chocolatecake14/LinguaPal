from functools import wraps
import threading
import ctypes
import wx
import gui
from gui import NVDASettingsDialog
import globalPluginHandler
import inputCore
import ui
import api
import tones
import config
import addonHandler
import textInfos
import treeInterceptorHandler
from scriptHandler import script

addonHandler.initTranslation()


def finally_(func, final):
    """Decorator to ensure final() is called after func(), even if it raises."""
    @wraps(func)
    def new(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        finally:
            final()
    return new


from .config_spec import (
    roleSECTION, resolveTranslateModel, prewarmConnection,
    cacheKey, cacheGet, cachePut, getQuickPrompt, PRESET_INDICES,
)
from .api_client import translateStream
from .streaming import ThinkFilter, SpeechStreamer
from .screen_capture import capture_foreground_window, capture_full_screen
from .updater import checkForUpdates
from .dialogs import GeminiChatDialog, showWhatsNew
from .settings_panel import LinguaPalSettingsPanel


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = _("LinguaPal")

    LAYER_COMMANDS = {
        "kb:c": "translateClipboard",
        "kb:t": "swapLanguages",
        "kb:g": "customPrompt",
        "kb:d": "describeScreen",
        "kb:w": "describeFullScreen",
        "kb:1": "quickPrompt1",
        "kb:numpad1": "quickPrompt1",
        "kb:2": "quickPrompt2",
        "kb:numpad2": "quickPrompt2",
        "kb:3": "quickPrompt3",
        "kb:numpad3": "quickPrompt3",
        "kb:4": "quickPrompt4",
        "kb:numpad4": "quickPrompt4",
        "kb:5": "quickPrompt5",
        "kb:numpad5": "quickPrompt5",
        "kb:6": "quickPrompt6",
        "kb:numpad6": "quickPrompt6",
        "kb:7": "quickPrompt7",
        "kb:numpad7": "quickPrompt7",
        "kb:8": "quickPrompt8",
        "kb:numpad8": "quickPrompt8",
        "kb:9": "quickPrompt9",
        "kb:numpad9": "quickPrompt9",
        "kb:0": "quickPrompt0",
        "kb:numpad0": "quickPrompt0",
        "kb:s": "openSettingsDialog",
        "kb:u": "checkForUpdates",
        "kb:n": "showWhatsNew",
        "kb:h": "layerHelp",
        "kb:escape": "layerCancel",
    }

    def __init__(self):
        super().__init__()
        NVDASettingsDialog.categoryClasses.append(LinguaPalSettingsPanel)
        self.chatDialog = None
        self.toolsMenuItem = None
        self._translateGen = 0
        self._inLayer = False
        self._layerTimer = None
        self._savedBindings = {}
        self._initMenu()
        if config.conf[roleSECTION].get("checkUpdatesAtStartup", True):
            wx.CallLater(5000, checkForUpdates, False)
        # Pay the TLS handshake while NVDA is still settling, not on first use.
        wx.CallLater(8000, prewarmConnection)

    def _initMenu(self):
        try:
            self.linguaPalMenu = wx.Menu()

            item_layer = self.linguaPalMenu.Append(wx.ID_ANY, _("&Command Layer\tNVDA+Shift+L"))
            self._bindMenuItem(item_layer, lambda evt: wx.CallAfter(self.script_commandLayer, None))

            self.linguaPalMenu.AppendSeparator()

            item_trans = self.linguaPalMenu.Append(wx.ID_ANY, _("&Translate Selected or Clipboard Text (C)"))
            self._bindMenuItem(item_trans, lambda evt: wx.CallAfter(self.script_translateClipboard, None))

            item_trans_sel = self.linguaPalMenu.Append(wx.ID_ANY, _("Translate &Selected Text"))
            self._bindMenuItem(item_trans_sel, lambda evt: wx.CallAfter(self.script_translateSelection, None))

            item_swap = self.linguaPalMenu.Append(wx.ID_ANY, _("S&wap Translation Language (T)"))
            self._bindMenuItem(item_swap, lambda evt: wx.CallAfter(self.script_swapLanguages, None))

            item_chat = self.linguaPalMenu.Append(wx.ID_ANY, _("&Chat with AI (G)"))
            self._bindMenuItem(item_chat, lambda evt: wx.CallAfter(self.script_customPrompt, None))

            item_desc = self.linguaPalMenu.Append(wx.ID_ANY, _("&Describe Focused Window (D)"))
            self._bindMenuItem(item_desc, lambda evt: wx.CallAfter(self.script_describeScreen, None))

            item_full = self.linguaPalMenu.Append(wx.ID_ANY, _("Describe &Full Screen (W)"))
            self._bindMenuItem(item_full, lambda evt: wx.CallAfter(self.script_describeFullScreen, None))

            self.linguaPalMenu.AppendSeparator()

            quickMenu = wx.Menu()
            for i in PRESET_INDICES:
                name, _ = getQuickPrompt(i)
                item = quickMenu.Append(wx.ID_ANY, f"Preset &{i}: {name} ({i})")
                handler = (lambda idx: (lambda evt: wx.CallAfter(self._executeQuickPrompt, idx)))(i)
                self._bindMenuItem(item, handler)
            self.linguaPalMenu.AppendSubMenu(quickMenu, _("&Quick Prompts (1-9, 0)"))

            self.linguaPalMenu.AppendSeparator()

            item_settings = self.linguaPalMenu.Append(wx.ID_ANY, _("&Settings... (S)"))
            self._bindMenuItem(item_settings, lambda evt: wx.CallAfter(self.script_openSettingsDialog, None))

            item_whatsnew = self.linguaPalMenu.Append(wx.ID_ANY, _("&What's New... (N)"))
            self._bindMenuItem(item_whatsnew, lambda evt: wx.CallAfter(showWhatsNew))

            item_updates = self.linguaPalMenu.Append(wx.ID_ANY, _("Check for &Updates... (U)"))
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

    def _enterLayer(self):
        self._inLayer = True
        self._savedBindings = {}
        for key, scriptName in self.LAYER_COMMANDS.items():
            normKey = inputCore.normalizeGestureIdentifier(key)
            if hasattr(self, "_gestureMap") and normKey in self._gestureMap:
                self._savedBindings[normKey] = self._gestureMap[normKey]
            try:
                self.bindGesture(key, scriptName)
            except Exception:
                pass
        self._layerTimer = wx.CallLater(5000, self._onLayerTimeout)
        tones.beep(523, 60)
        ui.message(_("LinguaPal"))

    def _exitLayer(self):
        if not self._inLayer:
            return
        self._inLayer = False
        if self._layerTimer:
            try:
                if self._layerTimer.IsRunning():
                    self._layerTimer.Stop()
            except Exception:
                pass
            self._layerTimer = None
        if hasattr(self, "_gestureMap"):
            for key in self.LAYER_COMMANDS:
                normKey = inputCore.normalizeGestureIdentifier(key)
                if normKey in self._savedBindings:
                    self._gestureMap[normKey] = self._savedBindings[normKey]
                else:
                    try:
                        self.removeGestureBinding(key)
                    except Exception:
                        pass
        self._savedBindings.clear()

    def _onLayerTimeout(self):
        if not self._inLayer:
            return
        self._exitLayer()
        tones.beep(262, 50)
        ui.message(_("LinguaPal layer timed out"))

    def getScript(self, gesture):
        if not self._inLayer:
            return super().getScript(gesture)
        script = super().getScript(gesture)
        if not script:
            script = self.script_layerError
        return finally_(script, self._exitLayer)

    @script(
        gesture="kb:NVDA+shift+l",
        description=_(
            "Activates the LinguaPal command layer. "
            "Then press a single key: C for selected or clipboard text, T for target language, "
            "G for chat, D for describe window, W for full screen, "
            "1 to 9 and 0 for quick prompts, "
            "S for settings, U for updates, N for what's new, H for help, or Escape to cancel."
        )
    )
    def script_commandLayer(self, gesture):
        if self._inLayer:
            self._exitLayer()
            tones.beep(350, 40)
            ui.message(_("LinguaPal layer closed"))
            return
        self._enterLayer()

    def script_layerCancel(self, gesture):
        tones.beep(350, 40)
        ui.message(_("LinguaPal layer closed"))

    def script_layerError(self, gesture):
        tones.beep(220, 80)
        ui.message(_("Unknown command. LinguaPal layer closed."))

    def script_layerHelp(self, gesture):
        ui.message(_(
            "LinguaPal layer commands: "
            "C: Translate selected or clipboard text. "
            "T: Swap target language. "
            "G: Chat with AI. "
            "D: Describe focused window. "
            "W: Describe full screen. "
            "1 to 9, 0: Quick prompts on selected or clipboard text. "
            "S: Settings. "
            "U: Check for updates. "
            "N: What's new. "
            "H: Help. "
            "Escape: Cancel."
        ))

    @script(description=_("Checks for LinguaPal updates"))
    def script_checkForUpdates(self, gesture):
        wx.CallAfter(checkForUpdates, True)

    @script(description=_("Shows LinguaPal What's New dialog"))
    def script_showWhatsNew(self, gesture):
        wx.CallAfter(showWhatsNew)

    @script(description=_("Swaps active translation target language with the secondary language"))
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

    @staticmethod
    def getSelectedText():
        candidates = []
        try:
            focus = api.getFocusObject()
            if focus:
                treeInterceptor = getattr(focus, "treeInterceptor", None)
                if (
                    isinstance(treeInterceptor, treeInterceptorHandler.DocumentTreeInterceptor)
                    and not treeInterceptor.passThrough
                ):
                    candidates.append(treeInterceptor)
                candidates.append(focus)
        except Exception:
            pass

        try:
            caret = api.getCaretObject()
            if caret and caret not in candidates:
                candidates.append(caret)
        except Exception:
            pass

        for obj in candidates:
            try:
                info = obj.makeTextInfo(textInfos.POSITION_SELECTION)
                if info and not info.isCollapsed:
                    text = info.text
                    if text and text.strip():
                        return text
            except (RuntimeError, NotImplementedError, AttributeError):
                continue
        return None

    def _translateText(self, text):
        provider = config.conf[roleSECTION]["model"]
        model = resolveTranslateModel(provider)
        cached = cacheGet(cacheKey(provider, model, text))
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
            args=(text, provider, model, self._translateGen),
            daemon=True
        ).start()

    @script(
        description=_(
            "Translates selected text if present, otherwise translates clipboard text, using the currently selected AI model"
        )
    )
    def script_translateClipboard(self, gesture):
        selected = self.getSelectedText()
        if selected:
            self._translateText(selected)
            return

        try:
            clip = api.getClipData()
        except Exception:
            clip = None

        if not clip or not clip.strip():
            tones.beep(300, 100)
            ui.message(_("No text selected and clipboard is empty"))
            return

        self._translateText(clip)

    @script(
        description=_(
            "Translates selected/highlighted text using the currently selected AI model"
        )
    )
    def script_translateSelection(self, gesture):
        selected = self.getSelectedText()
        if not selected:
            tones.beep(300, 100)
            ui.message(_("No text selected"))
            return

        self._translateText(selected)

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

    @script(description=_("Opens LinguaPal chat dialog"))
    def script_customPrompt(self, gesture):
        try:
            dlg = self._liveChatDialog()
            if dlg is not None:
                dlg.Raise()
                return
            self._openChatDialog()
        except Exception as e:
            ui.message(_("Error: ") + str(e))

    @script(description=_("Describe focused window using AI vision"))
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

    @script(description=_("Describe entire screen using AI vision"))
    def script_describeFullScreen(self, gesture):
        tones.beep(550, 80)

        def worker():
            try:
                b64, mime = capture_full_screen()
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
                    prompt = _(
                        "Please describe this full screen capture in detail for a blind user. "
                        "Identify the open applications, visible windows, taskbar/status info, "
                        "dialog boxes, and the general layout of elements across the screen. "
                        "If the image is completely black, blank, or obscured, state only that the screen is black or blank, and do not guess or hallucinate any UI elements."
                    )
                    dlg.injectScreenshot(b64, mime, _("fullscreen.png"), prompt=prompt)
                except Exception as e:
                    ui.message(_("Error: ") + str(e))

            wx.CallAfter(openAndInject)

        threading.Thread(target=worker, daemon=True).start()

    def _executeQuickPrompt(self, index):
        text = self.getSelectedText()
        if not text:
            try:
                text = api.getClipData()
            except Exception:
                text = None

        if not text or not text.strip():
            tones.beep(300, 100)
            ui.message(_("No text selected and clipboard is empty"))
            return

        name, prompt_instruction = getQuickPrompt(index)
        if not prompt_instruction or not prompt_instruction.strip():
            tones.beep(300, 100)
            ui.message(_("Quick Prompt {index} has no instruction set. Please configure it in LinguaPal settings.").format(index=index))
            return

        tones.beep(550, 60)
        ui.message(_("Quick Prompt {index}: {name}").format(index=index, name=name))

        full_message = f"{prompt_instruction.strip()}\n\n{text.strip()}"

        def openAndInject():
            try:
                dlg = self._liveChatDialog()
                if dlg is None:
                    dlg = self._openChatDialog()
                else:
                    dlg.Raise()
                dlg.injectMessage(full_message)
            except Exception as e:
                ui.message(_("Error: ") + str(e))

        wx.CallAfter(openAndInject)

    @script(description=_("Runs Quick Prompt Preset 1 (Summarize) on selected or clipboard text and opens chat"))
    def script_quickPrompt1(self, gesture):
        self._executeQuickPrompt(1)

    @script(description=_("Runs Quick Prompt Preset 2 (Fix Grammar) on selected or clipboard text and opens chat"))
    def script_quickPrompt2(self, gesture):
        self._executeQuickPrompt(2)

    @script(description=_("Runs Quick Prompt Preset 3 (Explain Simply) on selected or clipboard text and opens chat"))
    def script_quickPrompt3(self, gesture):
        self._executeQuickPrompt(3)

    @script(description=_("Runs Quick Prompt Preset 4 (Rewrite Professionally) on selected or clipboard text and opens chat"))
    def script_quickPrompt4(self, gesture):
        self._executeQuickPrompt(4)

    @script(description=_("Runs Quick Prompt Preset 5 (Explain Code/Error) on selected or clipboard text and opens chat"))
    def script_quickPrompt5(self, gesture):
        self._executeQuickPrompt(5)

    @script(description=_("Runs Quick Prompt Preset 6 on selected or clipboard text and opens chat"))
    def script_quickPrompt6(self, gesture):
        self._executeQuickPrompt(6)

    @script(description=_("Runs Quick Prompt Preset 7 on selected or clipboard text and opens chat"))
    def script_quickPrompt7(self, gesture):
        self._executeQuickPrompt(7)

    @script(description=_("Runs Quick Prompt Preset 8 on selected or clipboard text and opens chat"))
    def script_quickPrompt8(self, gesture):
        self._executeQuickPrompt(8)

    @script(description=_("Runs Quick Prompt Preset 9 on selected or clipboard text and opens chat"))
    def script_quickPrompt9(self, gesture):
        self._executeQuickPrompt(9)

    @script(description=_("Runs Quick Prompt Preset 0 on selected or clipboard text and opens chat"))
    def script_quickPrompt0(self, gesture):
        self._executeQuickPrompt(0)

    @script(description=_("Opens LinguaPal settings panel"))
    def script_openSettingsDialog(self, gesture):
        try:
            wx.CallAfter(gui.mainFrame._popupSettingsDialog, NVDASettingsDialog, LinguaPalSettingsPanel)
        except Exception as e:
            ui.message(_("Error opening settings: ") + str(e))

    def onDialogClose(self, event):
        self.chatDialog = None
        event.Skip()

    def terminate(self):
        self._exitLayer()
        try:
            NVDASettingsDialog.categoryClasses.remove(LinguaPalSettingsPanel)
        except Exception:
            pass
        try:
            if self.toolsMenuItem and hasattr(gui.mainFrame, "sysTrayIcon") and gui.mainFrame.sysTrayIcon:
                gui.mainFrame.sysTrayIcon.toolsMenu.Remove(self.toolsMenuItem)
        except Exception:
            pass
