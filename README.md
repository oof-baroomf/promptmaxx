### Description

This is a tool to automatically copy-paste and apply edits from a web-based LLM, without requiring any specific edit formats.

In  many cases, especially for students, web-based LLM client subscriptions have higher value than API credits.

I personally think Gemini 2.5 Pro, OpenAI o3, and Qwen 480b are incredible models, even better than Claude 4 Opus for many use cases, but they struggle a lot with agentic workflows as opposed to the chat interface.

I have been using ChatGPT online for a while for programming (although for this hackathon I tried out Cline because I got increased rate limits), but this is inconvenient, and going back and forth doing edits is inefficient. For that reason, I made Promptmaxx, which automates this process without requiring the model to edit in a specific format.

### To use:

Install uv if you haven't already.

Install `tree`:
- `brew install tree`
- `sudo apt-get install tree`

Then, just run `uv run path/to/your/promptmaxx.py` in any directory. You can also create an alias to make it easier to invoke promptmaxx in the future.
