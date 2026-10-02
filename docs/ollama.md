# Running on open models with Ollama

Claude Code can run on open models served by [Ollama](https://ollama.com), and the plugin works there too. Install the plugin as usual, install Ollama, then:

```bash
ollama launch claude                        # pick a model interactively
ollama launch claude --model qwen3.5        # or name one
```

- **Local models keep the conversation on your machine.** Models with a `:cloud` suffix run on Ollama's servers instead.
- **Pick a model with tool calling and a large context.** Ollama recommends 64k tokens or more for local models. The skills run scripts and read their JSON, so a model that cannot call tools cannot use them.
- **The scripted figures do not depend on the model.** The bundled scripts compute them; how well they are explained, and anything read off a statement or receipt, still does.
- **Pages fall back to chat.** When a session cannot publish interactive pages, skills reply with the same results as tables in chat.

See [Ollama's Claude Code guide](https://docs.ollama.com/integrations/claude-code) for setup and model choices.
