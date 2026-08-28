import type { AudioEffectConfig, WorkletResponse } from './types'

export interface AudioContextManagerLike {
  getAudioContext(): AudioContext
  insertEffectNode(node: AudioNode | null): void
}

export class AudioEffectManager {
  private workletNode: AudioWorkletNode | null = null
  private currentConfig: AudioEffectConfig | null = null
  private initPromise: Promise<void>

  constructor(
    private contextManager: AudioContextManagerLike,
    private processorUrl: string,
    private wasmUrl: string
  ) {
    this.initPromise = this.doInitWorklet()
  }

  async setConfig(config: AudioEffectConfig | null): Promise<void> {
    if (this.currentConfig === config) {
      return
    }

    this.currentConfig = config
    await this.initPromise

    if (config === null) {
      this.contextManager.insertEffectNode(null)
      if (this.workletNode) {
        this.workletNode.port.postMessage({ type: 'setEnabled', data: { enabled: false } })
      }
      return
    }

    this.applyConfig(config)
  }

  private applyConfig(config: AudioEffectConfig): void {
    if (!this.workletNode) return

    const audioContext = this.contextManager.getAudioContext()

    this.workletNode.port.postMessage({ type: 'loadConfig', data: { configJson: config } })
    this.workletNode.port.postMessage({
      type: 'prepare',
      data: {
        sampleRate: audioContext.sampleRate,
        channels: audioContext.destination.maxChannelCount || 2,
      },
    })
    this.workletNode.port.postMessage({ type: 'setEnabled', data: { enabled: true } })
    this.contextManager.insertEffectNode(this.workletNode)
  }

  getWorkletNode(): AudioWorkletNode | null {
    return this.workletNode
  }

  getCurrentConfig(): AudioEffectConfig | null {
    return this.currentConfig
  }

  private async doInitWorklet(): Promise<void> {
    const audioContext = this.contextManager.getAudioContext()

    try {
      const [, wasmBinary] = await Promise.all([
        audioContext.audioWorklet.addModule(this.processorUrl),
        fetch(this.wasmUrl).then(res => res.arrayBuffer()),
      ])

      this.workletNode = new AudioWorkletNode(audioContext, 'audio-effect-processor', {
        numberOfInputs: 1,
        numberOfOutputs: 1,
      })

      await new Promise<void>((resolve, reject) => {
        const timeout = setTimeout(() => {
          reject(new Error('AudioWorklet initialization timeout'))
        }, 10000)

        this.workletNode!.port.onmessage = (event: MessageEvent<WorkletResponse>) => {
          const response = event.data

          if (response.type === 'ready') {
            clearTimeout(timeout)
            resolve()
          } else if (response.type === 'error') {
            clearTimeout(timeout)
            reject(new Error(response.error))
          }
        }

        this.workletNode!.port.postMessage({ type: 'init', data: { wasmBinary } }, [wasmBinary])
      })
    } catch (error) {
      console.error('Failed to initialize AudioWorklet:', error)
      throw error
    }
  }
}
