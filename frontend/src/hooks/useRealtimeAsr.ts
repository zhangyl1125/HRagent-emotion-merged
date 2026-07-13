import { useCallback, useEffect, useRef, useState } from 'react';
import { api, getWsApiBase } from '../api/client';

type AsrStatus = 'idle' | 'connecting' | 'recording' | 'error';
type AsrMode = 'realtime' | 'recorded' | null;

type AsrServerEvent = {
  type: 'status' | 'partial' | 'final' | 'error';
  text?: string;
  preview?: string;
  transcript?: string;
  emotion?: string;
  message?: string;
  code?: string;
};

type UseRealtimeAsrOptions = {
  onPartialTranscript?: (text: string, event: AsrServerEvent) => void;
  onFinalTranscript?: (text: string, event: AsrServerEvent) => void;
  onError?: (message: string) => void;
};

type AudioContextConstructor = typeof AudioContext;
type AudioWindow = Window & { webkitAudioContext?: AudioContextConstructor };

type BrowserSpeechRecognitionResult = {
  isFinal: boolean;
  [index: number]: { transcript: string };
  length: number;
};

type BrowserSpeechRecognitionEvent = {
  resultIndex: number;
  results: { [index: number]: BrowserSpeechRecognitionResult; length: number };
};

type BrowserSpeechRecognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((event: BrowserSpeechRecognitionEvent) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};

type BrowserSpeechRecognitionConstructor = new () => BrowserSpeechRecognition;

type SpeechWindow = Window & {
  SpeechRecognition?: BrowserSpeechRecognitionConstructor;
  webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor;
};

const TARGET_SAMPLE_RATE = 16000;
const MAX_RECORDING_MS = 60000;
const LIVE_HTTP_CHUNK_MS = 750;

function isRealtimeAuthError(message = ''): boolean {
  return (
    message.includes('ASR 实时服务鉴权失败') ||
    message.includes('Realtime ASR') ||
    message.includes('qwen3-asr-flash-realtime') ||
    message.includes('未被 Realtime ASR 服务接受')
  );
}

function secureContextMessage(): string | null {
  const isLocalhost = ['localhost', '127.0.0.1', '::1'].includes(window.location.hostname);
  if (window.isSecureContext || isLocalhost) return null;
  return `当前页面是 HTTP 非安全地址，浏览器会禁用麦克风。请使用 https://${window.location.hostname}:8443${window.location.pathname} 访问。`;
}

function chooseMimeType(): string {
  if (!('MediaRecorder' in window)) return '';
  const preferred = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];
  return preferred.find((type) => MediaRecorder.isTypeSupported(type)) || '';
}

function pcm16FromFloat32(input: Float32Array, sampleRate: number): ArrayBuffer {
  const ratio = sampleRate / TARGET_SAMPLE_RATE;
  const length = Math.max(1, Math.floor(input.length / ratio));
  const buffer = new ArrayBuffer(length * 2);
  const view = new DataView(buffer);

  for (let i = 0; i < length; i += 1) {
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    let count = 0;
    for (let j = start; j < end; j += 1) {
      sum += input[j];
      count += 1;
    }
    const sample = Math.max(-1, Math.min(1, count ? sum / count : input[start] || 0));
    view.setInt16(i * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }

  return buffer;
}

function nextTranscript(current: string, incoming: string): string {
  const text = incoming.trim();
  if (!text) return current;
  if (!current) return text;
  if (text === current || current.endsWith(text)) return current;
  if (text.startsWith(current)) return text;
  if (text.length > current.length && text.includes(current.slice(-Math.min(8, current.length)))) return text;
  return `${current}${text}`;
}

function nextCumulativeTranscript(current: string, incoming: string): string {
  const text = incoming.trim();
  if (!text) return current;
  if (!current || text.startsWith(current)) return text;
  if (current.startsWith(text)) return current;
  return text.length >= current.length ? text : current;
}

function wavBlobFromPcm(chunks: ArrayBuffer[], sampleRate: number): Blob {
  const pcmLength = chunks.reduce((total, chunk) => total + chunk.byteLength, 0);
  const buffer = new ArrayBuffer(44 + pcmLength);
  const view = new DataView(buffer);
  const writeText = (offset: number, value: string) => {
    for (let index = 0; index < value.length; index += 1) view.setUint8(offset + index, value.charCodeAt(index));
  };

  writeText(0, 'RIFF');
  view.setUint32(4, 36 + pcmLength, true);
  writeText(8, 'WAVE');
  writeText(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeText(36, 'data');
  view.setUint32(40, pcmLength, true);

  let offset = 44;
  const output = new Uint8Array(buffer);
  for (const chunk of chunks) {
    output.set(new Uint8Array(chunk), offset);
    offset += chunk.byteLength;
  }
  return new Blob([buffer], { type: 'audio/wav' });
}

export function useRealtimeAsr(options: UseRealtimeAsrOptions = {}) {
  const [status, setStatus] = useState<AsrStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const silentGainRef = useRef<GainNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const recorderChunksRef = useRef<BlobPart[]>([]);
  const recorderMimeTypeRef = useRef('audio/webm');
  const pcmChunksRef = useRef<ArrayBuffer[]>([]);
  const pcmBytesRef = useRef(0);
  const livePreviewTimerRef = useRef<number | null>(null);
  const livePreviewBusyRef = useRef(false);
  const liveHttpDisabledRef = useRef(false);
  const speechRecognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const speechPreviewActiveRef = useRef(false);
  const stopTimerRef = useRef<number | null>(null);
  const transcriptRef = useRef('');
  const speechFinalTextRef = useRef('');
  const speechInterimTextRef = useRef('');
  const manualStopRef = useRef(false);
  const hasRealtimePreviewRef = useRef(false);
  const optionsRef = useRef(options);

  useEffect(() => {
    optionsRef.current = options;
  }, [options]);

  const clearStopTimer = useCallback(() => {
    if (stopTimerRef.current !== null) {
      window.clearTimeout(stopTimerRef.current);
      stopTimerRef.current = null;
    }
  }, []);

  const emitTranscript = useCallback((text: string, event: AsrServerEvent, final = false) => {
    const cumulativePreview = ['browser_preview', 'http_preview', 'server_realtime'].includes(event.code || '');
    const next = cumulativePreview
      ? nextCumulativeTranscript(transcriptRef.current, text)
      : nextTranscript(transcriptRef.current, text);
    if (!next) return;
    transcriptRef.current = next;
    hasRealtimePreviewRef.current = true;
    if (event.code === 'server_realtime') liveHttpDisabledRef.current = true;
    if (final) optionsRef.current.onFinalTranscript?.(next, { ...event, transcript: next });
    else optionsRef.current.onPartialTranscript?.(next, { ...event, preview: next });
  }, []);

  const cleanupSpeechPreview = useCallback(() => {
    speechPreviewActiveRef.current = false;
    if (!speechRecognitionRef.current) return;
    speechRecognitionRef.current.onresult = null;
    speechRecognitionRef.current.onerror = null;
    speechRecognitionRef.current.onend = null;
    try {
      speechRecognitionRef.current.abort();
    } catch {
      // Recognition may already be closed.
    }
    speechRecognitionRef.current = null;
  }, []);

  const startSpeechPreview = useCallback((resetText = false): boolean => {
    const SpeechRecognitionCtor = (window as SpeechWindow).SpeechRecognition || (window as SpeechWindow).webkitSpeechRecognition;
    if (!SpeechRecognitionCtor) return false;
    speechPreviewActiveRef.current = true;
    if (resetText) {
      speechFinalTextRef.current = '';
      speechInterimTextRef.current = '';
    }

    const recognition = new SpeechRecognitionCtor();
    recognition.lang = 'zh-CN';
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onresult = (event) => {
      let finalText = speechFinalTextRef.current;
      let interimText = '';
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        const transcript = result[0]?.transcript || '';
        if (!transcript) continue;
        if (result.isFinal) finalText += transcript;
        else interimText += transcript;
      }
      speechFinalTextRef.current = finalText;
      speechInterimTextRef.current = interimText;
      emitTranscript(`${finalText}${interimText}`, { type: 'partial', code: 'browser_preview' }, false);
    };

    recognition.onerror = () => {
      // Server realtime or final HTTP transcription can still provide text.
    };

    recognition.onend = () => {
      speechRecognitionRef.current = null;
      if (speechPreviewActiveRef.current && !manualStopRef.current) {
        window.setTimeout(() => startSpeechPreview(false), 120);
      }
    };

    try {
      recognition.start();
      speechRecognitionRef.current = recognition;
      return true;
    } catch {
      speechRecognitionRef.current = null;
      return false;
    }
  }, [emitTranscript]);

  const cleanupAudio = useCallback((stopTracks = true) => {
    if (livePreviewTimerRef.current !== null) {
      window.clearInterval(livePreviewTimerRef.current);
      livePreviewTimerRef.current = null;
    }
    livePreviewBusyRef.current = false;
    pcmChunksRef.current = [];
    pcmBytesRef.current = 0;
    processorRef.current?.disconnect();
    sourceRef.current?.disconnect();
    silentGainRef.current?.disconnect();
    processorRef.current = null;
    sourceRef.current = null;
    silentGainRef.current = null;
    const context = audioContextRef.current;
    audioContextRef.current = null;
    if (context && context.state !== 'closed') {
      void context.close();
    }
    if (stopTracks) {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
  }, []);

  const stopRecorderNow = useCallback(() => {
    const recorder = recorderRef.current;
    recorderRef.current = null;
    if (!recorder) return;
    recorder.ondataavailable = null;
    recorder.onstop = null;
    recorder.onerror = null;
    if (recorder.state !== 'inactive') recorder.stop();
  }, []);

  const cleanup = useCallback((closeSocket = true) => {
    clearStopTimer();
    stopRecorderNow();
    cleanupAudio();
    cleanupSpeechPreview();
    if (closeSocket && wsRef.current) {
      wsRef.current.onopen = null;
      wsRef.current.onmessage = null;
      wsRef.current.onerror = null;
      wsRef.current.onclose = null;
      if (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING) {
        wsRef.current.close();
      }
      wsRef.current = null;
    }
  }, [cleanupAudio, cleanupSpeechPreview, clearStopTimer, stopRecorderNow]);

  const fail = useCallback((message: string) => {
    cleanup();
    setError(message);
    setStatus('error');
    optionsRef.current.onError?.(message);
  }, [cleanup]);

  const closeServerRealtimeOnly = useCallback(() => {
    const ws = wsRef.current;
    wsRef.current = null;
    if (!ws) return;
    ws.onopen = null;
    ws.onmessage = null;
    ws.onerror = null;
    ws.onclose = null;
    if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) ws.close();
  }, []);

  const processPcmPreview = useCallback(async () => {
    if (livePreviewBusyRef.current || liveHttpDisabledRef.current || pcmBytesRef.current < TARGET_SAMPLE_RATE) return;
    livePreviewBusyRef.current = true;
    const snapshot = pcmChunksRef.current.slice();
    try {
      const result = await api.transcribeAudio(wavBlobFromPcm(snapshot, TARGET_SAMPLE_RATE), null, 'zh');
      const text = String(result.text || '').trim();
      if (text && !liveHttpDisabledRef.current) {
        emitTranscript(text, { type: 'partial', code: 'http_preview', preview: text, emotion: result.audio_emotion || undefined }, false);
      }
    } catch {
      // A later cumulative snapshot can still be recognized while recording continues.
    } finally {
      livePreviewBusyRef.current = false;
    }
  }, [emitTranscript]);

  const startFallbackRecorder = useCallback((stream: MediaStream) => {
    if (!('MediaRecorder' in window)) return;
    recorderChunksRef.current = [];
    const mimeType = chooseMimeType();
    recorderMimeTypeRef.current = mimeType || 'audio/webm';
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    recorderRef.current = recorder;
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) recorderChunksRef.current.push(event.data);
    };
    recorder.start(LIVE_HTTP_CHUNK_MS);
  }, []);

  const stopFallbackRecorder = useCallback(() => new Promise<BlobPart[]>((resolve) => {
    const recorder = recorderRef.current;
    if (!recorder) {
      resolve(recorderChunksRef.current.splice(0));
      return;
    }
    recorderRef.current = null;
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) recorderChunksRef.current.push(event.data);
    };
    recorder.onstop = () => {
      recorder.ondataavailable = null;
      recorder.onstop = null;
      recorder.onerror = null;
      resolve(recorderChunksRef.current.splice(0));
    };
    recorder.onerror = () => resolve(recorderChunksRef.current.splice(0));
    if (recorder.state === 'inactive') resolve(recorderChunksRef.current.splice(0));
    else recorder.stop();
  }), []);

  const transcribeFallback = useCallback(async (chunks: BlobPart[]) => {
    if (!chunks.length || transcriptRef.current.trim()) return;
    try {
      setStatus('connecting');
      const blob = new Blob(chunks, { type: recorderMimeTypeRef.current });
      const result = await api.transcribeAudio(blob, null, 'zh');
      const text = String(result.text || '').trim();
      if (text) emitTranscript(text, { type: 'final', transcript: text, emotion: result.audio_emotion || undefined }, true);
      setStatus('idle');
    } catch (err) {
      const message = err instanceof Error ? err.message : '语音转写失败，请重试。';
      fail(message);
    }
  }, [emitTranscript, fail]);

  const startAudioStreaming = useCallback(async (stream: MediaStream) => {
    const AudioContextCtor = window.AudioContext || (window as AudioWindow).webkitAudioContext;
    if (!AudioContextCtor) throw new Error('当前浏览器不支持实时音频处理，请使用最新版 Chrome 或 Edge。');

    const audioContext = new AudioContextCtor();
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(2048, 1, 1);
    const silentGain = audioContext.createGain();
    silentGain.gain.value = 0;

    processor.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0);
      const pcm = pcm16FromFloat32(input, audioContext.sampleRate);
      pcmChunksRef.current.push(pcm);
      pcmBytesRef.current += pcm.byteLength;
      const ws = wsRef.current;
      if (ws?.readyState === WebSocket.OPEN) ws.send(pcm);
    };

    source.connect(processor);
    processor.connect(silentGain);
    silentGain.connect(audioContext.destination);

    audioContextRef.current = audioContext;
    sourceRef.current = source;
    processorRef.current = processor;
    silentGainRef.current = silentGain;
    livePreviewTimerRef.current = window.setInterval(() => {
      void processPcmPreview();
    }, LIVE_HTTP_CHUNK_MS);
  }, [processPcmPreview]);

  const stop = useCallback(async () => {
    manualStopRef.current = true;
    liveHttpDisabledRef.current = true;
    clearStopTimer();
    cleanupSpeechPreview();
    cleanupAudio(false);
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'stop' }));
      window.setTimeout(() => {
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) ws.close();
      }, 3500);
    } else if (ws?.readyState === WebSocket.CONNECTING) {
      ws.close();
    }
    const chunks = await stopFallbackRecorder();
    cleanupAudio();
    if (!transcriptRef.current.trim()) await transcribeFallback(chunks);
    else setStatus('idle');
  }, [cleanupAudio, cleanupSpeechPreview, clearStopTimer, stopFallbackRecorder, transcribeFallback]);

  const start = useCallback(async () => {
    try {
      setError(null);
      transcriptRef.current = '';
      speechFinalTextRef.current = '';
      speechInterimTextRef.current = '';
      hasRealtimePreviewRef.current = false;
      liveHttpDisabledRef.current = false;
      pcmChunksRef.current = [];
      pcmBytesRef.current = 0;
      manualStopRef.current = false;
      const secureMessage = secureContextMessage();
      if (secureMessage) throw new Error(secureMessage);
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error('当前浏览器不支持麦克风录音，请使用最新版 Chrome 或 Edge。');
      }

      cleanup();
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          noiseSuppression: true,
          echoCancellation: true,
          autoGainControl: true,
        },
        video: false,
      });
      streamRef.current = stream;
      startFallbackRecorder(stream);
      const browserPreviewStarted = startSpeechPreview(true);
      setStatus('recording');
      stopTimerRef.current = window.setTimeout(() => {
        void stop();
      }, MAX_RECORDING_MS);

      const ws = new WebSocket(`${getWsApiBase()}/asr/realtime`);
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;
      await startAudioStreaming(stream);

      ws.onopen = () => {
        setStatus('recording');
      };

      ws.onmessage = (message) => {
        let event: AsrServerEvent;
        try {
          event = JSON.parse(String(message.data)) as AsrServerEvent;
        } catch {
          return;
        }
        if (event.type === 'error') {
          closeServerRealtimeOnly();
          if (isRealtimeAuthError(event.message || '')) {
            setError(null);
            setStatus('recording');
            return;
          }
          if (!browserPreviewStarted && !hasRealtimePreviewRef.current) {
            setStatus('recording');
          }
          return;
        }
        if (event.type === 'partial') {
          emitTranscript(event.preview || event.text || event.transcript || '', { ...event, code: 'server_realtime' }, false);
          return;
        }
        if (event.type === 'final') {
          emitTranscript(event.transcript || event.text || event.preview || '', { ...event, code: 'server_realtime' }, true);
        }
      };

      ws.onerror = () => {
        closeServerRealtimeOnly();
        if (!manualStopRef.current && !browserPreviewStarted && !hasRealtimePreviewRef.current) setStatus('recording');
      };

      ws.onclose = () => {
        wsRef.current = null;
        if (!manualStopRef.current && !browserPreviewStarted && !hasRealtimePreviewRef.current) setStatus('recording');
      };
    } catch (err) {
      const message = err instanceof Error ? err.message : '语音输入启动失败。';
      fail(message);
    }
  }, [cleanup, closeServerRealtimeOnly, emitTranscript, fail, startAudioStreaming, startFallbackRecorder, startSpeechPreview, stop]);

  useEffect(() => () => {
    manualStopRef.current = true;
    cleanup();
  }, [cleanup]);

  return {
    status,
    mode: 'realtime' as AsrMode,
    error,
    isRecording: status === 'recording',
    isConnecting: status === 'connecting',
    isTranscribing: status === 'connecting',
    start,
    stop,
  };
}
