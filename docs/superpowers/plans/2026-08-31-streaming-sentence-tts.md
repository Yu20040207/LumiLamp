# 方舟流式短句 TTS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 LumiLamp 在方舟生成第一条自然短句后立即开始 TTS/播放，同时继续接收后续文本，从约 14–15 秒的完整串行等待改为可测量的首次出声优化路径。

**Architecture:** 保留现有 ASR、KWS、ALSA 和半双工状态机。新增纯短句切分器、方舟 SSE 流客户端以及一个有界三句队列的生产者/消费者；`VoiceLoop` 只协调状态、时钟、取消和历史原子写入，供应商协议和 WAV 播放留在各自适配器。

**Tech Stack:** Python 3.13、标准库 `urllib`/`json`/`asyncio`、现有 `unittest`、方舟 ChatCompletions SSE、豆包 TTS 2.0 HTTP、ALSA `aplay`。

**Spec:** `docs/superpowers/specs/2026-08-31-streaming-sentence-tts-design.md`

## Global Constraints

- 只修改树莓派语音软件；不得访问 GPIO、ESP32-S3、串口、舵机或固件。
- 不实现播报中打断、全双工、回声消除或 TTS WebSocket 音频流。
- 方舟请求使用现有 `ARK_API_KEY`、`ARK_MODEL_ID` 和 `https://ark.cn-beijing.volces.com/api/v3/chat/completions`；新请求必须含 `stream: true`。
- SSE 正常结束仅接受 `data: [DONE]`；日志不得包含文本、凭证、请求头、SSE 原始正文或音频。
- 自然句界为 `。！？；`；无句界达到 30 字时优先在 `，、` 切分，队列最大 3 句。
- 严格半双工：方舟流、TTS 合成或扬声器播放期间不得启动普通 ASR 或 KWS。
- 成功时才追加完整用户/助手回合到 `ConversationHistory`；异常、取消和部分回答均不追加。
- 临时 WAV 必须唯一命名并在成功、失败、取消后删除。
- 所有自动测试不得访问网络、麦克风或扬声器；真实云端和 USB 测试必须另行得到用户确认。
- 用户禁止 commit、push、reset、clean 和删除现有用户文件；每项任务运行验证但不提交。

---

## File Structure

- Create: `src/lumilamp/voice/sentence_segmenter.py` — 纯文本增量缓冲与自然短句切分。
- Create: `src/lumilamp/voice/streaming_reply.py` — 方舟短句生产者、三句有界队列、顺序 TTS 消费者、取消与结果对象。
- Modify: `src/lumilamp/voice/ark.py` — 构造 `stream: true` 请求、严格 SSE 帧解析、同步迭代器与脱敏错误映射。
- Modify: `src/lumilamp/voice/voice_loop.py` — 使用流式回答适配器、原子历史写入、首句/首声/完成日志和状态转换。
- Modify: `src/lumilamp/voice/voice_cli.py` — 实现从阻塞 Ark 流到异步适配器的边界、短句 TTS 播放适配器和运行时装配。
- Modify: `src/lumilamp/voice/wake_cache.py`、`scripts/prepare_wake_replies.py` — 支持显式准备一个固定网络错误提示 WAV，不在运行时下载。
- Test: `tests/test_sentence_segmenter.py`、`tests/test_streaming_reply.py`、`tests/test_voice_ark.py`、`tests/test_voice_loop.py`、`tests/test_voice_cli.py`、`tests/test_wake_cache.py`。

### Task 1: 纯短句切分器

**Files:**

- Create: `src/lumilamp/voice/sentence_segmenter.py`
- Test: `tests/test_sentence_segmenter.py`

**Interfaces:**

- Produces `SentenceSegmenter(max_chars: int = 30)` with `push(delta: str) -> list[str]` and `finish() -> list[str]`.
- `push` only accepts `str`; blank deltas return `[]`; returned strings are nonblank, preserve exact source order and include their boundary punctuation.

- [ ] **Step 1: Write failing segmentation tests**

```python
def test_emits_complete_chinese_sentence_across_frames() -> None:
    segmenter = SentenceSegmenter()
    assert segmenter.push("我是露") == []
    assert segmenter.push("米。很高兴见到你！") == ["我是露米。", "很高兴见到你！"]

def test_splits_long_unpunctuated_text_at_latest_comma_before_limit() -> None:
    segmenter = SentenceSegmenter(max_chars=8)
    assert segmenter.push("前四个字，后面继续说话") == ["前四个字，"]
```

- [ ] **Step 2: Run the focused test to verify RED**

Run: `.venv/bin/python -m unittest tests.test_sentence_segmenter`

Expected: import failure because `sentence_segmenter` does not exist.

- [ ] **Step 3: Implement the smallest pure buffer**

```python
TERMINATORS = frozenset("。！？；")
FALLBACK_BOUNDARIES = frozenset("，、")

class SentenceSegmenter:
    def push(self, delta: str) -> list[str]: ...
    def finish(self) -> list[str]: ...
```

Use a private string buffer. Repeatedly emit the earliest terminator; if no terminator exists and buffer length reaches `max_chars`, emit through the last fallback boundary at or before the limit, otherwise emit exactly `max_chars` characters. `finish()` emits one trimmed nonblank residual once and then clears it.

- [ ] **Step 4: Add boundary tests and verify GREEN**

Add explicit tests for blank deltas, multi-sentence one-frame input, hard 30-character split, trailing residual at `finish()`, double `finish()`, and non-string rejection. Run:

`.venv/bin/python -m unittest tests.test_sentence_segmenter`

Expected: all pass with no network or audio subprocess.

- [ ] **Step 5: Run static check without commit**

Run: `.venv/bin/python -m compileall -q src tests && git diff --check -- src/lumilamp/voice/sentence_segmenter.py tests/test_sentence_segmenter.py`

Expected: exit 0. Do not commit.

### Task 2: 方舟 SSE 协议与流式文本迭代器

**Files:**

- Modify: `src/lumilamp/voice/ark.py`
- Test: `tests/test_voice_ark.py`

**Interfaces:**

- Consumes `VoiceConfig`, `ConversationHistory.messages()`, `SYSTEM_PROMPT`, `ARK_ENDPOINT`.
- Produces `build_stream_chat_body(model_id, messages) -> dict[str, object]`, `parse_sse_data(data: str) -> str | None`, and `stream_ark(config, history, user_text) -> Iterator[str]`.
- `stream_ark` yields nonempty `choices[0].delta.content` fragments in order; it never mutates `history`.

- [ ] **Step 1: Write failing protocol tests**

```python
def test_build_stream_body_preserves_existing_chat_shape() -> None:
    body = build_stream_chat_body("model", [{"role": "user", "content": "你好"}])
    assert body["stream"] is True
    assert body["messages"][-1] == {"role": "user", "content": "你好"}

def test_sse_parser_ignores_usage_and_accepts_done() -> None:
    assert parse_sse_data('{"choices":[{"delta":{"content":"你好"}}]}') == "你好"
    assert parse_sse_data('{"choices":[]}') is None
    assert parse_sse_data("[DONE]") is None
```

- [ ] **Step 2: Run focused tests to verify RED**

Run: `.venv/bin/python -m unittest tests.test_voice_ark.ArkClientTests`

Expected: import or attribute failure for the new functions.

- [ ] **Step 3: Implement strict request and SSE parsing**

Make `build_stream_chat_body()` call the existing normalized body builder, then add exactly `"stream": True`. Parse only `data:` payloads; accept `[DONE]`; ignore empty choice arrays; reject malformed JSON, missing/non-list choices, malformed delta objects and non-string content with stable redacted `ValueError`s. Preserve existing non-streaming functions unchanged.

- [ ] **Step 4: Implement `stream_ark` and history safety tests**

Use `urlopen(..., timeout=30)` with the existing Bearer header. Iterate decoded response lines, process only `data:` lines, yield valid fragments, require `[DONE]`, and close the response/generator on exit. Add fakes proving request body contains `stream: true`, fragments preserve order, HTTP errors retain only status/request ID, malformed stream raises, missing `[DONE]` raises, and history remains unchanged after both success and error.

- [ ] **Step 5: Verify GREEN and static checks without commit**

Run: `.venv/bin/python -m unittest tests.test_voice_ark && .venv/bin/python -m compileall -q src tests && git diff --check -- src/lumilamp/voice/ark.py tests/test_voice_ark.py`

Expected: all pass; no network is contacted because `urlopen` is faked.

### Task 3: 有界短句生产/消费管线

**Files:**

- Create: `src/lumilamp/voice/streaming_reply.py`
- Test: `tests/test_streaming_reply.py`

**Interfaces:**

- Consumes `AsyncIterator[str]` of Ark text deltas, `SentenceSegmenter`, and `Callable[[str], Awaitable[None]]` for one short-sentence playback.
- Produces `StreamingReplyResult(full_text: str, sentences_played: int, first_sentence_at: float | None, first_audio_at: float | None, completed_at: float)` and `stream_and_play(deltas, speak_sentence, clock, max_queue_size=3) -> Awaitable[StreamingReplyResult]`.
- `speak_sentence` is invoked one at a time and in exact original sentence order.

- [ ] **Step 1: Write failing success/concurrency tests**

```python
async def test_consumer_plays_first_completed_sentence_while_producer_continues() -> None:
    # producer yields “第一句。” then blocks until playback records its start
    # expected events prove producer resumes before first playback finishes
    result = await stream_and_play(deltas(), speak, clock)
    self.assertEqual(spoken, ["第一句。", "第二句。"])
    self.assertEqual(result.full_text, "第一句。第二句。")
```

Add an `asyncio.Queue(maxsize=3)` pressure test where the fourth enqueue waits until the consumer removes an item; assert peak pending count never exceeds three.

- [ ] **Step 2: Run focused tests to verify RED**

Run: `.venv/bin/python -m unittest tests.test_streaming_reply`

Expected: import failure because the pipeline module does not exist.

- [ ] **Step 3: Implement producer, consumer, sentinel and result**

Use one private sentinel object. The producer feeds deltas through `SentenceSegmenter`, appends every text fragment to `full_text_parts`, and `await queue.put(sentence)` for each sentence. In `finally`, it enqueues the sentinel unless cancelled. The consumer reads until the sentinel, records `first_audio_at` immediately before its first `await speak_sentence(sentence)`, then plays each following sentence serially. `asyncio.TaskGroup` or explicit task cancellation must propagate a producer or consumer failure and await the sibling task.

- [ ] **Step 4: Add error/cancellation tests and verify GREEN**

Add tests that: a producer exception after the first sentence preserves exactly that played sentence and raises a typed `StreamingReplyError(stage="ark", sentences_played=1)`; a playback exception cancels the producer and prevents later playback; cancellation leaves no pending tasks; an empty stream raises `StreamingReplyError(stage="ark")`; exception text is never embedded in the result/log fields. Run:

`.venv/bin/python -m unittest tests.test_streaming_reply`

- [ ] **Step 5: Run static check without commit**

Run: `.venv/bin/python -m compileall -q src tests && git diff --check -- src/lumilamp/voice/streaming_reply.py tests/test_streaming_reply.py`

Expected: exit 0.

### Task 4: 流式 Ark 与单句 TTS 运行时适配器

**Files:**

- Modify: `src/lumilamp/voice/voice_cli.py`
- Test: `tests/test_voice_cli.py`

**Interfaces:**

- Consumes `stream_ark`, `StreamingReplyResult`, `stream_and_play`, `VoiceConfig`, `AlsaDevice`, `ConversationHistory`.
- Produces `ArkStreamAdapter.stream(text: str) -> AsyncIterator[str]` and `SentenceTtsPlaybackAdapter.__call__(sentence: str) -> Awaitable[None]`.
- Both adapters map expected provider/device failures to `VoiceAdapterError` without leaking details.

- [ ] **Step 1: Write failing adapter tests**

```python
async def test_ark_stream_adapter_yields_fragments_without_appending_history() -> None:
    adapter = ArkStreamAdapter(config, history, stream_ark=fake_stream)
    assert [part async for part in adapter.stream("问题")] == ["第一句", "。"]
    assert history.messages() == []

async def test_sentence_tts_adapter_deletes_unique_wav_after_each_sentence() -> None:
    await adapter("第一句。")
    assert played == ["第一句。"]
    assert not temporary_path.exists()
```

- [ ] **Step 2: Run focused tests to verify RED**

Run: `.venv/bin/python -m unittest tests.test_voice_cli.ArkStreamAdapterTests tests.test_voice_cli.SentenceTtsPlaybackAdapterTests`

Expected: import or attribute failure for the new adapters.

- [ ] **Step 3: Implement adapters with controlled thread boundary**

`ArkStreamAdapter` must obtain the blocking `stream_ark` iterator in a worker thread and retrieve each next fragment through `asyncio.to_thread`; use a helper returning an explicit sentinel rather than allowing `StopIteration` to cross a Future. On `aclose()` or cancellation, close the owned iterator/response. `SentenceTtsPlaybackAdapter` must reuse current `TtsPlaybackAdapter` validation, create one uniquely named WAV under `wake_cache_dir`, synthesize, set user-approved 80% volume, call `aplay`, and delete its own WAV in `finally`.

- [ ] **Step 4: Add mapped-error, cancellation and ordering tests**

Test Ark HTTP/URL/malformed errors become `VoiceAdapterError("Ark stream failed")`; no API key/text appears in messages; TTS error removes its temporary WAV; two awaited sentence calls use distinct paths and do not overlap. Run:

`.venv/bin/python -m unittest tests.test_voice_cli`

- [ ] **Step 5: Run static check without commit**

Run: `.venv/bin/python -m compileall -q src tests && git diff --check -- src/lumilamp/voice/voice_cli.py tests/test_voice_cli.py`

Expected: exit 0.

### Task 5: VoiceLoop 流式状态、历史与延迟日志

**Files:**

- Modify: `src/lumilamp/voice/voice_loop.py`
- Modify: `src/lumilamp/voice/voice_cli.py`
- Test: `tests/test_voice_loop.py`
- Test: `tests/test_voice_cli.py`

**Interfaces:**

- Consumes `ArkStreamAdapter.stream`, `SentenceTtsPlaybackAdapter`, `stream_and_play`, `ConversationHistory`, injected monotonic `Clock` and `ReportLatency`.
- Produces a streaming response callable returning `StreamingReplyResult`; existing wake/ASR/30-second interfaces remain valid.

- [ ] **Step 1: Write failing loop tests**

```python
async def test_history_is_appended_only_after_all_streamed_sentences_play() -> None:
    result = await loop.run_once()
    self.assertEqual(history.messages(), [])  # after idle sleep clears completed history
    self.assertEqual(history.appended, [("问题", "第一句。第二句。")])

async def test_stream_failure_after_first_sentence_plays_error_once_without_history() -> None:
    await loop.run_once()
    self.assertEqual(spoken, ["第一句。", "网络好像断开了"])
    self.assertEqual(history.appended, [])
```

Add a fake-clock test for the exact success line:

```text
voice_latency status=ok asr=1.00s ark_first_sentence=2.00s first_audio=2.50s answer_complete=4.00s total=5.00s
```

- [ ] **Step 2: Run focused tests to verify RED**

Run: `.venv/bin/python -m unittest tests.test_voice_loop`

Expected: failures because `VoiceLoop` still calls complete-answer `ask()` then `speak()` serially.

- [ ] **Step 3: Implement the streaming turn path**

Introduce an injected `respond_to_turn(user_text) -> Awaitable[StreamingReplyResult]` boundary constructed from the Task 3 pipeline and Task 4 adapters. In the success path, append `history.append_turn(user_text, result.full_text)` only after pipeline completion. Start `SPEAKING` when the pipeline reports first audio, retain microphone closure until completion, then run the existing 300 ms guard. Preserve non-streaming `AskAdapter` tests only until all call sites migrate; remove obsolete adapter path only after replacement tests cover all original failure categories.

- [ ] **Step 4: Implement failure behavior and logs**

Map stream failure before any sentence, after partial sentence, TTS failure and cancellation to existing session cleanup semantics. Use one cached error-reply callback exactly once for Ark stream failure; never retry a full answer. Emit only stable fields: `status`, `failure_stage`, `sentences_played`, `asr`, `ark_first_sentence` when known, `first_audio` when known, `answer_complete` when known, and `total`.

- [ ] **Step 5: Verify full loop tests without commit**

Run: `.venv/bin/python -m unittest tests.test_voice_loop tests.test_voice_cli && .venv/bin/python -m compileall -q src tests && git diff --check`

Expected: all offline state, history, half-duplex, cancellation and latency tests pass. Do not commit.

### Task 6: 显式准备网络错误提示缓存

**Files:**

- Modify: `src/lumilamp/voice/wake_cache.py`
- Modify: `scripts/prepare_wake_replies.py`
- Test: `tests/test_wake_cache.py`

**Interfaces:**

- Produces `NETWORK_ERROR_REPLY = "网络好像断开了"` and `WakeReplyCache.path_for_error() -> Path`.
- The cache manifest records the error prompt filename and exact text; `validate()` requires it only after the new format version is prepared.

- [ ] **Step 1: Write failing cache/manifest tests**

```python
def test_prepare_generates_network_error_wav_and_manifest_entry() -> None:
    cache.prepare(fake_synthesize)
    assert cache.path_for_error().name == "network-interrupted.wav"
    cache.validate()
```

- [ ] **Step 2: Run focused tests to verify RED**

Run: `.venv/bin/python -m unittest tests.test_wake_cache`

Expected: missing `path_for_error`/manifest mismatch.

- [ ] **Step 3: Implement explicit preparation only**

Increment `WAKE_REPLY_FORMAT_VERSION`, include the error prompt in preparation/manifest validation, and preserve atomic temp-file publication. Do not call this tool from `voice_cli` startup or runtime; a missing cache must remain a clear validation failure.

- [ ] **Step 4: Verify tests and cache tooling without cloud calls**

Run: `.venv/bin/python -m unittest tests.test_wake_cache && .venv/bin/python -m compileall -q src tests && git diff --check -- src/lumilamp/voice/wake_cache.py scripts/prepare_wake_replies.py tests/test_wake_cache.py`

Expected: pass using fake synthesis only. Do not generate the actual WAV yet and do not commit.

### Task 7: Offline regression gate and authorized integration checklist

**Files:**

- Modify: `README.md`
- Test: existing full test suite

**Interfaces:**

- Documents the explicit commands for cache preparation, CLI dry-run, safe shutdown and the evidence categories; no runtime API changes.

- [ ] **Step 1: Write/adjust documentation verification test only if an existing executable contract requires it**

Do not create a prose-grep test. If `tests/test_pyproject_metadata.py` or an existing command test needs an updated concrete command, test that command's behavior instead.

- [ ] **Step 2: Document user-confirmed cloud/physical gates**

Add the exact sequence: prepare error WAV only after TTS quota confirmation; run `voice_cli --dry-run`; run one minimal Ark SSE request only after Ark quota confirmation; then perform one USB microphone/speaker latency run after physical-audio confirmation. State that no ESP32/servo operation occurs.

- [ ] **Step 3: Run the complete offline gate**

Run: `.venv/bin/python -m unittest discover -s tests -p 'test_*.py' && .venv/bin/python -m compileall -q src tests && git diff --check`

Expected: all tests pass, compile succeeds, no whitespace errors. Do not commit.

- [ ] **Step 4: Stop and request explicit runtime authorization**

Report static/code evidence separately. Ask before: (a) one TTS request to create the error WAV; (b) one Ark streaming request; (c) USB mic/speaker playback. Do not treat offline success as cloud or physical-hardware validation.

## Plan Self-Review

- Spec coverage: Tasks 1–2 cover natural splitting and strict SSE; Tasks 3–5 cover bounded queue, sequential playback, history, cancellation, failure behavior and latency metrics; Task 6 covers the explicit error prompt cache; Task 7 covers docs and evidence gates.
- Placeholder scan: no unresolved placeholders or unspecified error behavior remains; all external calls have explicit authorization gates.
- Type consistency: Task 1 produces strings consumed by Task 3; Task 2 produces `Iterator[str]` adapted in Task 4 to `AsyncIterator[str]`; Task 3 produces `StreamingReplyResult` consumed by Task 5; Task 6 supplies the error-reply callback used by Task 5.
