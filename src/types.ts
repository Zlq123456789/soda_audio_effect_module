/**
 * ByteDance / Soda Music Audio Effect Type Definitions
 */

export type AudioEffectConfig = string // JSON formatted DSP chain configuration

export interface WorkletInitData {
  wasmBinary: ArrayBuffer
}

export interface WorkletLoadConfigData {
  configJson: AudioEffectConfig
}

export interface WorkletSetEnabledData {
  enabled: boolean
}

export interface WorkletPrepareData {
  sampleRate: number
  channels: number
}

export type WorkletMessage =
  | { type: 'init'; data: WorkletInitData }
  | { type: 'loadConfig'; data: WorkletLoadConfigData }
  | { type: 'setEnabled'; data: WorkletSetEnabledData }
  | { type: 'prepare'; data: WorkletPrepareData }
  | { type: 'release' }

export type WorkletResponse =
  | { type: 'ready' }
  | { type: 'configLoaded' }
  | { type: 'prepared' }
  | { type: 'error'; error: string }

export interface DSPChainNode {
  name: string
  type: 'gain' | 'equalizer' | 'drc' | 'stereo_width' | 'fdn_reverb' | 'limiter_lookahead_sig' | string
  enable: boolean
  modes?: string[]
  [key: string]: any
}

export interface DSPChain {
  name: string
  enable: boolean
  modes: string[]
  nodes: DSPChainNode[]
  type: 'chain'
}

export interface DSPConfigSchema {
  name: string
  desc: string
  update_timestamp: number
  chains: DSPChain[]
}
