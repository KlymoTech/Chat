# Telegram student enrollment by phone

1. Connect the agent to its Telegram bot in Integrations and finish webhook setup.
2. In Education > Students, enter the student's **Telegram phone number**, including country code (for example `+919876543210`).
3. Create the student's active enrollment for the correct course, batch, and Education agent. Configure course knowledge and publish the agent when ready.
4. The student opens the bot in a private chat and sends `/start`. The bot asks them to tap **Share my phone number**.
5. Telegram sends the student's own contact. The server matches the enrolled phone number and links the account automatically. The student can then send course questions normally.

Typing a phone number as text, sharing someone else's contact, forwarding a contact, or sharing in a group does not verify an account. A verified account still needs an active enrollment before it can access course knowledge.

Changing or clearing the registered phone number removes verification; the student must share their contact again. Explicitly revoked accounts remain blocked until staff resolves them. Phone numbers are unique within each workspace.
