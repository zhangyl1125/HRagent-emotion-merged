import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import type { AsrTranscribeResponse } from '../types/domain';

type SpeechToTextStatus = 'idle' | 'recording' | 'transcribing' | 'error';

type UseSpeechToTextOptions = {
  sessionId?: string | null;
  language?: string;
  maxDurationMs?: number;
  onTranscript?: (text: string, result: AsrTranscribeResponse) => void;
  onError?: (message: string) => void;
};

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

export function useSpeechToText(options: UseSpeechToTextOptions = {}) {
  const [status, setStatus] = useState<SpeechToTextStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const mimeTypeRef = useRef('audio/webm');
  const stopTimerRef = useRef<number | null>(null);
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

  const cleanupStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const fail = useCallback((message: string) => {
    setError(message);
    setStatus('error');
    optionsRef.current.onError?.(message);
  }, []);

  const transcribe = useCallback(async (chunks: BlobPart[]) => {
    if (!chunks.length) {
      fail('没有收到录音内容，请重新录制。');
      return;
    }
    try {
      setStatus('transcribing');
      const result = await api.transcribeAudio(
        new Blob(chunks, { type: mimeTypeRef.current }),
        optionsRef.current.sessionId,
        optionsRef.current.language || 'zh',
      );
      const text = (result.text || '').trim();
      if (!text) throw new Error('语音转写没有返回文本。');
      setError(null);
      setStatus('idle');
      optionsRef.current.onTranscript?.(text, result);
    } catch (err) {
      const message = err instanceof Error ? err.message : '语音转写失败，请重试。';
      fail(message);
    }
  }, [fail]);

  const stopRecording = useCallback(async () => {
    clearStopTimer();
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === 'inactive') {
      cleanupStream();
      setStatus((current) => (current === 'recording' ? 'idle' : current));
      return;
    }
    recorder.stop();
  }, [clearStopTimer, cleanupStream]);

  const startRecording = useCallback(async () => {
    try {
      setError(null);
      const secureMessage = secureContextMessage();
      if (secureMessage) throw new Error(secureMessage);
      if (!navigator.mediaDevices?.getUserMedia || !('MediaRecorder' in window)) {
        throw new Error('当前浏览器不支持录音上传，请使用最新版 Chrome 或 Edge。');
      }

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
      chunksRef.current = [];
      const mimeType = chooseMimeType();
      mimeTypeRef.current = mimeType || 'audio/webm';
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };

      recorder.onstop = () => {
        clearStopTimer();
        const chunks = chunksRef.current;
        chunksRef.current = [];
        recorderRef.current = null;
        cleanupStream();
        void transcribe(chunks);
      };

      recorder.onerror = () => {
        clearStopTimer();
        cleanupStream();
        fail('录音过程中发生错误，请重新录制。');
      };

      recorder.start();
      setStatus('recording');
      const maxDurationMs = optionsRef.current.maxDurationMs || 60000;
      stopTimerRef.current = window.setTimeout(() => {
        void stopRecording();
      }, maxDurationMs);
    } catch (err) {
      cleanupStream();
      const message = err instanceof Error ? err.message : '语音输入启动失败。';
      fail(message);
    }
  }, [clearStopTimer, cleanupStream, fail, stopRecording, transcribe]);

  useEffect(() => () => {
    clearStopTimer();
    if (recorderRef.current && recorderRef.current.state !== 'inactive') {
      recorderRef.current.ondataavailable = null;
      recorderRef.current.onstop = null;
      recorderRef.current.onerror = null;
      recorderRef.current.stop();
    }
    cleanupStream();
  }, [clearStopTimer, cleanupStream]);

  return {
    status,
    error,
    recording: status === 'recording',
    transcribing: status === 'transcribing',
    startRecording,
    stopRecording,
  };
}
