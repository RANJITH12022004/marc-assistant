# Marc laptop assistant — project brief

Marc is a local Windows voice assistant that turns speech into laptop actions. The only neural piece that was fine-tuned is an intent classifier named Laya. The rest is rules, speech tools, and operating-system commands.

The fruit-fly brain network is not in this project. It can sit beside Marc as a second decision system, but it does not replace the language model.

## What the app does

You say **hey jarvis** or **hey marc**. A small Dynamic Island UI wakes, listens, and acts on the laptop:

- open or close apps (Chrome, Spotify, terminal, camera, WhatsApp)
- type into the focused window
- press Enter
- play or pause media
- search Google or YouTube and pick “the first” result
- take a photo
- read Gmail, Calendar, and Drive after you sign in

After each command it listens again. Three silences, or **sleep** / **goodbye**, return it to idle. It is not always listening.

## How one turn works

```text
mic → wake word → speech-to-text
    → pending confirm?
    → follow-up ("play the first", "send it", more dictation)
    → compound / clause rules ("open Spotify and play music")
    → Laya (fine-tuned intent model) if rules miss
    → Gemini only if the utterance is still unclear, chat, or a plan rules missed
    → Windows tool (taskkill, media keys, paste/type, browser, Google APIs)
    → short reply, then listen again
```

Fast OS phrases never go through the big model. **Open Spotify**, **start music**, **close terminal**, and **type …** are caught by regex plans before Laya. Gemini Flash-Lite is only for leftover chat or unclear requests. Mail summaries stay local unless you turn Gemini mail on.

## What the project is made of

| Layer | What it is |
|---|---|
| Voice loop | Mic, openWakeWord (`hey jarvis`), Google speech-to-text, Whisper only if Google hears speech but returns empty |
| Session | Remembers YouTube pick lists, dictation mode, last app, pending confirm |
| Rules | Compound phrases and follow-ups. This is most of the live behavior |
| Laya | Fine-tuned intent model, loaded from `E:\laya-models\marc-intent` with `--laya` |
| Gemini | Optional planner for unclear or conversational turns |
| Tools | Allowlisted apps, hotkeys, camera, Playwright browser, Gmail / Calendar / Drive / Maps |
| UI | Top-center Dynamic Island |

Laya does not hear audio and does not click the mouse. It only answers: given this transcript, which intent is it, and does it need a plan, a confirm, or a refusal?

## What was actually fine-tuned

The base model is **Laya** on **ModernBERT-large** (`answerdotai/ModernBERT-large`): hidden size 1024, decision head of 2 layers, max context 1024 tokens. The Hub start was `convaiinnovations/laya`. It was not trained from scratch.

The task is typed decisions, trained with Laya’s RLCD / GRPO-style loop (not a normal “predict the next word” fine-tune). For each utterance the model answers:

- **intent** — one of 26 labels in the live taxonomy:
  - `open_app`
  - `close_app`
  - `focus_window`
  - `web_search`
  - `web_navigate`
  - `youtube_search`
  - `youtube_media`
  - `play_video`
  - `type_text`
  - `hotkey`
  - `file_find`
  - `file_open`
  - `system_status`
  - `volume_media`
  - `clipboard`
  - `settings`
  - `mail_search`
  - `mail_summarize`
  - `mail_compose`
  - `whatsapp_send`
  - `multi_step`
  - `clarify`
  - `chat`
  - `refuse`
- plus scores for **needs_planner**, **needs_confirm**, **is_multi_step**, and **destructive**

The training file that was uploaded and trained is **marc intents v3 RLCD**:

- about **22,500** training utterances and **2,500** holdout
- generated from the app list, hotkeys, and intent templates (Kaggle dataset `ranjithd0212/marc-intents-v3-rlcd`)
- checkpoint metadata says **4 of 4 epochs**; the agent config on the same folder records **7,313 updates**, about **2 hours**, `fine_tuned: true`
- that checkpoint was copied onto this laptop at `E:\laya-models\marc-intent` and is what `--laya` loads

A later **v4** set exists (4,320 train / 480 holdout, same intent list) with `"trained": false`. It was not the model that is running.

What was **not** fine-tuned:

- speech recognition
- wake word
- text-to-speech
- the regex router
- Gemini
- any fruit-fly network

A local 500-example eval file is **rules-only** (73%) and predates the fine-tune. The written target for the holdout after training was **intent accuracy at least 0.85**. That number is not stored as a finished eval in this repo.

## Where the fruit-fly brain fits

The September 2026 release (`flybrain` / MaleCNS v1.0) is a different kind of network: about **166,700** leaky integrate-and-fire neurons and tens of millions of synapses copied from the male fruit-fly connectome. Nothing inside that brain is trained. You stimulate some neurons, step the network, and read what the descending (“motor”) neurons do. The library even exposes a reservoir-style readout: collect spikes, then fit a small classifier on top.

Marc’s analog is **sensory input → decision → body command**:

| Marc | Fruit-fly network |
|---|---|
| Microphone and speech-to-text | Sensory drive (you choose which neurons to stimulate) |
| Laya intent head, or the regex router | The wiring that maps that drive toward an action |
| `open_app` / `close_app` / `volume_media` / `type_text` | Descending readout: a few discrete motor commands |
| Windows tools | The “body” that actually moves |

It does not fit as a drop-in replacement for Laya. The fly network has no tokens, no intents, and no laptop knowledge. A workable experiment is:

1. Keep Marc’s ears and hands (speech-to-text and the OS tools).
2. Encode a short transcript as a sensory pattern into `FlyBrain`.
3. Train only a small readout on the v3 intent labels (or on a tiny action set: play, pause, close, type).
4. Compare that readout with the already fine-tuned ModernBERT head on the same holdout.

That comparison is the research: a **trained language encoder that names an intent** versus an **untrained biological wiring diagram plus a linear readout**, both driving the same Windows actions.
