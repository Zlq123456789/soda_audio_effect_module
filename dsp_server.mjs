import net from 'net';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

process.on('uncaughtException', (err) => {
  console.error("DSP Server Uncaught Exception:", err);
});
process.on('unhandledRejection', (reason, promise) => {
  console.error("DSP Server Unhandled Rejection:", reason);
});

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const wasmPath = path.join(__dirname, 'wasm', 'byte_audio_tuner_wasm.wasm');
import { pathToFileURL } from 'url';
const wasmMjsPath = path.join(__dirname, 'wasm', 'byte_audio_tuner_wasm.mjs');
const ByteAudioTunerWasm = (await import(pathToFileURL(wasmMjsPath).href)).default;

console.log("Loading WASM DSP core...");
const wasmBinary = fs.readFileSync(wasmPath);
const module = await ByteAudioTunerWasm({ wasmBinary });
console.log("WASM DSP core initialized!");

let effectHandle1 = 0;
let effectHandle2 = 0;
let currentSampleRate = 48000;
let currentIntensity = 100;
let isSwitching = false;

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

function createSingleHandle(configStr, sampleRate) {
  const handlePtrPtr = module._malloc(4);
  module.HEAP32[handlePtrPtr >>> 2] = 0;
  const createErr = module._EffectCreate(handlePtrPtr);
  if (createErr !== 0) {
    module._free(handlePtrPtr);
    console.error("EffectCreate failed:", createErr);
    return 0;
  }
  const handle = module.HEAP32[handlePtrPtr >>> 2] >>> 0;
  module._free(handlePtrPtr);

  const enc = new TextEncoder();
  const b = enc.encode(configStr);
  const configCStr = module._malloc(b.length + 1);
  module.HEAPU8.set(b, configCStr);
  module.HEAPU8[configCStr + b.length] = 0;

  const cmdErr = module._EffectCommand(handle, EFFECT_JSON_DIR, configCStr, -2);
  module._free(configCStr);
  if (cmdErr !== 0) {
    console.error("EffectCommand(JSON) failed:", cmdErr);
    try { module._EffectRelease(handle); } catch (e) {}
    return 0;
  }

  const prepStr = `${sampleRate},128,2`;
  const pBytes = enc.encode(prepStr);
  const pCStr = module._malloc(pBytes.length + 1);
  module.HEAPU8.set(pBytes, pCStr);
  module.HEAPU8[pCStr + pBytes.length] = 0;

  const prepErr = module._EffectCommand(handle, EFFECT_PREPARE, pCStr, EFFECT_USING_EXTERNAL_RAW_BUFFER);
  module._free(pCStr);
  if (prepErr !== 0) {
    console.error("EffectCommand(PREPARE) failed:", prepErr);
    try { module._EffectRelease(handle); } catch (e) {}
    return 0;
  }

  return handle;
}

function releaseHandle(handle) {
  if (handle) {
    try { module._EffectRelease(handle); } catch (e) {}
  }
}

function loadEffect(configJson, sampleRate = 48000, intensity = 100) {
  isSwitching = true;
  try {
    currentSampleRate = sampleRate;
    if (typeof intensity === 'number' && Number.isFinite(intensity)) {
      currentIntensity = intensity;
    }

    if (effectHandle1) {
      releaseHandle(effectHandle1);
      effectHandle1 = 0;
    }
    if (effectHandle2) {
      releaseHandle(effectHandle2);
      effectHandle2 = 0;
    }

    if (!configJson) {
      console.log("DSP bypassed (Original Sound)");
      isSwitching = false;
      return true;
    }

    let configStr = configJson;
    if (typeof configStr !== 'string') {
      configStr = JSON.stringify(configStr);
    }

    effectHandle1 = createSingleHandle(configStr, sampleRate);
    effectHandle2 = createSingleHandle(configStr, sampleRate);

    if (!effectHandle1) {
      console.error("Failed to initialize primary DSP effect handle!");
      if (effectHandle2) {
        releaseHandle(effectHandle2);
        effectHandle2 = 0;
      }
      isSwitching = false;
      return false;
    }

    console.log(`DSP dual-cascade effect loaded successfully (SR: ${sampleRate}, Intensity: ${currentIntensity}%)`);
    isSwitching = false;
    return true;
  } catch (err) {
    console.error("Error in loadEffect:", err);
    isSwitching = false;
    return false;
  }
}

// TCP Server
const PORT = 9988;
const server = net.createServer((socket) => {
  socket.setNoDelay(true);
  console.log("Desktop client connected!");

  let rxBuffer = Buffer.alloc(0);

  socket.on('data', (chunk) => {
    try {
      rxBuffer = Buffer.concat([rxBuffer, chunk]);

      while (rxBuffer.length >= 8) {
        const msgType = rxBuffer.readUInt32LE(0);
        const payloadLen = rxBuffer.readUInt32LE(4);

        if (rxBuffer.length < 8 + payloadLen) {
          break;
        }

        const payload = rxBuffer.subarray(8, 8 + payloadLen);
        rxBuffer = rxBuffer.subarray(8 + payloadLen);

        if (msgType === 1) {
          // CMD 1: Load Effect Config
          const jsonStr = payload.toString('utf-8');
          const req = JSON.parse(jsonStr);
          const initInt = (req.intensity !== undefined) ? Number(req.intensity) : currentIntensity;
          const ok = loadEffect(req.config, req.sampleRate || 48000, initInt);
          
          const resp = Buffer.allocUnsafe(8);
          resp.writeUInt32LE(1, 0);
          resp.writeUInt32LE(ok ? 1 : 0, 4);
          socket.write(resp);
        } else if (msgType === 2) {
          // CMD 2: Process Audio Chunk (Dual-Stage Cascade)
          const floatCount = payloadLen / 4;
          const totalFrames = floatCount / 2;

          const resp = Buffer.allocUnsafe(8 + payloadLen);
          resp.writeUInt32LE(2, 0);
          resp.writeUInt32LE(payloadLen, 4);

          if (!effectHandle1 || isSwitching || currentIntensity === 0) {
            // Bypass / 0% Dry
            payload.copy(resp, 8);
            socket.write(resp);
          } else {
            try {
              const chunkFrames = 128;
              const bufferPtr1 = module._EffectGetProcessBuffer(effectHandle1, chunkFrames, 2, 0);
              
              if (!bufferPtr1 || bufferPtr1 === 0) {
                payload.copy(resp, 8);
                socket.write(resp);
                continue;
              }

              const dataPtr1 = module.HEAP32[(bufferPtr1 + BufferLayout.data_ptr_off) >>> 2] >>> 0;
              if (!dataPtr1 || dataPtr1 === 0) {
                payload.copy(resp, 8);
                socket.write(resp);
                continue;
              }

              module.HEAP32[(bufferPtr1 + BufferLayout.audio_type_off) >>> 2] = EFFECT_AUDIO_STREAMING;
              module.HEAP32[(bufferPtr1 + BufferLayout.channel_num_off) >>> 2] = 2;
              module.HEAP32[(bufferPtr1 + BufferLayout.samplerate_off) >>> 2] = currentSampleRate;
              module.HEAP32[(bufferPtr1 + BufferLayout.frame_num_off) >>> 2] = chunkFrames;

              let bufferPtr2 = 0;
              let dataPtr2 = 0;
              if (currentIntensity > 100 && effectHandle2) {
                bufferPtr2 = module._EffectGetProcessBuffer(effectHandle2, chunkFrames, 2, 0);
                if (bufferPtr2 && bufferPtr2 !== 0) {
                  dataPtr2 = module.HEAP32[(bufferPtr2 + BufferLayout.data_ptr_off) >>> 2] >>> 0;
                  if (dataPtr2 && dataPtr2 !== 0) {
                    module.HEAP32[(bufferPtr2 + BufferLayout.audio_type_off) >>> 2] = EFFECT_AUDIO_STREAMING;
                    module.HEAP32[(bufferPtr2 + BufferLayout.channel_num_off) >>> 2] = 2;
                    module.HEAP32[(bufferPtr2 + BufferLayout.samplerate_off) >>> 2] = currentSampleRate;
                    module.HEAP32[(bufferPtr2 + BufferLayout.frame_num_off) >>> 2] = chunkFrames;
                  }
                }
              }

              const inFloats = new Float32Array(payload.buffer, payload.byteOffset, floatCount);
              const outFloats = new Float32Array(resp.buffer, resp.byteOffset + 8, floatCount);
              const dataOffset1 = dataPtr1 >>> 2;
              const dataOffset2 = dataPtr2 ? (dataPtr2 >>> 2) : 0;

              for (let offset = 0; offset < totalFrames; offset += chunkFrames) {
                const count = Math.min(chunkFrames, totalFrames - offset);
                for (let i = 0; i < count; i++) {
                  let l = inFloats[(offset + i) * 2 + 0] || 0;
                  let r = inFloats[(offset + i) * 2 + 1] || 0;
                  if (!Number.isFinite(l)) l = 0;
                  if (!Number.isFinite(r)) r = 0;
                  module.HEAPF32[dataOffset1 + i * 2 + 0] = l;
                  module.HEAPF32[dataOffset1 + i * 2 + 1] = r;
                }

                const err1 = module._EffectProcessBuffer(effectHandle1, bufferPtr1);
                if (err1 !== 0) {
                  for (let i = 0; i < count; i++) {
                    outFloats[(offset + i) * 2 + 0] = inFloats[(offset + i) * 2 + 0] || 0;
                    outFloats[(offset + i) * 2 + 1] = inFloats[(offset + i) * 2 + 1] || 0;
                  }
                  continue;
                }

                if (currentIntensity <= 100) {
                  // 0% ~ 100%: Smooth Dry/Wet Mix
                  const alpha = Math.max(0, Math.min(1.0, currentIntensity / 100.0));
                  for (let i = 0; i < count; i++) {
                    const inL = inFloats[(offset + i) * 2 + 0] || 0;
                    const inR = inFloats[(offset + i) * 2 + 1] || 0;
                    const l1 = module.HEAPF32[dataOffset1 + i * 2 + 0];
                    const r1 = module.HEAPF32[dataOffset1 + i * 2 + 1];
                    const outL = inL * (1.0 - alpha) + (Number.isFinite(l1) ? l1 : inL) * alpha;
                    const outR = inR * (1.0 - alpha) + (Number.isFinite(r1) ? r1 : inR) * alpha;
                    outFloats[(offset + i) * 2 + 0] = Math.max(-1.0, Math.min(1.0, outL));
                    outFloats[(offset + i) * 2 + 1] = Math.max(-1.0, Math.min(1.0, outR));
                  }
                } else {
                  // 100% ~ 200%: True Dual-Stage Cascaded Stack (Stage 1 -> Stage 2)
                  if (bufferPtr2 && dataOffset2) {
                    for (let i = 0; i < count; i++) {
                      let l1 = module.HEAPF32[dataOffset1 + i * 2 + 0];
                      let r1 = module.HEAPF32[dataOffset1 + i * 2 + 1];
                      if (!Number.isFinite(l1)) l1 = 0;
                      if (!Number.isFinite(r1)) r1 = 0;
                      module.HEAPF32[dataOffset2 + i * 2 + 0] = l1;
                      module.HEAPF32[dataOffset2 + i * 2 + 1] = r1;
                    }

                    const err2 = module._EffectProcessBuffer(effectHandle2, bufferPtr2);
                    if (err2 === 0) {
                      const beta = Math.max(0, Math.min(1.0, (currentIntensity - 100.0) / 100.0));
                      for (let i = 0; i < count; i++) {
                        const l1 = module.HEAPF32[dataOffset1 + i * 2 + 0];
                        const r1 = module.HEAPF32[dataOffset1 + i * 2 + 1];
                        const l2 = module.HEAPF32[dataOffset2 + i * 2 + 0];
                        const r2 = module.HEAPF32[dataOffset2 + i * 2 + 1];
                        const outL = l1 * (1.0 - beta) + (Number.isFinite(l2) ? l2 : l1) * beta;
                        const outR = r1 * (1.0 - beta) + (Number.isFinite(r2) ? r2 : r1) * beta;
                        outFloats[(offset + i) * 2 + 0] = Math.max(-1.0, Math.min(1.0, outL));
                        outFloats[(offset + i) * 2 + 1] = Math.max(-1.0, Math.min(1.0, outR));
                      }
                    } else {
                      for (let i = 0; i < count; i++) {
                        const l1 = module.HEAPF32[dataOffset1 + i * 2 + 0];
                        const r1 = module.HEAPF32[dataOffset1 + i * 2 + 1];
                        outFloats[(offset + i) * 2 + 0] = Math.max(-1.0, Math.min(1.0, l1));
                        outFloats[(offset + i) * 2 + 1] = Math.max(-1.0, Math.min(1.0, r1));
                      }
                    }
                  } else {
                    for (let i = 0; i < count; i++) {
                      const l1 = module.HEAPF32[dataOffset1 + i * 2 + 0];
                      const r1 = module.HEAPF32[dataOffset1 + i * 2 + 1];
                      outFloats[(offset + i) * 2 + 0] = Math.max(-1.0, Math.min(1.0, l1));
                      outFloats[(offset + i) * 2 + 1] = Math.max(-1.0, Math.min(1.0, r1));
                    }
                  }
                }
              }

              socket.write(resp);
            } catch (procErr) {
              console.error("Audio processing error, falling back to bypass:", procErr);
              payload.copy(resp, 8);
              socket.write(resp);
            }
          }
        } else if (msgType === 3) {
          // CMD 3: Set Real-time Intensity (0 ~ 200%)
          try {
            let val = 100;
            if (payloadLen >= 4 && (payloadLen !== 4 || payload[0] === 0x7b)) {
              // JSON format
              const parsed = JSON.parse(payload.toString('utf-8'));
              val = Number(parsed.intensity);
            } else if (payloadLen === 4) {
              val = payload.readFloatLE(0);
              if (!Number.isFinite(val) || val < 0 || val > 300) {
                val = payload.readUInt32LE(0);
              }
            }
            if (Number.isFinite(val)) {
              currentIntensity = Math.max(0, Math.min(200, val));
            }
          } catch (e) {
            console.error("Failed to parse CMD 3 intensity:", e);
          }

          const resp = Buffer.allocUnsafe(8);
          resp.writeUInt32LE(3, 0);
          resp.writeUInt32LE(1, 4);
          socket.write(resp);
        }
      }
    } catch (e) {
      console.error("Socket packet parse error:", e);
    }
  });

  socket.on('error', (e) => console.log("Socket error:", e.message));
  socket.on('close', () => console.log("Client disconnected"));
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`🚀 Native DSP TCP Service listening on 127.0.0.1:${PORT}`);
});
