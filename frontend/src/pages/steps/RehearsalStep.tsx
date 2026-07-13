import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useWorkflow } from '../../context/WorkflowContext';
import { EmotionBadge } from '../../components/rehearsal/EmotionBadge';
import { useRealtimeAsr } from '../../hooks/useRealtimeAsr';
import { useTtsPlayback } from '../../hooks/useTtsPlayback';
import type { BigFivePersonality, ConversationTurn } from '../../types/domain';
import { firstText } from '../../utils/format';

function VoiceWave({ active }: { active?: boolean }) {
  return (
    <span className={`voice-wave ${active ? 'active' : ''}`} aria-hidden="true">
      <span /><span /><span /><span /><span />
    </span>
  );
}

function isRecoverableAsrError(message = '') {
  return (
    message.includes('ASR 实时服务鉴权失败') ||
    message.includes('Realtime ASR') ||
    message.includes('qwen3-asr-flash-realtime') ||
    message.includes('未被 Realtime ASR 服务接受')
  );
}

function ChatMessage({
  turn,
  isStreaming,
  employeeName,
  onSpeak,
  onStopSpeak,
  ttsBusy,
  ttsPlaying,
  ttsActiveText,
  ttsDisplayText,
  ttsDuration,
}: {
  turn: ConversationTurn;
  isStreaming?: boolean;
  employeeName: string;
  onSpeak?: (text: string) => void;
  onStopSpeak?: () => void;
  ttsBusy?: boolean;
  ttsPlaying?: boolean;
  ttsActiveText?: string;
  ttsDisplayText?: string;
  ttsDuration?: number;
}) {
  const [textHidden, setTextHidden] = useState(false);
  const speaker = turn.speaker || 'system';
  if (speaker === 'system') {
    return (
      <div className="chat-msg system">
        <div className="system-bubble">{turn.text}</div>
      </div>
    );
  }

  const isManager = speaker === 'manager' || speaker === 'you';
  const employeeLabel = employeeName ? `${employeeName}（员工）` : '员工';
  const text = String(turn.text || '');
  const isActiveVoice = Boolean(!isManager && text && ttsActiveText === text && (ttsBusy || ttsPlaying));
  const voiceText = isActiveVoice ? (ttsDisplayText || text) : text;
  const estimatedSeconds = Math.max(2, Math.round((ttsDuration && ttsDuration > 0 ? ttsDuration : Math.max(2, text.length / 4))));

  if (!isManager && text) {
    return (
      <div className="chat-msg employee voice-chat-msg">
        <div className="chat-avatar">{employeeName.slice(0, 1).toUpperCase() || '员'}</div>
        <div className="chat-content">
          <div className="chat-meta"><span>{employeeLabel}</span></div>
          <div className="voice-stack left">
            <button
              className={`voice-bubble employee-voice ${isActiveVoice ? 'is-active' : ''}`}
              type="button"
              disabled={ttsBusy && !isActiveVoice}
              onClick={() => {
                if (isActiveVoice && ttsPlaying) onStopSpeak?.();
                else onSpeak?.(text);
              }}
              aria-label={isActiveVoice && ttsPlaying ? '暂停员工语音' : '播放员工语音'}
              title={isActiveVoice && ttsPlaying ? '暂停员工语音' : '播放员工语音'}
            >
              <span className="voice-duration">{estimatedSeconds}s</span>
              <VoiceWave active={isActiveVoice && ttsPlaying} />
              <span className={isActiveVoice && ttsPlaying ? 'pause-btn' : 'play-btn'} aria-hidden="true" />
            </button>
            {!textHidden && <div className="voice-text">{voiceText}</div>}
            <div className="voice-actions">
              <button type="button" onClick={() => setTextHidden((value) => !value)}>{textHidden ? '显示文本' : '隐藏文本'}</button>
              <button type="button" onClick={() => void navigator.clipboard?.writeText(text)}>复制</button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`chat-msg ${isManager ? 'manager' : 'employee'}`}>
      {!isManager && <div className="chat-avatar">{employeeName.slice(0, 1).toUpperCase() || '员'}</div>}
      <div className="chat-content">
        <div className="chat-meta"><span>{isManager ? '你（管理者 / HRBP）' : employeeLabel}</span></div>
        <div className="chat-bubble">{text || (isStreaming ? <span className="typing-text">正在输入...</span> : '')}</div>
      </div>
      {isManager && <div className="chat-avatar manager-avatar">你</div>}
    </div>
  );
}

const personalityLabels: Array<[keyof BigFivePersonality, string]> = [
  ['openness', '开放'],
  ['conscientiousness', '尽责'],
  ['extraversion', '外向'],
  ['agreeableness', '宜人'],
  ['neuroticism', '敏感'],
];

function personalityText(personality?: BigFivePersonality | null) {
  if (!personality) return '';
  return personalityLabels.map(([key, label]) => `${label} ${Math.round(Number(personality[key]) || 0)}`).join(' / ');
}

function formatNumber(value: unknown, fallback = '0') {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(2) : fallback;
}

export default function RehearsalStep() {
  const navigate = useNavigate();
  const {
    session,
    options,
    selectedIntentId,
    liveConversation,
    rehearsalStreaming,
    sendMessage,
    updateRehearsalContext,
    endRehearsal,
    showToast,
  } = useWorkflow();
  const [message, setMessage] = useState('');
  const [contextOpen, setContextOpen] = useState(false);
  const [runtimeNote, setRuntimeNote] = useState('');
  const [lastAudioEmotion, setLastAudioEmotion] = useState<string | null>(null);
  const [lastInputMode, setLastInputMode] = useState<'text' | 'voice_asr'>('text');
  const [pendingAutoTts, setPendingAutoTts] = useState(false);
  const chatListRef = useRef<HTMLDivElement | null>(null);
  const messageInputRef = useRef<HTMLTextAreaElement | null>(null);
  const turns = liveConversation || session?.conversation || [];
  const employeeName = session?.employee_profile?.employee_alias || session?.employee_profile?.name || '员工';
  const runtimeNotesCount = session?.rehearsal_context?.runtime_notes?.length || 0;
  const currentIntentId = firstText([selectedIntentId, session?.intent?.intent_id, session?.intent?.id], '');
  const canonicalIntent = options.intents.find((item) => (
    item.id === currentIntentId ||
    item.id === session?.intent?.name ||
    item.name === session?.intent?.name
  ));
  const intentName = firstText([canonicalIntent?.name, canonicalIntent?.id, session?.intent?.name, currentIntentId], '未设置');
  const primaryMotive = options.motives.find((item) => item.id === session?.motivation?.primary_motive_id);
  const secondaryMotives = (session?.motivation?.secondary_motive_ids || [])
    .map((id) => options.motives.find((item) => item.id === id))
    .filter(Boolean);
  const emotionAnchor = options.emotion_anchors.find((item) => item.id === session?.emotion_state?.current_anchor_id);
  const vad = session?.emotion_state?.current_vad;
  const satisfaction = typeof session?.motivation?.total_satisfaction === 'number'
    ? `${Math.round(session.motivation.total_satisfaction)} 分`
    : '0%';
  const personality = personalityText(session?.personality);
  const asr = useRealtimeAsr({
    onPartialTranscript: (text, event) => {
      setMessage(text);
      setLastInputMode('voice_asr');
      setLastAudioEmotion(event.emotion || null);
    },
    onFinalTranscript: (text, event) => {
      setMessage(text);
      setLastInputMode('voice_asr');
      setLastAudioEmotion(event.emotion || null);
    },
    onError: (msg) => {
      if (!isRecoverableAsrError(msg)) showToast(msg, 'error');
    },
  });
  const tts = useTtsPlayback((msg) => showToast(msg, 'error'));

  useEffect(() => {
    const node = chatListRef.current;
    if (!node) return;
    window.requestAnimationFrame(() => {
      node.scrollTo({ top: node.scrollHeight, behavior: 'smooth' });
    });
  }, [liveConversation, rehearsalStreaming, turns.length]);

  useEffect(() => {
    const textarea = messageInputRef.current;
    if (!textarea) return;
    textarea.style.height = 'auto';
    const styles = window.getComputedStyle(textarea);
    const lineHeight = Number.parseFloat(styles.lineHeight) || 22;
    const paddingY = Number.parseFloat(styles.paddingTop) + Number.parseFloat(styles.paddingBottom);
    const borderY = Number.parseFloat(styles.borderTopWidth) + Number.parseFloat(styles.borderBottomWidth);
    const maxHeight = Math.ceil(lineHeight * 4 + paddingY + borderY);
    const nextHeight = Math.min(textarea.scrollHeight, maxHeight);
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > maxHeight ? 'auto' : 'hidden';
  }, [message]);


  useEffect(() => {
    if (!pendingAutoTts || rehearsalStreaming) return;
    const lastTurn = turns[turns.length - 1];
    if (!lastTurn || lastTurn.speaker !== 'employee' || !lastTurn.text) return;
    tts.enqueueStreamText(String(lastTurn.text), true);
    setPendingAutoTts(false);
  }, [pendingAutoTts, rehearsalStreaming, turns, tts.enqueueStreamText]);

  const submit = async () => {
    if (asr.isRecording) await asr.stop();
    const text = message.trim();
    if (!text) return;
    setMessage('');
    tts.resetStream();
    setPendingAutoTts(true);
    await sendMessage(text, { inputMode: lastInputMode, audioEmotion: lastAudioEmotion });
    setLastAudioEmotion(null);
    setLastInputMode('text');
  };

  const applyContext = async () => {
    const note = runtimeNote.trim();
    if (!note) {
      showToast('请先输入新增信息或模拟要求。', 'error');
      return;
    }

    const updated = await updateRehearsalContext({ runtime_note: note });
    if (updated) {
      setRuntimeNote('');
      setContextOpen(false);
    }
  };

  const clearContext = async () => {
    const updated = await updateRehearsalContext({ clear_context: true });
    if (updated) setRuntimeNote('');
  };

  const finish = async () => {
    await endRehearsal();
    navigate('/app/report');
  };

  return (
    <section id="screen-rehearsal" className="screen active">
      <div className="page-intro compact-intro">
        <h1>对话预演</h1>
        <p>围绕当前员工、意图、人格与诉求进行绩效反馈练习。</p>
      </div>
      <div className="rehearsal-workbench">
        <section className="soft-card rehearsal-card">
          <div className="rehearsal-head">
            <div><span className="status-badge success">进行中</span><span className="muted rehearsal-subtitle">企业级对话工作台</span></div>
            <button className="btn btn-danger-ghost" onClick={finish}>结束预演</button>
          </div>
          <div className="chat-list" ref={chatListRef}>
            {!turns.length && <div className="chat-empty empty-state">输入第一句话开始预演。</div>}
            {turns.map((turn, index) => (
              <ChatMessage
                key={String(turn.metadata?.stream_id || turn.turn_index || `${turn.speaker}-${index}`)}
                turn={turn}
                employeeName={employeeName}
                onSpeak={(text) => void tts.play(text)}
                onStopSpeak={tts.stop}
                ttsBusy={tts.loading}
                ttsPlaying={tts.playing}
                ttsActiveText={tts.activeText}
                ttsDisplayText={tts.displayText}
                ttsDuration={tts.duration}
                isStreaming={Boolean(liveConversation && rehearsalStreaming && index === turns.length - 1 && turn.speaker === 'employee' && !turn.text)}
              />
            ))}
          </div>
          <div className="message-bar">
            <textarea
              ref={messageInputRef}
              value={message}
              onChange={(event) => {
                setMessage(event.target.value);
                if (!asr.isRecording) setLastInputMode('text');
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  if (!rehearsalStreaming) void submit();
                }
              }}
              placeholder="请输入你的回复..."
              rows={1}
            />
            <button
              className={`mic-button ${asr.isRecording ? 'recording' : ''} ${asr.isConnecting ? 'connecting' : ''}`}
              title={asr.isRecording ? '停止实时语音输入' : '开始实时语音输入'}
              aria-label={asr.isRecording ? '停止实时语音输入' : '开始实时语音输入'}
              type="button"
              disabled={rehearsalStreaming || asr.isConnecting}
              onClick={() => {
                if (asr.isRecording) void asr.stop();
                else void asr.start();
              }}
            >
              <span className="mic-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" focusable="false">
                  <path d="M12 3.75a3.25 3.25 0 0 0-3.25 3.25v4.1a3.25 3.25 0 0 0 6.5 0V7A3.25 3.25 0 0 0 12 3.75Z" />
                  <path d="M6.25 10.75a.75.75 0 0 1 1.5 0v.35a4.25 4.25 0 0 0 8.5 0v-.35a.75.75 0 0 1 1.5 0v.35a5.76 5.76 0 0 1-5 5.71v1.69h2.1a.75.75 0 0 1 0 1.5h-5.7a.75.75 0 0 1 0-1.5h2.1v-1.69a5.76 5.76 0 0 1-5-5.71v-.35Z" />
                </svg>
              </span>
            </button>
            <button className="btn btn-primary send-button" onClick={submit} disabled={rehearsalStreaming || asr.isConnecting}>{asr.isConnecting ? '连接中' : rehearsalStreaming ? '回复中' : '发送'}</button>
          </div>
          {asr.isRecording && <div className="asr-hint">正在实时识别语音，文字会同步进入输入框。</div>}
          {asr.isConnecting && <div className="asr-hint">正在连接实时语音识别服务...</div>}
          {tts.loading && <div className="asr-hint">正在生成员工回复语音...</div>}
          {tts.playing && <div className="asr-hint">正在播放员工回复。</div>}
          {asr.status === 'error' && asr.error && !isRecoverableAsrError(asr.error) && <div className="asr-hint error">{asr.error}</div>}
          {tts.status === 'error' && tts.error && <div className="asr-hint error">{tts.error}</div>}
        </section>

        <aside className="soft-card conversation-context-panel summary-panel">
          <h2>会话上下文</h2>
          <div className="context-facts">
            <div><span>当前员工</span><strong>{employeeName}</strong></div>
            <div><span>当前意图</span><strong>{intentName}</strong></div>
            <div><span>主诉求</span><strong>{primaryMotive?.name || session?.motivation?.primary_motive_id || '未设置'}</strong></div>
            <div><span>辅诉求</span><strong>{secondaryMotives.map((item) => item?.name || item?.id).join(' / ') || '未设置'}</strong></div>
            <div><span>总满足度</span><strong>{satisfaction}</strong></div>
            <div><span>当前情绪</span><strong>{emotionAnchor?.name || session?.emotion_state?.current_anchor_id || '未设置'}</strong></div>
            <div><span>动态设定</span><strong>{runtimeNotesCount ? `${runtimeNotesCount} 条` : '未追加'}</strong></div>
          </div>
          {personality && <div className="summary-block"><h3>人格倾向</h3><p>{personality}</p></div>}
          {vad && <div className="summary-block"><h3>VAD</h3><p>Valence {formatNumber(vad.valence)} / Arousal {formatNumber(vad.arousal)} / Dominance {formatNumber(vad.dominance)}</p></div>}
          {session?.emotion_state?.current_attitude && <EmotionBadge emotionState={session.emotion_state} />}
          {session?.motivation?.last_change_reason && <div className="summary-block"><h3>最近满足度变化</h3><p>{session.motivation.last_change_reason}</p></div>}
          {session?.emotion_state?.last_reason_summary && <div className="summary-block"><h3>最近情绪变化</h3><p>{session.emotion_state.last_reason_summary}</p></div>}
          <button className="btn btn-secondary" type="button" onClick={() => setContextOpen(true)}>调整动态信息</button>
        </aside>
      </div>

      <div className={`rehearsal-context-widget ${contextOpen ? 'open' : ''}`}>
        {contextOpen && (
          <div className="rehearsal-context-panel" role="dialog" aria-label="调整动态信息">
            <div className="context-panel-head">
              <div>
                <strong>调整动态信息</strong>
                <span>{runtimeNotesCount ? `已追加 ${runtimeNotesCount} 条动态信息` : '动态信息将在本次预演持续生效'}</span>
              </div>
              <button className="context-close" type="button" aria-label="关闭" onClick={() => setContextOpen(false)}>×</button>
            </div>
            <label className="context-field">
              <span>新增员工信息 / 临时事件 / 模拟要求</span>
              <textarea
                value={runtimeNote}
                onChange={(event) => setRuntimeNote(event.target.value)}
                disabled={rehearsalStreaming}
                placeholder="例如：员工刚知道奖金减少，对 PIP 很敏感；这轮希望员工更防御、更追问证据，不要太快让步。"
                rows={5}
              />
            </label>
            <div className="context-actions">
              <button className="btn btn-primary" type="button" onClick={applyContext} disabled={rehearsalStreaming}>应用到后续回复</button>
              <button className="btn btn-secondary" type="button" onClick={() => setRuntimeNote('')} disabled={rehearsalStreaming}>清空输入</button>
              <button className="btn btn-danger-ghost" type="button" onClick={clearContext} disabled={rehearsalStreaming}>清空动态设定</button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
