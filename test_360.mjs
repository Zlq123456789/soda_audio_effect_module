
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const wasmPath = path.join(__dirname, 'wasm', 'byte_audio_tuner_wasm.wasm');
const ByteAudioTunerWasm = (await import('file:///C:/Users/zlq/.gemini/antigravity/scratch/soda_audio_effect_module/wasm/byte_audio_tuner_wasm.mjs')).default;

console.log("Loading WASM...");
const wasmBinary = fs.readFileSync(wasmPath);
const module = await ByteAudioTunerWasm({ wasmBinary });
console.log("WASM Loaded!");

const configJson = fs.readFileSync(path.join(__dirname, 'presets', '2_surround_360.json'), 'utf-8');

const sampleRate = 48000;
const handlePtrPtr = module._malloc(4);
module.HEAP32[handlePtrPtr >>> 2] = 0;
const createErr = module._EffectCreate(handlePtrPtr);
console.log("EffectCreate result:", createErr);
const effectHandle = module.HEAP32[handlePtrPtr >>> 2] >>> 0;
module._free(handlePtrPtr);

const enc = new TextEncoder();
const b = enc.encode(configJson);
const configCStr = module._malloc(b.length + 1);
module.HEAPU8.set(b, configCStr);
module.HEAPU8[configCStr + b.length] = 0;

const cmdErr = module._EffectCommand(effectHandle, 0, configCStr, -2);
module._free(configCStr);
console.log("EffectCommand(JSON) result:", cmdErr);

const prepStr = `${sampleRate},128,2`;
const pBytes = enc.encode(prepStr);
const pCStr = module._malloc(pBytes.length + 1);
module.HEAPU8.set(pBytes, pCStr);
module.HEAPU8[pCStr + pBytes.length] = 0;

const prepErr = module._EffectCommand(effectHandle, 1, pCStr, 1);
module._free(pCStr);
console.log("EffectCommand(PREPARE) result:", prepErr);

// Now test processing 100 buffers of 1024 frames (128 chunk frames)
const chunkFrames = 128;
const totalFrames = 1024;
const floatCount = totalFrames * 2;
const inFloats = new Float32Array(floatCount).fill(0.1);
const outFloats = new Float32Array(floatCount);

const BufferLayout = {
  data_ptr_off: 0,
  frame_num_off: 4,
  channel_num_off: 8,
  samplerate_off: 12,
  audio_type_off: 20,
  max_buf_bytes_off: 24,
};

const bufferPtr = module._EffectGetProcessBuffer(effectHandle, chunkFrames, 2, 0);
console.log("bufferPtr:", bufferPtr);
const dataPtr = module.HEAP32[(bufferPtr + BufferLayout.data_ptr_off) >>> 2] >>> 0;
console.log("dataPtr:", dataPtr);

module.HEAP32[(bufferPtr + BufferLayout.audio_type_off) >>> 2] = 0;
module.HEAP32[(bufferPtr + BufferLayout.channel_num_off) >>> 2] = 2;
module.HEAP32[(bufferPtr + BufferLayout.samplerate_off) >>> 2] = sampleRate;
module.HEAP32[(bufferPtr + BufferLayout.frame_num_off) >>> 2] = chunkFrames;

const dataOffset = dataPtr >>> 2;

for (let frame = 0; frame < 50; frame++) {
  for (let offset = 0; offset < totalFrames; offset += chunkFrames) {
    const count = Math.min(chunkFrames, totalFrames - offset);
    for (let i = 0; i < count; i++) {
      module.HEAPF32[dataOffset + i * 2 + 0] = inFloats[(offset + i) * 2 + 0] || 0;
      module.HEAPF32[dataOffset + i * 2 + 1] = inFloats[(offset + i) * 2 + 1] || 0;
    }

    const err = module._EffectProcessBuffer(effectHandle, bufferPtr);
    if (err !== 0) {
      console.error("ProcessBuffer returned error:", err, "at frame", frame);
    }
  }
}

console.log("360 Surround 50 buffers processed successfully without crashing!");
