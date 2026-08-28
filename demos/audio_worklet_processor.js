/**
 * Soda Music ByteAudio DSP AudioWorklet Processor
 * Runs directly on the real-time Audio Thread for 0-latency, 0-crackle DSP playback
 */

const EFFECT_JSON_DIR = 0;
const EFFECT_PREPARE = 1;
const EFFECT_USING_EXTERNAL_RAW_BUFFER = 1;
const EFFECT_AUDIO_STREAMING = 0;

const BufferLayout = {
  data_ptr_off: 0,
  frame_num_off: 4,
  channel_num_off: 8,
  samplerate_off: 12,
  audio_type_off: 20,
  max_buf_bytes_off: 24,
};

class WasmEffectSdk {
  constructor() {
    this.module = null;
    this.handlePtr = 0;
    this.bufferPtr = 0;
    this.dataPtr = 0;
    this.maxBufBytes = 0;
    this.frameCap = 0;
    this.sampleRate = 44100;
    this.configLoaded = false;
  }

  get isReady() {
    return this.module !== null && this.handlePtr !== 0;
  }

  get isConfigLoaded() {
    return this.configLoaded;
  }

  async init(wasmBinary, wasmGlueFactory) {
    this.module = await wasmGlueFactory({ wasmBinary });

    const handlePtrPtr = this.module._malloc(4);
    this.module.HEAP32[handlePtrPtr >>> 2] = 0;

    const err = this.module._EffectCreate(handlePtrPtr);
    if (err !== 0) {
      throw new Error(`EffectCreate failed: ${err}`);
    }

    this.handlePtr = this.module.HEAP32[handlePtrPtr >>> 2] >>> 0;
    this.module._free(handlePtrPtr);

    if (!this.handlePtr) {
      throw new Error('EffectCreate returned null handle');
    }
  }

  loadConfig(configJson) {
    if (!this.module) throw new Error('WASM not initialized');

    if (this.handlePtr) {
      try { this.module._EffectRelease(this.handlePtr); } catch (e) {}
      this.handlePtr = 0;
    }

    const handlePtrPtr = this.module._malloc(4);
    this.module.HEAP32[handlePtrPtr >>> 2] = 0;
    const createErr = this.module._EffectCreate(handlePtrPtr);
    if (createErr !== 0) {
      this.module._free(handlePtrPtr);
      throw new Error(`EffectCreate failed: ${createErr}`);
    }
    this.handlePtr = this.module.HEAP32[handlePtrPtr >>> 2] >>> 0;
    this.module._free(handlePtrPtr);

    this.bufferPtr = 0;
    this.dataPtr = 0;
    this.maxBufBytes = 0;
    this.frameCap = 0;

    const enc = new TextEncoder();
    const b = enc.encode(configJson);
    const configCStr = this.module._malloc(b.length + 1);
    this.module.HEAPU8.set(b, configCStr);
    this.module.HEAPU8[configCStr + b.length] = 0;

    const err = this.module._EffectCommand(this.handlePtr, EFFECT_JSON_DIR, configCStr, -2);
    this.module._free(configCStr);

    if (err !== 0) throw new Error(`EffectCommand(JSON_DIR) failed: ${err}`);
    this.configLoaded = true;
  }

  prepare(sampleRate, channels) {
    if (!this.isReady) return;
    this.sampleRate = sampleRate;
    this.bufferPtr = 0;
    this.dataPtr = 0;
    this.maxBufBytes = 0;
    this.frameCap = 0;

    const prepareCtx = `${sampleRate},128,${channels}`;
    const enc = new TextEncoder();
    const b = enc.encode(prepareCtx);
    const prepCStr = this.module._malloc(b.length + 1);
    this.module.HEAPU8.set(b, prepCStr);
    this.module.HEAPU8[prepCStr + b.length] = 0;

    const err = this.module._EffectCommand(
      this.handlePtr,
      EFFECT_PREPARE,
      prepCStr,
      EFFECT_USING_EXTERNAL_RAW_BUFFER
    );
    this.module._free(prepCStr);

    if (err !== 0) throw new Error(`EffectCommand(PREPARE) failed: ${err}`);
  }

  process(inputs, outputs) {
    if (!this.isReady || !this.configLoaded) return false;

    const channels = Math.min(inputs.length, outputs.length);
    const frameCount = inputs[0]?.length ?? 0;
    if (frameCount === 0) return false;

    const needBytes = frameCount * channels * 4;

    if (!this.bufferPtr || this.frameCap < frameCount || (this.maxBufBytes > 0 && needBytes > this.maxBufBytes)) {
      this.bufferPtr = this.module._EffectGetProcessBuffer(this.handlePtr, frameCount, channels, 0);
      if (this.bufferPtr) {
        this.dataPtr = this.module.HEAP32[(this.bufferPtr + BufferLayout.data_ptr_off) >>> 2] >>> 0;
        this.maxBufBytes = this.module.HEAP32[(this.bufferPtr + BufferLayout.max_buf_bytes_off) >>> 2] | 0;
        this.frameCap = this.module.HEAP32[(this.bufferPtr + BufferLayout.frame_num_off) >>> 2] | 0;
      }
    }

    if (!this.bufferPtr || !this.dataPtr) return false;

    this.module.HEAP32[(this.bufferPtr + BufferLayout.audio_type_off) >>> 2] = EFFECT_AUDIO_STREAMING;
    this.module.HEAP32[(this.bufferPtr + BufferLayout.channel_num_off) >>> 2] = channels;
    this.module.HEAP32[(this.bufferPtr + BufferLayout.samplerate_off) >>> 2] = this.sampleRate;
    this.module.HEAP32[(this.bufferPtr + BufferLayout.frame_num_off) >>> 2] = frameCount;

    const dataOffset = this.dataPtr >>> 2;
    for (let i = 0; i < frameCount; i++) {
      for (let ch = 0; ch < channels; ch++) {
        this.module.HEAPF32[dataOffset + i * channels + ch] = inputs[ch]?.[i] ?? 0;
      }
    }

    const err = this.module._EffectProcessBuffer(this.handlePtr, this.bufferPtr);
    if (err === 0) {
      for (let i = 0; i < frameCount; i++) {
        for (let ch = 0; ch < channels; ch++) {
          if (outputs[ch]) {
            outputs[ch][i] = this.module.HEAPF32[dataOffset + i * channels + ch];
          }
        }
      }
      return true;
    }
    return false;
  }

  release() {
    if (this.handlePtr && this.module) {
      try { this.module._EffectRelease(this.handlePtr); } catch (e) {}
      this.handlePtr = 0;
    }
    this.configLoaded = false;
  }
}

class AudioEffectProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.sdk = new WasmEffectSdk();
    this.effectEnabled = true;
    this.port.onmessage = this.handleMessage.bind(this);
  }

  async handleMessage(event) {
    const message = event.data;
    switch (message.type) {
      case 'init':
        try {
          const factory = new Function(message.data.wasmGlueCode + '; return ByteAudioTunerWasm;')();
          await this.sdk.init(message.data.wasmBinary, factory);
          this.port.postMessage({ type: 'ready' });
        } catch (err) {
          this.port.postMessage({ type: 'error', error: err.message || String(err) });
        }
        break;

      case 'loadConfig':
        try {
          this.sdk.loadConfig(message.data.configJson);
          this.port.postMessage({ type: 'configLoaded' });
        } catch (err) {
          this.port.postMessage({ type: 'error', error: err.message || String(err) });
        }
        break;

      case 'setEnabled':
        this.effectEnabled = message.data.enabled;
        break;

      case 'prepare':
        try {
          this.sdk.prepare(message.data.sampleRate, message.data.channels);
          this.port.postMessage({ type: 'prepared' });
        } catch (err) {
          this.port.postMessage({ type: 'error', error: err.message || String(err) });
        }
        break;

      case 'release':
        this.sdk.release();
        break;
    }
  }

  process(inputs, outputs) {
    const input = inputs[0];
    const output = outputs[0];

    if (!input || !input.length || !output || !output.length) {
      return true;
    }

    if (!this.effectEnabled || !this.sdk.isReady || !this.sdk.isConfigLoaded) {
      for (let ch = 0; ch < Math.min(input.length, output.length); ch++) {
        if (input[ch] && output[ch]) {
          output[ch].set(input[ch]);
        }
      }
      return true;
    }

    const success = this.sdk.process(input, output);
    if (!success) {
      for (let ch = 0; ch < Math.min(input.length, output.length); ch++) {
        if (input[ch] && output[ch]) {
          output[ch].set(input[ch]);
        }
      }
    }
    return true;
  }
}

registerProcessor('audio-effect-processor', AudioEffectProcessor);
