.chat-item {
  display: flex;
  flex-direction: column;
  margin: 18px 24px;
}

.chat-item.left {
  align-items: flex-start;
}

.chat-item.right {
  align-items: flex-end;
}

.voice-bubble {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 120px;
  max-width: 220px;
  height: 54px;
  padding: 0 18px;
  border-radius: 22px;
  font-size: 18px;
  font-weight: 600;
}

.left .voice-bubble {
  background: #f4f3fa;
  color: #333;
}

.right .voice-bubble {
  background: #6c3df4;
  color: #fff;
  border-bottom-right-radius: 6px;
}

.play-btn {
  width: 0;
  height: 0;
  border-left: 13px solid currentColor;
  border-top: 9px solid transparent;
  border-bottom: 9px solid transparent;
}

.pause-btn {
  width: 16px;
  height: 20px;
  border-left: 6px solid currentColor;
  border-right: 6px solid currentColor;
}

.wave {
  display: flex;
  align-items: center;
  gap: 3px;
}

.wave span {
  width: 3px;
  border-radius: 999px;
  background: currentColor;
}

.wave span:nth-child(1) { height: 12px; }
.wave span:nth-child(2) { height: 20px; }
.wave span:nth-child(3) { height: 28px; }
.wave span:nth-child(4) { height: 18px; }
.wave span:nth-child(5) { height: 24px; }

.voice-text {
  margin-top: 10px;
  max-width: 86%;
  padding: 16px 18px;
  border-radius: 20px;
  font-size: 17px;
  line-height: 1.7;
  color: #8a8a96;
  background: #f4f3fa;
}

.left .voice-text {
  border-top-left-radius: 6px;
}

.right .voice-text {
  background: #efe9ff;
  color: #6c3df4;
  border-top-right-radius: 6px;
}

.voice-actions {
  margin-top: 8px;
  display: flex;
  gap: 16px;
  font-size: 14px;
  color: #6c3df4;
}

.voice-actions button {
  border: none;
  background: transparent;
  color: inherit;
  font-size: inherit;
  padding: 0;
}