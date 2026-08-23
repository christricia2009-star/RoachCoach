# API Keys + Live Radar

Open **More → API & Radar Settings** in the iOS app.

Enter the deployed backend URL and any provider credentials you have. Credentials are stored in the iOS Keychain. They are not embedded in the source or app bundle.

Supported fields:
- OpenRouter
- Grok / xAI
- Anthropic
- Instagram
- X bearer token
- Partnership API
- Telecom API
- Uber partner ID/secret
- DoorDash partner API
- AWS access/secret
- LLM strategy/provider/model

Tap **SCAN NOW** on the Radar screen. The app sends the configured credentials to the backend for that explicit scan and requests a location-aware live radar pass.

The first live pass gathers nearby California traffic cameras and active backend radar contacts. The backend is structured so additional collectors can be enabled without changing the iOS settings screen.
