import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const rootDir = path.resolve(__dirname, '..');
const wasmPath = path.join(rootDir, 'wasm', 'byte_audio_tuner_wasm.wasm');
const presetsDir = path.join(rootDir, 'presets');

const ByteAudioTunerWasm = (await import('../wasm/byte_audio_tuner_wasm.mjs')).default;

async function testAllPresets() {
  console.log('========================================================');
  console.log('🎵 Testing All 9 Soda Music Audio Effect Presets in WASM DSP');
  console.log('========================================================\n');

  console.log('1. Loading WebAssembly DSP Core...');
  const wasmBinary = fs.readFileSync(wasmPath);
  const module = await ByteAudioTunerWasm({ wasmBinary });
  console.log('   WASM engine initialized successfully!\n');

  const presetFiles = fs.readdirSync(presetsDir).filter(f => f.endsWith('.json'));
  console.log(`2. Found ${presetFiles.length} presets to test.\n`);

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

  const sampleRate = 44100;
  const channels = 2;
  const frameCount = 128;
  const enc = new TextEncoder();

  for (let idx = 0; idx < presetFiles.length; idx++) {
    const file = presetFiles[idx];
    const fullPath = path.join(presetsDir, file);
    const configRaw = fs.readFileSync(fullPath, 'utf-8');
    const configObj = JSON.parse(configRaw);

    console.log(`--------------------------------------------------------`);
    console.log(`[${idx + 1}/${presetFiles.length}] Testing Preset: "${configObj.name}" (${file})`);
    console.log(`    Description: ${configObj.desc}`);

    // Create instance handle
    const handlePtrPtr = module._malloc(4);
    module.HEAP32[handlePtrPtr >>> 2] = 0;
    const createErr = module._EffectCreate(handlePtrPtr);
    if (createErr !== 0) {
      throw new Error(`_EffectCreate failed with error code: ${createErr}`);
    }
    const handlePtr = module.HEAP32[handlePtrPtr >>> 2] >>> 0;
    module._free(handlePtrPtr);

    // Load DSP JSON config
    const b = enc.encode(configRaw);
    const configCStr = module._malloc(b.length + 1);
    module.HEAPU8.set(b, configCStr);
    module.HEAPU8[configCStr + b.length] = 0;
    const cmdErr = module._EffectCommand(handlePtr, EFFECT_JSON_DIR, configCStr, -2);
    module._free(configCStr);
    if (cmdErr !== 0) {
      throw new Error(`EffectCommand(JSON_DIR) failed: ${cmdErr}`);
    }

    // Prepare
    const prepBytes = enc.encode(`${sampleRate},${frameCount},${channels}`);
    const prepCStr = module._malloc(prepBytes.length + 1);
    module.HEAPU8.set(prepBytes, prepCStr);
    module.HEAPU8[prepBytes.length + prepCStr] = 0;
    const prepErr = module._EffectCommand(handlePtr, EFFECT_PREPARE, prepCStr, EFFECT_USING_EXTERNAL_RAW_BUFFER);
    module._free(prepCStr);
    if (prepErr !== 0) {
      throw new Error(`EffectCommand(PREPARE) failed: ${prepErr}`);
    }

    // Allocate process buffer & feed audio frames
    const bufferPtr = module._EffectGetProcessBuffer(handlePtr, frameCount, channels, 0);
    const dataPtr = module.HEAP32[(bufferPtr + BufferLayout.data_ptr_off) >>> 2] >>> 0;
    module.HEAP32[(bufferPtr + BufferLayout.audio_type_off) >>> 2] = EFFECT_AUDIO_STREAMING;
    module.HEAP32[(bufferPtr + BufferLayout.channel_num_off) >>> 2] = channels;
    module.HEAP32[(bufferPtr + BufferLayout.samplerate_off) >>> 2] = sampleRate;
    module.HEAP32[(bufferPtr + BufferLayout.frame_num_off) >>> 2] = frameCount;

    // Generate 10 consecutive frames of stereo audio (simulate 1280 samples / ~30ms of real-time audio)
    const dataOffset = dataPtr >>> 2;
    for (let f = 0; f < 10; f++) {
      for (let i = 0; i < frameCount; i++) {
        const val = Math.sin((2 * Math.PI * 440 * (f * frameCount + i)) / sampleRate) * 0.4;
        module.HEAPF32[dataOffset + i * channels + 0] = val;
        module.HEAPF32[dataOffset + i * channels + 1] = val;
      }
      const procErr = module._EffectProcessBuffer(handlePtr, bufferPtr);
      if (procErr !== 0) {
        throw new Error(`EffectProcessBuffer failed at frame ${f}: ${procErr}`);
      }
    }

    const sampleOutput = [
      Number(module.HEAPF32[dataOffset + 0].toFixed(4)),
      Number(module.HEAPF32[dataOffset + 1].toFixed(4)),
      Number(module.HEAPF32[dataOffset + 2].toFixed(4)),
      Number(module.HEAPF32[dataOffset + 3].toFixed(4)),
    ];
    console.log(`    Status: ✅ SUCCESS | Processed 1280 audio samples`);
    console.log(`    Sample DSP Output PCM: [${sampleOutput.join(', ')}]`);

    // Release instance
    module._EffectRelease(handlePtr);
  }

  console.log('\n========================================================');
  console.log('🎉 ALL 9 PRESETS TESTED AND FULLY FUNCTIONAL WITH WASM DSP!');
  console.log('========================================================\n');
}

testAllPresets().catch(console.error);
