import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api/client';

type TtsStatus = 'idle' | 'loading' | 'playing' | 'error';

type ReadyClip = {
  text: string;
  url: string;
  approxDuration: number;
};

function textForProgress(text: string, ratio: number): string {
  if (text.length === 0) return '';
  if (ratio >= 0.98) return text;
  const chars = Array.from(text);
  const count = Math.max(1, Math.ceil(chars.length * Math.max(0, Math.min(1, ratio))));
  return chars.slice(0, count).join('');
}

function takeSpeakableChunks(buffer: string, force = false): { chunks: string[]; rest: string } {
  const rest = buffer;
  if (force) return rest.trim() ? { chunks: [rest], rest: '' } : { chunks: [], rest: '' };

  const chunks: string[] = [];
  let remaining = rest;
  const minChars = 8;
  const semanticPausePattern = /[。！？!?；;，,、：:\n]/;

  while (remaining.length >= minChars) {
    const pauseIndex = remaining.search(semanticPausePattern);
    if (pauseIndex < minChars - 1) break;
    const end = pauseIndex + 1;
    chunks.push(remaining.slice(0, end));
    remaining = remaining.slice(end);
  }

  return { chunks, rest: remaining };
}

function estimateDuration(text: string): number {
  return Math.max(1.1, Array.from(text).length / 5.2);
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function synthesizeSpeechWithRetry(text: string): Promise<Blob> {
  let lastError: unknown = null;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      return await api.synthesizeSpeech(text);
    } catch (error) {
      lastError = error;
      if (attempt < 2) await wait(260 * (attempt + 1));
    }
  }
  throw lastError instanceof Error ? lastError : new Error('语音合成失败，请稍后重试。');
}

export function useTtsPlayback(onError?: (message: string) => void) {
  const [status, setStatus] = useState<TtsStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [activeText, setActiveText] = useState('');
  const [displayText, setDisplayText] = useState('');
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const currentClipRef = useRef<ReadyClip | null>(null);
  const chunkQueueRef = useRef<string[]>([]);
  const readyQueueRef = useRef<ReadyClip[]>([]);
  const prefetchingRef = useRef(false);
  const playingRef = useRef(false);
  const sourceTextRef = useRef('');
  const pendingTextRef = useRef('');
  const spokenTextRef = useRef('');
  const stoppedRef = useRef(false);
  const versionRef = useRef(0);
  const onErrorRef = useRef(onError);
  const prefetchNextRef = useRef<() => void>(() => undefined);
  const playReadyRef = useRef<() => void>(() => undefined);

  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  const revokeClip = useCallback((clip: ReadyClip | null) => {
    if (clip?.url) URL.revokeObjectURL(clip.url);
  }, []);

  const clearReadyQueue = useCallback(() => {
    readyQueueRef.current.forEach(revokeClip);
    readyQueueRef.current = [];
  }, [revokeClip]);

  const fail = useCallback((message: string) => {
    setError(message);
    setStatus('error');
    onErrorRef.current?.(message);
  }, []);

  playReadyRef.current = () => {
    if (playingRef.current || stoppedRef.current) return;
    const clip = readyQueueRef.current.shift();
    if (!clip) {
      if (chunkQueueRef.current.length) prefetchNextRef.current();
      setStatus(prefetchingRef.current || chunkQueueRef.current.length ? 'loading' : 'idle');
      return;
    }

    const version = versionRef.current;
    const audio = new Audio(clip.url);
    audioRef.current = audio;
    currentClipRef.current = clip;
    playingRef.current = true;
    stoppedRef.current = false;
    setError(null);
    setStatus('playing');
    setCurrentTime(0);
    setDuration(clip.approxDuration);

    audio.onloadedmetadata = () => {
      const nextDuration = Number.isFinite(audio.duration) ? audio.duration : clip.approxDuration;
      setDuration(nextDuration);
    };
    audio.ontimeupdate = () => {
      const nextCurrentTime = audio.currentTime || 0;
      const nextDuration = Number.isFinite(audio.duration) ? audio.duration : clip.approxDuration;
      const ratio = nextDuration > 0 ? nextCurrentTime / nextDuration : 0;
      setCurrentTime(nextCurrentTime);
      setDuration(nextDuration);
      setDisplayText(`${spokenTextRef.current}${textForProgress(clip.text, ratio)}`);
    };
    audio.onended = () => {
      if (version !== versionRef.current) return;
      spokenTextRef.current = `${spokenTextRef.current}${clip.text}`;
      setDisplayText(spokenTextRef.current);
      setCurrentTime(Number.isFinite(audio.duration) ? audio.duration : clip.approxDuration);
      revokeClip(clip);
      currentClipRef.current = null;
      audioRef.current = null;
      playingRef.current = false;
      setStatus(readyQueueRef.current.length || chunkQueueRef.current.length || prefetchingRef.current ? 'loading' : 'idle');
      playReadyRef.current();
      prefetchNextRef.current();
    };
    audio.onerror = () => {
      if (version !== versionRef.current) return;
      revokeClip(clip);
      currentClipRef.current = null;
      audioRef.current = null;
      playingRef.current = false;
      fail('语音播放失败，请稍后重试。');
    };

    void audio.play().then(() => {
      if (version === versionRef.current) setStatus('playing');
    }).catch((err: unknown) => {
      if (version !== versionRef.current) return;
      revokeClip(clip);
      currentClipRef.current = null;
      audioRef.current = null;
      playingRef.current = false;
      const message = err instanceof Error && err.name === 'NotAllowedError'
        ? '浏览器阻止了自动播放，请点击员工语音气泡播放。'
        : '语音播放失败，请稍后重试。';
      fail(message);
    });

    prefetchNextRef.current();
  };

  prefetchNextRef.current = () => {
    if (prefetchingRef.current || stoppedRef.current) return;
    if (readyQueueRef.current.length >= 2) return;
    const nextText = chunkQueueRef.current.shift();
    if (!nextText) return;

    const version = versionRef.current;
    prefetchingRef.current = true;
    if (!playingRef.current) setStatus('loading');
    setError(null);

    void synthesizeSpeechWithRetry(nextText).then((audioBlob) => {
      if (stoppedRef.current || version !== versionRef.current) return;
      const clip: ReadyClip = {
        text: nextText,
        url: URL.createObjectURL(audioBlob),
        approxDuration: estimateDuration(nextText),
      };
      readyQueueRef.current.push(clip);
      playReadyRef.current();
    }).catch((err: unknown) => {
      if (version !== versionRef.current) return;
      const message = err instanceof Error ? err.message : '语音合成失败，请稍后重试。';
      fail(message);
    }).finally(() => {
      if (version !== versionRef.current) return;
      prefetchingRef.current = false;
      if (!playingRef.current && readyQueueRef.current.length) playReadyRef.current();
      if (chunkQueueRef.current.length && readyQueueRef.current.length < 2) prefetchNextRef.current();
      if (!playingRef.current && !readyQueueRef.current.length && !chunkQueueRef.current.length) setStatus('idle');
    });
  };

  const stop = useCallback(() => {
    versionRef.current += 1;
    stoppedRef.current = true;
    chunkQueueRef.current = [];
    pendingTextRef.current = '';
    prefetchingRef.current = false;
    playingRef.current = false;
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      audioRef.current = null;
    }
    revokeClip(currentClipRef.current);
    currentClipRef.current = null;
    clearReadyQueue();
    setStatus('idle');
    setCurrentTime(0);
    setDuration(0);
  }, [clearReadyQueue, revokeClip]);

  const resetStream = useCallback(() => {
    stop();
    sourceTextRef.current = '';
    pendingTextRef.current = '';
    spokenTextRef.current = '';
    chunkQueueRef.current = [];
    stoppedRef.current = false;
    setActiveText('');
    setDisplayText('');
    setError(null);
  }, [stop]);

  const enqueueStreamText = useCallback((fullText: string, force = false) => {
    const text = fullText.trimStart();
    if (!text) return;
    setActiveText(text);
    if (!sourceTextRef.current || !text.startsWith(sourceTextRef.current)) {
      sourceTextRef.current = '';
      pendingTextRef.current = '';
      spokenTextRef.current = '';
      chunkQueueRef.current = [];
      clearReadyQueue();
      setDisplayText('');
    }
    const delta = text.slice(sourceTextRef.current.length);
    sourceTextRef.current = text;
    pendingTextRef.current = `${pendingTextRef.current}${delta}`;
    const { chunks, rest } = takeSpeakableChunks(pendingTextRef.current, force);
    pendingTextRef.current = rest;
    if (chunks.length) {
      chunkQueueRef.current.push(...chunks);
      stoppedRef.current = false;
      prefetchNextRef.current();
      playReadyRef.current();
    }
  }, [clearReadyQueue]);

  const play = useCallback(async (text: string) => {
    resetStream();
    enqueueStreamText(text, true);
  }, [enqueueStreamText, resetStream]);

  useEffect(() => () => stop(), [stop]);

  const progress = duration > 0 ? Math.max(0, Math.min(1, currentTime / duration)) : status === 'playing' ? 0.1 : 0;
  const syncedDisplayText = useMemo(() => displayText || textForProgress(activeText, progress), [activeText, displayText, progress]);

  return {
    status,
    error,
    activeText,
    displayText: syncedDisplayText,
    currentTime,
    duration,
    progress,
    play,
    stop,
    resetStream,
    enqueueStreamText,
    playing: status === 'playing',
    loading: status === 'loading',
  };
}
