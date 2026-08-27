import os
import tempfile
import threading
import time
import requests
import wx
import gui
import ui
import tones
from .config_spec import ADDON_VERSION, UPDATE_CHECK_URL, _parse_version


def downloadAndInstall(url):
    ui.message(_("Downloading update, please wait..."))
    tones.beep(440, 50)
    tones.beep(660, 50)

    def worker():
        try:
            filename = os.path.basename(url)
            if not filename.endswith(".nvda-addon"):
                filename = "LinguaPal-update.nvda-addon"
            path = os.path.join(tempfile.gettempdir(), filename)
            r = requests.get(url, stream=True, timeout=30)
            if r.status_code == 200:
                with open(path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                tones.beep(660, 50)
                tones.beep(880, 70)
                wx.CallAfter(ui.message, _("Download complete. Starting installer..."))
                wx.CallAfter(os.startfile, path)
            else:
                tones.beep(200, 200)
                wx.CallAfter(ui.message, _("Download failed: server returned status {code}.").format(code=r.status_code))
        except Exception as e:
            tones.beep(200, 200)
            wx.CallAfter(ui.message, _("Download error: ") + str(e))

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


_is_checking_updates = False
_update_lock = threading.Lock()


def checkForUpdates(showMessages=True):
    global _is_checking_updates
    with _update_lock:
        if _is_checking_updates:
            if showMessages:
                wx.CallAfter(ui.message, _("Already checking for updates, please wait..."))
            return
        _is_checking_updates = True

    def worker():
        global _is_checking_updates
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
                    if showMessages:
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
        finally:
            with _update_lock:
                _is_checking_updates = False

    threading.Thread(target=worker, daemon=True).start()
