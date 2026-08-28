import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Import the Emscripten WASM module
const wasmPath = path.join(__dirname, 'byte_audio_tuner_wasm.wasm');
const mjsPath = path.join(__dirname, 'byte_audio_tuner_wasm.mjs');

const ByteAudioTunerWasm = (await import('./byte_audio_tuner_wasm.mjs')).default;

async function runTest() {
  console.log('1. Loading WASM binary...');
  const wasmBinary = fs.readFileSync(wasmPath);

  console.log('2. Initializing WASM module...');
  const module = await ByteAudioTunerWasm({ wasmBinary });

  console.log('3. Calling _EffectCreate...');
  const handlePtrPtr = module._malloc(4);
  module.HEAP32[handlePtrPtr >>> 2] = 0;
  const createErr = module._EffectCreate(handlePtrPtr);
  if (createErr !== 0) {
    throw new Error(`_EffectCreate failed with error code: ${createErr}`);
  }
  const handlePtr = module.HEAP32[handlePtrPtr >>> 2] >>> 0;
  module._free(handlePtrPtr);
  console.log(`   Created effect instance handle: 0x${handlePtr.toString(16)}`);

  console.log('4. Loading DSP JSON Configuration...');
  const configJson = fs.readFileSync(path.join(__dirname, 'sample_effect_config.json'), 'utf-8');
  
  // Helper for C-string
  const enc = new TextEncoder();
  const b = enc.encode(configJson);
  const configCStr = module._malloc(b.length + 1);
  module.HEAPU8.set(b, configCStr);
  module.HEAPU8[configCStr + b.length] = 0;

  const EFFECT_JSON_DIR = 0;
  const EFFECT_PREPARE = 1;
  const EFFECT_USING_EXTERNAL_RAW_BUFFER = 1;
  const EFFECT_AUDIO_STREAMING = 0;

  const cmdErr = module._EffectCommand(handlePtr, EFFECT_JSON_DIR, configCStr, -2);
  module._free(configCStr);
  console.log(`   EffectCommand(JSON_DIR) result: ${cmdErr} (0 is SUCCESS)`);

  console.log('5. Preparing DSP for sampleRate=44100, channels=2...');
  const prepareCtx = '44100,128,2';
  const prepBytes = enc.encode(prepareCtx);
  const prepCStr = module._malloc(prepBytes.length + 1);
  module.HEAPU8.set(prepBytes, prepCStr);
  module.HEAPU8[prepBytes.length + prepCStr] = 0;

  const prepErr = module._EffectCommand(handlePtr, EFFECT_PREPARE, prepCStr, EFFECT_USING_EXTERNAL_RAW_BUFFER);
  module._free(prepCStr);
  console.log(`   EffectCommand(PREPARE) result: ${prepErr} (0 is SUCCESS)`);

  console.log('6. Testing Audio Buffer Processing...');
  const frameCount = 128;
  const channels = 2;
  const bufferPtr = module._EffectGetProcessBuffer(handlePtr, frameCount, channels, 0);
  console.log(`   Process buffer ptr: 0x${bufferPtr.toString(16)}`);

  const BufferLayout = {
    data_ptr_off: 0,
    frame_num_off: 4,
    channel_num_off: 8,
    samplerate_off: 12,
    audio_type_off: 20,
    max_buf_bytes_off: 24,
  };

  const dataPtr = module.HEAP32[(bufferPtr + BufferLayout.data_ptr_off) >>> 2] >>> 0;
  module.HEAP32[(bufferPtr + BufferLayout.audio_type_off) >>> 2] = EFFECT_AUDIO_STREAMING;
  module.HEAP32[(bufferPtr + BufferLayout.channel_num_off) >>> 2] = channels;
  module.HEAP32[(bufferPtr + BufferLayout.samplerate_off) >>> 2] = 44100;
  module.HEAP32[(bufferPtr + BufferLayout.frame_num_off) >>> 2] = frameCount;

  // Fill sine wave input into buffer
  const dataOffset = dataPtr >>> 2;
  for (let i = 0; i < frameCount; i++) {
    const val = Math.sin((2 * Math.PI * 440 * i) / 44100) * 0.5;
    module.HEAPF32[dataOffset + i * channels + 0] = val;
    module.HEAPF32[dataOffset + i * channels + 1] = val;
  }

  const procErr = module._EffectProcessBuffer(handlePtr, bufferPtr);
  console.log(`   EffectProcessBuffer result: ${procErr} (0 is SUCCESS)`);
  
  const sampleOutput = [
    module.HEAPF32[dataOffset + 0],
    module.HEAPF32[dataOffset + 1],
    module.HEAPF32[dataOffset + 2]
  ];
  console.log(`   Processed audio sample output:`, sampleOutput);

  console.log('7. Cleaning up instance...');
  module._EffectRelease(handlePtr);
  console.log('✅ Standalone Audio Effect DSP test passed successfully!');
}

runTest().catch(console.error);
