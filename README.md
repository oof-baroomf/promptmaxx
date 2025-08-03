### Description

This is a tool to automatically copy-paste and apply edits from a web-based LLM, without requiring any specific edit formats.

In  many cases, especially for students, web-based LLM client subscriptions have higher value than API credits.

I personally think Gemini 2.5 Pro, OpenAI o3, and Deepseek R1-0528 are incredible models, even better than Claude 4 Opus for some use cases, but they struggle a lot with agentic workflows as opposed to the chat interface.

I have been using ChatGPT online for a while for difficult programming issues when Cline fails or using Deep Research, but going back and forth doing edits is inefficient and inconvenient. For that reason, I made PromptMaxx, which automates this process without requiring the model to edit in a specific format, which has been shown to be better as per _Let Me Speak Freely_ by Tam et. al. Honestly, I found it surprising that such a tool doesn't exist yet, given that many others are probably in a similar situation as me.


### To use:

Install uv if you haven't already.

Install `tree`:
- `brew install tree`
- `sudo apt-get install tree`

Then, just run `uv run path/to/your/promptmaxx.py` in any directory. You can also create an alias to make it easier to invoke promptmaxx in the future.
