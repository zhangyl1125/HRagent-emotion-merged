class AsrPcmWorkletProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetSampleRate = 16000;
    this.buffer = [];
    this.inputSampleRate = sampleRate;
    this.ratio = this.inputSampleRate / this.targetSampleRate;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;

    const channel = input[0];
    for (let i = 0; i < channel.length; i += this.ratio) {
      const idx = Math.floor(i);
      const sample = Math.max(-1, Math.min(1, channel[idx] || 0));
      const int16 = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      this.buffer.push(int16 | 0);
    }

    if (this.buffer.length >= 800) {
      const samples = this.buffer.splice(0, 800);
      const pcm = new Int16Array(samples.length);
      for (let i = 0; i < samples.length; i += 1) {
        pcm[i] = samples[i];
      }
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
    }

    return true;
  }
}

registerProcessor('asr-pcm-worklet', AsrPcmWorkletProcessor);
