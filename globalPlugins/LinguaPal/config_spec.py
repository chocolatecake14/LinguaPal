import collections
import config
import re
import threading
import time
import requests
import addonHandler
from urllib.parse import urlparse

addonHandler.initTranslation()

ADDON_VERSION = "1.3.0"
UPDATE_CHECK_URL = "https://raw.githubusercontent.com/chocolatecake14/LinguaPal/refs/heads/main/update.json"
roleSECTION = "LinguaPal"

GEMINI_DEFAULT_URL = "https://generativelanguage.googleapis.com"
GEMINI_PROXY_URL = "https://linguapal-gemini.exclusiveinfolab.workers.dev"
GROQ_DEFAULT_URL = "https://api.groq.com"

PRESET_INDICES = (1, 2, 3, 4, 5, 6, 7, 8, 9, 0)

QUICK_PROMPT_DEFAULTS = {
    1: {
        "name": _("Summarize"),
        "prompt": _("Summarize the following text clearly and concisely into key bullet points:"),
    },
    2: {
        "name": _("Fix Grammar"),
        "prompt": _("Proofread and correct grammar, spelling, and phrasing in the following text:"),
    },
    3: {
        "name": _("Explain Simply"),
        "prompt": _("Explain the following concept or text in simple and easy-to-understand terms:"),
    },
    4: {
        "name": _("Rewrite Professionally"),
        "prompt": _("Rewrite the following text in a clear, polished, and professional tone:"),
    },
    5: {
        "name": _("Explain Code or Error"),
        "prompt": _("Analyze and explain this code or error message, why it happens, and how to fix it:"),
    },
    6: {
        "name": _("Preset 6"),
        "prompt": "",
    },
    7: {
        "name": _("Preset 7"),
        "prompt": "",
    },
    8: {
        "name": _("Preset 8"),
        "prompt": "",
    },
    9: {
        "name": _("Preset 9"),
        "prompt": "",
    },
    0: {
        "name": _("Preset 0"),
        "prompt": "",
    },
}

confspec = {
    "translateTo": "string(default=English (United States))",
    "secondaryTranslateTo": "string(default=Urdu (Pakistan))",
    "apiKey": "string(default=)",
    "geminiApiKey": "string(default=)",
    "model": "string(default=groq)",
    "geminiModel": "string(default=gemini-3.1-flash-lite)",
    "useGeminiProxy": "boolean(default=False)",
    "groqModel": "string(default=openai/gpt-oss-20b)",
    "translateGroqModel": "string(default=auto)",
    "translateGeminiModel": "string(default=auto)",
    "systemPrompt": "string(default=You are a helpful AI assistant.)",
    "checkUpdatesAtStartup": "boolean(default=True)",
    "copyTranslationToClipboard": "boolean(default=True)",
    "geminiModelCache": "string(default=)",
    "groqModelCache": "string(default=)",
    "quickPrompt1Name": "string(default=Summarize)",
    "quickPrompt1": "string(default='Summarize the following text clearly and concisely into key bullet points:')",
    "quickPrompt2Name": "string(default='Fix Grammar')",
    "quickPrompt2": "string(default='Proofread and correct grammar, spelling, and phrasing in the following text:')",
    "quickPrompt3Name": "string(default='Explain Simply')",
    "quickPrompt3": "string(default='Explain the following concept or text in simple and easy-to-understand terms:')",
    "quickPrompt4Name": "string(default='Rewrite Professionally')",
    "quickPrompt4": "string(default='Rewrite the following text in a clear, polished, and professional tone:')",
    "quickPrompt5Name": "string(default='Explain Code or Error')",
    "quickPrompt5": "string(default='Analyze and explain this code or error message, why it happens, and how to fix it:')",
    "quickPrompt6Name": "string(default='Preset 6')",
    "quickPrompt6": "string(default='')",
    "quickPrompt7Name": "string(default='Preset 7')",
    "quickPrompt7": "string(default='')",
    "quickPrompt8Name": "string(default='Preset 8')",
    "quickPrompt8": "string(default='')",
    "quickPrompt9Name": "string(default='Preset 9')",
    "quickPrompt9": "string(default='')",
    "quickPrompt0Name": "string(default='Preset 0')",
    "quickPrompt0": "string(default='')",
}

config.conf.spec[roleSECTION] = confspec


def getQuickPrompt(index):
    default = QUICK_PROMPT_DEFAULTS.get(index, {"name": f"Preset {index}", "prompt": ""})
    cfg = config.conf[roleSECTION]
    name = cfg.get(f"quickPrompt{index}Name", default["name"])
    prompt = cfg.get(f"quickPrompt{index}", default["prompt"])
    return name, prompt


def setQuickPrompt(index, name, prompt):
    cfg = config.conf[roleSECTION]
    cfg[f"quickPrompt{index}Name"] = name
    cfg[f"quickPrompt{index}"] = prompt

# The list box keeps this many turns of scrollback...
MAX_CHAT_HISTORY = 50
# ...but re-uploading all of them on every reply just slows the next answer
# down, so only this many are actually sent.
MAX_CONTEXT_MESSAGES = 20

# Sentinels stored in the translation-model settings.
AUTO_MODEL = "auto"
SAME_MODEL = "same"

# Fast, non-reasoning Groq models worth translating with, best quality first.
# Auto only picks one the account actually returned from Fetch Models.
GROQ_FAST_TRANSLATE = (
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
)

# One pooled session for the whole add-on: keeps TLS connections alive between
# calls instead of paying DNS + TCP + TLS on every request.
_http = requests.Session()
_http.mount("https://", requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=8))

# (connect, read). A blocked host usually resets at once, but a network that
# silently drops packets instead will burn the whole connect timeout, so keep
# it short: the fallback is what matters then.
HTTP_TIMEOUT = (5, 60)

# Google is always tried first. When it turns out to be blocked, retrying it on
# every single request would cost a dead connection attempt each time, so the
# failure is remembered briefly and rechecked once it expires.
DIRECT_RECHECK_SECONDS = 600
_directBlockedUntil = 0.0

_prewarmLock = threading.Lock()
_lastPrewarm = 0.0

TRANS_CACHE_MAX = 32
TRANS_CACHE_MAX_CHARS = 8000
_transCache = collections.OrderedDict()

# Params some models reject. Once a model 400s on one, stop sending it.
_unsupportedParams = set()


def routingEnabled():
    return bool(config.conf[roleSECTION].get("useGeminiProxy", False))


def geminiBaseUrls():
    """Gemini endpoints to try, in order.

    Google direct always comes first. The LinguaPal proxy is a fallback that
    only exists when the user has ticked the routing option, and is only
    reached when the direct attempt fails.
    """
    if not routingEnabled():
        return [GEMINI_DEFAULT_URL]
    if time.time() < _directBlockedUntil:
        # Direct was blocked moments ago; do not pay for it on every request.
        return [GEMINI_PROXY_URL, GEMINI_DEFAULT_URL]
    return [GEMINI_DEFAULT_URL, GEMINI_PROXY_URL]


def groqBaseUrls():
    return [GROQ_DEFAULT_URL]


def noteEndpointFailure(url):
    global _directBlockedUntil
    if url == GEMINI_DEFAULT_URL:
        _directBlockedUntil = time.time() + DIRECT_RECHECK_SECONDS


def noteEndpointSuccess(url):
    global _directBlockedUntil
    if url == GEMINI_DEFAULT_URL:
        _directBlockedUntil = 0.0


def isNetworkError(exc):
    """True when the request never produced an HTTP response at all."""
    return isinstance(exc, (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
    ))


def isGeoBlocked(response):
    """Google answers a request from a banned country with 403 and this text."""
    if response.status_code not in (403, 451):
        return False
    try:
        message = response.json().get("error", {}).get("message", "")
    except Exception:
        message = response.text[:300]
    low = message.lower()
    return "location is not supported" in low or "not supported for the api" in low


def shouldFailover(response):
    """Worth trying the next endpoint instead of reporting this response."""
    return response.status_code >= 500 or isGeoBlocked(response)


def describeNetworkError(exc, url, provider, routingTried):
    """Turn a socket error into something a user can actually act on.

    "WinError 10054" tells an end user nothing. What they need to know is that
    the network refused the connection, and what to do about it.
    """
    host = urlparse(url).netloc if url else ""
    if provider == "gemini":
        if routingTried:
            return _("Gemini could not be reached, either directly or through the LinguaPal "
                     "proxy. It appears to be fully blocked on your network, so a VPN will "
                     "probably be needed.")
        return _("Gemini could not be reached. Your network may be blocking it. Open LinguaPal "
                 "settings and tick the option to route Gemini through the LinguaPal proxy, "
                 "then try again.")
    return _("Groq could not be reached at {host}. Your network may be blocking it, or your "
             "connection is down.").format(host=host or "api.groq.com")


def prewarmConnection():
    """Open the TLS connection early so the next request skips the handshake.

    A cold call pays DNS + TCP + TLS before a single byte of prompt is sent.
    Providers drop idle sockets after a minute or two, so this fires at the
    moments that reliably precede a translation.
    """
    global _lastPrewarm
    now = time.time()
    with _prewarmLock:
        if now - _lastPrewarm < 20:
            return
        _lastPrewarm = now

    def worker():
        try:
            # The status code is irrelevant; 401 still completes the handshake
            # and leaves a pooled keep-alive socket behind.
            if config.conf[roleSECTION].get("model", "groq") == "gemini":
                url = geminiBaseUrls()[0] + "/v1beta/models"
            else:
                url = groqBaseUrls()[0] + "/openai/v1/models"
            _http.head(url, timeout=(5, 5))
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()


def isReasoningModel(name):
    low = name.lower()
    if "qwen3" in low and "vl" not in low:
        return True
    return any(h in low for h in ("gpt-oss", "deepseek", "-r1", "magistral", "minimax", "qwq", "think"))


def resolveTranslateModel(provider):
    """The model to translate with, which need not be the chat model.

    Chatting with a reasoning model is reasonable; translating with one means
    waiting on a hidden chain of thought to render one sentence. Auto keeps the
    chat model unless it reasons, and only swaps in a model the account has
    actually reported via Fetch Models.
    """
    conf = config.conf[roleSECTION]
    if provider == "gemini":
        chosen = conf.get("translateGeminiModel", AUTO_MODEL)
        chatModel = conf.get("geminiModel", "gemini-3.1-flash-lite")
    else:
        chosen = conf.get("translateGroqModel", AUTO_MODEL)
        chatModel = conf.get("groqModel", "openai/gpt-oss-20b")
    if chosen and chosen not in (AUTO_MODEL, SAME_MODEL):
        return chosen
    if chosen == SAME_MODEL or provider == "gemini":
        # Gemini needs no auto swap: thinking is disabled per request instead.
        return chatModel
    if not isReasoningModel(chatModel):
        return chatModel
    available = [m for m in conf.get("groqModelCache", "").split(",") if m]
    for preferred in GROQ_FAST_TRANSLATE:
        if preferred in available:
            return preferred
    return chatModel


def cacheKey(provider, model, text):
    return (provider, model, config.conf[roleSECTION].get("translateTo", ""), text)


def cacheGet(key):
    result = _transCache.get(key)
    if result is not None:
        _transCache.move_to_end(key)
    return result


def cachePut(key, value):
    if len(key[3]) > TRANS_CACHE_MAX_CHARS:
        return
    _transCache[key] = value
    _transCache.move_to_end(key)
    while len(_transCache) > TRANS_CACHE_MAX:
        _transCache.popitem(last=False)


def cacheClear():
    _transCache.clear()


def _parse_version(v):
    try:
        parts = re.findall(r"\d+", str(v))
        return tuple(int(x) for x in parts) if parts else (0,)
    except (ValueError, AttributeError):
        return (0,)
