# LinguaPal

An NVDA add-on for seamless language translation, image description, and conversation with AI using Google Gemini and Groq.

## Important Note
This add-on was previously named **AskGemini** and has been completely overhauled into **LinguaPal**. If you have an older version of AskGemini installed, please remove it before installing LinguaPal to avoid conflicts.

## Features
- **Real-time Clipboard Translation:** Translate copied text instantly using your selected AI model.
- **Fast Dual-Target Language Swap:** Easily toggle between your Primary and Secondary target languages with a single hotkey.
- **Screen & Window Description (AI Vision):** Take a snapshot of your focused window and have AI describe visible UI controls, text, errors, and contents in detail.
- **AI Chat Dialog with Image Attachments:** Chat interactively with Gemini or Groq models, attach image files from your computer, and ask follow-up questions.
- **Dynamic Model Fetching:** Automatically query and refresh the latest available models for both Groq and Gemini with a single click.

## Default Hotkeys
- **NVDA + Alt + C:** Translate clipboard text to the active target language.
- **NVDA + Alt + T:** Swap active translation target language (Primary &harr; Secondary).
- **NVDA + Alt + G:** Open the LinguaPal AI chat window.
- **NVDA + Alt + D:** Describe the currently focused window using AI vision.
- **NVDA + Alt + S:** Open LinguaPal settings panel directly.

*Note: All shortcuts can be customized in the NVDA Input Gestures dialog (`NVDA Menu > Preferences > Input Gestures > LinguaPal`).*

## Setup Instructions
To get started, configure your API keys and language preferences:
1. Open NVDA Settings (`NVDA + Alt + S` or via `NVDA Menu > Preferences > Settings > LinguaPal`).
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
