"""Live ALSA microphone to Doubao bidirectional ASR coordination."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Any

from .asr import (
    ASR_ENDPOINT,
    build_audio_frame,
    build_connection_headers,
    build_start_frame,
    parse_server_frame,
)
from .config import AsrConfig
from .recorder import LevelConfig
from .streaming_audio import CHUNK_BYTES, UtterancePacketizer


def _consume_background_task(task: asyncio.Task[Any]) -> None:
    try:
        task.result()
    except BaseException:
        pass


async def _bounded_process_wait(process: Any, timeout: float) -> bool:
    waiter = asyncio.create_task(process.wait())
    try:
        done, _ = await asyncio.wait({waiter}, timeout=timeout)
    except BaseException:
        waiter.cancel()
        waiter.add_done_callback(_consume_background_task)
        raise
    if waiter not in done:
        waiter.cancel()
        waiter.add_done_callback(_consume_background_task)
        return False
    waiter.result()
    return True


async def _stop_owned_process(
    process: Any,
    term_timeout: float,
    kill_timeout: float,
) -> None:
    if process.returncode is not None:
        if not await _bounded_process_wait(process, kill_timeout):
            raise RuntimeError("owned audio process did not exit after termination")
        return

    try:
        process.terminate()
    except ProcessLookupError:
        pass

    if await _bounded_process_wait(process, term_timeout):
        return

    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    if not await _bounded_process_wait(process, kill_timeout):
        raise RuntimeError("owned audio process did not exit after termination")


async def terminate_owned_process(
    process: Any,
    term_timeout: float = 1.0,
    kill_timeout: float = 1.0,
) -> None:
    """Stop and reap one owned child within bounded TERM and KILL waits."""
    cleanup = asyncio.create_task(
        _stop_owned_process(process, term_timeout, kill_timeout)
    )
    cancellation: asyncio.CancelledError | None = None
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError as error:
            if cancellation is None:
                cancellation = error
        except BaseException:
            break

    try:
        cleanup.result()
    except BaseException as cleanup_error:
        if cancellation is None:
            raise
        cancellation.add_note(
            f"owned audio cleanup also failed: {type(cleanup_error).__name__}"
        )
    if cancellation is not None:
        raise cancellation


def _open_websocket(headers: dict[str, str]) -> Any:
    import websockets

    return websockets.connect(
        ASR_ENDPOINT,
        additional_headers=headers,
        open_timeout=15,
    )


async def _receive_final(socket: Any, on_partial: Callable[[str], None]) -> str:
    while True:
        response = await asyncio.wait_for(socket.recv(), timeout=15)
        if not isinstance(response, bytes):
            continue
        result = parse_server_frame(response)
        if result is None:
            continue
        if result.is_final:
            return result.text
        on_partial(result.text)


def _add_secondary_note(
    error: BaseException,
    source: str,
    secondary_error: BaseException,
) -> None:
    error.add_note(f"{source} also failed: {type(secondary_error).__name__}")


async def _settle_receiver(receiver: asyncio.Task[str]) -> None:
    cancelled_for_cleanup = not receiver.done()
    if cancelled_for_cleanup:
        receiver.cancel()
    try:
        await receiver
    except asyncio.CancelledError:
        if not cancelled_for_cleanup:
            raise


async def recognize_microphone(
    config: AsrConfig,
    device: str,
    level_config: LevelConfig,
    on_partial: Callable[[str], None],
) -> str:
    """Stream one microphone utterance and return its final transcript."""
    process = await asyncio.create_subprocess_exec(
        "arecord",
        "-D",
        device,
        "-t",
        "raw",
        "-f",
        "S16_LE",
        "-r",
        "16000",
        "-c",
        "1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    receiver: asyncio.Task[str] | None = None
    primary_error: BaseException | None = None
    try:
        if process.stdout is None:
            raise RuntimeError("arecord did not provide PCM output")
        packetizer = UtterancePacketizer(level_config)
        while True:
            try:
                chunk = await process.stdout.readexactly(CHUNK_BYTES)
            except asyncio.IncompleteReadError as exc:
                raise RuntimeError("microphone audio stream ended unexpectedly") from exc
            decision = packetizer.push(chunk)
            if decision.started:
                break
            if decision.finished:
                raise RuntimeError("no speech detected within 10 seconds")

        headers = build_connection_headers(
            config.app_id,
            config.access_token,
            config.resource_id,
            str(uuid.uuid4()),
        )
        async with _open_websocket(headers) as socket:
            await socket.send(
                build_start_frame(config.app_id, config.resource_id, sequence=1)
            )
            initial = await asyncio.wait_for(socket.recv(), timeout=15)
            if isinstance(initial, bytes):
                parse_server_frame(initial)

            receiver = asyncio.create_task(_receive_final(socket, on_partial))
            sequence = 2
            while True:
                if not decision.finished:
                    for packet in decision.packets:
                        await socket.send(build_audio_frame(packet, sequence, final=False))
                        sequence += 1
                    try:
                        chunk = await process.stdout.readexactly(CHUNK_BYTES)
                    except asyncio.IncompleteReadError as exc:
                        raise RuntimeError(
                            "microphone audio stream ended unexpectedly"
                        ) from exc
                    decision = packetizer.push(chunk)
                    continue

                final_packets = list(decision.packets)
                final_packets.extend(packetizer.finish())
                if not final_packets:
                    final_packets.append(b"")
                for packet in final_packets[:-1]:
                    await socket.send(build_audio_frame(packet, sequence, final=False))
                    sequence += 1
                await socket.send(
                    build_audio_frame(final_packets[-1], sequence, final=True)
                )
                break

            transcript = await asyncio.wait_for(receiver, timeout=15)
            if not transcript.strip():
                raise RuntimeError("Doubao ASR returned no final transcript")
            return transcript.strip()
    except BaseException as error:
        primary_error = error
        raise
    finally:
        secondary_errors: list[tuple[str, BaseException]] = []
        try:
            if receiver is not None:
                await _settle_receiver(receiver)
        except BaseException as error:
            if error is not primary_error:
                secondary_errors.append(("ASR receiver", error))

        try:
            await terminate_owned_process(process)
        except BaseException as error:
            secondary_errors.append(("owned audio cleanup", error))

        if primary_error is not None:
            for source, error in secondary_errors:
                _add_secondary_note(primary_error, source, error)
        elif secondary_errors:
            _, cleanup_error = secondary_errors[0]
            for later_source, later_error in secondary_errors[1:]:
                _add_secondary_note(cleanup_error, later_source, later_error)
            raise cleanup_error
