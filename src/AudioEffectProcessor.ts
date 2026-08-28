import type { WorkletMessage, WorkletResponse } from './types'
import { WasmEffectSdk } from './WasmEffectSdk'

class AudioEffectProcessor extends AudioWorkletProcessor {
  private sdk = new WasmEffectSdk()
  private effectEnabled = true

  constructor() {
    super()
    this.port.onmessage = this.handleMessage.bind(this)
  }

  private async handleMessage(event: MessageEvent<WorkletMessage>): Promise<void> {
    const message = event.data

    switch (message.type) {
      case 'init':
        try {
          await this.sdk.init(message.data.wasmBinary)
          this.postResponse({ type: 'ready' })
        } catch (err: any) {
          this.postResponse({ type: 'error', error: err.message || String(err) })
        }
        break

      case 'loadConfig':
        try {
          this.sdk.loadConfig(message.data.configJson)
          this.postResponse({ type: 'configLoaded' })
        } catch (err: any) {
          this.postResponse({ type: 'error', error: err.message || String(err) })
        }
        break

      case 'setEnabled':
        this.effectEnabled = message.data.enabled
        break

      case 'prepare':
        try {
          this.sdk.prepare(message.data.sampleRate, message.data.channels)
          this.postResponse({ type: 'prepared' })
        } catch (err: any) {
          this.postResponse({ type: 'error', error: err.message || String(err) })
        }
        break

      case 'release':
        this.sdk.release()
        break
    }
  }

  private postResponse(response: WorkletResponse): void {
    this.port.postMessage(response)
  }

  process(inputs: Float32Array[][], outputs: Float32Array[][]): boolean {
    const input = inputs[0]
    const output = outputs[0]

    if (!input?.length || !output?.length) {
      return true
    }

    if (!this.effectEnabled || !this.sdk.isReady || !this.sdk.isConfigLoaded) {
      for (let ch = 0; ch < Math.min(input.length, output.length); ch++) {
        if (input[ch] && output[ch]) {
          output[ch].set(input[ch])
        }
      }
      return true
    }

    const success = this.sdk.process(input, output)

    if (!success) {
      for (let ch = 0; ch < Math.min(input.length, output.length); ch++) {
        if (input[ch] && output[ch]) {
          output[ch].set(input[ch])
        }
      }
    }

    return true
  }
}

registerProcessor('audio-effect-processor', AudioEffectProcessor)
