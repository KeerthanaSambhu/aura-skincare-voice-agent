"""Phase 4: Aria's voice sessions.

The browser talks to Gemini Live directly with a short-lived token minted here.
Every order fact and policy decision still comes from this backend: the model
asks for a tool, the browser forwards the call to /api/voice/sessions/{id}/tool-calls,
and the result goes back to the model.
"""
