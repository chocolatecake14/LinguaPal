import base64
import io
import os
import ctypes
import ctypes.wintypes
import tempfile
import wx
import addonHandler

addonHandler.initTranslation()


def is_screen_curtain_active():
    """Check if NVDA Screen Curtain is currently active."""
    try:
        import vision
        from visionEnhancementProviders.screenCurtain import ScreenCurtainProvider
        if hasattr(vision, "handler") and vision.handler:
            for p in vision.handler.getActiveProviderInstances():
                if isinstance(p, ScreenCurtainProvider):
                    return True
    except Exception:
        pass
    return False


def is_image_black(image, max_brightness_threshold=5):
    """Return True if image is completely black or below brightness threshold."""
    try:
        raw = image.GetData()
        if not raw:
            return True
        return max(raw) <= max_brightness_threshold
    except Exception:
        return False


def _bitmap_to_b64(bitmap, w, h, max_side=1400):
    """Convert a wx.Bitmap to base64-encoded PNG data."""
    image = bitmap.ConvertToImage()
    if is_image_black(image):
        raise Exception(_(
            "The captured screen is completely black. "
            "If NVDA Screen Curtain is enabled or the display is off, please disable it to capture content."
        ))
    longest = max(w, h)
    if longest > max_side:
        # A full 4K grab is several megabytes; base64 of that is a slow upload
        # and buys no extra accuracy when describing a window.
        scale = max_side / float(longest)
        image = image.Scale(max(1, int(w * scale)), max(1, int(h * scale)), wx.IMAGE_QUALITY_HIGH)

    buf = io.BytesIO()
    if image.SaveFile(buf, wx.BITMAP_TYPE_PNG):
        data = buf.getvalue()
    else:
        # mkstemp rather than the deprecated, racy mktemp.
        fd, tmp = tempfile.mkstemp(suffix='.png')
        os.close(fd)
        try:
            image.SaveFile(tmp, wx.BITMAP_TYPE_PNG)
            with open(tmp, 'rb') as f:
                data = f.read()
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass
    return base64.b64encode(data).decode('utf-8'), 'image/png'


def capture_foreground_window(hwnd=None, max_side=1400):
    """Return (base64 png, mime) of the foreground window, downscaled."""
    if is_screen_curtain_active():
        raise Exception(_(
            "Screen capture failed because NVDA Screen Curtain is active. "
            "Please disable Screen Curtain to capture visible screen content."
        ))

    if hwnd is None:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
    rect = ctypes.wintypes.RECT()
    ok = ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    if ok and rect.right > rect.left and rect.bottom > rect.top:
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
    return _bitmap_to_b64(bitmap, w, h, max_side=max_side)


def capture_full_screen(max_side=1400):
    """Return (base64 png, mime) of the full virtual desktop / screen, downscaled."""
    if is_screen_curtain_active():
        raise Exception(_(
            "Screen capture failed because NVDA Screen Curtain is active. "
            "Please disable Screen Curtain to capture visible screen content."
        ))

    user32 = ctypes.windll.user32
    # SM_XVIRTUALSCREEN = 76, SM_YVIRTUALSCREEN = 77
    # SM_CXVIRTUALSCREEN = 78, SM_CYVIRTUALSCREEN = 79
    x = user32.GetSystemMetrics(76)
    y = user32.GetSystemMetrics(77)
    w = user32.GetSystemMetrics(78)
    h = user32.GetSystemMetrics(79)
    if w <= 0 or h <= 0:
        x, y = 0, 0
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
    if w <= 0 or h <= 0:
        w = wx.SystemSettings.GetMetric(wx.SYS_SCREEN_X)
        h = wx.SystemSettings.GetMetric(wx.SYS_SCREEN_Y)

    screen_dc = wx.ScreenDC()
    bitmap = wx.Bitmap(w, h)
    mem_dc = wx.MemoryDC()
    mem_dc.SelectObject(bitmap)
    mem_dc.Blit(0, 0, w, h, screen_dc, x, y)
    mem_dc.SelectObject(wx.NullBitmap)
    return _bitmap_to_b64(bitmap, w, h, max_side=max_side)
