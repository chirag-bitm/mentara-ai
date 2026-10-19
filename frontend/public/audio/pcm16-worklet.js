class Pcm16WorkletProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const durationMs = options.processorOptions?.chunkDurationMs ?? 100;
    this.chunkSize = Math.max(128, Math.round((sampleRate * durationMs) / 1000));
    this.chunk = new Int16Array(this.chunkSize);
    this.offset = 0;
    this.energy = 0;
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel) return true;

    for (let index = 0; index < channel.length; index += 1) {
      const sample = Math.max(-1, Math.min(1, channel[index]));
      this.chunk[this.offset] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      this.energy += sample * sample;
      this.offset += 1;

      if (this.offset === this.chunkSize) {
        const output = this.chunk;
        const level = Math.min(1, Math.sqrt(this.energy / this.chunkSize) * 4);
        this.port.postMessage(
          { type: "audio", buffer: output.buffer, level },
          [output.buffer],
        );
        this.chunk = new Int16Array(this.chunkSize);
        this.offset = 0;
        this.energy = 0;
      }
    }

    return true;
  }
}

registerProcessor("pcm16-worklet", Pcm16WorkletProcessor);
