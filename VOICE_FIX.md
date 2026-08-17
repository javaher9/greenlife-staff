# Voice recorder fix

This build fixes staff daily-report recording across modern Chrome/Edge/Android/iOS/Safari where supported.

Important:
- Browser microphone APIs require a secure context. Use `https://staff.greenlifeclinics.com`, not `http://192.168.x.x:port`.
- The user must allow Microphone permission for the site.
- The recorder selects a supported MIME type dynamically instead of forcing `audio/webm`.
- Recorded audio is uploaded as FormData directly, avoiding reliance on programmatic assignment to `<input type=file>`.
- Manual audio upload remains available as fallback.
- Recording auto-stops after 2 minutes.
