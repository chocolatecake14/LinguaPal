import threading
import wx
import ui
import config
from gui import SettingsPanel, guiHelper
from .config_spec import (
    roleSECTION, _http, HTTP_TIMEOUT, groqBaseUrls, geminiBaseUrls,
    AUTO_MODEL, SAME_MODEL, cacheClear, prewarmConnection, noteEndpointSuccess,
)
from .updater import checkForUpdates
from .dialogs import showWhatsNew


class LinguaPalSettingsPanel(SettingsPanel):
    title = _("LinguaPal")

    def makeSettings(self, settingsSizer):
        sHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

        # --- AI Provider Selection ---
        self.modelLabel = sHelper.addItem(wx.StaticText(self, label=_("Active AI Provider:")))
        self.modelChoice = sHelper.addItem(wx.Choice(self, choices=["Groq", "Gemini"]))
        current_provider = config.conf[roleSECTION].get("model", "groq").lower()
        self.modelChoice.SetSelection(0 if current_provider == "groq" else 1)

        # --- Groq Settings ---
        self.groqSectionLabel = sHelper.addItem(wx.StaticText(self, label=_("--- Groq Settings ---")))
        self.groqKeyLabel = sHelper.addItem(wx.StaticText(self, label=_("Groq API Key:")))
        self.groqKeyField = sHelper.addItem(wx.TextCtrl(
            self, value=config.conf[roleSECTION].get("apiKey", ""), style=wx.TE_PASSWORD
        ))

        self.groqModelLabel = sHelper.addItem(wx.StaticText(self, label=_("Groq Chat Model:")))
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

        self.groqTranslateLabel = sHelper.addItem(wx.StaticText(
            self, label=_("Groq Model Used for Translation:")))
        self.groqTranslateChoice = sHelper.addItem(wx.Choice(self))
        self._fillTranslateChoice(self.groqTranslateChoice, groq_choices,
                                  config.conf[roleSECTION].get("translateGroqModel", AUTO_MODEL))

        # --- Gemini Settings ---
        self.geminiSectionLabel = sHelper.addItem(wx.StaticText(self, label=_("--- Gemini Settings ---")))
        self.geminiKeyLabel = sHelper.addItem(wx.StaticText(self, label=_("Gemini API Key:")))
        self.geminiKeyField = sHelper.addItem(wx.TextCtrl(
            self, value=config.conf[roleSECTION].get("geminiApiKey", ""), style=wx.TE_PASSWORD
        ))

        self.geminiModelLabel = sHelper.addItem(wx.StaticText(self, label=_("Gemini Chat Model:")))
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

        self.geminiTranslateLabel = sHelper.addItem(wx.StaticText(
            self, label=_("Gemini Model Used for Translation:")))
        self.geminiTranslateChoice = sHelper.addItem(wx.Choice(self))
        self._fillTranslateChoice(self.geminiTranslateChoice, gemini_choices,
                                  config.conf[roleSECTION].get("translateGeminiModel", AUTO_MODEL))

        self.useGeminiProxyCheckBox = sHelper.addItem(wx.CheckBox(
            self,
            label=_("If Gemini is blocked on this network, retry through the LinguaPal proxy "
                    "(Google is always tried first)")
        ))
        self.useGeminiProxyCheckBox.SetValue(config.conf[roleSECTION].get("useGeminiProxy", False))

        # --- Translation & Language Settings ---
        self.transSectionLabel = sHelper.addItem(wx.StaticText(self, label=_("--- Translation & Language Settings ---")))
        languages = [
            "Afrikaans (South Africa)",
            "Albanian (Albania)",
            "Amharic (Ethiopia)",
            "Arabic (Modern Standard)",
            "Armenian (Armenia)",
            "Azerbaijani (Azerbaijan)",
            "Bengali (Bangladesh)",
            "Bosnian (Bosnia and Herzegovina)",
            "Bulgarian (Bulgaria)",
            "Catalan (Spain)",
            "Chinese (Simplified)",
            "Chinese (Traditional)",
            "Croatian (Croatia)",
            "Czech (Czech Republic)",
            "Danish (Denmark)",
            "Dutch (Netherlands)",
            "English (United Kingdom)",
            "English (United States)",
            "Estonian (Estonia)",
            "Filipino (Philippines)",
            "Finnish (Finland)",
            "French (France)",
            "Georgian (Georgia)",
            "German (Germany)",
            "Greek (Greece)",
            "Gujarati (India)",
            "Hebrew (Israel)",
            "Hindi (India)",
            "Hungarian (Hungary)",
            "Icelandic (Iceland)",
            "Indonesian (Indonesia)",
            "Irish (Ireland)",
            "Italian (Italy)",
            "Japanese (Japan)",
            "Kannada (India)",
            "Kazakh (Kazakhstan)",
            "Korean (South Korea)",
            "Kurdish (Kurmanji)",
            "Kurdish (Sorani)",
            "Kyrgyz (Kyrgyzstan)",
            "Latvian (Latvia)",
            "Lithuanian (Lithuania)",
            "Macedonian (North Macedonia)",
            "Malay (Malaysia)",
            "Malayalam (India)",
            "Marathi (India)",
            "Mongolian (Mongolia)",
            "Nepali (Nepal)",
            "Norwegian (Norway)",
            "Pashto (Afghanistan)",
            "Persian (Iran)",
            "Polish (Poland)",
            "Portuguese (Brazil)",
            "Portuguese (Portugal)",
            "Punjabi (India)",
            "Punjabi (Pakistan)",
            "Romanian (Romania)",
            "Russian (Russia)",
            "Serbian (Cyrillic)",
            "Serbian (Latin)",
            "Sindhi (Pakistan)",
            "Sinhala (Sri Lanka)",
            "Slovak (Slovakia)",
            "Slovenian (Slovenia)",
            "Somali (Somalia)",
            "Spanish (Latin America)",
            "Spanish (Spain)",
            "Swahili (Kenya)",
            "Swedish (Sweden)",
            "Tamil (India)",
            "Telugu (India)",
            "Thai (Thailand)",
            "Turkish (Turkey)",
            "Ukrainian (Ukraine)",
            "Urdu (Pakistan)",
            "Uzbek (Uzbekistan)",
            "Vietnamese (Vietnam)",
            "Welsh (United Kingdom)"
        ]
        languages.sort()

        self.langLabel = sHelper.addItem(wx.StaticText(self, label=_("Primary target language:")))
        self.langChoice = sHelper.addItem(wx.Choice(self))
        self.langChoice.Set(languages)
        current_primary = config.conf[roleSECTION].get("translateTo", "English (United States)")
        if current_primary in languages:
            self.langChoice.SetStringSelection(current_primary)
        else:
            matched = False
            for lang in languages:
                if current_primary and current_primary.split()[0].lower() in lang.lower():
                    self.langChoice.SetStringSelection(lang)
                    matched = True
                    break
            if not matched:
                self.langChoice.SetSelection(0)

        self.secondaryLangLabel = sHelper.addItem(wx.StaticText(self, label=_("Secondary target language:")))
        self.secondaryLangChoice = sHelper.addItem(wx.Choice(self))
        self.secondaryLangChoice.Set(languages)
        current_secondary = config.conf[roleSECTION].get("secondaryTranslateTo", "Urdu (Pakistan)")
        if current_secondary in languages:
            self.secondaryLangChoice.SetStringSelection(current_secondary)
        else:
            matched = False
            for lang in languages:
                if current_secondary and current_secondary.split()[0].lower() in lang.lower():
                    self.secondaryLangChoice.SetStringSelection(lang)
                    matched = True
                    break
            if not matched:
                self.secondaryLangChoice.SetStringSelection("Urdu (Pakistan)" if "Urdu (Pakistan)" in languages else languages[0])

        self.copyClipCheckBox = sHelper.addItem(wx.CheckBox(
            self, label=_("&Copy translation to clipboard automatically")
        ))
        self.copyClipCheckBox.SetValue(config.conf[roleSECTION].get("copyTranslationToClipboard", True))

        # --- General & Tool Settings ---
        self.generalSectionLabel = sHelper.addItem(wx.StaticText(self, label=_("--- General Settings ---")))
        self.promptLabel = sHelper.addItem(wx.StaticText(self, label=_("System Prompt (Persona):")))
        self.promptField = sHelper.addItem(wx.TextCtrl(
            self,
            value=config.conf[roleSECTION].get("systemPrompt", "You are a helpful AI assistant."),
            style=wx.TE_MULTILINE
        ))

        self.fetchModelsButton = sHelper.addItem(wx.Button(self, label=_("&Fetch Available Models (Requires API Key)")))
        self.fetchModelsButton.Bind(wx.EVT_BUTTON, self.onFetchModels)

        self.whatsNewButton = sHelper.addItem(wx.Button(self, label=_("What's &new...")))
        self.whatsNewButton.Bind(wx.EVT_BUTTON, lambda evt: showWhatsNew())

        self.updateCheckBox = sHelper.addItem(wx.CheckBox(self, label=_("Check for updates at NVDA startup")))
        self.updateCheckBox.SetValue(config.conf[roleSECTION].get("checkUpdatesAtStartup", True))

        self.updateButton = sHelper.addItem(wx.Button(self, label=_("Check for &updates now")))
        self.updateButton.Bind(wx.EVT_BUTTON, lambda evt: checkForUpdates(showMessages=True))

    def _updateChoices(self, choice_ctrl, new_choices):
        current_selection = choice_ctrl.GetStringSelection()
        choice_ctrl.SetItems(new_choices)
        if current_selection and choice_ctrl.FindString(current_selection) != wx.NOT_FOUND:
            choice_ctrl.SetStringSelection(current_selection)
        elif new_choices:
            choice_ctrl.SetSelection(0)

    def onFetchModels(self, event):
        if getattr(self, "_is_fetching_models", False):
            ui.message(_("Already fetching models, please wait..."))
            return
        self._is_fetching_models = True
        try:
            self.fetchModelsButton.Disable()
        except Exception:
            pass

        def worker():
            groq_ok = False
            gemini_ok = False
            try:
                groqKey = self.groqKeyField.GetValue().strip()
                if groqKey:
                    try:
                        r = _http.get(
                            groqBaseUrls()[0] + "/openai/v1/models",
                            headers={"Authorization": f"Bearer {groqKey}"},
                            timeout=10,
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
                                wx.CallAfter(self._refreshTranslateChoice, self.groqTranslateChoice, groq_names)
                                groq_ok = True
                    except Exception:
                        pass

                geminiKey = self.geminiKeyField.GetValue().strip()
                if geminiKey:
                    try:
                        r = None
                        for base in geminiBaseUrls():
                            try:
                                r = _http.get(
                                    f"{base}/v1beta/models",
                                    headers={"x-goog-api-key": geminiKey},
                                    timeout=HTTP_TIMEOUT,
                                )
                            except Exception:
                                r = None
                                continue
                            if r.status_code == 200:
                                noteEndpointSuccess(base)
                                break
                        if r is not None and r.status_code == 200:
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
                                wx.CallAfter(self._refreshTranslateChoice, self.geminiTranslateChoice, gemini_names)
                                gemini_ok = True
                    except Exception:
                        pass

                if groq_ok or gemini_ok:
                    wx.CallAfter(ui.message, _("Models refreshed successfully."))
                elif not groqKey and not geminiKey:
                    wx.CallAfter(ui.message, _("Please enter a Groq or Gemini API key first."))
                else:
                    wx.CallAfter(ui.message, _("Could not fetch models. Check your API keys."))
            finally:
                def finish():
                    self._is_fetching_models = False
                    try:
                        self.fetchModelsButton.Enable()
                    except Exception:
                        pass
                wx.CallAfter(finish)

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _translateLabels():
        return [_("Auto (fastest available)"), _("Same as chat model")]

    def _fillTranslateChoice(self, ctrl, choices, saved):
        ctrl.Set(self._translateLabels() + list(choices))
        if saved == SAME_MODEL:
            ctrl.SetSelection(1)
        elif saved and saved not in (AUTO_MODEL, SAME_MODEL) and ctrl.FindString(saved) != wx.NOT_FOUND:
            ctrl.SetStringSelection(saved)
        else:
            ctrl.SetSelection(0)

    @staticmethod
    def _readTranslateChoice(ctrl):
        index = ctrl.GetSelection()
        if index <= 0:
            return AUTO_MODEL
        if index == 1:
            return SAME_MODEL
        return ctrl.GetStringSelection()

    def _refreshTranslateChoice(self, ctrl, newChoices):
        self._fillTranslateChoice(ctrl, newChoices, self._readTranslateChoice(ctrl))

    def onSave(self):
        config.conf[roleSECTION]["model"] = self.modelChoice.GetStringSelection().lower()
        config.conf[roleSECTION]["apiKey"] = self.groqKeyField.GetValue().strip()
        config.conf[roleSECTION]["geminiApiKey"] = self.geminiKeyField.GetValue().strip()
        config.conf[roleSECTION]["groqModel"] = self.groqModelChoice.GetStringSelection()
        config.conf[roleSECTION]["geminiModel"] = self.geminiModelChoice.GetStringSelection()
        config.conf[roleSECTION]["useGeminiProxy"] = self.useGeminiProxyCheckBox.GetValue()
        config.conf[roleSECTION]["translateGroqModel"] = self._readTranslateChoice(self.groqTranslateChoice)
        config.conf[roleSECTION]["translateGeminiModel"] = self._readTranslateChoice(self.geminiTranslateChoice)
        config.conf[roleSECTION]["systemPrompt"] = self.promptField.GetValue()
        config.conf[roleSECTION]["translateTo"] = self.langChoice.GetStringSelection()
        config.conf[roleSECTION]["secondaryTranslateTo"] = self.secondaryLangChoice.GetStringSelection()
        config.conf[roleSECTION]["copyTranslationToClipboard"] = self.copyClipCheckBox.GetValue()
        config.conf[roleSECTION]["checkUpdatesAtStartup"] = self.updateCheckBox.GetValue()
        cacheClear()
        prewarmConnection()

