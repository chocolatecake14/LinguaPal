# LinguaPal

An NVDA add-on for seamless language translation, image description, and conversation with AI using Google Gemini and Groq.

## Important Note
This add-on was previously named **AskGemini** and has been completely overhauled into **LinguaPal**. If you have an older version of AskGemini installed, please remove it before installing LinguaPal to avoid conflicts.

## Features
- **Real-time Clipboard Translation:** Translate copied text instantly using your selected AI model.
- **Fast Dual-Target Language Swap:** Easily toggle between your Primary and Secondary target languages with a single key (`T`).
- **Screen & Window Description (AI Vision):** Describe your focused window (`D`) or the entire multi-monitor screen (`W`) with AI vision to identify visible UI controls, text, errors, and contents.
- **Quick Prompts (Keys 1-9, 0):** Run customizable AI actions on clipboard text (Summarize, Fix Grammar, Explain Simply, Rewrite Professionally, Explain Code/Error, plus 5 custom slots) and seamlessly continue chatting in the chat dialog.
- **AI Chat Dialog with Image Attachments:** Chat interactively with Gemini or Groq models, attach image files from your computer or paste from the clipboard, and ask follow-up questions.
- **NVDA Tools Submenu:** Access all LinguaPal actions, settings, update checks, and changelog from *NVDA Menu > Tools > LinguaPal*.
- **Integrated "What's New":** View detailed changelogs directly from the NVDA Tools menu or from the settings panel.
- **Dynamic Model Fetching:** Automatically query and refresh the latest available models for both Groq and Gemini with a single click.

## Hotkeys & Command Layer
To keep your keyboard free from shortcut conflicts with Windows and other add-ons, LinguaPal uses a **Command Layer** by default. Press the layer activation shortcut, release it, and then press a single key:

**NVDA + Shift + L**: Enters the Command Layer. While active, press:
- **C**: Translate clipboard text to the active target language.
- **T**: Swap active translation target language (Primary &harr; Secondary).
- **G**: Open the LinguaPal AI chat window.
- **D**: Describe the focused window using AI vision.
- **W**: Describe the entire full screen (all monitors) using AI vision.
- **1**: Quick Prompt 1 (Summarize clipboard text).
- **2**: Quick Prompt 2 (Fix grammar & phrasing).
- **3**: Quick Prompt 3 (Explain simply).
- **4**: Quick Prompt 4 (Rewrite professionally).
- **5**: Quick Prompt 5 (Explain code / error message).
- **6 to 9, 0**: Customizable Quick Prompts 6, 7, 8, 9, and 0.
- **S**: Open LinguaPal settings panel.
- **U**: Check for updates.
- **N**: View What's New.
- **H**: Hear available layer commands.
- **Escape**: Close the layer immediately.

*Note: The command layer automatically times out after 5 seconds of inactivity. If you prefer direct single-stroke hotkeys (such as `NVDA+Alt+C`), you can assign your preferred shortcuts anytime in the NVDA Input Gestures dialog (`NVDA Menu > Preferences > Input Gestures > LinguaPal`).*

## Setup Instructions
To get started, configure your API keys and language preferences:
1. Open NVDA Settings (`NVDA+Shift+L` then `S`, or via `NVDA Menu > Preferences > Settings > LinguaPal`).
2. Choose your preferred AI Provider (**Groq** or **Gemini**).
3. Paste your corresponding API key.
4. Select your **Primary target language** and **Secondary target language**.
5. (Optional) Customize the System Prompt (AI Persona) or fetch available models.
6. Click **OK** to save.

---

## How to Obtain API Keys

### 1. Google Gemini API Key
1. Visit [Google AI Studio](https://aistudio.google.com/) and sign in with your Google account.
2. Navigate to [Get API Key](https://aistudio.google.com/app/apikey).
3. Click **Create API key**.
4. Copy the generated key and paste it into LinguaPal settings under Gemini API Key.

### 2. Groq API Key
1. Visit the [Groq Console](https://console.groq.com/keys).
2. Sign in using a Google or GitHub account.
3. Click the **Create API Key** button.
4. Copy the new key and paste it into LinguaPal settings under Groq API Key.

---

## Requirements
- NVDA 2023.2 or later.
- Active internet connection.

## Contact & Contributing
Contributions are welcome! If you find a bug or have a suggestion for a new feature, feel free to open an issue or submit a pull request.

If you wish to reach out, contact on Telegram: [@MalikAli01](https://t.me/MalikAli01)

## License
Distributed under the GNU General Public License v2.0.
