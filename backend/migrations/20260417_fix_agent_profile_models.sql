-- Fix agent profiles that had model='gemini-3-flash-preview' (invalid for OpenAI SDK)
UPDATE agent_profiles SET model = 'gpt-4.1-mini' WHERE model = 'gemini-3-flash-preview';
