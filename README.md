# litellm-auth-proxy

A tiny local proxy that lets [OpenWhispr](https://github.com/OpenWhispr/openwhispr) talk to a
[LiteLLM](https://github.com/BerriAI/litellm) server that requires an API key (e.g. one serving `qwen3-asr`).

OpenWhispr's **Self-Hosted** transcription panel has no API key field. This proxy listens on
`127.0.0.1`, adds `Authorization: Bearer <key>` to every request, and forwards it to LiteLLM.

```
OpenWhispr ──► http://127.0.0.1:8787 (this proxy, adds key) ──► https://your-litellm-host
```

Single file, Python 3.8+, standard library only — nothing to install.

## 1. Configure

Edit the constant near the top of `litellm_auth_proxy.py` to point at your LiteLLM server
(base URL, **without** `/v1`):

```python
LITELLM_URL = "https://your-litellm-host:4000"
```

The API key is deliberately **not** stored in the file — pass it via the `LITELLM_API_KEY`
environment variable or `--key`.

## 2. Run

```bash
export LITELLM_API_KEY=sk-...
python3 litellm_auth_proxy.py
# Proxy listening on http://127.0.0.1:8787 -> https://your-litellm-host:4000
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--key` | `$LITELLM_API_KEY` | LiteLLM API key to inject (required) |
| `--upstream` | `LITELLM_URL` constant | Override the LiteLLM base URL for this run |
| `--model` | `$LITELLM_MODEL` | Force the `model` field of multipart uploads (e.g. `qwen3-asr`), for when the client sends a different model name |
| `--host` | `127.0.0.1` | Listen address (keep it on localhost — anyone who can reach the proxy can use your key) |
| `--port` | `8787` | Listen port |
| `-q`, `--quiet` | off | Don't log requests |

By default each request is logged with its upstream status, and error responses from LiteLLM
(first 500 bytes) are printed — handy for diagnosing a bad key (401) or wrong model name.

### Quick check

```bash
curl http://127.0.0.1:8787/v1/models
curl http://127.0.0.1:8787/v1/audio/transcriptions -F model=qwen3-asr -F file=@sample.wav
```

## 3. Configure OpenWhispr

1. Open OpenWhispr **Settings → Transcription** and choose the **Self-Hosted** option.
2. Set the server URL to the proxy:
   - `http://127.0.0.1:8787/v1`
   - (if OpenWhispr appends `/v1` itself and you see `/v1/v1/...` in the proxy log, use `http://127.0.0.1:8787` instead)
3. Set the model name to the name of the model **as configured in LiteLLM**, e.g. `qwen3-asr`.
   If OpenWhispr doesn't let you change it, or sends something like `whisper-1`, start the proxy
   with `--model qwen3-asr` and it will rewrite the model field for you.
4. Dictate something. The proxy terminal should show
   `-> POST https://your-litellm-host:4000/v1/audio/transcriptions = 200`.

## Run it in the background (Linux, systemd user service)

`~/.config/systemd/user/litellm-auth-proxy.service`:

```ini
[Unit]
Description=LiteLLM auth proxy for OpenWhispr

[Service]
Environment=LITELLM_API_KEY=sk-...
ExecStart=/usr/bin/python3 /path/to/litellm_auth_proxy.py --model qwen3-asr -q
Restart=on-failure

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now litellm-auth-proxy
```

## Notes / limitations

- Responses are buffered, not streamed — fine for transcription requests.
- A new upstream connection is opened per request.
- Any incoming `Authorization` header is replaced with the configured key.
