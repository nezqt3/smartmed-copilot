import assert from 'node:assert/strict'
import test from 'node:test'
import { encodeWav } from '../src/audioWav.ts'

test('microphone encoder writes mono 16 kHz PCM16 WAV accepted by ASR', () => {
  const samples = new Float32Array(16_000)
  samples[0] = -1
  samples[1] = 1
  const bytes = encodeWav(samples)
  const view = new DataView(bytes)
  const text = (start, length) => String.fromCharCode(...new Uint8Array(bytes, start, length))
  assert.equal(text(0, 4), 'RIFF')
  assert.equal(text(8, 4), 'WAVE')
  assert.equal(text(12, 4), 'fmt ')
  assert.equal(view.getUint16(20, true), 1)
  assert.equal(view.getUint16(22, true), 1)
  assert.equal(view.getUint32(24, true), 16_000)
  assert.equal(view.getUint16(34, true), 16)
  assert.equal(view.getUint32(40, true), 32_000)
  assert.equal(view.getInt16(44, true), -32768)
  assert.equal(view.getInt16(46, true), 32767)
})
