import ByteAudioTunerWasm from '../wasm/byte_audio_tuner_wasm.mjs'

const EFFECT_JSON_DIR = 0
const EFFECT_PREPARE = 1
const EFFECT_USING_EXTERNAL_RAW_BUFFER = 1
const EFFECT_AUDIO_STREAMING = 0

const BufferLayout = {
  data_ptr_off: 0,
  frame_num_off: 4,
  channel_num_off: 8,
  samplerate_off: 12,
  audio_type_off: 20,
  max_buf_bytes_off: 24,
}

export class WasmEffectSdk {
  private module: any = null
  private handlePtr = 0
  private bufferPtr = 0
  private dataPtr = 0
  private maxBufBytes = 0
  private frameCap = 0
  private sampleRate = 44100
  private configLoaded = false

  get isReady(): boolean {
    return this.module !== null && this.handlePtr !== 0
  }

  get isConfigLoaded(): boolean {
    return this.configLoaded
  }

  async init(wasmBinary: ArrayBuffer): Promise<void> {
    this.module = await ByteAudioTunerWasm({ wasmBinary })

    const handlePtrPtr = this.module._malloc(4)
    this.module.HEAP32[handlePtrPtr >>> 2] = 0

    const err = this.module._EffectCreate(handlePtrPtr)
    if (err !== 0) {
      throw new Error(`EffectCreate failed: ${err}`)
    }

    this.handlePtr = this.module.HEAP32[handlePtrPtr >>> 2] >>> 0
    this.module._free(handlePtrPtr)

    if (!this.handlePtr) {
      throw new Error('EffectCreate returned null handle')
    }
  }

  loadConfig(configJson: string): void {
    if (!this.module) {
      throw new Error('WASM not initialized')
    }

    if (this.handlePtr) {
      try {
        this.module._EffectRelease(this.handlePtr)
      } catch {}
      this.handlePtr = 0
    }

    const handlePtrPtr = this.module._malloc(4)
    this.module.HEAP32[handlePtrPtr >>> 2] = 0
    const createErr = this.module._EffectCreate(handlePtrPtr)
    if (createErr !== 0) {
      this.module._free(handlePtrPtr)
      throw new Error(`EffectCreate failed: ${createErr}`)
    }
    this.handlePtr = this.module.HEAP32[handlePtrPtr >>> 2] >>> 0
    this.module._free(handlePtrPtr)

    if (!this.handlePtr) {
      throw new Error('EffectCreate returned null handle')
    }

    this.bufferPtr = 0
    this.dataPtr = 0
    this.maxBufBytes = 0
    this.frameCap = 0

    const configCStr = this.mallocCString(configJson)
    const err = this.module._EffectCommand(this.handlePtr, EFFECT_JSON_DIR, configCStr, -2)
    this.module._free(configCStr)

    if (err !== 0) {
      throw new Error(`EffectCommand(JSON_DIR) failed: ${err}`)
    }

    this.configLoaded = true
  }

  prepare(sampleRate: number, channels: number): void {
    if (!this.isReady) return

    this.sampleRate = sampleRate
    this.bufferPtr = 0
    this.dataPtr = 0
    this.maxBufBytes = 0
    this.frameCap = 0

    const prepareCtx = `${sampleRate},128,${channels}`
    const prepareCStr = this.mallocCString(prepareCtx)

    const err = this.module._EffectCommand(
      this.handlePtr,
      EFFECT_PREPARE,
      prepareCStr,
      EFFECT_USING_EXTERNAL_RAW_BUFFER,
    )
    this.module._free(prepareCStr)

    if (err !== 0) {
      throw new Error(`EffectCommand(PREPARE) failed: ${err}`)
    }
  }

  process(inputs: Float32Array[], outputs: Float32Array[]): boolean {
    if (!this.isReady || !this.configLoaded) {
      return false
    }

    const channels = Math.min(inputs.length, outputs.length)
    const frameCount = inputs[0]?.length ?? 0

    if (frameCount === 0) return false

    const needBytes = frameCount * channels * 4

    if (!this.bufferPtr) {
      this.bufferPtr = this.module._EffectGetProcessBuffer(this.handlePtr, frameCount, channels, 0)
      if (this.bufferPtr) {
        this.dataPtr = this.module.HEAP32[(this.bufferPtr + BufferLayout.data_ptr_off) >>> 2] >>> 0
        this.maxBufBytes = this.module.HEAP32[(this.bufferPtr + BufferLayout.max_buf_bytes_off) >>> 2] | 0
        this.frameCap = this.module.HEAP32[(this.bufferPtr + BufferLayout.frame_num_off) >>> 2] | 0
      }
    }

    if (!this.bufferPtr || !this.dataPtr) return false

    if (this.frameCap < frameCount || (this.maxBufBytes > 0 && needBytes > this.maxBufBytes)) {
      this.bufferPtr = this.module._EffectGetProcessBuffer(this.handlePtr, frameCount, channels, 0)
      if (this.bufferPtr) {
        this.dataPtr = this.module.HEAP32[(this.bufferPtr + BufferLayout.data_ptr_off) >>> 2] >>> 0
        this.maxBufBytes = this.module.HEAP32[(this.bufferPtr + BufferLayout.max_buf_bytes_off) >>> 2] | 0
        this.frameCap = this.module.HEAP32[(this.bufferPtr + BufferLayout.frame_num_off) >>> 2] | 0
      }
    }

    this.module.HEAP32[(this.bufferPtr + BufferLayout.audio_type_off) >>> 2] = EFFECT_AUDIO_STREAMING
    this.module.HEAP32[(this.bufferPtr + BufferLayout.channel_num_off) >>> 2] = channels
    this.module.HEAP32[(this.bufferPtr + BufferLayout.samplerate_off) >>> 2] = this.sampleRate
    this.module.HEAP32[(this.bufferPtr + BufferLayout.frame_num_off) >>> 2] = frameCount

    const dataOffset = this.dataPtr >>> 2
    for (let i = 0; i < frameCount; i++) {
      for (let ch = 0; ch < channels; ch++) {
        this.module.HEAPF32[dataOffset + i * channels + ch] = inputs[ch]?.[i] ?? 0
      }
    }

    const err = this.module._EffectProcessBuffer(this.handlePtr, this.bufferPtr)

    if (err === 0) {
      for (let i = 0; i < frameCount; i++) {
        for (let ch = 0; ch < channels; ch++) {
          if (outputs[ch]) {
            outputs[ch][i] = this.module.HEAPF32[dataOffset + i * channels + ch]
          }
        }
      }
      return true
    }

    return false
  }

  release(): void {
    if (this.handlePtr && this.module) {
      try {
        this.module._EffectRelease(this.handlePtr)
      } catch {}
      this.handlePtr = 0
    }
    this.configLoaded = false
  }

  private mallocCString(s: string): number {
    const enc = new TextEncoder()
    const b = enc.encode(s)
    const p = this.module._malloc(b.length + 1)
    this.module.HEAPU8.set(b, p)
    this.module.HEAPU8[p + b.length] = 0
    return p
  }
}
